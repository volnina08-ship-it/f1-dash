"""RaceState — the complete, self-contained input for one simulation run.

The replay harness (Phase 0) and the live pipeline (Phase 1) both reduce the
world to this structure; the engine consumes nothing else. Times are float
seconds here (data-boundary code converts from the stored milliseconds).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

COMPOUNDS: tuple[str, ...] = ("SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET")
COMPOUND_INDEX: dict[str, int] = {c: i for i, c in enumerate(COMPOUNDS)}
DRY_COMPOUNDS: tuple[str, ...] = ("SOFT", "MEDIUM", "HARD")

TRACK_GREEN = "GREEN"
TRACK_YELLOW = "YELLOW"
TRACK_SC = "SC"
TRACK_VSC = "VSC"
TRACK_RED = "RED"


@dataclass
class DriverState:
    """One driver's situation at the current lap."""

    driver_number: int
    code: str  # e.g. "VER"
    team: str = ""
    position: int = 0
    # Cumulative race time relative to the leader, seconds. Leader == 0.0.
    # (Absolute time is irrelevant to outcomes; only gaps matter.)
    gap_to_leader_s: float = 0.0
    compound: str = "MEDIUM"
    tyre_age: int = 0  # laps completed on the current set
    pit_count: int = 0
    # Dry compounds already used this race (for the two-compound rule).
    used_compounds: tuple[str, ...] = ()
    # Fuel-corrected, degradation-corrected base pace distribution (see
    # models/pace.py): mean lap time on a zero-fuel car with fresh reference
    # tyres, plus lap-to-lap standard deviation.
    pace_mean_s: float = 90.0
    pace_std_s: float = 0.35
    # Per-lap retirement hazard (car + driver), already season-adjusted.
    dnf_per_lap: float = 0.0012
    retired: bool = False
    grid_position: int = 0

    def key(self) -> int:
        return self.driver_number


@dataclass
class CircuitParams:
    """Per-circuit simulation parameters (from the circuit_params table)."""

    circuit_id: str = "generic"
    lap_count: int = 57
    pit_loss_s: float = 22.0
    pit_loss_std_s: float = 0.9
    # Probability that at least one SC/VSC appears over a full race distance.
    sc_prob_race: float = 0.45
    vsc_prob_race: float = 0.35
    # How hard on-track passing is, 0 (trivial) .. 1 (Monaco).
    overtake_difficulty: float = 0.5
    drs_zones: int = 2
    # First-lap incident multiplier on the per-lap SC hazard.
    lap1_hazard_multiplier: float = 8.0

    @property
    def sc_per_lap(self) -> float:
        return _per_lap_hazard(self.sc_prob_race, self.lap_count)

    @property
    def vsc_per_lap(self) -> float:
        return _per_lap_hazard(self.vsc_prob_race, self.lap_count)


def _per_lap_hazard(p_race: float, laps: int) -> float:
    """Convert a per-race probability into a constant per-lap hazard."""
    p_race = min(max(p_race, 0.0), 0.999)
    if laps <= 0:
        return 0.0
    return 1.0 - (1.0 - p_race) ** (1.0 / laps)


@dataclass
class Weather:
    air_temp_c: float = 22.0
    track_temp_c: float = 32.0
    rainfall: bool = False
    # Probability of (more) rain affecting the remaining race. v1 only
    # inflates uncertainty with this (models/weather.py); no full wet model.
    rain_prob: float = 0.0


@dataclass
class RaceState:
    """Everything the engine needs to simulate the rest of a race."""

    session_key: str
    circuit: CircuitParams
    lap: int  # laps completed so far; 0 == pre-race (grid)
    total_laps: int
    drivers: list[DriverState]
    track_status: str = TRACK_GREEN
    weather: Weather = field(default_factory=Weather)
    # Laps the current SC/VSC period is still expected to last (only
    # meaningful when track_status is SC/VSC).
    intervention_laps_remaining: int = 0

    @property
    def laps_remaining(self) -> int:
        return max(0, self.total_laps - self.lap)

    @property
    def n_drivers(self) -> int:
        return len(self.drivers)

    def running_drivers(self) -> list[DriverState]:
        return [d for d in self.drivers if not d.retired]

    def sorted_by_position(self) -> list[DriverState]:
        # Retired cars sink to the back, keeping their last known order.
        return sorted(self.drivers, key=lambda d: (d.retired, d.position))

    def copy(self) -> RaceState:
        return replace(
            self,
            drivers=[replace(d) for d in self.drivers],
            circuit=replace(self.circuit),
            weather=replace(self.weather),
        )

    def validate(self) -> None:
        if self.total_laps <= 0:
            raise ValueError("total_laps must be positive")
        if not (0 <= self.lap <= self.total_laps):
            raise ValueError(f"lap {self.lap} outside [0, {self.total_laps}]")
        if not self.drivers:
            raise ValueError("RaceState needs at least one driver")
        nums = [d.driver_number for d in self.drivers]
        if len(set(nums)) != len(nums):
            raise ValueError("duplicate driver_number in RaceState")
        for d in self.drivers:
            if d.compound not in COMPOUND_INDEX:
                raise ValueError(f"unknown compound {d.compound!r} for {d.code}")


def grid_state(
    session_key: str,
    circuit: CircuitParams,
    grid: list[DriverState],
    total_laps: int | None = None,
    weather: Weather | None = None,
) -> RaceState:
    """Build a pre-race (lap 0) state from a starting grid.

    ``grid`` order == grid order. Gaps are seeded with a small per-row
    spread; the engine's first-lap chaos dominates anyway.
    """
    drivers = []
    for i, d in enumerate(grid):
        drivers.append(
            replace(
                d,
                position=i + 1,
                grid_position=i + 1,
                gap_to_leader_s=0.35 * i,
                retired=False,
            )
        )
    return RaceState(
        session_key=session_key,
        circuit=circuit,
        lap=0,
        total_laps=total_laps or circuit.lap_count,
        drivers=drivers,
        weather=weather or Weather(),
    )
