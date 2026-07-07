"""Monte Carlo engine invariants and directional behavior."""

from __future__ import annotations

import numpy as np
import pytest
from conftest import TOTAL_LAPS, make_grid

from apexodds.models import ModelBundle
from apexodds.sim import outputs
from apexodds.sim.engine import SimConfig, simulate
from apexodds.sim.state import CircuitParams, grid_state


def run(state, n_sims=1500, seed=42, **kwargs):
    models = ModelBundle.default(state.circuit)
    result = simulate(state, models, SimConfig(n_sims=n_sims, seed=seed, **kwargs))
    return result, outputs.aggregate(result)


def test_positions_are_permutations(fresh_state):
    result, _ = run(fresh_state, n_sims=200)
    pos = np.sort(result.final_position, axis=1)
    expected = np.arange(1, fresh_state.n_drivers + 1)
    assert (pos == expected).all()


def test_probability_identities(fresh_state):
    _, probs = run(fresh_state)
    win = sum(d.win_p for d in probs.drivers)
    podium = sum(d.podium_p for d in probs.drivers)
    top10 = sum(d.top10_p for d in probs.drivers)
    assert win == pytest.approx(1.0, abs=1e-9)
    assert podium == pytest.approx(3.0, abs=1e-9)
    assert top10 == pytest.approx(10.0, abs=1e-9)
    for d in probs.drivers:
        assert 0.0 <= d.win_p <= 1.0
        assert d.win_p <= d.podium_p + 1e-12
        assert d.podium_p <= d.top10_p + 1e-12


def test_determinism(fresh_state):
    r1, _ = run(fresh_state, n_sims=300, seed=7)
    r2, _ = run(fresh_state, n_sims=300, seed=7)
    assert (r1.final_position == r2.final_position).all()
    assert (r1.next_pit_lap == r2.next_pit_lap).all()


def test_dominant_leader_wins(circuit):
    grid = make_grid()
    grid[0].pace_mean_s -= 1.5  # 1.5 s/lap faster than the field
    state = grid_state("t", circuit, grid, total_laps=TOTAL_LAPS)
    _, probs = run(state)
    assert probs.driver("D01").win_p > 0.85


def test_faster_driver_usually_beats_slower(fresh_state):
    _, probs = run(fresh_state)
    h2h = probs.h2h_frame()
    # D01 is 0.08 s/lap faster than D02 and 1.5 s/lap faster than D20.
    assert h2h.loc["D01", "D20"] > 0.9
    assert h2h.loc["D01", "D02"] > 0.5


def test_overtake_difficulty_protects_leader():
    """A slower leader survives far more often at a Monaco-like circuit."""
    def leader_win(difficulty: float) -> float:
        circuit = CircuitParams(
            circuit_id="x", lap_count=40, overtake_difficulty=difficulty,
            sc_prob_race=0.0, vsc_prob_race=0.0,
        )
        grid = make_grid(6)
        grid[0].pace_mean_s += 0.35  # pole sitter is slower than P2
        state = grid_state("t", circuit, grid, total_laps=40)
        models = ModelBundle.default(circuit)
        # No first-lap chaos/DNF noise: isolate on-track passing.
        cfg = SimConfig(n_sims=1500, seed=11, lap1_extra_std_s=0.0)
        result = simulate(state, models, cfg)
        return float((result.final_position[:, 0] == 1).mean())

    easy, monaco = leader_win(0.15), leader_win(0.97)
    assert monaco > easy + 0.15
    assert easy < 0.45


def test_retired_driver_never_wins(fresh_state):
    state = fresh_state.copy()
    state.drivers[4].retired = True
    _, probs = run(state, n_sims=400)
    d = probs.driver(state.drivers[4].code)
    assert d.win_p == 0.0
    assert d.dnf_p == 1.0
    assert d.exp_finish > state.n_drivers - 4


def test_everyone_pits_at_least_once(fresh_state):
    """Two-dry-compound rule: finishers must have stopped at least once."""
    result, _ = run(fresh_state, n_sims=400)
    finished = ~result.dnf
    assert (result.pit_count[finished] >= 1).mean() > 0.99


def test_pit_windows_are_plausible(fresh_state):
    _, probs = run(fresh_state, n_sims=400)
    for d in probs.drivers:
        if d.pit_prob > 0.5:
            assert 1 <= d.pit_window_open <= d.pit_window_p50 <= d.pit_window_close <= TOTAL_LAPS


def test_mid_race_state_simulates(circuit):
    """Simulating from lap 30 with gaps/tyre state behaves sanely."""
    grid = make_grid(10)
    state = grid_state("t", circuit, grid, total_laps=TOTAL_LAPS)
    state.lap = 30
    for i, d in enumerate(state.drivers):
        d.gap_to_leader_s = 2.5 * i
        d.tyre_age = 10
        d.compound = "HARD"
        d.used_compounds = ("MEDIUM",)
        d.pit_count = 1
    _, probs = run(state, n_sims=600)
    lead = probs.driver("D01")
    assert lead.win_p > 0.55  # fastest + in the lead with 20 to go
    assert sum(d.win_p for d in probs.drivers) == pytest.approx(1.0, abs=1e-9)


def test_sc_state_bunches_field(circuit):
    grid = make_grid(10)
    state = grid_state("t", circuit, grid, total_laps=TOTAL_LAPS)
    state.lap = 20
    for i, d in enumerate(state.drivers):
        d.gap_to_leader_s = 4.0 * i  # big spread pre-SC
    state.track_status = "SC"
    state.intervention_laps_remaining = 3
    _, probs_sc = run(state, n_sims=800, seed=5)
    state_green = state.copy()
    state_green.track_status = "GREEN"
    _, probs_green = run(state_green, n_sims=800, seed=5)
    # SC erases the gaps → the leader is less safe than under green.
    assert probs_sc.driver("D01").win_p < probs_green.driver("D01").win_p
