# APEXODDS — project context

Live F1 race simulator + probability engine (win/podium/top10/xP per driver,
recomputed every lap from Monte Carlo simulation). Phase 0 = backtest engine
on historical data; Phase 1 = live dashboard. Full spec: the technical brief
(F1 Live Probability Engine, Fázis 0 + Fázis 1).

## Architecture (data flows left → right)

```
FastF1 / OpenF1 / Jolpica
   → apexodds.data (fetch_*, normalize)        raw + normalized parquet, Supabase
   → apexodds.models (pace, tyres, pitloss,    fittable components, JSON params,
     hazards, overtake, weather)               hand-set priors as fallback
   → apexodds.sim (state → engine → outputs)   RaceState → N vectorized worlds → probs
   → apexodds.backtest (replay, calibrate,     lap-by-lap replay → sim_snapshots →
     report)                                   Brier/logloss vs baselines → md/png
   → apexodds.api (FastAPI + WS)               replay stream today, live in M6
```

The engine consumes **only** `RaceState` + `ModelBundle` + `SimConfig`; the
replay harness and the future live pipeline are just two different
`RaceState` producers. Keep it that way.

## Hard rules

- **No look-ahead in replay**: at lap k only rows with `lap_number <= k`
  may influence the state (`RaceReplay._visible` is the single gate;
  `tests/test_replay.py::test_no_look_ahead` proves it — keep that test).
- **Units**: persisted data is integer milliseconds (`*_ms`); all sim math
  is float seconds. Convert only at the data boundary (normalize/db).
- **Vectorize**: engine hot path is (n_sims × drivers) numpy; no Python
  loops over worlds. Perf gate: <2 s per full recompute at n_sims=3000
  (`python scripts/benchmark_engine.py`).
- **Determinism**: everything stochastic takes a seed; same seed + state →
  identical results (tested).
- Session keys: `"{year}_{round:02d}_{session_type}"` (e.g. `2024_05_R`).
- OpenF1 free tier: 3 req/s, 30 req/min — always go through
  `OpenF1Client` (rate-limited), cache dumps locally, never hammer.
- Defaults in models/circuits CSV are **priors**, clearly replaceable by
  `fit()` outputs; don't silently bake fitted values into code.
- F1 trademarks: never. Footer/disclaimers: "Unofficial, not associated
  with Formula 1". Phase 0-1 non-commercial.

## Commands

```bash
uv venv && uv pip install -e . --group dev   # setup (extras: .[etl] .[db] .[live])
pytest                                       # offline suite, no network needed
ruff check apexodds tests                    # lint
python scripts/benchmark_engine.py           # engine perf
python -m apexodds.data.fetch_fastf1 --season 2024        # ETL (needs .[etl])
python -m apexodds.data.fetch_openf1 --year 2024          # OpenF1 dumps
python -m apexodds.data.db --init                         # apply db/schema.sql
uvicorn apexodds.api.main:app --reload                    # replay API
```

Local data lake (gitignored): `data/raw/`, `data/normalized/{session_key}/`,
`data/snapshots/{session_key}.parquet`, `data/models/`, `data/fastf1_cache/`.

## Milestones / status

- M1 ETL 2022-2025 → parquet + Supabase (fetchers ready; bulk run pending)
- M2 train components (fit() functions ready; training runs pending)
- M3 engine + replay end-to-end — **done, tested on synthetic race**
- M4 backtest 60+ races + calibration report → GO/NO-GO (harness ready)
- M5 replay-mode web dashboard — **built** (`apps/web`, Next.js 15 +
  Framer Motion; demo race in `src/data/race.json` from
  `scripts/make_demo_race.py`; deploy = Vercel import, root dir `apps/web`)
- M6 first live GP weekend (OpenF1 realtime subscription needed)

## Known quirks / decisions

- The brief's `packages/` directory is implemented as the importable
  `apexodds/` package (`packages/data/...` → `apexodds/data/...`).
- Classification of DNFs: ranked behind finishers by retirement lap; the
  "90% distance = classified" rule is simplified away (v1).
- Wet races: no wet model in v1 — rain only inflates pace variance and
  hazards (`models/weather.py`). Flag such races in calibration reports.
- 2026 regulations: historical tyre/pace priors are weak for 2026 — the
  within-weekend online fit path (M2) matters more than usual.
- `sim/engine.py` resolves on-track passing with odd-even transposition
  rounds gated by the overtake model; pit-lane position changes are free.
  `sort_rounds` caps on-track positions gained per lap (default 5).
