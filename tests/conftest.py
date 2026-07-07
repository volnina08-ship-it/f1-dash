"""Shared fixtures: synthetic grids and a fully synthetic normalized race.

The synthetic race is deterministic and shaped like real data (pits with
slow in/out laps, an SC window, one retirement, a clear pace order) so
replay/calibration tests exercise the whole pipeline without network access.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from apexodds.sim.state import CircuitParams, DriverState, grid_state

N_DRIVERS = 20
TOTAL_LAPS = 50
BASE_PACE = 90.0
PACE_STEP = 0.08  # driver d is d*step slower per lap
SC_LAPS = range(25, 28)
DNF_DRIVER = 17
DNF_LAP = 30


def make_grid(n: int = N_DRIVERS) -> list[DriverState]:
    return [
        DriverState(
            driver_number=d + 1,
            code=f"D{d + 1:02d}",
            team=f"T{d // 2}",
            compound="MEDIUM",
            pace_mean_s=BASE_PACE + PACE_STEP * d,
            pace_std_s=0.35,
        )
        for d in range(n)
    ]


@pytest.fixture
def circuit() -> CircuitParams:
    return CircuitParams(circuit_id="testland", lap_count=TOTAL_LAPS)


@pytest.fixture
def fresh_state(circuit):
    return grid_state("2024_99_R", circuit, make_grid(), total_laps=TOTAL_LAPS)


def build_synthetic_session(target: Path, seed: int = 3) -> Path:
    """Write a normalized session dir (laps/results/session.json) to disk."""
    rng = np.random.default_rng(seed)
    rows = []
    pit_lap = {d: 20 + (d % 8) for d in range(N_DRIVERS)}
    cum = np.zeros(N_DRIVERS)
    alive = np.ones(N_DRIVERS, dtype=bool)

    for lap in range(1, TOTAL_LAPS + 1):
        status = "4" if lap in SC_LAPS else "1"
        lap_times = np.array(
            [BASE_PACE + PACE_STEP * d + rng.normal(0, 0.3) for d in range(N_DRIVERS)]
        )
        if lap == 1:
            lap_times += 4.0
        if status == "4":
            lap_times = np.full(N_DRIVERS, BASE_PACE * 1.35) + rng.normal(0, 0.2, N_DRIVERS)
        is_pit_in = np.array([lap == pit_lap[d] for d in range(N_DRIVERS)])
        is_pit_out = np.array([lap == pit_lap[d] + 1 for d in range(N_DRIVERS)])
        lap_times = lap_times + is_pit_in * 6.0 + is_pit_out * 12.0

        if lap == DNF_LAP:
            alive[DNF_DRIVER] = False
        cum = np.where(alive, cum + lap_times, cum)
        order = np.argsort(np.where(alive, cum, np.inf))
        position = np.empty(N_DRIVERS, dtype=int)
        position[order] = np.arange(1, N_DRIVERS + 1)

        for d in range(N_DRIVERS):
            if not alive[d] and lap >= DNF_LAP:
                continue
            stint = 1 if lap <= pit_lap[d] else 2
            age = lap if stint == 1 else lap - pit_lap[d]
            rows.append(
                {
                    "session_key": "2024_99_R",
                    "driver_number": d + 1,
                    "code": f"D{d + 1:02d}",
                    "team": f"T{d // 2}",
                    "lap_number": lap,
                    "lap_time_ms": int(round(lap_times[d] * 1000)),
                    "s1_ms": None,
                    "s2_ms": None,
                    "s3_ms": None,
                    "is_pit_in": bool(is_pit_in[d]),
                    "is_pit_out": bool(is_pit_out[d]),
                    "compound": "MEDIUM" if stint == 1 else "HARD",
                    "tyre_age": int(age),
                    "stint_id": stint,
                    "track_status": status,
                    "position": int(position[d]),
                }
            )

    laps = pd.DataFrame(rows)
    laps["driver_number"] = laps["driver_number"].astype("Int64")
    laps["tyre_age"] = laps["tyre_age"].astype("Int64")
    laps["position"] = laps["position"].astype("Int64")

    final = laps[laps["lap_number"] == TOTAL_LAPS].sort_values("position")
    finish_order = final["driver_number"].tolist() + [DNF_DRIVER + 1]
    results = pd.DataFrame(
        {
            "session_key": "2024_99_R",
            "driver_number": pd.array(finish_order, dtype="Int64"),
            "code": [f"D{n:02d}" for n in finish_order],
            "team": [f"T{(n - 1) // 2}" for n in finish_order],
            # Grid ~ pace order with one swap so grid and model priors differ.
            "grid_position": pd.array(
                [_grid_slot(n) for n in finish_order], dtype="Int64"
            ),
            "finish_position": pd.array(range(1, N_DRIVERS + 1), dtype="Int64"),
            "classified": [True] * (N_DRIVERS - 1) + [False],
            "dnf": [False] * (N_DRIVERS - 1) + [True],
            "laps": pd.array(
                [TOTAL_LAPS] * (N_DRIVERS - 1) + [DNF_LAP - 1], dtype="Int64"
            ),
            "points": 0.0,
        }
    )

    target.mkdir(parents=True, exist_ok=True)
    laps.to_parquet(target / "laps.parquet", index=False)
    results.to_parquet(target / "results.parquet", index=False)
    (target / "session.json").write_text(
        json.dumps(
            {
                "session_key": "2024_99_R",
                "year": 2024,
                "round": 99,
                "session_type": "R",
                "event_name": "Testland GP",
                "circuit": "Testland",
                "total_laps": TOTAL_LAPS,
            }
        )
    )
    return target


# Grid deliberately disagrees with pace: the fastest car starts P6 (recovery
# drive) and a midfielder is on pole, so the static grid prior is beatable by
# anything that actually watches the race.
GRID_SHUFFLE = {1: 6, 10: 1, 3: 4, 4: 3, 6: 7, 7: 8, 8: 9, 9: 10}


def _grid_slot(driver_number: int) -> int:
    return GRID_SHUFFLE.get(driver_number, driver_number)


@pytest.fixture(scope="session")
def synthetic_session(tmp_path_factory) -> Path:
    return build_synthetic_session(tmp_path_factory.mktemp("race") / "2024_99_R")
