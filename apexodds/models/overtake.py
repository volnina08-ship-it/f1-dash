"""On-track overtaking model.

P(pass within one lap | attacker has caught the car ahead) as a logistic
function of the per-lap pace delta and the circuit's overtake difficulty.
This is what makes "faster but stuck behind" (Monaco) emerge in the sim:
the engine only swaps two cars on track when this model says the attack
succeeded; otherwise the attacker loses time in dirty air.

Default coefficients are calibrated to plausible anchor points, e.g.
+1.0 s/lap advantage → ~45% per-lap pass chance at an easy track, ~6% at
Monaco-like difficulty. ``fit`` re-estimates them from historical
position-change data (OpenF1 ``position`` + ``intervals``).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import optimize


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30.0, 30.0)))


@dataclass
class OvertakeModel:
    intercept: float = -0.31
    pace_coef: float = 1.29  # per s/lap of attacker advantage
    difficulty_coef: float = -3.92  # per unit of circuit difficulty (0..1)
    drs_coef: float = 0.30  # bonus when DRS is available (folded in by caller)

    def p_pass(
        self,
        pace_delta_s: np.ndarray | float,
        difficulty: np.ndarray | float,
        drs: np.ndarray | float = 1.0,
    ) -> np.ndarray:
        """Per-lap pass probability. ``pace_delta_s`` > 0 → attacker faster.

        ``drs`` is the fraction/flag of DRS availability (engine passes 1.0
        under green once within range, 0.0 when DRS is disabled).
        """
        z = (
            self.intercept
            + self.pace_coef * np.asarray(pace_delta_s, dtype=np.float64)
            + self.difficulty_coef * np.asarray(difficulty, dtype=np.float64)
            + self.drs_coef * np.asarray(drs, dtype=np.float64)
        )
        return _sigmoid(z)

    # ------------------------------------------------------------------ fit

    @classmethod
    def fit(cls, attempts: pd.DataFrame, l2: float = 1e-3) -> OvertakeModel:
        """Fit by regularized logistic regression.

        ``attempts`` rows are catch situations: columns ``pace_delta_s``,
        ``difficulty``, ``drs`` (0/1) and outcome ``passed`` (0/1). Building
        this table from raw position/interval data lives in the ETL layer.
        """
        x = attempts[["pace_delta_s", "difficulty", "drs"]].to_numpy(dtype=np.float64)
        y = attempts["passed"].to_numpy(dtype=np.float64)
        if len(y) < 50:
            raise ValueError(f"not enough attempts to fit ({len(y)})")
        design = np.column_stack([np.ones(len(y)), x])

        def loss(beta: np.ndarray) -> float:
            p = _sigmoid(design @ beta)
            eps = 1e-9
            nll = -np.mean(y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps))
            return nll + l2 * float(beta[1:] @ beta[1:])

        beta0 = np.array([-0.3, 1.3, -3.9, 0.3])
        res = optimize.minimize(loss, beta0, method="L-BFGS-B")
        b = res.x
        return cls(
            intercept=float(b[0]),
            pace_coef=float(b[1]),
            difficulty_coef=float(b[2]),
            drs_coef=float(b[3]),
        )

    # ------------------------------------------------------- serialization

    def to_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def from_json(cls, path: str | Path) -> OvertakeModel:
        return cls(**json.loads(Path(path).read_text()))
