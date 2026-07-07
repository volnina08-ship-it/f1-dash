"""ETL + data layer.

- :mod:`apexodds.data.fetch_fastf1` — historical download → normalized parquet
- :mod:`apexodds.data.fetch_openf1` — rate-limit-aware OpenF1 REST client
- :mod:`apexodds.data.normalize`    — source-specific frames → internal schema
- :mod:`apexodds.data.circuits`     — circuit_params seed table + loader
- :mod:`apexodds.data.db`           — Supabase (Postgres) read/write helpers
- :mod:`apexodds.data.live_client`  — Phase 1 live stream sources (+ replay source)

Internal schema convention: times are integer milliseconds (``*_ms``),
session keys are ``"{year}_{round:02d}_{session_type}"`` (e.g. ``2024_05_R``).
"""
