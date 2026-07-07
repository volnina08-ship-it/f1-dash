"""Strategy heuristics: pit triggers, rule enforcement, compound choice."""

from __future__ import annotations

import numpy as np

from apexodds.models.tyres import DegradationModel
from apexodds.sim.strategy import (
    StrategyParams,
    choose_next_compound,
    decide_pits,
    draw_stint_targets,
)

P = StrategyParams()


def test_stint_targets_positive_and_spread():
    rng = np.random.default_rng(0)
    nominals = DegradationModel().stint_targets(57)
    idx = np.zeros((500, 3), dtype=np.int8)  # SOFT
    targets = draw_stint_targets(rng, idx, nominals, P)
    assert (targets >= P.min_stint_laps).all()
    assert targets.std() > 0.5  # per-world plans differ


def test_worn_tyres_trigger_pit():
    rng = np.random.default_rng(1)
    n, d = 200, 4
    age = np.full((n, d), 30, dtype=np.int16)
    target = np.full((n, d), 22.0)
    used = np.full((n, d), 0b010, dtype=np.uint8)  # only MEDIUM used
    quiet = np.zeros(n, dtype=bool)
    pits = decide_pits(rng, age, target, used, quiet, quiet, 20, np.ones((n, d), bool), P)
    assert pits.all()


def test_no_pit_in_final_laps_when_rule_satisfied():
    rng = np.random.default_rng(2)
    n, d = 200, 4
    age = np.full((n, d), 30, dtype=np.int16)
    target = np.full((n, d), 22.0)
    used = np.full((n, d), 0b011, dtype=np.uint8)  # two compounds used
    quiet = np.zeros(n, dtype=bool)
    pits = decide_pits(rng, age, target, used, quiet, quiet, 2, np.ones((n, d), bool), P)
    assert not pits.any()


def test_rule_forces_late_stop():
    rng = np.random.default_rng(3)
    n, d = 200, 4
    age = np.full((n, d), 12, dtype=np.int16)
    target = np.full((n, d), 40.0)  # nobody would stop on wear alone
    used = np.full((n, d), 0b001, dtype=np.uint8)  # one compound so far
    quiet = np.zeros(n, dtype=bool)
    pits = decide_pits(rng, age, target, used, quiet, quiet, 8, np.ones((n, d), bool), P)
    assert pits.all()


def test_sc_invites_cheap_stop():
    rng = np.random.default_rng(4)
    n, d = 4000, 1
    age = np.full((n, d), 14, dtype=np.int16)
    target = np.full((n, d), 24.0)  # not due yet on wear
    used = np.full((n, d), 0b010, dtype=np.uint8)
    sc = np.ones(n, dtype=bool)
    quiet = np.zeros(n, dtype=bool)
    under_sc = decide_pits(rng, age, target, used, sc, quiet, 30, np.ones((n, d), bool), P)
    under_green = decide_pits(
        rng, age, target, used, quiet, quiet, 30, np.ones((n, d), bool), P
    )
    assert under_sc.mean() > 0.6
    assert under_green.mean() == 0.0


def test_compound_choice_respects_rule():
    rng = np.random.default_rng(5)
    nominals = DegradationModel().stint_targets(57)
    # Only MEDIUM used, ~25 laps left → must NOT pick MEDIUM again.
    used = np.full(300, 0b010, dtype=np.uint8)
    choice = choose_next_compound(rng, 25, used, nominals, P)
    assert (choice != 1).all()
    # Rule satisfied → free choice, and short remaining favors softer tyres.
    used2 = np.full(300, 0b011, dtype=np.uint8)
    choice2 = choose_next_compound(rng, 12, used2, nominals, P)
    assert (choice2 == 0).mean() > 0.5
