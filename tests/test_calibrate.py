"""Calibration metric correctness and baseline construction."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apexodds.backtest.calibrate import (
    add_baselines,
    brier_score,
    evaluate_snapshots,
    expected_calibration_error,
    log_loss,
    max_calibration_gap,
    reliability_table,
)


def test_brier_and_logloss_known_values():
    p = np.array([1.0, 0.0, 0.5])
    y = np.array([1.0, 0.0, 1.0])
    assert brier_score(p, y) == pytest.approx(0.25 / 3)
    assert log_loss(np.array([0.5]), np.array([1.0])) == pytest.approx(np.log(2))


def test_perfect_predictions_score_zero():
    y = np.array([1.0, 0.0, 1.0, 0.0])
    assert brier_score(y, y) == 0.0
    assert log_loss(y, y) < 1e-5


def test_reliability_table_recovers_frequencies():
    rng = np.random.default_rng(0)
    p = rng.uniform(0, 1, 50_000)
    y = (rng.random(50_000) < p).astype(float)  # perfectly calibrated
    table = reliability_table(p, y)
    assert len(table) == 10
    assert (table["p_mean"] - table["y_rate"]).abs().max() < 0.03
    assert expected_calibration_error(p, y) < 0.02
    assert max_calibration_gap(p, y) < 0.03


def _fake_snapshots() -> pd.DataFrame:
    rows = []
    for lap in range(0, 50, 5):
        for i in range(10):
            rows.append(
                {
                    "session_key": "s",
                    "lap": lap,
                    "total_laps": 50,
                    "driver_number": i + 1,
                    "code": f"D{i + 1:02d}",
                    "current_position": i + 1,
                    "grid_position": i + 1,
                    "win_p": 0.55 if i == 0 else 0.05,
                    "podium_p": min(0.9, 0.7 - 0.05 * i) if i < 5 else 0.1,
                    "top10_p": 0.95,
                    "actual_win": 1.0 if i == 0 else 0.0,
                    "actual_podium": 1.0 if i < 3 else 0.0,
                    "actual_top10": 1.0,
                }
            )
    return pd.DataFrame(rows)


def test_add_baselines_shapes_and_ranges():
    df = add_baselines(_fake_snapshots())
    for col in (
        "baseline_leader_win_p",
        "baseline_leader_podium_p",
        "baseline_leader_top10_p",
        "baseline_grid_win_p",
        "baseline_grid_podium_p",
        "baseline_grid_top10_p",
    ):
        assert col in df.columns
        assert df[col].between(0, 1).all()
    # Grid-prior win probabilities renormalize to 1 per (session, lap).
    sums = df.groupby(["session_key", "lap"])["baseline_grid_win_p"].sum()
    assert np.allclose(sums, 1.0)
    # Leader baseline: P1 gets ~1 for the win.
    leader_rows = df[df["current_position"] == 1]
    assert (leader_rows["baseline_leader_win_p"] > 0.9).all()


def test_evaluate_snapshots_structure():
    summary = evaluate_snapshots(_fake_snapshots())
    m = summary.metrics
    assert set(m["source"].unique()) == {"model", "leader", "grid"}
    assert set(m["target"].unique()) == {"win", "podium", "top10"}
    assert (m["brier"] >= 0).all()
    assert "win" in summary.reliability
    # The stylized model here is confident-and-right → beats the grid prior.
    win = m[(m["target"] == "win") & (m["phase"] == "50-75%")].set_index("source")
    assert win.loc["model", "brier"] < win.loc["grid", "brier"]
