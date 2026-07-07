"""Phase 0 main deliverable: replay harness, calibration, reports.

- :mod:`apexodds.backtest.replay`    — plays a historical race as if live,
  runs the full pipeline each lap, emits sim_snapshots
- :mod:`apexodds.backtest.calibrate` — Brier / log loss / reliability vs
  naive baselines, bucketed by race phase
- :mod:`apexodds.backtest.report`    — markdown + PNG reports (win-prob
  time series, reliability diagrams)
"""
