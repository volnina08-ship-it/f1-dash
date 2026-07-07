"""Aggregate raw simulation worlds into the probability outputs.

This is the payload the product shows: win/podium/top-10 probabilities,
expected finish with percentiles, DNF risk, next-pit-window distribution,
head-to-head matrix and constructor aggregates — plus ``to_frame()`` which
produces the ``sim_snapshots`` rows persisted by the backtest/live loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from apexodds.sim.engine import SimResult

POINTS = np.zeros(64, dtype=np.float64)
POINTS[1:11] = [25, 18, 15, 12, 10, 8, 6, 4, 2, 1]


@dataclass
class DriverProbabilities:
    driver_number: int
    code: str
    team: str
    current_position: int
    win_p: float
    podium_p: float
    top10_p: float
    dnf_p: float
    exp_finish: float
    finish_p5: int
    finish_p50: int
    finish_p95: int
    exp_points: float
    # Next pit stop, over worlds where at least one more stop happens.
    pit_prob: float  # P(at least one more stop)
    pit_window_open: int  # p25 lap | 0 when pit_prob ~ 0
    pit_window_p50: int
    pit_window_close: int  # p75 lap


@dataclass
class RaceProbabilities:
    lap: int
    total_laps: int
    n_sims: int
    drivers: list[DriverProbabilities]
    # h2h[i, j] = P(driver i finishes ahead of driver j), row/col order == codes.
    h2h: np.ndarray = field(repr=False)
    codes: list[str] = field(default_factory=list)

    def driver(self, code: str) -> DriverProbabilities:
        return next(d for d in self.drivers if d.code == code)

    def to_frame(self, session_key: str = "") -> pd.DataFrame:
        """One row per driver — the ``sim_snapshots`` schema."""
        rows = [
            {
                "session_key": session_key,
                "lap": self.lap,
                "total_laps": self.total_laps,
                "driver_number": d.driver_number,
                "code": d.code,
                "team": d.team,
                "current_position": d.current_position,
                "win_p": d.win_p,
                "podium_p": d.podium_p,
                "top10_p": d.top10_p,
                "dnf_p": d.dnf_p,
                "exp_finish": d.exp_finish,
                "finish_p5": d.finish_p5,
                "finish_p50": d.finish_p50,
                "finish_p95": d.finish_p95,
                "exp_points": d.exp_points,
                "pit_prob": d.pit_prob,
                "pit_window_open": d.pit_window_open,
                "pit_window_p50": d.pit_window_p50,
                "pit_window_close": d.pit_window_close,
            }
            for d in self.drivers
        ]
        return pd.DataFrame(rows)

    def h2h_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.h2h, index=self.codes, columns=self.codes)

    def constructors(self) -> pd.DataFrame:
        """P(win/podium) that at least one car of the team achieves it,
        plus expected team points."""
        teams: dict[str, dict[str, float]] = {}
        by_team: dict[str, list[int]] = {}
        for i, d in enumerate(self.drivers):
            by_team.setdefault(d.team or d.code, []).append(i)
        for team, idxs in by_team.items():
            teams[team] = {
                "win_p": _any_p([self.drivers[i].win_p for i in idxs]),
                "podium_p": _any_p([self.drivers[i].podium_p for i in idxs]),
                "exp_points": float(sum(self.drivers[i].exp_points for i in idxs)),
            }
        return (
            pd.DataFrame.from_dict(teams, orient="index")
            .rename_axis("team")
            .sort_values("exp_points", ascending=False)
        )


def _any_p(ps: list[float]) -> float:
    """P(at least one) under (an approximation of) independence — fine for
    display; exact joint numbers would need the raw worlds."""
    out = 1.0
    for p in ps:
        out *= 1.0 - p
    return 1.0 - out


def aggregate(result: SimResult) -> RaceProbabilities:
    pos = result.final_position  # (N, D)
    n, d = pos.shape

    win_p = (pos == 1).mean(axis=0)
    podium_p = (pos <= 3).mean(axis=0)
    top10_p = (pos <= 10).mean(axis=0)
    dnf_p = result.dnf.mean(axis=0)
    exp_finish = pos.mean(axis=0)
    p5, p50, p95 = np.percentile(pos, [5, 50, 95], axis=0).astype(int)
    exp_points = POINTS[np.minimum(pos, 63)].mean(axis=0)

    # Head-to-head: P(i ahead of j). D is small, so the (N, D, D) burst is fine.
    h2h = (pos[:, :, None] < pos[:, None, :]).mean(axis=0)

    drivers = []
    for i in range(d):
        stops = result.next_pit_lap[:, i]
        stopping = stops > 0
        pit_prob = float(stopping.mean())
        if stopping.any():
            q25, q50, q75 = np.percentile(stops[stopping], [25, 50, 75]).astype(int)
        else:
            q25 = q50 = q75 = 0
        drivers.append(
            DriverProbabilities(
                driver_number=result.driver_numbers[i],
                code=result.codes[i],
                team=result.teams[i],
                current_position=result.start_positions[i],
                win_p=float(win_p[i]),
                podium_p=float(podium_p[i]),
                top10_p=float(top10_p[i]),
                dnf_p=float(dnf_p[i]),
                exp_finish=float(exp_finish[i]),
                finish_p5=int(p5[i]),
                finish_p50=int(p50[i]),
                finish_p95=int(p95[i]),
                exp_points=float(exp_points[i]),
                pit_prob=pit_prob,
                pit_window_open=int(q25),
                pit_window_p50=int(q50),
                pit_window_close=int(q75),
            )
        )
    drivers.sort(key=lambda dd: (-dd.win_p, dd.exp_finish))

    return RaceProbabilities(
        lap=result.from_lap,
        total_laps=result.total_laps,
        n_sims=result.n_sims,
        drivers=drivers,
        h2h=h2h,
        codes=result.codes,
    )
