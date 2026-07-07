"""Generate the demo race for the web dashboard (apps/web/src/data/race.json).

Scripts a plausible, dramatic 2025 Hungarian GP (VER charging from P10 on an
offset strategy, mid-race Safety Car, late duel), then runs the REAL replay
pipeline (live pace estimation + Monte Carlo engine) over it lap by lap and
exports everything the UI needs: timing rows, probabilities, finish
distributions and an event feed.

    .venv/bin/python scripts/make_demo_race.py [--check]

--check only prints the story (final classification + key gaps) without the
expensive replay, for quick parameter iteration.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from apexodds.backtest.replay import RaceReplay, ReplayConfig
from apexodds.sim import engine, outputs

SESSION_KEY = "2025_14_R"
TOTAL_LAPS = 70
BASE = 81.6  # Hungaroring race-pace baseline, seconds
FUEL = 0.052  # s per remaining lap
SEED = 11
N_SIMS = 2500

SC_START, SC_END = 31, 34  # SC on track those laps (deployed lap 31)
VSC_LAP = 52
SC_LAP_TIME = 118.0
VSC_LAP_TIME = 99.0

# num, code, team, color, grid, base pace delta (s/lap)
DRIVERS = [
    (4,  "NOR", "McLaren",      "#FF8000", 1,  0.06),
    (81, "PIA", "McLaren",      "#FF8000", 2,  0.12),
    (16, "LEC", "Ferrari",      "#E8002D", 3,  0.30),
    (63, "RUS", "Mercedes",     "#27F4D2", 4,  0.33),
    (44, "HAM", "Ferrari",      "#E8002D", 5,  0.34),
    (14, "ALO", "Aston Martin", "#229971", 6,  0.58),
    (30, "LAW", "Racing Bulls", "#6692FF", 7,  0.66),
    (10, "GAS", "Alpine",       "#00A1E8", 8,  0.72),
    (12, "ANT", "Mercedes",     "#27F4D2", 9,  0.52),
    (1,  "VER", "Red Bull",     "#3671C6", 10, 0.00),
    (18, "STR", "Aston Martin", "#229971", 11, 0.85),
    (27, "HUL", "Sauber",       "#52E252", 12, 0.82),
    (23, "ALB", "Williams",     "#64C4FF", 13, 0.68),
    (55, "SAI", "Williams",     "#64C4FF", 14, 0.64),
    (22, "TSU", "Red Bull",     "#3671C6", 15, 0.60),
    (31, "OCO", "Haas",         "#B6BABD", 16, 0.90),
    (87, "BEA", "Haas",         "#B6BABD", 17, 0.95),
    (6,  "HAD", "Racing Bulls", "#6692FF", 18, 0.88),
    (43, "COL", "Alpine",       "#00A1E8", 19, 0.97),
    (5,  "BOR", "Sauber",       "#52E252", 20, 1.02),
]
NUMS = [d[0] for d in DRIVERS]
CODE = {d[0]: d[1] for d in DRIVERS}
TEAM = {d[0]: d[2] for d in DRIVERS}
COLOR = {d[0]: d[3] for d in DRIVERS}
GRID = {d[0]: d[4] for d in DRIVERS}
PACE = {d[0]: d[5] for d in DRIVERS}

# Strategy script: (start compound, [(pit lap, new compound), ...])
# Most of the field: MEDIUM -> HARD in the lap 18-26 window. VER runs long on
# HARD and takes the cheap SC stop; PIA's SC stop goes wrong (slow).
STRATEGY: dict[int, tuple[str, list[tuple[int, str]]]] = {
    4:  ("MEDIUM", [(22, "HARD")]),
    81: ("MEDIUM", [(20, "HARD"), (31, "HARD")]),   # second bite under SC, slow
    16: ("MEDIUM", [(24, "HARD")]),
    63: ("MEDIUM", [(23, "HARD")]),
    44: ("MEDIUM", [(18, "HARD")]),                  # undercut attempt on RUS
    14: ("MEDIUM", [(21, "HARD")]),
    30: ("MEDIUM", [(19, "HARD")]),
    10: ("MEDIUM", [(25, "HARD")]),
    12: ("MEDIUM", [(26, "HARD")]),
    1:  ("HARD",   [(31, "MEDIUM")]),                # the offset: cheap SC stop
    18: ("MEDIUM", [(20, "HARD")]),
    27: ("MEDIUM", [(23, "HARD")]),
    23: ("MEDIUM", [(22, "HARD")]),
    55: ("MEDIUM", [(25, "HARD")]),
    22: ("HARD",   [(31, "MEDIUM")]),
    31: ("MEDIUM", [(19, "HARD")]),
    87: ("MEDIUM", [(24, "HARD")]),
    6:  ("MEDIUM", [(21, "HARD")]),
    43: ("MEDIUM", [(26, "HARD")]),
    5:  ("MEDIUM", [(18, "HARD")]),
}
SLOW_STOPS = {81: 31}  # PIA's SC stop: wheel-gun drama
DNFS = {31: 30, 55: 51}  # last completed lap: OCO crash -> SC; SAI hydraulics -> VSC

DEG = {"MEDIUM": (0.048, 0.0009, 30, 0.10), "HARD": (0.030, 0.0004, 48, 0.08)}
COMPOUND_OFFSET = {"MEDIUM": 0.0, "HARD": 0.52}
PIT_IN_EXTRA, PIT_OUT_EXTRA = 5.5, 13.5
SC_PIT_IN_EXTRA, SC_PIT_OUT_EXTRA = 3.0, 7.5


def _deg(compound: str, age: int) -> float:
    lin, quad, cliff, cliff_rate = DEG[compound]
    d = COMPOUND_OFFSET[compound] + lin * age + quad * age * age
    return d + cliff_rate * max(0, age - cliff)


def build_laps(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    cum = {n: 0.0 for n in NUMS}
    compound = {n: STRATEGY[n][0] for n in NUMS}
    age = {n: 0 for n in NUMS}
    stint = {n: 1 for n in NUMS}
    prev_gap_ahead = {n: 99.0 for n in NUMS}
    prev_pos = {n: GRID[n] for n in NUMS}

    for lap in range(1, TOTAL_LAPS + 1):
        sc = SC_START <= lap <= SC_END
        vsc = lap == VSC_LAP
        status = "4" if sc else ("6" if vsc else "1")
        alive = [n for n in NUMS if lap <= DNFS.get(n, TOTAL_LAPS)]

        lap_time: dict[int, float] = {}
        pit_in: dict[int, bool] = {}
        pit_out: dict[int, bool] = {}
        for n in alive:
            pits = STRATEGY[n][1]
            pit_in[n] = any(lap == pl for pl, _ in pits)
            pit_out[n] = any(lap == pl + 1 for pl, _ in pits)

            if sc:
                t = SC_LAP_TIME + rng.normal(0, 0.25)
            elif vsc:
                t = VSC_LAP_TIME + rng.normal(0, 0.3)
            else:
                t = BASE + PACE[n] + FUEL * (TOTAL_LAPS - lap) + _deg(compound[n], age[n])
                t += rng.normal(0, 0.26)
                if lap == 1:
                    t += 5.0 + 0.42 * (GRID[n] - 1) + rng.normal(0, 0.35)
                # Dirty air: within 1.2s of the car ahead -> pace capped.
                elif prev_gap_ahead[n] < 1.2 and prev_pos[n] > 1:
                    t += 0.24
                # VER's recovery through midfield traffic costs real time.
                if n == 1 and 2 <= lap <= 16:
                    t += 0.30
                # NOR manages the gap, then finds pace for the final stint.
                if n == 4 and lap >= 55:
                    t -= 0.12
            if pit_in[n]:
                t += SC_PIT_IN_EXTRA if sc else PIT_IN_EXTRA
                if SLOW_STOPS.get(n) == lap:
                    t += 4.6  # the wheel-gun drama is real time
            if pit_out[n]:
                t += SC_PIT_OUT_EXTRA if (SC_START <= lap - 1 <= SC_END) else PIT_OUT_EXTRA
            lap_time[n] = t

        for n in alive:
            cum[n] += lap_time[n]

        order = sorted(alive, key=lambda n: cum[n])
        pos = {n: i + 1 for i, n in enumerate(order)}
        for i, n in enumerate(order):
            prev_gap_ahead[n] = 99.0 if i == 0 else cum[n] - cum[order[i - 1]]
            prev_pos[n] = pos[n]

        for n in alive:
            rows.append(
                {
                    "session_key": SESSION_KEY,
                    "driver_number": n,
                    "code": CODE[n],
                    "team": TEAM[n],
                    "lap_number": lap,
                    "lap_time_ms": int(round(lap_time[n] * 1000)),
                    "s1_ms": None, "s2_ms": None, "s3_ms": None,
                    "is_pit_in": pit_in[n],
                    "is_pit_out": pit_out[n],
                    "compound": compound[n],
                    "tyre_age": age[n] + 1,
                    "stint_id": stint[n],
                    "track_status": status,
                    "position": pos[n],
                }
            )

        for n in alive:  # tyre state rolls over AFTER the lap is recorded
            if pit_in[n]:
                new = next(c for pl, c in STRATEGY[n][1] if pl == lap)
                compound[n] = new
                age[n] = 0
                stint[n] += 1
            else:
                age[n] += 1

    laps = pd.DataFrame(rows)
    for col in ("driver_number", "tyre_age", "stint_id", "position"):
        laps[col] = laps[col].astype("Int64")
    laps["lap_time_ms"] = laps["lap_time_ms"].astype("Int64")
    return laps


def build_results(laps: pd.DataFrame) -> pd.DataFrame:
    final = laps[laps["lap_number"] == TOTAL_LAPS].sort_values("position")
    order = [int(n) for n in final["driver_number"]]
    # DNFs classified behind finishers, later retirement first.
    dnf_sorted = sorted(DNFS, key=lambda n: -DNFS[n])
    order += dnf_sorted
    return pd.DataFrame(
        {
            "session_key": SESSION_KEY,
            "driver_number": pd.array(order, dtype="Int64"),
            "code": [CODE[n] for n in order],
            "team": [TEAM[n] for n in order],
            "grid_position": pd.array([GRID[n] for n in order], dtype="Int64"),
            "finish_position": pd.array(range(1, len(order) + 1), dtype="Int64"),
            "classified": [n not in DNFS for n in order],
            "dnf": [n in DNFS for n in order],
            "laps": pd.array([DNFS.get(n, TOTAL_LAPS) for n in order], dtype="Int64"),
            "points": 0.0,
        }
    )


def write_session(target: Path, laps: pd.DataFrame, results: pd.DataFrame) -> None:
    target.mkdir(parents=True, exist_ok=True)
    laps.to_parquet(target / "laps.parquet", index=False)
    results.to_parquet(target / "results.parquet", index=False)
    (target / "session.json").write_text(
        json.dumps(
            {
                "session_key": SESSION_KEY, "year": 2025, "round": 14,
                "session_type": "R", "event_name": "Hungarian Grand Prix",
                "circuit": "Hungaroring", "country": "Hungary",
                "total_laps": TOTAL_LAPS,
            }
        )
    )


# --------------------------------------------------------------------- export


def synth_sectors(rng: np.random.Generator, last_ms: int) -> list[int]:
    f1 = 0.293 + rng.normal(0, 0.004)
    f2 = 0.405 + rng.normal(0, 0.004)
    s1 = int(last_ms * f1)
    s2 = int(last_ms * f2)
    return [s1, s2, last_ms - s1 - s2]


def export(session_dir: Path, out_path: Path) -> None:
    rng = np.random.default_rng(99)
    replay = RaceReplay(
        session_dir,
        circuit_id="hungaroring",
        config=ReplayConfig(n_sims=N_SIMS, seed=SEED, snapshot_every=1),
    )
    laps = replay.laps
    results = replay.results.set_index("driver_number")

    from apexodds.models.pace import LivePaceEstimator

    estimator = LivePaceEstimator(prior=replay.prior)
    aug = replay._laps_aug

    lap_payloads = []
    events: list[dict] = []
    prev_win: dict[int, float] = {}
    prev_leader: int | None = None
    session_best = {0: 10**9, 1: 10**9, 2: 10**9}
    personal_best: dict[int, dict[int, int]] = {n: {0: 10**9, 1: 10**9, 2: 10**9} for n in NUMS}

    events.append({"lap": 0, "type": "info", "text": "Grid set — formation lap complete"})

    for lap in range(0, TOTAL_LAPS + 1):
        if lap > 0:
            new = aug[(aug["lap_number"] == lap) & aug["is_clean"]]
            for row in new.itertuples():
                estimator.add_lap(int(row.driver_number), float(row.base_pace_s))

        # ---- probabilities (skip the post-race lap: fill from actuals)
        if lap < TOTAL_LAPS:
            state = replay.build_state(lap, estimator)
            result = engine.simulate(
                state, replay.models, engine.SimConfig(n_sims=N_SIMS, seed=SEED)
            )
            probs = outputs.aggregate(result)
            by_num = {d.driver_number: d for d in probs.drivers}
            dists = {}
            didx = {n: i for i, n in enumerate(result.driver_numbers)}
            for n in NUMS:
                counts = np.bincount(
                    result.final_position[:, didx[n]], minlength=len(NUMS) + 1
                )[1:]
                dists[n] = [round(float(c) / N_SIMS, 4) for c in counts]
            status = state.track_status
        else:
            by_num, dists, status = {}, {}, "GREEN"

        # ---- timing rows from the (visible) data
        visible = laps[laps["lap_number"] <= max(lap, 1)]
        rows_payload = {}
        if lap == 0:
            for n in NUMS:
                rows_payload[str(n)] = {
                    "pos": GRID[n], "gap": 0, "int": 0, "last": None,
                    "s": None, "sf": None,
                    "cmp": STRATEGY[n][0][0], "age": 0, "pits": 0, "ld": 0, "out": False,
                }
        else:
            cur = visible[visible["lap_number"] == lap]
            per = {int(r.driver_number): r for r in cur.itertuples()}
            cum_ms = visible.groupby("driver_number")["lap_time_ms"].sum()
            done = visible.groupby("driver_number")["lap_number"].max()
            leader_laps = int(done.max())
            med = float(visible["lap_time_ms"].median())
            eff = {}
            for n in NUMS:
                if n in done.index:
                    deficit = leader_laps - int(done.loc[n])
                    eff[n] = float(cum_ms.loc[n]) + deficit * med
            running = [n for n in NUMS if lap <= DNFS.get(n, TOTAL_LAPS)]
            order = sorted(running, key=lambda n: eff[n])
            leader_eff = eff[order[0]] if order else 0.0
            pits_so_far = visible.groupby("driver_number")["is_pit_in"].sum()
            for i, n in enumerate(order):
                r = per.get(n)
                last_ms = int(r.lap_time_ms) if r is not None else None
                sectors, flags = None, None
                if last_ms and str(r.track_status) == "1" and not (r.is_pit_in or r.is_pit_out):
                    sectors = synth_sectors(rng, last_ms)
                    flags = []
                    for si, sms in enumerate(sectors):
                        if sms < session_best[si]:
                            session_best[si] = sms
                            personal_best[n][si] = sms
                            flags.append(2)
                        elif sms < personal_best[n][si]:
                            personal_best[n][si] = sms
                            flags.append(1)
                        else:
                            flags.append(0)
                ld = leader_laps - int(done.loc[n])
                ahead = order[i - 1] if i else None
                rows_payload[str(n)] = {
                    "pos": i + 1,
                    "gap": int(eff[n] - leader_eff),
                    "int": int(eff[n] - eff[ahead]) if ahead else 0,
                    "last": last_ms,
                    "s": sectors, "sf": flags,
                    "cmp": (r.compound[0] if r is not None else "M"),
                    "age": int(r.tyre_age) if r is not None else 0,
                    "pits": int(pits_so_far.get(n, 0)),
                    "ld": ld, "out": False,
                }
            out_pos = len(order)
            for n in sorted((x for x in NUMS if x not in running), key=lambda x: -DNFS[x]):
                out_pos += 1
                rows_payload[str(n)] = {
                    "pos": out_pos, "gap": 0, "int": 0, "last": None, "s": None,
                    "sf": None, "cmp": "M", "age": 0,
                    "pits": int(pits_so_far.get(n, 0)), "ld": 0, "out": True,
                }

        # ---- probability payload
        probs_payload = {}
        for n in NUMS:
            if n in by_num:
                d = by_num[n]
                probs_payload[str(n)] = {
                    "win": round(d.win_p, 4), "pod": round(d.podium_p, 4),
                    "t10": round(d.top10_p, 4), "xp": round(d.exp_finish, 2),
                    "dnf": round(d.dnf_p, 4), "pitP": round(d.pit_prob, 3),
                    "pitLo": d.pit_window_open, "pitMid": d.pit_window_p50,
                    "pitHi": d.pit_window_close, "dist": dists[n],
                }
            else:  # terminal lap: collapse to the actual result
                fp = int(results.loc[n, "finish_position"])
                dist = [0.0] * len(NUMS)
                dist[fp - 1] = 1.0
                probs_payload[str(n)] = {
                    "win": 1.0 if fp == 1 else 0.0,
                    "pod": 1.0 if fp <= 3 else 0.0,
                    "t10": 1.0 if fp <= 10 else 0.0,
                    "xp": float(fp), "dnf": 1.0 if bool(results.loc[n, "dnf"]) else 0.0,
                    "pitP": 0.0, "pitLo": 0, "pitMid": 0, "pitHi": 0, "dist": dist,
                }

        ui_status = {"GREEN": "GREEN", "SC": "SC", "VSC": "VSC", "RED": "RED"}.get(status, "GREEN")
        if lap == 0:
            ui_status = "GREEN"
        lap_payloads.append({"lap": lap, "status": ui_status, "t": rows_payload, "p": probs_payload})

        # ---- events
        if lap == 1:
            events.append({"lap": 1, "type": "start", "text": "Lights out! NOR leads into turn 1, VER up to P8 on lap one"})
        for n, last_lap in DNFS.items():
            if lap == last_lap + 1:
                cause = "crashes at turn 4" if n == 31 else "stops with hydraulics failure"
                events.append({"lap": lap, "type": "dnf", "text": f"{CODE[n]} {cause} — out of the race"})
        if lap == SC_START:
            events.append({"lap": lap, "type": "sc", "text": "SAFETY CAR deployed — pit window is open"})
        if lap == SC_END + 1:
            events.append({"lap": lap, "type": "green", "text": "Safety Car in — racing resumes, field bunched"})
        if lap == VSC_LAP:
            events.append({"lap": lap, "type": "vsc", "text": "Virtual Safety Car — sectors under delta"})
        if lap == VSC_LAP + 1:
            events.append({"lap": lap, "type": "green", "text": "VSC ending — green flag"})
        if 0 < lap < TOTAL_LAPS:
            cur = laps[laps["lap_number"] == lap]
            for r in cur[cur["is_pit_in"]].itertuples():
                n = int(r.driver_number)
                nxt = next((c for pl, c in STRATEGY[n][1] if pl == lap), "?")
                slow = " — SLOW STOP (4.6s), wheel-gun trouble!" if SLOW_STOPS.get(n) == lap else ""
                events.append({"lap": lap, "type": "pit", "text": f"{CODE[n]} pits: {r.compound} → {nxt}{slow}"})
        if lap > 0 and rows_payload:
            leader = next(int(k) for k, v in rows_payload.items() if v["pos"] == 1)
            if prev_leader is not None and leader != prev_leader:
                events.append({"lap": lap, "type": "lead", "text": f"NEW LEADER: {CODE[leader]} ahead of {CODE[prev_leader]}"})
            prev_leader = leader
        cur_win = {n: probs_payload[str(n)]["win"] for n in NUMS}
        if prev_win:
            swings = sorted(NUMS, key=lambda n: abs(cur_win[n] - prev_win.get(n, 0)), reverse=True)
            top = swings[0]
            delta = cur_win[top] - prev_win.get(top, 0)
            if abs(delta) >= 0.10 and lap < TOTAL_LAPS:
                events.append({
                    "lap": lap, "type": "model",
                    "text": f"Model: {CODE[top]} win {prev_win.get(top, 0) * 100:.0f}% → {cur_win[top] * 100:.0f}%",
                })
        prev_win = cur_win
        if lap == TOTAL_LAPS:
            podium = [n for n in NUMS if probs_payload[str(n)]["xp"] <= 3]
            podium.sort(key=lambda n: probs_payload[str(n)]["xp"])
            events.append({"lap": lap, "type": "finish",
                           "text": f"CHEQUERED FLAG — {CODE[podium[0]]} wins from {CODE[podium[1]]} and {CODE[podium[2]]}"})
        print(f"lap {lap:2d} done ({ui_status})")

    payload = {
        "session": {
            "key": SESSION_KEY, "name": "Hungarian Grand Prix",
            "circuit": "Hungaroring", "country": "Hungary",
            "totalLaps": TOTAL_LAPS, "nSims": N_SIMS,
            "overtakeDifficulty": 0.80, "pitLossS": 21.0,
        },
        "drivers": [
            {"num": n, "code": CODE[n], "team": TEAM[n], "color": COLOR[n], "grid": GRID[n]}
            for n in NUMS
        ],
        "laps": lap_payloads,
        "events": events,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"wrote {out_path} ({out_path.stat().st_size / 1024:.0f} KB, {len(events)} events)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="story sanity check only")
    args = parser.parse_args()

    rng = np.random.default_rng(SEED)
    laps = build_laps(rng)
    results = build_results(laps)

    print("=== final classification ===")
    final = laps[laps["lap_number"] == TOTAL_LAPS].sort_values("position")
    cum = laps.groupby("driver_number")["lap_time_ms"].sum()
    lead = cum.loc[final["driver_number"].iloc[0]]
    for r in final.itertuples():
        gap = (cum.loc[r.driver_number] - lead) / 1000
        print(f"P{int(r.position):2d} {r.code} +{gap:6.1f}s  {r.compound}({int(r.tyre_age)})")
    for n, last in DNFS.items():
        print(f"DNF {CODE[n]} (lap {last + 1})")
    if args.check:
        return

    session_dir = Path("data/demo") / SESSION_KEY
    write_session(session_dir, laps, results)
    export(session_dir, Path("apps/web/src/data/race.json"))


if __name__ == "__main__":
    main()
