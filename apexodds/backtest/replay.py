"""Race replay harness — emulates live mode on historical data.

Plays a normalized session lap by lap; at every lap k it rebuilds the
``RaceState`` from *only* the data visible up to lap k, updates the live
pace estimator, runs the Monte Carlo engine and records a snapshot row per
driver. The output frame is the ``sim_snapshots`` table plus the actual
outcomes (``actual_*`` columns, joined after the loop purely for
calibration — they are never fed to the model).

LOOK-AHEAD RULE: everything that enters the RaceState at lap k must be
knowable at the end of lap k. All slicing goes through
:meth:`RaceReplay._visible`; grid, starting compounds and the (prior)
models are pre-race knowledge; retirement is only inferred once a car has
stopped completing laps.
"""

from __future__ import annotations

import bisect
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from apexodds.data.circuits import circuit_params
from apexodds.models import ModelBundle
from apexodds.models.pace import (
    LivePaceEstimator,
    PacePrior,
    clean_lap_mask,
    fuel_penalty_s,
)
from apexodds.sim import engine, outputs
from apexodds.sim.state import (
    TRACK_GREEN,
    TRACK_RED,
    TRACK_SC,
    TRACK_VSC,
    DriverState,
    RaceState,
    Weather,
)

log = logging.getLogger(__name__)


@dataclass
class ReplayConfig:
    n_sims: int = 2000
    seed: int | None = 7
    snapshot_every: int = 1  # snapshot every k-th lap
    grid_prior_slope_s: float = 0.06  # synthetic prior: pace gap per grid slot
    synthetic_base_pace_s: float = 92.0


@dataclass
class RaceReplay:
    session_dir: str | Path
    circuit_id: str | None = None
    config: ReplayConfig = field(default_factory=ReplayConfig)
    models: ModelBundle | None = None

    def __post_init__(self) -> None:
        self.session_dir = Path(self.session_dir)
        self.laps = pd.read_parquet(self.session_dir / "laps.parquet")
        self.results = pd.read_parquet(self.session_dir / "results.parquet")
        meta_path = self.session_dir / "session.json"
        self.meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        self.session_key = self.meta.get("session_key", self.session_dir.name)
        self.total_laps = int(
            self.meta.get("total_laps") or self.laps["lap_number"].max()
        )
        cid = self.circuit_id or _slug(self.meta.get("circuit", ""))
        self.circuit = circuit_params(cid, lap_count=self.total_laps)
        if self.models is None:
            self.models = ModelBundle.default(self.circuit)

        self._prepare_static()

    # ------------------------------------------------------------ preparation

    def _prepare_static(self) -> None:
        """Pre-race knowledge + causal per-lap derived columns."""
        res = self.results.set_index("driver_number")
        self.driver_numbers = [int(n) for n in res.index]
        self.codes = res["code"].to_dict()
        self.teams = res["team"].to_dict()
        self.grid = {
            int(n): int(g) if pd.notna(g) else 20
            for n, g in res["grid_position"].to_dict().items()
        }

        # Retirement lap: a car that stops completing laps *and* is flagged
        # DNF in the results is treated as retired once k passes its last
        # completed lap. (The DNF flag only disambiguates "retired" from
        # "running but lapped" — visibly knowable live.)
        last_lap = self.laps.groupby("driver_number")["lap_number"].max()
        self.retired_after = {
            int(n): int(last_lap.get(n, 0)) for n in self.driver_numbers
        }
        self.is_dnf = res["dnf"].to_dict()

        # Causal per-lap base-pace observations (fuel- and tyre-corrected;
        # each row only uses that lap's own data + fixed priors).
        laps = self.laps.copy()
        lap_s = laps["lap_time_ms"].astype("Float64") / 1000.0
        fuel = fuel_penalty_s(laps["lap_number"].to_numpy(), self.total_laps)
        deg = np.array(
            [
                self.models.tyres.delta(c if isinstance(c, str) else "MEDIUM", a)
                for c, a in zip(
                    laps["compound"].fillna("MEDIUM"),
                    pd.to_numeric(laps["tyre_age"], errors="coerce").fillna(5),
                    strict=True,
                )
            ]
        )
        laps["base_pace_s"] = lap_s.to_numpy(dtype=np.float64, na_value=np.nan) - fuel - deg
        laps["is_clean"] = clean_lap_mask(laps)
        self._laps_aug = laps

        self.prior = self._ensure_prior_coverage(self._build_prior())

    def _build_prior(self) -> PacePrior:
        """Quali-based prior when a sibling qualifying dump exists,
        otherwise a synthetic grid-order prior (absolute level barely
        matters — only pace deltas drive outcomes)."""
        key = self.session_key
        if key.endswith("_R"):
            quali_dir = self.session_dir.parent / (key[:-2] + "_Q")
            quali_laps = quali_dir / "laps.parquet"
            if quali_laps.exists():
                q = pd.read_parquet(quali_laps)
                best = (
                    q.groupby("driver_number")["lap_time_ms"].min().dropna() / 1000.0
                )
                if len(best) >= 5:
                    log.info("%s: qualifying prior from %s", key, quali_dir.name)
                    return PacePrior.from_quali({int(k): float(v) for k, v in best.items()})
        cfg = self.config
        means = {
            n: cfg.synthetic_base_pace_s + cfg.grid_prior_slope_s * (self.grid[n] - 1)
            for n in self.driver_numbers
        }
        return PacePrior(mean_s=means, std_s={n: 0.45 for n in means}, weight_laps=6.0)

    def _ensure_prior_coverage(self, prior: PacePrior) -> PacePrior:
        """Every driver needs a prior entry (pit-lane starters may miss quali)."""
        missing = [n for n in self.driver_numbers if n not in prior.mean_s]
        if missing:
            worst = max(prior.mean_s.values())
            for n in missing:
                prior.mean_s[n] = worst + 0.5
                prior.std_s[n] = 0.6
        return prior

    # ------------------------------------------------------------- visibility

    def _visible(self, lap: int) -> pd.DataFrame:
        """THE look-ahead gate: rows knowable at the end of lap ``lap``."""
        return self._laps_aug[self._laps_aug["lap_number"] <= lap]

    # ------------------------------------------------------------------- run

    def run(self) -> pd.DataFrame:
        """Replay the race; return sim_snapshots (+ actual_* columns)."""
        estimator = LivePaceEstimator(prior=self.prior)
        frames: list[pd.DataFrame] = []

        for lap in range(0, self.total_laps):
            if lap > 0:
                new = self._laps_aug[
                    (self._laps_aug["lap_number"] == lap) & self._laps_aug["is_clean"]
                ]
                for row in new.itertuples():
                    estimator.add_lap(int(row.driver_number), float(row.base_pace_s))
            if lap % self.config.snapshot_every:
                continue

            state = self.build_state(lap, estimator)
            if state is None:
                continue
            sim_cfg = engine.SimConfig(n_sims=self.config.n_sims, seed=self.config.seed)
            result = engine.simulate(state, self.models, sim_cfg)
            probs = outputs.aggregate(result)
            frame = probs.to_frame(self.session_key)
            frame["track_status"] = state.track_status
            frame["grid_position"] = frame["driver_number"].map(self.grid)
            frames.append(frame)

        if not frames:
            raise ValueError(f"replay of {self.session_key} produced no snapshots")
        snapshots = pd.concat(frames, ignore_index=True)
        return self._join_actuals(snapshots)

    # ---------------------------------------------------------- state builder

    def build_state(self, lap: int, estimator: LivePaceEstimator) -> RaceState | None:
        visible = self._visible(lap)
        per_driver = visible.groupby("driver_number")

        med_lap = self.config.synthetic_base_pace_s
        if len(visible):
            med = (visible["lap_time_ms"].dropna() / 1000.0).median()
            if pd.notna(med):
                med_lap = float(med)

        # Cumulative race time; missing lap times filled with the driver's
        # visible median so gaps stay finite (red-flag data holes etc.).
        cum_s: dict[int, float] = {}
        laps_done: dict[int, int] = {}
        for n in self.driver_numbers:
            if n not in per_driver.groups:
                cum_s[n] = 0.0
                laps_done[n] = 0
                continue
            g = per_driver.get_group(n)
            t = g["lap_time_ms"].astype("Float64") / 1000.0
            laps_done[n] = int(g["lap_number"].max())
            if t.notna().any():
                cum_s[n] = float(t.fillna(t.median()).sum())
            else:
                cum_s[n] = laps_done[n] * med_lap

        leader_laps = max(laps_done.values(), default=0)

        drivers: list[DriverState] = []
        mid_stop: set[int] = set()
        for n in self.driver_numbers:
            retired = bool(self.is_dnf.get(n, False)) and lap > self.retired_after.get(
                n, self.total_laps
            )
            # Charge lapped cars their lap deficit so effective gaps order
            # the field correctly.
            deficit = max(leader_laps - laps_done[n], 0)
            eff_cum = cum_s[n] + deficit * med_lap
            compound, age = self._tyres_at(n, lap, per_driver)
            # Mid-stop: if the driver's current lap is the in-lap, the car
            # is in the pit lane right now. Without this the engine sees
            # worn tyres and immediately charges a SECOND stop on top of
            # the in-lap cost already in cum time. Model the stop as done:
            # fresh (inferred) compound + the not-yet-paid out-lap share.
            if not retired and lap > 0 and laps_done[n] == lap and n in per_driver.groups:
                g = per_driver.get_group(n)
                last_row = g.loc[g["lap_number"].idxmax()]
                if bool(last_row["is_pit_in"]):
                    used_so_far = tuple(g["compound"].dropna().unique())
                    compound = self._infer_next_compound(used_so_far, self.total_laps - lap)
                    age = 0
                    eff_cum += self.circuit.pit_loss_s * 0.55
                    mid_stop.add(n)
            pace_mean, pace_std = estimator.estimate(n)
            drivers.append(
                DriverState(
                    driver_number=n,
                    code=str(self.codes.get(n, n)),
                    team=str(self.teams.get(n, "")),
                    position=0,  # filled below
                    gap_to_leader_s=eff_cum,
                    compound=compound,
                    tyre_age=age,
                    pit_count=int(
                        per_driver.get_group(n)["is_pit_in"].sum()
                    )
                    if n in per_driver.groups
                    else 0,
                    used_compounds=tuple(
                        per_driver.get_group(n)["compound"].dropna().unique()
                    )
                    if n in per_driver.groups
                    else (),
                    pace_mean_s=pace_mean,
                    pace_std_s=pace_std,
                    retired=retired,
                    grid_position=self.grid.get(n, 20),
                )
            )

        # Positions: recorded live positions when available, else effective gap.
        drivers = self._assign_positions(drivers, lap, visible, mid_stop)
        running = [d for d in drivers if not d.retired]
        if len(running) < 2:
            return None
        leader_gap = min(d.gap_to_leader_s for d in running)
        for d in drivers:
            d.gap_to_leader_s = (d.gap_to_leader_s - leader_gap) if not d.retired else 0.0

        if lap == 0:
            for d in drivers:
                d.position = d.grid_position
                d.gap_to_leader_s = 0.35 * (d.grid_position - 1)
            drivers.sort(key=lambda d: d.position)

        status, rain = self._status_at(lap, visible)
        return RaceState(
            session_key=self.session_key,
            circuit=self.circuit,
            lap=lap,
            total_laps=self.total_laps,
            drivers=drivers,
            track_status=status,
            weather=Weather(rainfall=rain),
            intervention_laps_remaining=2 if status == TRACK_SC else 1,
        )

    def _infer_next_compound(self, used: tuple[str, ...], laps_remaining: int) -> str:
        """The compound a mid-stop car most plausibly emerges on: stint
        length closest to the laps remaining, honoring the two-compound rule."""
        from apexodds.sim.state import COMPOUND_INDEX, DRY_COMPOUNDS

        targets = self.models.tyres.stint_targets(self.total_laps)
        dry_used = {c for c in used if c in DRY_COMPOUNDS}
        best, best_score = "HARD", float("inf")
        for c in DRY_COMPOUNDS:
            score = abs(float(targets[COMPOUND_INDEX[c]]) - laps_remaining)
            if len(dry_used) == 1 and c in dry_used:
                score += 1e6
            if score < best_score:
                best, best_score = c, score
        return best

    def _tyres_at(self, n: int, lap: int, per_driver) -> tuple[str, int]:
        if lap == 0 or n not in per_driver.groups:
            # Starting compound: stint-1 tyre choice is visible on the grid.
            first = self._laps_aug[self._laps_aug["driver_number"] == n]
            first = first[first["lap_number"] == 1]
            compound = first["compound"].iloc[0] if len(first) else "MEDIUM"
            return (compound if isinstance(compound, str) else "MEDIUM"), 0
        g = per_driver.get_group(n)
        last = g.loc[g["lap_number"].idxmax()]
        compound = last["compound"] if isinstance(last["compound"], str) else "MEDIUM"
        age = int(last["tyre_age"]) if pd.notna(last["tyre_age"]) else 5
        return compound, age

    def _assign_positions(
        self,
        drivers: list[DriverState],
        lap: int,
        visible: pd.DataFrame,
        mid_stop: set[int] | None = None,
    ) -> list[DriverState]:
        mid_stop = mid_stop or set()
        recorded: dict[int, int] = {}
        if lap > 0 and "position" in visible.columns:
            latest = visible.sort_values("lap_number").groupby("driver_number").tail(1)
            for row in latest.itertuples():
                if pd.notna(row.position):
                    recorded[int(row.driver_number)] = int(row.position)
        running = [d for d in drivers if not d.retired]
        if recorded and len(recorded) >= len(running) - 2:
            # Mid-stop cars carry a stale recorded position (the pit-lane
            # time isn't posted yet), so slot them by effective gap instead.
            ordered = [d for d in running if d.driver_number not in mid_stop]
            ordered.sort(
                key=lambda d: (recorded.get(d.driver_number, 99), d.gap_to_leader_s)
            )
            for d in sorted(
                (d for d in running if d.driver_number in mid_stop),
                key=lambda d: d.gap_to_leader_s,
            ):
                idx = bisect.bisect_left([x.gap_to_leader_s for x in ordered],
                                         d.gap_to_leader_s)
                ordered.insert(idx, d)
            running = ordered
        else:
            running.sort(key=lambda d: d.gap_to_leader_s)
        for i, d in enumerate(running):
            d.position = i + 1
        for j, d in enumerate([d for d in drivers if d.retired]):
            d.position = len(running) + j + 1
        return drivers

    def _status_at(self, lap: int, visible: pd.DataFrame) -> tuple[str, bool]:
        if lap == 0:
            return TRACK_GREEN, False
        codes = set(
            "".join(
                visible.loc[visible["lap_number"] == lap, "track_status"]
                .fillna("")
                .astype(str)
            )
        )
        if "5" in codes:
            return TRACK_RED, False
        if "4" in codes:
            return TRACK_SC, False
        if "6" in codes or "7" in codes:
            return TRACK_VSC, False
        return TRACK_GREEN, False

    # ------------------------------------------------------------- evaluation

    def _join_actuals(self, snapshots: pd.DataFrame) -> pd.DataFrame:
        res = self.results.set_index("driver_number")
        pos = pd.to_numeric(res["finish_position"], errors="coerce")
        snapshots["actual_position"] = snapshots["driver_number"].map(pos)
        snapshots["actual_win"] = (snapshots["actual_position"] == 1).astype(float)
        snapshots["actual_podium"] = (snapshots["actual_position"] <= 3).astype(float)
        snapshots["actual_top10"] = (snapshots["actual_position"] <= 10).astype(float)
        snapshots["actual_dnf"] = snapshots["driver_number"].map(
            res["dnf"].astype(bool)
        ).astype(float)
        return snapshots


def _slug(name: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(name).lower()).strip("_")


def replay_race(session_dir: str | Path, **kwargs) -> pd.DataFrame:
    """Convenience wrapper: replay one race and persist the snapshots."""
    from apexodds.config import get_settings

    replay = RaceReplay(session_dir, **kwargs)
    snapshots = replay.run()
    out_dir = get_settings().snapshots_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{replay.session_key}.parquet"
    snapshots.to_parquet(out, index=False)
    log.info("wrote %s (%d rows)", out, len(snapshots))
    return snapshots
