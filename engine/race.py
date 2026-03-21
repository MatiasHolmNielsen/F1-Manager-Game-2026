from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, TYPE_CHECKING

from engine.tyres import (
    TYRE_COMPOUNDS, COMPOUND_PACE_DELTA, TYRE_LIFE_BASE,
    TyreStint, RaceStrategy,
    race_laps, adjusted_tyre_life, ai_strategy, suggest_strategies,
    _build_pit_schedule, _tyre_score,
)
from engine.qualifying import QualiResult, simulate_qualifying

if TYPE_CHECKING:
    from models.driver import Driver
    from models.car import Car
    from models.circuit import Circuit


POINTS_SYSTEM = {
    1: 25, 2: 18, 3: 15, 4: 12, 5: 10,
    6: 8,  7: 6,  8: 4,  9: 2,  10: 1,
}

DNF_REASONS = [
    "Engine failure",
    "Gearbox failure",
    "Hydraulic issue",
    "Suspension failure",
    "Brake failure",
    "Collision damage",
    "Electrical fault",
    "Power unit failure",
]

OVERTAKE_THRESHOLD = 0.5   # seconds/lap faster needed before an attempt is considered
BATTLE_RANGE_S = 1.0       # max gap (seconds) between cars for an overtake to be possible


@dataclass
class RaceEntry:
    driver: Driver
    car: Car
    team_id: str
    team_name: str
    team_color: str


@dataclass
class RaceResult:
    position: int
    driver: Driver
    team_id: str
    team_name: str
    team_color: str
    time_gap: float     # seconds behind leader (0.0 for P1)
    points: int
    fastest_lap: bool = False
    dnf: bool = False
    dnf_reason: str = ""
    grid_position: int = 0  # qualifying grid slot (1-based; 0 = unknown)


@dataclass
class DriverLapState:
    total_race_time: float
    fuel_load: float
    tyre_compound: str
    tyre_age: int
    stint_index: int
    dnf: bool
    dnf_reason: str
    pit_this_lap: bool
    dnf_lap: int = 0  # which lap the DNF happened on


@dataclass
class DriverLapRecord:
    lap: int
    lap_time: float       # seconds
    compound: str         # compound run on this lap
    tyre_age: int         # laps on this set at the START of the lap
    wear_pct: float       # tyre wear fraction 0–100 (as used when computing the lap)
    fuel_load: float      # kg remaining at the start of the lap
    position: int         # position after the lap (0 = DNF on this lap)
    pitted: bool = False  # pitted at the end of this lap
    dnf: bool = False     # retired on this lap


@dataclass
class PitStop:
    driver_name: str
    team_name: str
    team_color: str
    lap: int
    old_compound: str
    new_compound: str
    stationary_time: float   # seconds the car was stationary (crew work)
    pit_lane_loss: float     # seconds spent traversing the pit lane
    total_time: float        # stationary_time + pit_lane_loss


@dataclass
class RaceReport:
    results: List[RaceResult]
    events: List[str]                    # notable race events for display
    pit_stops: List[PitStop]             # every pit stop recorded during the race
    fastest_lap_time: float = 0.0        # overall fastest lap (seconds)
    driver_fastest_laps: Dict[str, float] = field(default_factory=dict)   # did -> best lap (s)
    lap_data: Dict[str, List[DriverLapRecord]] = field(default_factory=dict)  # did -> per-lap records


# ─── Lap simulation helpers ────────────────────────────────────────────────────

def _base_lap_time(entry: RaceEntry, circuit, weather: str) -> float:
    """Base lap time for this driver/car at this circuit, without fuel/tyre/noise."""
    driver = entry.driver
    car = entry.car

    ref_lap_time = circuit.length_km * 20.5

    aero_w = circuit.aero_weight
    engine_w = circuit.engine_weight
    mech_w = 1.0 - aero_w

    car_delta = -(
        car.aerodynamics      * aero_w   * 0.50
        + car.engine          * engine_w * 0.50
        + car.mechanical_grip * mech_w   * 0.15
    ) * 0.048

    if weather == "wet":
        eff_pace = driver.pace * 0.15 + driver.wet_weather * 0.85
    else:
        eff_pace = driver.pace

    driver_delta = -(
        eff_pace             * 0.40
        + driver.consistency * 0.20
        + driver.mental      * 0.12
        + driver.experience  * 0.10
    ) * 0.022

    return ref_lap_time + car_delta + driver_delta


def _attempt_overtake(
    faster_entry: RaceEntry,
    slower_entry: RaceEntry,
    circuit,
    speed_delta: float,
) -> tuple[bool, bool]:
    """Return (overtake_success, collision) for this duel attempt."""
    attacker = faster_entry.driver
    defender = slower_entry.driver

    circuit_factor = (100 - circuit.overtaking_difficulty) / 100
    overtake_chance = (
        (speed_delta / 0.8)
        * (attacker.overtaking / 100)
        * (1.0 + attacker.aggression / 200.0)
        * circuit_factor
    )
    defend_factor = (defender.defending * 0.7 + defender.aggression * 0.3) / 200.0
    effective_chance = overtake_chance * (1.0 - defend_factor)
    effective_chance = max(0.0, min(0.95, effective_chance))

    collision_prob = (attacker.aggression / 100) * (defender.aggression / 100) * 0.025
    if random.random() < collision_prob:
        return False, True

    return random.random() < effective_chance, False


# ─── Race ─────────────────────────────────────────────────────────────────────

def _performance_score(
    entry: RaceEntry,
    circuit,
    weather: str,
    grid_position: int = 10,
    strategy: Optional[RaceStrategy] = None,
) -> float:
    """
    Legacy single-score race performance (kept for any callers outside the main sim).
    """
    driver = entry.driver
    car = entry.car

    aero_w = circuit.aero_weight
    engine_w = circuit.engine_weight
    mech_w = 1.0 - aero_w

    car_base = (
        car.aerodynamics  * aero_w   * 0.50
        + car.engine      * engine_w * 0.50
        + car.mechanical_grip * mech_w * 0.15
    )
    overtake_chance = (100 - circuit.overtaking_difficulty) / 100
    braking_bonus = car.braking * 0.05 * overtake_chance

    car_score = car_base * 0.48 + braking_bonus

    if strategy:
        tire_score = _tyre_score(strategy, circuit, weather, car, driver)
    else:
        combined_tyre = car.tire_deg * 0.40 + driver.tire_management * 0.60
        tire_score = (combined_tyre / 100) * 12 / circuit.tire_wear_factor

    if weather == "wet":
        eff_pace = driver.pace * 0.15 + driver.wet_weather * 0.85
    else:
        eff_pace = driver.pace

    driver_score = (
        eff_pace             * 0.40
        + driver.consistency * 0.20
        + driver.car_control * 0.18
        + driver.mental      * 0.12
        + driver.experience  * 0.10
    ) * 0.45

    grid_bonus = 3.5 - (grid_position - 1) * (5.5 / 19)

    stability = (driver.consistency + driver.mental) / 200
    variance = 2.5 * (1.0 + (1.0 - stability))
    randomness = random.gauss(0, variance)

    return car_score + tire_score + driver_score + grid_bonus + randomness


def simulate_race(
    entries: List[RaceEntry],
    circuit,
    weather: str = "dry",
    grid: Optional[List[str]] = None,
    strategies: Optional[Dict[str, RaceStrategy]] = None,
) -> RaceReport:
    """Simulate a full race lap-by-lap and return a RaceReport."""
    total_laps = race_laps(circuit)
    events: List[str] = []

    # Resolve strategies for every driver
    resolved_strategies: Dict[str, RaceStrategy] = {}
    for entry in entries:
        did = entry.driver.id
        if strategies and did in strategies:
            resolved_strategies[did] = strategies[did]
        else:
            resolved_strategies[did] = ai_strategy(entry, circuit, weather)

    entry_map: Dict[str, RaceEntry] = {e.driver.id: e for e in entries}

    # Build pit schedules
    pit_schedules: Dict[str, Dict[int, str]] = {
        did: _build_pit_schedule(strat)
        for did, strat in resolved_strategies.items()
    }

    # Grid position lookup
    def grid_pos(did: str) -> int:
        if grid and did in grid:
            return grid.index(did) + 1
        return 10

    # Initialise per-driver state; add small grid-gap offset (0.3s per grid slot)
    states: Dict[str, DriverLapState] = {}
    for entry in entries:
        did = entry.driver.id
        strat = resolved_strategies[did]
        first_compound = strat.stints[0].compound if strat.stints else "medium"
        gp = grid_pos(did)
        states[did] = DriverLapState(
            total_race_time=(gp - 1) * 0.3,
            fuel_load=100.0,
            tyre_compound=first_compound,
            tyre_age=0,
            stint_index=0,
            dnf=False,
            dnf_reason="",
            pit_this_lap=False,
        )

    fastest_lap_time: float = float("inf")
    fastest_lap_driver: Optional[str] = None
    driver_fastest_laps: Dict[str, float] = {}   # type: ignore[assignment]
    pit_stop_log: List[PitStop] = []
    lap_data: Dict[str, List[DriverLapRecord]] = {did: [] for did in entry_map}

    # ── Lap-by-lap simulation ────────────────────────────────────────────────
    for lap in range(1, total_laps + 1):
        lap_times: Dict[str, float] = {}   # did -> this lap's raw time (excludes pit time)
        lap_snapshots: Dict[str, dict] = {}  # temporary per-lap data before position is known

        for did, state in states.items():
            if state.dnf:
                continue

            entry = entry_map[did]
            driver = entry.driver
            car = entry.car

            # ── Incident check ──────────────────────────────────────────
            mech_prob = (100 - car.reliability) / 100 * 0.003
            ctrl_prob = (100 - driver.car_control) / 100 * 0.0015
            if random.random() < mech_prob + ctrl_prob:
                state.dnf = True
                state.dnf_reason = random.choice(DNF_REASONS)
                state.dnf_lap = lap
                events.append(f"Lap {lap}: {driver.name} retires — {state.dnf_reason}")
                continue

            # ── Tyre life & puncture ────────────────────────────────────
            life = adjusted_tyre_life(state.tyre_compound, circuit, car, driver)
            if state.tyre_age > life:
                overrun_laps = state.tyre_age - life
                puncture_prob = min(0.05, overrun_laps * 0.008)
                if random.random() < puncture_prob:
                    state.dnf = True
                    state.dnf_reason = random.choice(["Tyre failure", "Puncture"])
                    state.dnf_lap = lap
                    events.append(f"Lap {lap}: {driver.name} retires — {state.dnf_reason}")
                    continue

            # ── Compute lap time ────────────────────────────────────────
            base = _base_lap_time(entry, circuit, weather)

            fuel_delta = (state.fuel_load / 100.0) * 2.8

            wear_frac = min(1.0, state.tyre_age / max(1, life))
            tyre_delta = wear_frac ** 2 * 4.5 + COMPOUND_PACE_DELTA[state.tyre_compound]

            stability = (driver.consistency + driver.mental) / 200.0
            lap_sigma = 0.25 * (1.0 + (1.0 - stability))
            lap_noise = random.gauss(0, lap_sigma)

            lap_time = base + fuel_delta + tyre_delta + lap_noise

            # ── Driver mistake (low-experience big error) ─────────────
            mistake_prob = max(0.0, (60.0 - driver.experience) / 100.0) * 0.04
            if random.random() < mistake_prob:
                mistake_time = round(random.uniform(1.5, 4.0), 1)
                lap_time += mistake_time
                if lap <= 15:
                    events.append(
                        f"Lap {lap}: {driver.name} makes a mistake, +{mistake_time}s"
                    )

            lap_times[did] = lap_time
            state.total_race_time += lap_time

            if lap_time < fastest_lap_time:
                fastest_lap_time = lap_time
                fastest_lap_driver = did
            if lap_time < driver_fastest_laps.get(did, float("inf")):
                driver_fastest_laps[did] = lap_time

            # ── Snapshot (before state changes, position filled in later) ──
            lap_snapshots[did] = {
                "lap_time": lap_time,
                "compound": state.tyre_compound,
                "tyre_age": state.tyre_age,
                "wear_pct": round(wear_frac * 100, 1),
                "fuel_load": round(state.fuel_load, 1),
                "pitted": False,
            }

            # ── Update fuel & tyre age ──────────────────────────────────
            state.tyre_age += 1
            state.fuel_load = max(0.0, state.fuel_load - 100.0 / total_laps)
            state.pit_this_lap = False

            # ── Pit stop ────────────────────────────────────────────────
            if lap in pit_schedules.get(did, {}):
                next_compound = pit_schedules[did][lap]
                old_compound = state.tyre_compound
                stationary_s = round(2.1 + (90 - car.pit_crew) * 0.025 + random.gauss(0, 0.15), 2)
                stationary_s = max(1.8, stationary_s)
                total_pit_s = circuit.pit_lane_loss + stationary_s
                state.total_race_time += total_pit_s
                state.tyre_age = 0
                state.tyre_compound = next_compound
                state.stint_index += 1
                state.pit_this_lap = True
                if did in lap_snapshots:
                    lap_snapshots[did]["pitted"] = True
                pit_stop_log.append(PitStop(
                    driver_name=driver.name,
                    team_name=entry.team_name,
                    team_color=entry.team_color,
                    lap=lap,
                    old_compound=old_compound,
                    new_compound=next_compound,
                    stationary_time=stationary_s,
                    pit_lane_loss=float(circuit.pit_lane_loss),
                    total_time=round(total_pit_s, 2),
                ))
                events.append(
                    f"Lap {lap}: {driver.name} pits ({next_compound}, {total_pit_s:.1f}s)"
                )

        # ── Overtaking pass ─────────────────────────────────────────────
        # Sort active drivers by total race time (lowest = leader)
        active = [did for did, s in states.items() if not s.dnf]
        active.sort(key=lambda d: states[d].total_race_time)

        i = len(active) - 1
        while i > 0:
            behind_did = active[i]
            ahead_did  = active[i - 1]

            if behind_did not in lap_times or ahead_did not in lap_times:
                i -= 1
                continue

            # Only allow overtakes between cars that are actually in battle range
            gap = states[behind_did].total_race_time - states[ahead_did].total_race_time
            if gap > BATTLE_RANGE_S:
                i -= 1
                continue

            # Positive speed_delta = behind driver was faster this lap
            speed_delta = lap_times[ahead_did] - lap_times[behind_did]

            if speed_delta >= OVERTAKE_THRESHOLD:
                success, collision = _attempt_overtake(
                    entry_map[behind_did], entry_map[ahead_did], circuit, speed_delta
                )

                if collision:
                    for did, label in [(behind_did, entry_map[behind_did].driver.name),
                                       (ahead_did,  entry_map[ahead_did].driver.name)]:
                        if random.random() < 0.40:
                            states[did].dnf = True
                            states[did].dnf_reason = "Collision"
                            events.append(f"Lap {lap}: {label} retires after collision!")
                        else:
                            damage_s = round(random.uniform(15.0, 35.0), 1)
                            states[did].total_race_time += damage_s
                            events.append(f"Lap {lap}: {label} carries collision damage (+{damage_s}s)")

                elif success:
                    t_ahead  = states[ahead_did].total_race_time
                    t_behind = states[behind_did].total_race_time
                    mid = (t_ahead + t_behind) / 2.0
                    states[behind_did].total_race_time = mid - 0.25
                    states[ahead_did].total_race_time  = mid + 0.25
                    active[i - 1] = behind_did
                    active[i]     = ahead_did

                    new_pos = i
                    if new_pos <= 10:
                        events.append(
                            f"Lap {lap}: {entry_map[behind_did].driver.name} overtakes "
                            f"{entry_map[ahead_did].driver.name} for P{new_pos}"
                        )

            i -= 1

        # ── Record lap data (position now known after overtaking) ────────
        active.sort(key=lambda d: states[d].total_race_time)
        for pos_idx, did in enumerate(active, 1):
            if did in lap_snapshots:
                s = lap_snapshots[did]
                lap_data[did].append(DriverLapRecord(
                    lap=lap,
                    lap_time=s["lap_time"],
                    compound=s["compound"],
                    tyre_age=s["tyre_age"],
                    wear_pct=s["wear_pct"],
                    fuel_load=s["fuel_load"],
                    position=pos_idx,
                    pitted=s["pitted"],
                ))
        # Record DNF laps (drivers who retired this lap)
        for did, state in states.items():
            if state.dnf and state.dnf_lap == lap and did not in lap_snapshots:
                lap_data[did].append(DriverLapRecord(
                    lap=lap, lap_time=0.0, compound=state.tyre_compound,
                    tyre_age=state.tyre_age, wear_pct=0.0, fuel_load=0.0,
                    position=0, dnf=True,
                ))

    # ── Build final results ──────────────────────────────────────────────────
    finisher_dids = [did for did, s in states.items() if not s.dnf]
    dnf_dids      = [did for did, s in states.items() if s.dnf]

    finisher_dids.sort(key=lambda d: states[d].total_race_time)
    leader_time = states[finisher_dids[0]].total_race_time if finisher_dids else 0.0

    results: List[RaceResult] = []

    for pos, did in enumerate(finisher_dids, 1):
        entry = entry_map[did]
        gap = round(states[did].total_race_time - leader_time, 3)
        results.append(RaceResult(
            position=pos,
            driver=entry.driver,
            team_id=entry.team_id,
            team_name=entry.team_name,
            team_color=entry.team_color,
            time_gap=gap,
            points=POINTS_SYSTEM.get(pos, 0),
            grid_position=grid_pos(did),
        ))

    for pos, did in enumerate(dnf_dids, len(finisher_dids) + 1):
        entry = entry_map[did]
        results.append(RaceResult(
            position=pos,
            driver=entry.driver,
            team_id=entry.team_id,
            team_name=entry.team_name,
            team_color=entry.team_color,
            time_gap=0.0,
            points=0,
            dnf=True,
            dnf_reason=states[did].dnf_reason,
            grid_position=grid_pos(did),
        ))

    # Fastest lap bonus (top-10 finisher only)
    if fastest_lap_driver and fastest_lap_driver in finisher_dids:
        fl_pos = finisher_dids.index(fastest_lap_driver) + 1
        for r in results:
            if r.driver.id == fastest_lap_driver:
                r.fastest_lap = True
                if fl_pos <= 10:
                    r.points += 1
                break

    return RaceReport(
        results=results,
        events=events,
        pit_stops=pit_stop_log,
        fastest_lap_time=fastest_lap_time if fastest_lap_time < float("inf") else 0.0,
        driver_fastest_laps=driver_fastest_laps,
        lap_data=lap_data,
    )
