"""Vectorized Monte Carlo race engine.

Simulates N parallel "worlds" of the remaining race as (worlds × drivers)
numpy arrays. Per lap: lap-time draws (pace + fuel + tyre wear + noise),
hazard draws (DNF, SC/VSC deployment), strategy decisions and pit
execution, then on-track position resolution *gated by the overtake
model* — being faster is not enough, you must get past, which is what
makes a Monaco simulation behave like Monaco.

Positions are maintained explicitly per world (front → back driver
indices) and updated with odd-even transposition rounds so all pass
attempts vectorize across worlds. A failed attack clamps the attacker to
a dirty-air gap behind the defender (time loss), a successful one swaps
the pair. Pit exits and retirements pass/get passed freely.

Performance target (brief §6): full recompute in ~1-2 s on CPU with
N = 2000-5000 worlds — see scripts/benchmark_engine.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from apexodds.models import ModelBundle
from apexodds.models.pace import fuel_penalty_s
from apexodds.models.weather import uncertainty_inflation
from apexodds.sim import strategy as strat
from apexodds.sim.state import COMPOUND_INDEX, TRACK_SC, TRACK_VSC, RaceState
from apexodds.sim.strategy import StrategyParams

_BIG = 1.0e9  # cumulative-time sentinel for retired cars


@dataclass(frozen=True)
class SimConfig:
    n_sims: int = 3000
    seed: int | None = None
    # Odd-even transposition rounds per lap; cars can gain at most this many
    # on-track positions per lap (pit-lane shuffles resolve regardless).
    sort_rounds: int = 5
    # Dirty-air gap (s) an attacker sits at after a failed pass, U(lo, hi).
    follow_gap_s: tuple[float, float] = (0.25, 0.9)
    sc_lap_factor: float = 1.35  # field lap time under SC vs mean pace
    vsc_lap_factor: float = 1.22
    sc_duration_laps: tuple[int, int] = (3, 6)  # inclusive
    vsc_duration_laps: tuple[int, int] = (1, 3)
    queue_gap_s: float = 0.9  # bunched-field spacing behind the SC
    lap1_extra_std_s: float = 1.3  # first-lap chaos
    lap1_dnf_multiplier: float = 4.0
    fuel_start_kg: float = 100.0
    fuel_effect_s_per_kg: float = 0.033
    max_tyre_age: int = 60  # degradation lookup table horizon
    strategy: StrategyParams = field(default_factory=StrategyParams)


@dataclass
class SimResult:
    """Raw per-world outcomes; aggregate with sim/outputs.py."""

    driver_numbers: list[int]
    codes: list[str]
    teams: list[str]
    grid_positions: list[int]
    start_positions: list[int]  # positions at the simulated-from lap
    final_position: np.ndarray  # (N, D) int16, 1-based classification
    dnf: np.ndarray  # (N, D) bool
    dnf_lap: np.ndarray  # (N, D) int16, 0 = finished
    next_pit_lap: np.ndarray  # (N, D) int16, 0 = no further stop
    pit_count: np.ndarray  # (N, D) int16, total stops incl. pre-state ones
    final_gap_s: np.ndarray  # (N, D) float32, to the winner
    from_lap: int
    total_laps: int
    n_sims: int


def simulate(state: RaceState, models: ModelBundle, config: SimConfig) -> SimResult:
    state.validate()
    rng = np.random.default_rng(config.seed)
    n = config.n_sims
    drivers = state.drivers
    d = len(drivers)
    total = state.total_laps
    circuit = state.circuit

    inflation = uncertainty_inflation(state.weather)

    # ---------------------------------------------------------- static per driver
    pace_mean = np.array([dr.pace_mean_s for dr in drivers])
    pace_std = np.array([dr.pace_std_s for dr in drivers]) * inflation.pace_std_multiplier
    dnf_rate = (
        np.array([dr.dnf_per_lap for dr in drivers]) * inflation.hazard_multiplier
    ).clip(0.0, 0.05)

    deg_table = models.tyres.table(config.max_tyre_age)  # (compounds, age)
    stint_nominals = models.tyres.stint_targets(total)  # (compounds,)
    difficulty = float(circuit.overtake_difficulty)
    sc_rate = min(circuit.sc_per_lap * inflation.hazard_multiplier, 0.25)
    vsc_rate = min(circuit.vsc_per_lap * inflation.hazard_multiplier, 0.25)

    # ------------------------------------------------------- dynamic (N, D) state
    cum = np.tile(
        np.array([dr.gap_to_leader_s for dr in drivers], dtype=np.float64), (n, 1)
    )
    alive = np.tile(np.array([not dr.retired for dr in drivers]), (n, 1))
    cum[~alive] = _BIG
    tyre_age = np.tile(
        np.array([dr.tyre_age for dr in drivers], dtype=np.int16), (n, 1)
    )
    compound = np.tile(
        np.array([COMPOUND_INDEX[dr.compound] for dr in drivers], dtype=np.int8), (n, 1)
    )
    pit_count = np.tile(
        np.array([dr.pit_count for dr in drivers], dtype=np.int16), (n, 1)
    )
    used_mask = np.tile(_used_masks(drivers), (n, 1))
    dnf_lap = np.zeros((n, d), dtype=np.int16)
    dnf_lap[~alive] = max(state.lap, 1)  # already-retired cars
    next_pit_lap = np.zeros((n, d), dtype=np.int16)

    # Front-to-back driver indices per world.
    order = np.tile(_initial_order(drivers), (n, 1))

    stint_target = strat.draw_stint_targets(rng, compound, stint_nominals, config.strategy)

    sc_rem = np.zeros(n, dtype=np.int16)
    vsc_rem = np.zeros(n, dtype=np.int16)
    if state.track_status == TRACK_SC:
        sc_rem[:] = max(state.intervention_laps_remaining, 1)
        cum = _bunch_field(cum, alive, config.queue_gap_s)
    elif state.track_status == TRACK_VSC:
        vsc_rem[:] = max(state.intervention_laps_remaining, 1)

    mean_field_pace = float(pace_mean.mean())

    # ------------------------------------------------------------------ lap loop
    for lap in range(state.lap + 1, total + 1):
        laps_remaining = total - lap
        is_lap1 = lap == 1

        # --- retirements
        rate = dnf_rate[None, :] * (config.lap1_dnf_multiplier if is_lap1 else 1.0)
        died = alive & (rng.random((n, d)) < rate)
        if died.any():
            alive &= ~died
            dnf_lap[died] = lap
            cum[died] = _BIG

        # --- SC / VSC deployment (one intervention at a time)
        quiet = (sc_rem == 0) & (vsc_rem == 0)
        dnf_in_world = died.any(axis=1)
        lap1_mult = circuit.lap1_hazard_multiplier if is_lap1 else 1.0
        p_sc = np.clip(
            sc_rate * lap1_mult + dnf_in_world * models.hazards.p_sc_given_dnf, 0.0, 0.95
        )
        sc_starts = quiet & (rng.random(n) < p_sc)
        if sc_starts.any():
            sc_rem[sc_starts] = rng.integers(
                config.sc_duration_laps[0], config.sc_duration_laps[1] + 1,
                size=int(sc_starts.sum()),
            )
            cum[sc_starts] = _bunch_field(
                cum[sc_starts], alive[sc_starts], config.queue_gap_s
            )
        p_vsc = np.clip(
            vsc_rate * lap1_mult + dnf_in_world * models.hazards.p_vsc_given_dnf, 0.0, 0.95
        )
        vsc_starts = quiet & ~sc_starts & (rng.random(n) < p_vsc)
        if vsc_starts.any():
            vsc_rem[vsc_starts] = rng.integers(
                config.vsc_duration_laps[0], config.vsc_duration_laps[1] + 1,
                size=int(vsc_starts.sum()),
            )

        sc_active = sc_rem > 0
        vsc_active = vsc_rem > 0
        green = ~(sc_active | vsc_active)

        # --- lap times
        age_clipped = np.minimum(tyre_age, config.max_tyre_age)
        lap_time = (
            pace_mean[None, :]
            + fuel_penalty_s(lap, total, config.fuel_effect_s_per_kg, config.fuel_start_kg)
            + deg_table[compound, age_clipped]
            + rng.standard_normal((n, d)) * pace_std[None, :]
        )
        if is_lap1:
            lap_time += (
                np.abs(rng.standard_normal((n, d))) * config.lap1_extra_std_s + 2.0
            )  # standing start + first-lap traffic is always slow
        if sc_active.any():
            sc_pace = mean_field_pace * config.sc_lap_factor
            lap_time = np.where(
                sc_active[:, None],
                sc_pace + rng.standard_normal((n, d)) * 0.2,
                lap_time,
            )
        if vsc_active.any():
            lap_time = np.where(
                vsc_active[:, None],
                pace_mean[None, :] * config.vsc_lap_factor
                + rng.standard_normal((n, d)) * 0.3,
                lap_time,
            )

        # --- strategy: pit decisions and execution
        pits = strat.decide_pits(
            rng, tyre_age, stint_target, used_mask, sc_active, vsc_active,
            laps_remaining, alive, config.strategy,
        )
        if pits.any():
            idx = np.nonzero(pits)
            loss = models.pitloss.sample(rng, size=len(idx[0]))
            pay = np.ones(len(idx[0]))
            pay = np.where(
                sc_active[idx[0]], config.strategy.sc_pit_loss_factor, pay
            )
            pay = np.where(
                vsc_active[idx[0]], config.strategy.vsc_pit_loss_factor, pay
            )
            lap_time[idx] += loss * pay

            new_comp = strat.choose_next_compound(
                rng, laps_remaining, used_mask[idx], stint_nominals, config.strategy
            )
            compound[idx] = new_comp
            used_mask[idx] |= (1 << new_comp).astype(np.uint8)
            pit_count[idx] += 1
            stint_target[idx] = strat.draw_stint_targets(
                rng, new_comp, stint_nominals, config.strategy
            )
            first_stop = pits & (next_pit_lap == 0)
            next_pit_lap[first_stop] = lap

        # --- advance clocks and tyres
        cum = np.where(alive, cum + lap_time, cum)
        tyre_age = np.where(pits, 0, tyre_age + 1).astype(np.int16)

        # --- position resolution (overtake-gated under green)
        order, cum = _resolve_positions(
            rng, order, cum, lap_time, alive, pits, green,
            models, difficulty, config,
        )

        sc_rem = np.maximum(sc_rem - 1, 0)
        vsc_rem = np.maximum(vsc_rem - 1, 0)

    # ------------------------------------------------------------ classification
    # Finishers rank by final time; DNFs rank behind all finishers, later
    # retirement first (distance-completed proxy).
    sort_key = np.where(alive, cum, _BIG + (total - dnf_lap).astype(np.float64) * 1e3)
    final_order = np.argsort(sort_key, axis=1, kind="stable")
    final_position = np.empty((n, d), dtype=np.int16)
    np.put_along_axis(
        final_position, final_order, np.arange(1, d + 1, dtype=np.int16)[None, :], axis=1
    )
    winner_time = np.take_along_axis(cum, final_order[:, :1], axis=1)
    final_gap = np.where(alive, cum - winner_time, np.nan).astype(np.float32)

    return SimResult(
        driver_numbers=[dr.driver_number for dr in drivers],
        codes=[dr.code for dr in drivers],
        teams=[dr.team for dr in drivers],
        grid_positions=[dr.grid_position for dr in drivers],
        start_positions=[dr.position for dr in drivers],
        final_position=final_position,
        dnf=~alive,
        dnf_lap=dnf_lap,
        next_pit_lap=next_pit_lap,
        pit_count=pit_count,
        final_gap_s=final_gap,
        from_lap=state.lap,
        total_laps=total,
        n_sims=n,
    )


# ---------------------------------------------------------------------- helpers


def _used_masks(drivers) -> np.ndarray:
    masks = np.zeros(len(drivers), dtype=np.uint8)
    for i, dr in enumerate(drivers):
        m = 0
        for c in (*dr.used_compounds, dr.compound):
            idx = COMPOUND_INDEX.get(c, 5)
            if idx < strat.N_DRY:
                m |= 1 << idx
        masks[i] = m
    return masks


def _initial_order(drivers) -> np.ndarray:
    ranked = sorted(range(len(drivers)), key=lambda i: (drivers[i].retired, drivers[i].position))
    return np.array(ranked, dtype=np.int16)


def _bunch_field(cum: np.ndarray, alive: np.ndarray, queue_gap_s: float) -> np.ndarray:
    """Compress running cars into an SC queue, preserving order."""
    rank = np.argsort(np.argsort(cum, axis=1, kind="stable"), axis=1, kind="stable")
    leader = np.min(np.where(alive, cum, np.inf), axis=1, keepdims=True)
    queued = leader + rank * queue_gap_s
    return np.where(alive, queued, cum)


def _resolve_positions(
    rng: np.random.Generator,
    order: np.ndarray,  # (N, D) driver indices front→back
    cum: np.ndarray,  # (N, D) per driver index
    lap_time: np.ndarray,  # (N, D) this lap, per driver index
    alive: np.ndarray,
    pitted: np.ndarray,
    green: np.ndarray,  # (N,) worlds under green flag
    models: ModelBundle,
    difficulty: float,
    config: SimConfig,
) -> tuple[np.ndarray, np.ndarray]:
    """Odd-even transposition rounds with overtake gating.

    For each adjacent (ahead, behind) pair where the car behind ended the
    lap on less cumulative time ("caught"), the swap goes through freely if
    either car pitted or retired (pit-lane / passing-a-dead-car), otherwise
    it succeeds with the overtake model's probability. A failed attack
    clamps the attacker into dirty air behind the defender. Non-green
    worlds sort freely (pit drops under SC still shuffle the queue; equal
    SC lap times keep the rest stable).
    """
    n, d = order.shape
    if d < 2:
        return order, cum

    # Hot loop: work in position space. Gather car attributes into running
    # order once, run the odd-even rounds on plain strided slices (cheap),
    # scatter cum back once. Values travel with the car on every swap.
    cum_o = np.take_along_axis(cum, order, axis=1)
    lt_o = np.take_along_axis(lap_time, order, axis=1)
    free_o = np.take_along_axis(pitted | ~alive, order, axis=1)
    not_green = ~green[:, None]

    for _ in range(config.sort_rounds):
        for parity in (0, 1):
            if d - 1 <= parity:
                continue
            front = slice(parity, d - 1, 2)
            back = slice(parity + 1, d, 2)
            t_a, t_b = cum_o[:, front], cum_o[:, back]
            caught = t_b < t_a
            if not caught.any():
                continue

            free = free_o[:, front] | free_o[:, back] | not_green
            p = models.overtake.p_pass(lt_o[:, front] - lt_o[:, back], difficulty)
            success = caught & (free | (rng.random(p.shape) < p))
            # Failed attackers sit in dirty air just behind the defender.
            blocked = caught & ~success
            if blocked.any():
                gap = rng.uniform(*config.follow_gap_s, size=t_b.shape)
                t_b = np.where(blocked, t_a + gap, t_b)

            for arr in (cum_o, lt_o, free_o, order):
                # Materialize both new columns BEFORE writing: the slice
                # expressions are views into arr.
                b_vals = t_b if arr is cum_o else arr[:, back]
                new_front = np.where(success, b_vals, arr[:, front])
                new_back = np.where(success, arr[:, front], b_vals)
                arr[:, front] = new_front
                arr[:, back] = new_back

    np.put_along_axis(cum, order, cum_o, axis=1)
    return order, cum
