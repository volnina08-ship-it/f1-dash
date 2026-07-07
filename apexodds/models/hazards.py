"""Safety car / VSC / DNF hazard models.

Circuit-level: constant per-lap hazards for SC and VSC derived from
per-race appearance probabilities (Baku ≠ Barcelona), with a first-lap
multiplier (lap-1 incidents are far more likely). Deployments are also
triggered conditionally on DNFs inside the engine.

Driver-level: per-lap retirement hazard combining car reliability (team)
and driver incident-proneness, fitted from season results.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from apexodds.sim.state import CircuitParams

# ~7% of car-starts end in DNF in the modern era → per-lap ≈ 0.0012 over ~57 laps.
DEFAULT_DNF_PER_LAP = 0.0012


@dataclass
class HazardModel:
    sc_per_lap: float = 0.010
    vsc_per_lap: float = 0.008
    lap1_multiplier: float = 8.0
    # Probability that a DNF immediately triggers an intervention.
    p_sc_given_dnf: float = 0.45
    p_vsc_given_dnf: float = 0.30
    red_flag_prob_race: float = 0.04  # informational in v1 (not simulated)
    # driver_number -> per-lap DNF hazard; fall back to the default.
    dnf_per_lap: dict[int, float] = field(default_factory=dict)

    @classmethod
    def from_circuit(
        cls, circuit: CircuitParams, dnf_per_lap: dict[int, float] | None = None
    ) -> HazardModel:
        return cls(
            sc_per_lap=circuit.sc_per_lap,
            vsc_per_lap=circuit.vsc_per_lap,
            lap1_multiplier=circuit.lap1_hazard_multiplier,
            dnf_per_lap=dict(dnf_per_lap or {}),
        )

    def dnf_array(self, driver_numbers: list[int]) -> np.ndarray:
        return np.array(
            [self.dnf_per_lap.get(n, DEFAULT_DNF_PER_LAP) for n in driver_numbers],
            dtype=np.float64,
        )

    # ------------------------------------------------------------------ fit

    @staticmethod
    def fit_dnf_rates(
        results: pd.DataFrame,
        prior_races: float = 20.0,
        prior_rate: float = 0.07,
    ) -> dict[int, float]:
        """Per-driver DNF-per-lap hazard from a results table.

        ``results`` needs ``driver_number``, ``dnf`` (bool) and ``laps``
        (laps completed, for exposure). Shrunk toward the field-wide prior
        with ``prior_races`` pseudo-races so small samples stay sane.
        """
        rates: dict[int, float] = {}
        for driver, g in results.groupby("driver_number"):
            dnfs = float(g["dnf"].sum())
            races = float(len(g))
            race_rate = (dnfs + prior_rate * prior_races) / (races + prior_races)
            mean_laps = float(g["laps"].clip(lower=1).mean()) or 55.0
            rates[int(driver)] = 1.0 - (1.0 - min(race_rate, 0.6)) ** (1.0 / mean_laps)
        return rates

    @staticmethod
    def fit_circuit_rates(
        race_control: pd.DataFrame, total_laps_by_session: dict[str, int]
    ) -> dict[str, float]:
        """Per-lap SC hazard for one circuit from race_control messages.

        ``race_control`` needs ``session_key`` and ``category`` (with
        'SafetyCar' / 'VirtualSafetyCar' style values, as normalized by
        apexodds.data.normalize). Returns {"sc_per_lap": ..., "vsc_per_lap": ...}.
        """
        n_sessions = len(total_laps_by_session)
        if n_sessions == 0:
            raise ValueError("no sessions supplied")
        total_laps = sum(total_laps_by_session.values())
        cat = race_control["category"].astype(str).str.upper()
        sc_events = race_control[cat.str.contains("SAFETYCAR") & ~cat.str.contains("VIRTUAL")]
        vsc_events = race_control[cat.str.contains("VIRTUAL")]
        # Count deployment periods, not messages.
        sc_races = sc_events.groupby("session_key").size().clip(upper=3).sum()
        vsc_races = vsc_events.groupby("session_key").size().clip(upper=3).sum()
        return {
            "sc_per_lap": float(np.clip((sc_races + 0.5) / (total_laps + 50), 1e-4, 0.05)),
            "vsc_per_lap": float(np.clip((vsc_races + 0.5) / (total_laps + 50), 1e-4, 0.05)),
        }

    # ------------------------------------------------------- serialization

    def to_json(self, path: str | Path) -> None:
        payload = asdict(self)
        payload["dnf_per_lap"] = {str(k): v for k, v in self.dnf_per_lap.items()}
        Path(path).write_text(json.dumps(payload, indent=2))

    @classmethod
    def from_json(cls, path: str | Path) -> HazardModel:
        payload = json.loads(Path(path).read_text())
        payload["dnf_per_lap"] = {int(k): v for k, v in payload.get("dnf_per_lap", {}).items()}
        return cls(**payload)
