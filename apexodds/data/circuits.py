"""Circuit parameter table: seed priors + loader.

The packaged CSV holds hand-set priors (pit loss, SC/VSC likelihood,
overtake difficulty). M1/M2 replace them with values fitted from
historical data via the model ``fit`` functions and write the result to
the ``circuit_params`` table; this loader stays the fallback so the sim
always has parameters for any circuit.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

from apexodds.sim.state import CircuitParams

SEED_CSV = Path(__file__).parent / "seed" / "circuit_params.csv"


@lru_cache(maxsize=1)
def load_circuit_table(path: str | None = None) -> pd.DataFrame:
    df = pd.read_csv(path or SEED_CSV)
    df["circuit_id"] = df["circuit_id"].str.strip()
    return df.set_index("circuit_id", drop=False)


def circuit_params(circuit_id: str, lap_count: int | None = None) -> CircuitParams:
    """CircuitParams for a circuit; unknown ids get generic defaults."""
    table = load_circuit_table()
    if circuit_id in table.index:
        row = table.loc[circuit_id]
        return CircuitParams(
            circuit_id=circuit_id,
            lap_count=int(lap_count or row["lap_count"]),
            pit_loss_s=float(row["pit_loss_s"]),
            pit_loss_std_s=float(row["pit_loss_std_s"]),
            sc_prob_race=float(row["sc_prob_race"]),
            vsc_prob_race=float(row["vsc_prob_race"]),
            overtake_difficulty=float(row["overtake_difficulty"]),
            drs_zones=int(row["drs_zones"]),
            lap1_hazard_multiplier=float(row["lap1_hazard_multiplier"]),
        )
    return CircuitParams(circuit_id=circuit_id, lap_count=int(lap_count or 57))
