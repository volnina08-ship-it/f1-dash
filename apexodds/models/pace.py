"""Driver pace: fuel correction, pre-race priors, live in-race estimation.

Reference frame used everywhere: a driver's *base pace* is the expected lap
time with **zero fuel on fresh reference tyres (MEDIUM)** on this circuit.
The engine adds fuel and tyre effects back on top of it, so estimation here
must strip exactly those effects (same formulas, shared constants).

Live estimation is a rolling robust estimate over the last clean laps,
Bayesian-blended with the pre-race prior: early in the race the prior
dominates; after ~10-15 clean laps the live pace takes over.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

FUEL_EFFECT_S_PER_KG = 0.033  # ~0.03-0.035 s/kg; calibrate per circuit later
FUEL_START_KG = 100.0

# Track statuses considered green in the internal schema.
GREEN_STATUSES = {"1", "GREEN", "ALLCLEAR", ""}


def fuel_mass_kg(lap: np.ndarray | float, total_laps: int, start_kg: float = FUEL_START_KG):
    """Approximate fuel on board while driving lap ``lap`` (1-indexed)."""
    lap = np.asarray(lap, dtype=np.float64)
    frac = np.clip((total_laps - lap + 0.5) / total_laps, 0.0, 1.0)
    return start_kg * frac


def fuel_penalty_s(
    lap: np.ndarray | float,
    total_laps: int,
    effect: float = FUEL_EFFECT_S_PER_KG,
    start_kg: float = FUEL_START_KG,
):
    return effect * fuel_mass_kg(lap, total_laps, start_kg)


def fuel_correct_s(
    lap_time_s: np.ndarray,
    lap_number: np.ndarray,
    total_laps: int,
    effect: float = FUEL_EFFECT_S_PER_KG,
) -> np.ndarray:
    """Raw lap times → zero-fuel equivalents."""
    return np.asarray(lap_time_s, dtype=np.float64) - fuel_penalty_s(
        lap_number, total_laps, effect
    )


def _bool_col(laps: pd.DataFrame, name: str) -> pd.Series:
    if name in laps.columns:
        return laps[name].fillna(False).astype(bool)
    return pd.Series(False, index=laps.index)


def clean_lap_mask(laps: pd.DataFrame, traffic_threshold_s: float = 3.5) -> pd.Series:
    """Representative racing laps: green flag, no in/out lap, not lap 1,
    and not more than ``traffic_threshold_s`` above the driver's rolling
    best (traffic / mistakes / damage)."""
    if "track_status" in laps.columns:
        status = laps["track_status"].fillna("").astype(str)
    else:
        status = pd.Series("", index=laps.index)
    green = status.str.upper().isin(GREEN_STATUSES)
    not_pit = ~_bool_col(laps, "is_pit_in") & ~_bool_col(laps, "is_pit_out")
    not_first = laps["lap_number"] > 1
    lap_s = laps["lap_time_ms"] / 1000.0
    rolling_best = lap_s.groupby(laps["driver_number"]).cummin()
    in_range = lap_s <= rolling_best + traffic_threshold_s
    return green & not_pit & not_first & in_range & lap_s.notna()


@dataclass
class PacePrior:
    """Pre-race base-pace prior per driver (mean, std, pseudo-lap weight)."""

    mean_s: dict[int, float] = field(default_factory=dict)
    std_s: dict[int, float] = field(default_factory=dict)
    # Prior weight in "equivalent clean laps": how many live laps it takes
    # for data to pull even with the prior.
    weight_laps: float = 8.0

    @classmethod
    def from_quali(
        cls,
        quali_best_s: dict[int, float],
        race_pace_factor: float = 1.06,
        gap_compression: float = 0.7,
        std_s: float = 0.35,
        weight_laps: float = 8.0,
    ) -> PacePrior:
        """Prior from qualifying times.

        Race base pace ≈ pole_time * factor, plus each driver's quali gap
        compressed (quali gaps overstate race-pace gaps). FP long runs and
        season form can refine this via :meth:`blend`.
        """
        finite = {k: v for k, v in quali_best_s.items() if v and np.isfinite(v)}
        if not finite:
            raise ValueError("no valid qualifying times")
        pole = min(finite.values())
        worst_gap = max(v - pole for v in finite.values()) if len(finite) > 1 else 1.5
        base = pole * race_pace_factor
        means, stds = {}, {}
        for n, q in quali_best_s.items():
            gap = (q - pole) if (q and np.isfinite(q)) else worst_gap + 0.5
            means[n] = base + gap_compression * gap
            stds[n] = std_s
        return cls(mean_s=means, std_s=stds, weight_laps=weight_laps)

    def blend(self, other_mean_s: dict[int, float], weight: float = 0.3) -> PacePrior:
        """Mix in another mean source (FP long runs, season form model)."""
        mixed = dict(self.mean_s)
        for n, m in other_mean_s.items():
            if n in mixed and np.isfinite(m):
                mixed[n] = (1 - weight) * mixed[n] + weight * m
            elif np.isfinite(m):
                mixed[n] = m
        return PacePrior(mean_s=mixed, std_s=dict(self.std_s), weight_laps=self.weight_laps)


@dataclass
class LivePaceEstimator:
    """Rolling robust pace estimate, blended with the prior.

    Feed it *base-pace observations*: raw lap time minus fuel penalty minus
    tyre delta (compound offset + wear), i.e. already in the reference frame.
    The replay/live pipeline does that correction using the tyre model.
    """

    prior: PacePrior
    window: int = 10
    min_std_s: float = 0.15
    max_std_s: float = 1.2
    _laps: dict[int, deque] = field(default_factory=lambda: defaultdict(lambda: deque(maxlen=50)))

    def add_lap(self, driver_number: int, base_pace_s: float) -> None:
        if np.isfinite(base_pace_s):
            self._laps[driver_number].append(float(base_pace_s))

    def n_laps(self, driver_number: int) -> int:
        return len(self._laps[driver_number])

    def estimate(self, driver_number: int) -> tuple[float, float]:
        """Posterior (mean, std) of the driver's base pace."""
        prior_mean = self.prior.mean_s.get(driver_number, np.nan)
        prior_std = self.prior.std_s.get(driver_number, 0.4)
        obs = list(self._laps[driver_number])[-self.window:]
        if not obs:
            if np.isnan(prior_mean):
                raise KeyError(f"no prior and no laps for driver {driver_number}")
            return float(prior_mean), float(prior_std)
        arr = np.asarray(obs, dtype=np.float64)
        live_mean = float(np.median(arr))
        mad = float(np.median(np.abs(arr - live_mean))) * 1.4826
        live_std = float(np.clip(mad if mad > 0 else prior_std, self.min_std_s, self.max_std_s))
        if np.isnan(prior_mean):
            return live_mean, live_std
        # Confidence grows with ALL clean laps seen (the location estimate
        # stays windowed for responsiveness): after ~10-15 laps live pace
        # outweighs the prior, per the brief.
        n = self.n_laps(driver_number)
        w = n / (n + self.prior.weight_laps)
        mean = w * live_mean + (1 - w) * float(prior_mean)
        std = float(np.clip(w * live_std + (1 - w) * prior_std, self.min_std_s, self.max_std_s))
        return mean, std
