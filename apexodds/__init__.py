"""APEXODDS — telemetry-driven live F1 race simulator and probability engine.

Phase 0: historical ETL, component models, Monte Carlo engine, backtest/calibration.
Phase 1: live ingestion + FastAPI/WebSocket + web dashboard.

Subpackages (mirrors the technical brief's ``packages/`` layout):

- :mod:`apexodds.data`     — ETL + data layer (FastF1, OpenF1, Supabase, normalization)
- :mod:`apexodds.models`   — learned component models (pace, tyres, pit loss, hazards, overtake)
- :mod:`apexodds.sim`      — vectorized Monte Carlo engine (race state, engine, strategy, outputs)
- :mod:`apexodds.backtest` — replay harness, calibration metrics, reports
- :mod:`apexodds.api`      — FastAPI + WebSocket service (Phase 1)

Conventions:

- Persisted data (parquet/Postgres) stores times as integer **milliseconds** (``*_ms``).
- All in-memory simulation math uses float **seconds**. Convert at the data boundary only.
- Anything that consumes historical data during a replay must be free of look-ahead bias:
  at lap ``k`` only rows with ``lap_number <= k`` may be visible.
"""

__version__ = "0.1.0"
