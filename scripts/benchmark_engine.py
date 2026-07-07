"""Engine performance benchmark (brief §6: full recompute in ~1-2 s on CPU).

    python scripts/benchmark_engine.py
"""

from __future__ import annotations

import time

from apexodds.models import ModelBundle
from apexodds.sim.engine import SimConfig, simulate
from apexodds.sim.state import CircuitParams, DriverState, grid_state


def build_state(n_drivers: int = 20, laps: int = 57):
    circuit = CircuitParams(circuit_id="bench", lap_count=laps)
    grid = [
        DriverState(
            driver_number=i + 1,
            code=f"D{i + 1:02d}",
            compound="MEDIUM",
            pace_mean_s=90.0 + 0.07 * i,
            pace_std_s=0.35,
        )
        for i in range(n_drivers)
    ]
    return grid_state("bench", circuit, grid, total_laps=laps)


def main() -> None:
    state = build_state()
    models = ModelBundle.default(state.circuit)

    for n_sims in (1000, 2000, 3000, 5000):
        cfg = SimConfig(n_sims=n_sims, seed=1)
        simulate(state, models, cfg)  # warm-up (allocations, cache)
        runs = []
        for _ in range(3):
            t0 = time.perf_counter()
            simulate(state, models, cfg)
            runs.append(time.perf_counter() - t0)
        best = min(runs)
        status = "OK " if best < 2.0 else "SLOW"
        print(
            f"[{status}] n_sims={n_sims:5d} drivers=20 laps=57 -> "
            f"{best * 1000:7.1f} ms (best of 3)"
        )


if __name__ == "__main__":
    main()
