"""Tyre degradation curves per compound (and per circuit category).

lap_time_delta(age) = offset + lin*age + quad*age² (+ cliff_rate*(age-cliff) beyond the cliff)

``offset`` is the fresh-tyre pace delta versus the reference compound
(MEDIUM == 0.0 by convention); the wear terms are the degradation proper.

Defaults are hand-set priors for the ground-effect era. ``fit`` re-estimates
the wear terms from stint data (fuel-corrected lap times); fresh-pace offsets
are only identifiable across compounds with car/driver controls, so they stay
priors unless explicitly overridden.

2026 note: new regulations + new compounds — treat all of this as a weak
prior and lean on within-weekend online fitting (FP long runs) next season.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

import numpy as np
import pandas as pd

from apexodds.sim.state import COMPOUND_INDEX, COMPOUNDS


@dataclass(frozen=True)
class CompoundCurve:
    offset_s: float = 0.0  # fresh pace vs reference compound
    lin_s: float = 0.03  # s/lap of age
    quad_s: float = 0.001  # s/lap²
    cliff_lap: int = 60  # age where the cliff starts
    cliff_rate_s: float = 0.25  # extra s/lap beyond the cliff
    # Rough stint length teams target on this compound, as fraction of race
    # distance (used by the in-sim strategy heuristics).
    stint_frac: float = 0.40

    def delta(self, age: np.ndarray | float) -> np.ndarray | float:
        age = np.asarray(age, dtype=np.float64)
        base = self.offset_s + self.lin_s * age + self.quad_s * age**2
        cliff = self.cliff_rate_s * np.clip(age - self.cliff_lap, 0.0, None)
        return base + cliff


DEFAULT_CURVES: dict[str, CompoundCurve] = {
    "SOFT": CompoundCurve(offset_s=-0.55, lin_s=0.055, quad_s=0.0022, cliff_lap=16,
                          cliff_rate_s=0.30, stint_frac=0.28),
    "MEDIUM": CompoundCurve(offset_s=0.0, lin_s=0.035, quad_s=0.0012, cliff_lap=26,
                            cliff_rate_s=0.22, stint_frac=0.42),
    "HARD": CompoundCurve(offset_s=0.55, lin_s=0.022, quad_s=0.0007, cliff_lap=38,
                          cliff_rate_s=0.18, stint_frac=0.58),
    # Wet compounds only matter once the v2 wet model lands; keep them sane.
    "INTERMEDIATE": CompoundCurve(offset_s=8.0, lin_s=0.05, quad_s=0.001, cliff_lap=30,
                                  cliff_rate_s=0.2, stint_frac=0.5),
    "WET": CompoundCurve(offset_s=14.0, lin_s=0.04, quad_s=0.001, cliff_lap=40,
                         cliff_rate_s=0.2, stint_frac=0.6),
}


@dataclass
class DegradationModel:
    curves: dict[str, CompoundCurve] = field(
        default_factory=lambda: dict(DEFAULT_CURVES)
    )
    circuit_category: str = "default"  # e.g. street / high-deg / low-deg

    def delta(self, compound: str, age: np.ndarray | float) -> np.ndarray | float:
        return self.curves[compound].delta(age)

    def table(self, max_age: int) -> np.ndarray:
        """(n_compounds, max_age+1) lookup of pace delta by compound index/age.

        Row order follows :data:`apexodds.sim.state.COMPOUNDS` so the engine
        can index it with its compound-index arrays directly.
        """
        ages = np.arange(max_age + 1, dtype=np.float64)
        return np.stack([self.curves[c].delta(ages) for c in COMPOUNDS])

    def stint_targets(self, lap_count: int) -> np.ndarray:
        """Nominal stint length in laps per compound index, for strategy."""
        return np.array(
            [max(3.0, self.curves[c].stint_frac * lap_count) for c in COMPOUNDS]
        )

    # ------------------------------------------------------------------ fit

    def fit(self, laps: pd.DataFrame, min_stint_laps: int = 5) -> DegradationModel:
        """Fit linear+quadratic wear per compound from clean race stints.

        ``laps`` uses the internal schema: driver identifier, ``compound``,
        ``tyre_age`` and ``fuel_corrected_ms`` columns; in/out laps and
        non-green laps should already be filtered (see
        :func:`apexodds.models.pace.clean_lap_mask`).

        Uses the within-stint transformation (demeaning per stint) so each
        stint's unknown base pace drops out; only the wear shape is
        estimated. Cliff parameters are not auto-fitted in v1.
        """
        required = {"driver_number", "compound", "tyre_age", "fuel_corrected_ms", "stint_id"}
        missing = required - set(laps.columns)
        if missing:
            raise ValueError(f"laps missing columns: {sorted(missing)}")

        new_curves = dict(self.curves)
        for compound, group in laps.groupby("compound"):
            if compound not in new_curves:
                continue
            rows = []
            for _, stint in group.groupby(["driver_number", "stint_id"]):
                if len(stint) < min_stint_laps:
                    continue
                t = stint["fuel_corrected_ms"].to_numpy(dtype=np.float64) / 1000.0
                a = stint["tyre_age"].to_numpy(dtype=np.float64)
                rows.append((t - t.mean(), a - a.mean(), a**2 - (a**2).mean()))
            if not rows:
                continue
            y = np.concatenate([r[0] for r in rows])
            x1 = np.concatenate([r[1] for r in rows])
            x2 = np.concatenate([r[2] for r in rows])
            design = np.column_stack([x1, x2])
            coef, *_ = np.linalg.lstsq(design, y, rcond=None)
            lin = float(np.clip(coef[0], 0.0, 0.5))
            quad = float(np.clip(coef[1], 0.0, 0.05))
            new_curves[compound] = replace(new_curves[compound], lin_s=lin, quad_s=quad)
        return DegradationModel(curves=new_curves, circuit_category=self.circuit_category)

    # ------------------------------------------------------- serialization

    def to_json(self, path: str | Path) -> None:
        payload = {
            "circuit_category": self.circuit_category,
            "curves": {c: asdict(v) for c, v in self.curves.items()},
        }
        Path(path).write_text(json.dumps(payload, indent=2))

    @classmethod
    def from_json(cls, path: str | Path) -> DegradationModel:
        payload = json.loads(Path(path).read_text())
        curves = {c: CompoundCurve(**v) for c, v in payload["curves"].items()}
        return cls(curves=curves, circuit_category=payload.get("circuit_category", "default"))


def compound_bit(compound: str) -> int:
    """Bit flag for dry-compound usage tracking (two-compound rule)."""
    idx = COMPOUND_INDEX[compound]
    return 1 << idx if idx < 3 else 0
