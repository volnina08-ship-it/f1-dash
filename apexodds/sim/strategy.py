"""In-sim pit strategy heuristics (vectorized over worlds × drivers).

Not an optimizer — the goal is a *plausible distribution* over strategies:
- stint-length targets per compound with per-world noise,
- opportunistic "cheap" stops under SC/VSC,
- the two-dry-compound rule enforced near the end,
- compound choice by matching nominal stint length to the laps remaining.

v1 is dry-race strategy only; wet running is handled by uncertainty
inflation (models/weather.py), not by inter/wet strategy switching.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Popcount lookup for 3-bit dry-compound usage masks (bit i == COMPOUNDS[i] used).
POPCOUNT = np.array([bin(i).count("1") for i in range(8)], dtype=np.int8)
N_DRY = 3  # SOFT, MEDIUM, HARD indices 0..2


@dataclass(frozen=True)
class StrategyParams:
    stint_noise_sigma: float = 0.14  # lognormal sigma on stint targets
    min_stint_laps: int = 5
    no_pit_window: int = 4  # never plan a stop with this few laps left
    # Stretch-to-finish: skip a wear-triggered stop when the current set can
    # reach the flag within this many laps past its target (teams nurse
    # tyres home instead of pitting from the lead at lap 46/50).
    stretch_tolerance_laps: int = 6
    # Cheap stop under interventions: eligible when tyre age exceeds this
    # fraction of the stint target, then taken with the given probability.
    sc_pit_age_frac: float = 0.40
    sc_pit_prob: float = 0.85
    vsc_pit_age_frac: float = 0.55
    vsc_pit_prob: float = 0.55
    # Fraction of the normal pit loss actually paid when stopping under
    # SC/VSC (the field is slowed, so the relative loss shrinks).
    sc_pit_loss_factor: float = 0.50
    vsc_pit_loss_factor: float = 0.70
    # Force a stop this many laps from the end if the two-compound rule is
    # still unsatisfied.
    rule_force_window: int = 10
    # Soft score nudge (seconds-ish units) against choices that keep the
    # two-compound rule unsatisfied while another stop is still likely.
    rule_soft_penalty: float = 6.0
    compound_choice_noise: float = 3.0


def draw_stint_targets(
    rng: np.random.Generator,
    compound_idx: np.ndarray,
    nominal_targets: np.ndarray,
    params: StrategyParams,
) -> np.ndarray:
    """Per-world stint-length target for the compound just fitted.

    ``compound_idx`` any-shape int array; ``nominal_targets`` (n_compounds,)
    from the tyre model. Lognormal noise gives each simulated world its own
    plan, which is what spreads the predicted pit window.
    """
    base = nominal_targets[compound_idx]
    noise = np.exp(rng.normal(0.0, params.stint_noise_sigma, size=compound_idx.shape))
    return np.maximum(base * noise, params.min_stint_laps)


def decide_pits(
    rng: np.random.Generator,
    tyre_age: np.ndarray,  # (N, D) age at the start of this lap
    stint_target: np.ndarray,  # (N, D)
    used_mask: np.ndarray,  # (N, D) uint8 dry-compound bits
    sc_active: np.ndarray,  # (N,) bool
    vsc_active: np.ndarray,  # (N,) bool
    laps_remaining: int,  # after the current lap completes
    alive: np.ndarray,  # (N, D) bool
    params: StrategyParams,
) -> np.ndarray:
    """Boolean (N, D): who comes in at the end of this lap."""
    age_next = tyre_age + 1
    age_at_flag = age_next + laps_remaining
    can_stretch = age_at_flag <= stint_target + params.stretch_tolerance_laps
    want = (age_next >= stint_target) & ~can_stretch

    cheap_sc = (
        sc_active[:, None]
        & (age_next >= params.sc_pit_age_frac * stint_target)
        & (rng.random(tyre_age.shape) < params.sc_pit_prob)
    )
    cheap_vsc = (
        vsc_active[:, None]
        & (age_next >= params.vsc_pit_age_frac * stint_target)
        & (rng.random(tyre_age.shape) < params.vsc_pit_prob)
    )

    rule_unsat = POPCOUNT[used_mask] < 2
    forced = rule_unsat & (1 <= laps_remaining) & (laps_remaining <= params.rule_force_window)

    planned = (want | cheap_sc | cheap_vsc) & (age_next >= params.min_stint_laps)
    planned &= laps_remaining > params.no_pit_window
    return alive & (planned | (forced & (age_next >= 2)))


def choose_next_compound(
    rng: np.random.Generator,
    laps_remaining: int,
    used_mask: np.ndarray,  # (M,) uint8 for the pitting subset
    nominal_targets: np.ndarray,  # (n_compounds,)
    params: StrategyParams,
) -> np.ndarray:
    """Dry compound index (M,) for cars pitting now.

    Score each dry compound by |nominal stint − laps remaining| plus noise;
    penalize choices that would leave the two-compound rule unsatisfied —
    softly while more stops are plausible, prohibitively when this is
    realistically the last stop.
    """
    m = len(used_mask)
    dry_targets = nominal_targets[:N_DRY]  # (3,)
    score = np.abs(dry_targets[None, :] - laps_remaining).astype(np.float64)
    score = score + rng.normal(0.0, params.compound_choice_noise, size=(m, N_DRY))

    bits = (1 << np.arange(N_DRY, dtype=np.uint8))[None, :]  # (1, 3)
    still_unsat = POPCOUNT[used_mask[:, None] | bits] < 2  # (M, 3)
    last_stop_horizon = float(dry_targets.max()) + 6.0
    penalty = np.where(laps_remaining <= last_stop_horizon, 1e6, params.rule_soft_penalty)
    score = score + still_unsat * penalty

    return np.argmin(score, axis=1).astype(np.int8)
