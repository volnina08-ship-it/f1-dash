"""Weather / track evolution — v1 stub.

v1 policy per the brief: no full wet-race model. Rain (falling or
threatening) only *inflates uncertainty*: wider pace noise and higher
intervention/DNF hazards, which correctly fattens the outcome
distributions. A proper wet model (crossover lap, inter/wet pace,
drying line, track evolution) is v2.
"""

from __future__ import annotations

from dataclasses import dataclass

from apexodds.sim.state import Weather


@dataclass(frozen=True)
class UncertaintyInflation:
    pace_std_multiplier: float = 1.0
    hazard_multiplier: float = 1.0


def uncertainty_inflation(weather: Weather) -> UncertaintyInflation:
    """Map current weather to (pace-noise, hazard) multipliers."""
    if weather.rainfall:
        return UncertaintyInflation(pace_std_multiplier=2.2, hazard_multiplier=3.0)
    p = min(max(weather.rain_prob, 0.0), 1.0)
    return UncertaintyInflation(
        pace_std_multiplier=1.0 + 1.2 * p,
        hazard_multiplier=1.0 + 2.0 * p,
    )
