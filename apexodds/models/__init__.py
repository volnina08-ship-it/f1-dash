"""Learned component models consumed by the Monte Carlo engine.

Each model is independently fittable/testable and serializes to JSON under
``data/models/``. Everything ships with hand-set priors so the whole
pipeline runs before any training has happened — training (M2) then
replaces the priors with fitted parameters.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apexodds.models.hazards import HazardModel
from apexodds.models.overtake import OvertakeModel
from apexodds.models.pitloss import PitLossModel
from apexodds.models.tyres import DegradationModel
from apexodds.sim.state import CircuitParams


@dataclass
class ModelBundle:
    """The full set of component models the engine consumes."""

    tyres: DegradationModel = field(default_factory=DegradationModel)
    pitloss: PitLossModel = field(default_factory=PitLossModel)
    hazards: HazardModel = field(default_factory=HazardModel)
    overtake: OvertakeModel = field(default_factory=OvertakeModel)

    @classmethod
    def default(cls, circuit: CircuitParams | None = None) -> ModelBundle:
        """Prior-only bundle wired to a circuit's parameters."""
        circuit = circuit or CircuitParams()
        return cls(
            tyres=DegradationModel(),
            pitloss=PitLossModel(mean_s=circuit.pit_loss_s, std_s=circuit.pit_loss_std_s),
            hazards=HazardModel.from_circuit(circuit),
            overtake=OvertakeModel(),
        )


__all__ = [
    "DegradationModel",
    "HazardModel",
    "ModelBundle",
    "OvertakeModel",
    "PitLossModel",
]
