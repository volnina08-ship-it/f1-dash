"""Replay harness: end-to-end on a synthetic race + the no-look-ahead proof."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from conftest import DNF_DRIVER, DNF_LAP, build_synthetic_session

from apexodds.backtest.calibrate import evaluate_snapshots
from apexodds.backtest.replay import RaceReplay, ReplayConfig

FAST_CFG = ReplayConfig(n_sims=300, seed=7, snapshot_every=5)


@pytest.fixture(scope="module")
def snapshots(synthetic_session):
    return RaceReplay(synthetic_session, config=FAST_CFG).run()


def test_replay_produces_valid_snapshots(snapshots):
    snaps = snapshots
    assert snaps["win_p"].between(0, 1).all()
    sums = snaps.groupby("lap")["win_p"].sum()
    assert np.allclose(sums, 1.0, atol=1e-9)
    assert (snaps.groupby("lap")["driver_number"].count() == 20).all()
    # Exactly one actual winner flagged.
    lap0 = snaps[snaps["lap"] == 0]
    assert lap0["actual_win"].sum() == 1.0


def test_replay_converges_on_the_winner(snapshots):
    """The model should increasingly favor the true winner of a
    dominant-pace synthetic race (if not, something is broken)."""
    snaps = snapshots
    mid = snaps[snaps["lap"] == 30]
    winner_mid = mid[mid["actual_win"] == 1.0].iloc[0]
    assert winner_mid["win_p"] == mid["win_p"].max()
    late = snaps[snaps["lap"] == 35]
    winner_late = late[late["actual_win"] == 1.0].iloc[0]
    assert winner_late["win_p"] > 0.5


def test_replay_tracks_retirement(snapshots):
    snaps = snapshots
    dnf_number = DNF_DRIVER + 1
    after = snaps[(snaps["lap"] >= DNF_LAP + 1) & (snaps["driver_number"] == dnf_number)]
    assert len(after) > 0
    assert (after["win_p"] == 0.0).all()
    assert (after["dnf_p"] == 1.0).all()


def test_replay_beats_naive_baselines_mid_race(snapshots):
    """Phase 0 gate on the synthetic race (sanity check of the harness)."""
    snaps = snapshots
    summary = evaluate_snapshots(snaps)
    m = summary.metrics
    mid = m[(m["target"] == "win") & (m["phase"].isin(["25-50%", "50-75%"]))]
    model = mid[mid["source"] == "model"]["brier"].mean()
    grid = mid[mid["source"] == "grid"]["brier"].mean()
    assert model < grid


def test_no_look_ahead(synthetic_session, tmp_path):
    """Snapshots up to lap k must be identical when the future is rewritten.

    We clone the session and make every lap AFTER the cut wildly different
    (the eventual winner suddenly 20 s/lap slower). If any pipeline stage
    peeked past the current lap, pre-cut snapshots would change.
    """
    cut = 20
    original = RaceReplay(synthetic_session, config=FAST_CFG).run()

    mutated_dir = build_synthetic_session(tmp_path / "2024_99_R")
    laps = pd.read_parquet(mutated_dir / "laps.parquet")
    future = laps["lap_number"] > cut
    winner = laps["driver_number"] == 1
    laps.loc[future & winner, "lap_time_ms"] += 20_000
    laps.loc[future, "track_status"] = "4"  # even the flags differ
    laps.to_parquet(mutated_dir / "laps.parquet", index=False)

    mutated = RaceReplay(mutated_dir, config=FAST_CFG).run()

    cols = ["lap", "driver_number", "win_p", "podium_p", "top10_p", "exp_finish",
            "current_position", "pit_window_p50", "track_status"]
    a = original[original["lap"] <= cut][cols].reset_index(drop=True)
    b = mutated[mutated["lap"] <= cut][cols].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)
