"""Pit stop total time loss per circuit.

"Total loss" = pit lane delta + service time versus a flying lap, i.e. the
number you add to a car's cumulative race time when it pits under green.
Modelled as Normal(mean, std) plus an exponential slow-stop tail (stuck
wheel gun, traffic in the box) with probability ``slow_prob``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass
class PitLossModel:
    mean_s: float = 22.0
    std_s: float = 0.9
    slow_prob: float = 0.06
    slow_extra_mean_s: float = 4.0
    circuit_id: str = "generic"

    def sample(self, rng: np.random.Generator, size: int | tuple[int, ...]) -> np.ndarray:
        loss = rng.normal(self.mean_s, self.std_s, size=size)
        slow = rng.random(size) < self.slow_prob
        loss = loss + slow * rng.exponential(self.slow_extra_mean_s, size=size)
        return np.clip(loss, self.mean_s * 0.7, None)

    @classmethod
    def fit(cls, pitstops: pd.DataFrame, circuit_id: str = "generic") -> PitLossModel:
        """Fit from the internal ``pitstops`` table (``total_loss_ms``).

        Robust location/scale (median + MAD) so slow stops don't drag the
        core distribution; the tail is estimated from the exceedances.
        """
        loss = pitstops["total_loss_ms"].dropna().to_numpy(dtype=np.float64) / 1000.0
        if len(loss) < 5:
            raise ValueError(f"not enough pit stops to fit ({len(loss)})")
        med = float(np.median(loss))
        mad = float(np.median(np.abs(loss - med))) * 1.4826
        std = max(mad, 0.3)
        slow_cut = med + 2.5 * std
        slow = loss[loss > slow_cut]
        slow_prob = len(slow) / len(loss)
        slow_extra = float(np.mean(slow - med)) if len(slow) else 4.0
        return cls(
            mean_s=med,
            std_s=std,
            slow_prob=float(np.clip(slow_prob, 0.01, 0.25)),
            slow_extra_mean_s=slow_extra,
            circuit_id=circuit_id,
        )

    def to_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def from_json(cls, path: str | Path) -> PitLossModel:
        return cls(**json.loads(Path(path).read_text()))
