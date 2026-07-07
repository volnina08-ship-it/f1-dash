# APEXODDS — F1 Live Probability Engine

Telemetry-driven, live F1 race simulator and probability calculator: the
F1 live-timing leaderboard experience, extended with what F1 doesn't show —
**per-driver win / podium / top-10 probabilities recomputed live from Monte
Carlo simulation** at every relevant event (new lap, pit stop, SC/VSC,
overtake, rain).

- **Phase 0 (this codebase):** historical ETL → component models →
  vectorized Monte Carlo engine → backtest/replay harness with calibration
  reports. GO/NO-GO gate: beat naive baselines mid-race with a reliability
  curve within ±5%.
- **Phase 1:** replay-mode web dashboard, then live operation on OpenF1
  real-time data.

## Quickstart

```bash
uv venv && uv pip install -e . --group dev
pytest                              # full offline test suite (synthetic race)
python scripts/benchmark_engine.py  # engine speed target: <2 s per recompute
```

Simulate a race from priors in a few lines:

```python
from apexodds.data.circuits import circuit_params
from apexodds.models import ModelBundle
from apexodds.sim import outputs
from apexodds.sim.engine import SimConfig, simulate
from apexodds.sim.state import DriverState, grid_state

circuit = circuit_params("monza")
grid = [DriverState(driver_number=i + 1, code=f"D{i + 1:02d}",
                    pace_mean_s=90 + 0.07 * i) for i in range(20)]
state = grid_state("demo", circuit, grid)
result = simulate(state, ModelBundle.default(circuit), SimConfig(n_sims=3000, seed=1))
print(outputs.aggregate(result).to_frame("demo").head())
```

### Historical data + backtest (M1, M3-M4)

```bash
uv pip install -e '.[etl]'
python -m apexodds.data.fetch_fastf1 --season 2024            # → data/normalized/
python - <<'PY'
from apexodds.backtest.replay import replay_race
from apexodds.backtest.calibrate import evaluate_snapshots
from apexodds.backtest.report import race_report, calibration_report

snaps = replay_race("data/normalized/2024_01_R")   # → data/snapshots/
race_report(snaps, "reports")
calibration_report(evaluate_snapshots(snaps), "reports")
PY
```

### Replay API (Phase 1 skeleton)

```bash
uvicorn apexodds.api.main:app --reload
# GET /sessions, GET /snapshots/{session}/{lap}, WS /ws/replay/{session}?speed=2
```

## Layout

```
apexodds/            # Python package (the brief's packages/ layout, importable)
├── data/            # fetch_fastf1, fetch_openf1, normalize, db, live_client, circuits
├── models/          # pace, tyres, pitloss, hazards, overtake, weather (v2 stub)
├── sim/             # state, engine (numpy Monte Carlo), strategy, outputs
├── backtest/        # replay, calibrate, report — Phase 0 deliverable
└── api/             # FastAPI + WebSocket (replay mode today, live in M6)
apps/web/            # Next.js dashboard (Phase 1)
db/schema.sql        # Supabase (Postgres) normalized core
notebooks/           # exploration
scripts/             # benchmark_engine.py
tests/               # offline suite incl. a no-look-ahead proof
```

## Data sources

| Source | Use | Notes |
|---|---|---|
| FastF1 | 2018+ laps/tyres/weather/results | model training + backtests, local cache |
| OpenF1 REST | 2023+ gaps/stints/pits/positions | free tier: 3 req/s, 30 req/min (client enforces) |
| Jolpica (Ergast) | 1950+ calendars/results | long-run priors |
| OpenF1 realtime (paid) / livef1 | Phase 1 live | ~3 s latency; unofficial |

Data dumps live under `data/` (gitignored); Supabase is the durable copy
(`SUPABASE_DB_URL`, see `.env.example`).

## Status & risks

Milestones M1-M6 and open risks (2026 regulation change → weak historical
priors, wet races handled by uncertainty inflation only, data licensing
before any commercial step) are tracked in [CLAUDE.md](CLAUDE.md) and the
project brief.

*Unofficial project; not associated with Formula 1. No F1 trademarks. Phase
0-1 is non-commercial (development, calibration, demo).*
