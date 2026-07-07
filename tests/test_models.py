"""Component model behavior: fits recover synthetic truths, priors are sane."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apexodds.models.hazards import HazardModel
from apexodds.models.overtake import OvertakeModel
from apexodds.models.pace import (
    LivePaceEstimator,
    PacePrior,
    clean_lap_mask,
    fuel_correct_s,
    fuel_penalty_s,
)
from apexodds.models.pitloss import PitLossModel
from apexodds.models.tyres import DegradationModel
from apexodds.sim.state import CircuitParams

# ------------------------------------------------------------------- tyres


def test_tyre_tables_monotone_in_age():
    model = DegradationModel()
    table = model.table(50)
    for row in table[:3]:  # dry compounds
        assert (np.diff(row) >= 0).all()


def test_tyre_fit_recovers_wear_rate():
    rng = np.random.default_rng(0)
    rows = []
    true_lin, true_quad = 0.045, 0.0015
    for stint in range(40):
        base = rng.uniform(88, 92)
        ages = np.arange(1, rng.integers(10, 25))
        times = base + true_lin * ages + true_quad * ages**2 + rng.normal(0, 0.15, len(ages))
        for a, t in zip(ages, times, strict=True):
            rows.append(
                {
                    "driver_number": stint % 20,
                    "stint_id": stint,
                    "compound": "MEDIUM",
                    "tyre_age": a,
                    "fuel_corrected_ms": t * 1000,
                }
            )
    fitted = DegradationModel().fit(pd.DataFrame(rows))
    assert fitted.curves["MEDIUM"].lin_s == pytest.approx(true_lin, abs=0.015)
    assert fitted.curves["MEDIUM"].quad_s == pytest.approx(true_quad, abs=0.001)


def test_tyre_json_roundtrip(tmp_path):
    model = DegradationModel()
    model.to_json(tmp_path / "tyres.json")
    loaded = DegradationModel.from_json(tmp_path / "tyres.json")
    assert loaded.curves == model.curves


# ----------------------------------------------------------------- pit loss


def test_pitloss_sampling_stats():
    model = PitLossModel(mean_s=22.0, std_s=0.8, slow_prob=0.05)
    rng = np.random.default_rng(1)
    samples = model.sample(rng, 20_000)
    assert samples.mean() == pytest.approx(22.0 + 0.05 * model.slow_extra_mean_s, abs=0.2)
    assert (samples >= 22.0 * 0.7).all()


def test_pitloss_fit():
    rng = np.random.default_rng(2)
    loss = rng.normal(21.0, 0.7, 300)
    loss[:20] += rng.exponential(5.0, 20)  # slow-stop tail
    fitted = PitLossModel.fit(pd.DataFrame({"total_loss_ms": loss * 1000}), "somewhere")
    assert fitted.mean_s == pytest.approx(21.0, abs=0.5)
    assert 0.01 <= fitted.slow_prob <= 0.25


# ------------------------------------------------------------------ hazards


def test_circuit_hazard_conversion():
    c = CircuitParams(circuit_id="x", lap_count=50, sc_prob_race=0.6)
    per_lap = c.sc_per_lap
    assert 1 - (1 - per_lap) ** 50 == pytest.approx(0.6, abs=1e-9)


def test_dnf_rates_shrink_small_samples():
    results = pd.DataFrame(
        {
            "driver_number": [1] * 2 + [2] * 30,
            "dnf": [True, True] + [False] * 30,
            "laps": 55,
        }
    )
    rates = HazardModel.fit_dnf_rates(results)
    # Two DNFs in two races must NOT give a ~100% race hazard after shrinkage.
    assert rates[1] < 0.005
    assert rates[2] < rates[1]


# ----------------------------------------------------------------- overtake


def test_overtake_probability_shape():
    model = OvertakeModel()
    easy = model.p_pass(1.0, 0.2)
    monaco = model.p_pass(1.0, 0.97)
    slow_attacker = model.p_pass(0.1, 0.2)
    assert easy > 4 * monaco
    assert easy > slow_attacker


def test_overtake_fit_recovers_direction():
    rng = np.random.default_rng(3)
    n = 4000
    pace = rng.uniform(-0.5, 2.0, n)
    diff = rng.uniform(0.1, 0.95, n)
    logit = -0.3 + 1.3 * pace - 3.9 * diff + 0.3
    passed = rng.random(n) < 1 / (1 + np.exp(-logit))
    fitted = OvertakeModel.fit(
        pd.DataFrame(
            {"pace_delta_s": pace, "difficulty": diff, "drs": 1.0, "passed": passed}
        )
    )
    assert fitted.pace_coef > 0.8
    assert fitted.difficulty_coef < -2.5


# --------------------------------------------------------------------- pace


def test_fuel_correction_is_larger_early():
    assert fuel_penalty_s(1, 57) > fuel_penalty_s(50, 57)
    raw = np.array([95.0, 95.0])
    corrected = fuel_correct_s(raw, np.array([1, 50]), 57)
    assert corrected[0] < corrected[1]  # early lap had more fuel to strip


def test_live_estimator_blends_prior_to_live():
    prior = PacePrior(mean_s={1: 92.0}, std_s={1: 0.4}, weight_laps=8.0)
    est = LivePaceEstimator(prior=prior)
    assert est.estimate(1)[0] == 92.0
    for _ in range(30):
        est.add_lap(1, 90.0)
    mean, std = est.estimate(1)
    assert mean == pytest.approx(90.0, abs=0.6)  # live data dominates
    assert std >= est.min_std_s


def test_clean_lap_mask_filters_junk():
    laps = pd.DataFrame(
        {
            "driver_number": [1] * 5,
            "lap_number": [1, 2, 3, 4, 5],
            "lap_time_ms": [95000, 90000, 90200, 96000, 104000],
            "is_pit_in": [False, False, False, True, False],
            "is_pit_out": [False, False, False, False, True],
            "track_status": ["1", "1", "1", "1", "1"],
        }
    )
    mask = clean_lap_mask(laps)
    assert mask.tolist() == [False, True, True, False, False]
