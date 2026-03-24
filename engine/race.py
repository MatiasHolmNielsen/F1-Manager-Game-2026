from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, TYPE_CHECKING

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

SC_PROBABILITY  = 0.50     # chance of full Safety Car on incident
VSC_PROBABILITY = 0.25     # additional chance of Virtual Safety Car on incident


def _check_safety_car() -> Optional[str]:
    """Roll for safety car deployment. Returns 'SC', 'VSC', or None."""
    roll = random.random()
    if roll < SC_PROBABILITY:
        return "SC"
    if roll < SC_PROBABILITY + VSC_PROBABILITY:
        return "VSC"
    return None


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _weather_compound_delta(compound: str, rain_prob: float) -> float:
    """Per-lap pace delta (seconds) for a compound at the current track wetness."""
    from engine.tyres import COMPOUND_PACE_DELTA
    base = COMPOUND_PACE_DELTA.get(compound, 0.0)

    if compound in ("soft", "medium", "hard"):
        if rain_prob <= 55:
            return base
        elif rain_prob <= 65:
            t = (rain_prob - 55) / 10
            return base + _lerp(0.0, 2.0, t)
        elif rain_prob <= 80:
            t = (rain_prob - 65) / 15
            return base + _lerp(2.0, 5.0, t)
        elif rain_prob <= 92:
            t = (rain_prob - 80) / 12
            return base + _lerp(5.0, 9.0, t)
        else:
            t = (rain_prob - 92) / 8
            return base + _lerp(9.0, 12.5, t)

    elif compound == "intermediate":
        if rain_prob <= 40:
            return 6.0
        elif rain_prob <= 65:
            t = (rain_prob - 40) / 25
            return _lerp(6.0, 0.2, t)
        elif rain_prob <= 92:
            return 0.2
        else:
            t = (rain_prob - 92) / 8
            return _lerp(0.2, 2.7, t)

    elif compound == "wet":
        if rain_prob <= 55:
            return 12.0
        elif rain_prob <= 70:
            t = (rain_prob - 55) / 15
            return _lerp(12.0, 3.0, t)
        elif rain_prob <= 82:
            t = (rain_prob - 70) / 12
            return _lerp(3.0, 0.8, t)
        else:
            return 0.8

    return base


def _effective_wet_weight(rain_prob: float) -> float:
    """Scale wet_weather stat weight from 0 → 0.85 as rain_prob rises 40 → 100."""
    if rain_prob <= 40:
        return 0.0
    elif rain_prob <= 65:
        t = (rain_prob - 40) / 25
        return _lerp(0.0, 0.30, t)
    elif rain_prob <= 80:
        t = (rain_prob - 65) / 15
        return _lerp(0.30, 0.60, t)
    else:
        t = min(1.0, (rain_prob - 80) / 20)
        return _lerp(0.60, 0.85, t)


def _generate_weather_forecast(
    rain_prob: float,
    rain_decreasing: bool,
    rise_rate: float,
    decay_rate: float,
    front_arrival_lap: int,
    current_lap: int,
) -> List[float]:
    """Simulate next 8 laps of rain probability with increasing uncertainty."""
    noise_by_offset = [5, 5, 12, 12, 12, 20, 20, 20]
    forecast: List[float] = []
    prob = rain_prob
    for i in range(8):
        if rain_decreasing:
            rate = decay_rate
            prob = max(0.0, prob - max(0.0, random.gauss(rate, rate * 0.3)))
        elif current_lap + i >= front_arrival_lap and rise_rate > 0:
            rate = rise_rate
            prob = min(100.0, prob + max(0.0, random.gauss(rate, rate * 0.35)))
        noise = random.gauss(0, noise_by_offset[i])
        forecast.append(max(0.0, min(100.0, prob + noise)))
    return forecast


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
    rain_prob: float = 0.0  # track wetness on this lap (0–100)


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
    overtakes_made: Dict[str, int] = field(default_factory=dict)   # did -> successful overtakes
    defenses_made: Dict[str, int] = field(default_factory=dict)    # did -> successful defenses
    peak_rain_prob: float = 0.0          # highest rain_prob reached during the race
    weather_summary: List[str] = field(default_factory=list)  # key weather events for debrief


# ─── Lap simulation helpers ────────────────────────────────────────────────────

def _base_lap_time(entry: RaceEntry, circuit, rain_prob: float) -> float:
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

    wet_w = _effective_wet_weight(rain_prob)
    eff_pace = driver.pace * (1.0 - wet_w) + driver.wet_weather * wet_w

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
    player_team_id: Optional[str] = None,
    sc_pit_callback: Optional[Callable] = None,
    weather_callback: Optional[Callable] = None,
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
    overtakes_made: Dict[str, int] = {did: 0 for did in entry_map}
    defenses_made: Dict[str, int] = {did: 0 for did in entry_map}
    prev_positions: Dict[str, int] = {did: grid_pos(did) for did in entry_map}
    pit_recovery_laps_left: Dict[str, int] = {did: 0 for did in entry_map}

    # ── Safety Car state ─────────────────────────────────────────────────────
    sc_state: Optional[str] = None   # "SC", "VSC", or None
    sc_laps_remaining: int = 0
    sc_lap_count: int = 0             # laps elapsed since SC/VSC deployed (0 = deployment lap)

    # ── Weather state ─────────────────────────────────────────────────────────
    rain_prob: float = 85.0 if weather == "wet" else 0.0
    front_active: bool = False
    front_arrival_lap: int = 0
    front_rise_rate: float = 0.0
    front_decay_rate: float = 0.0
    peak_duration: int = 0
    laps_above_peak: int = 0
    rain_decreasing: bool = False
    peak_rain_prob: float = rain_prob
    weather_summary: List[str] = []
    episode_below_60_count: int = 0
    thresholds_crossed: dict = {"warning": False, "damp": False, "wet": False, "drying": False}
    player_ignored_warning: bool = False
    weather_sc_fired: bool = False
    warning_cooldown: int = 0   # laps until warning threshold can fire again

    if weather == "dry" and random.random() * 100 < circuit.weather_chance:
        earliest = max(3, int(total_laps * 0.15))
        latest   = max(earliest + 1, min(total_laps - 5, int(total_laps * 0.85)))
        front_arrival_lap = random.randint(earliest, latest)
        strength = random.choices(["light", "moderate", "heavy"], weights=[40, 40, 20])[0]
        rise_rates   = {"light": 5.5, "moderate": 10.0, "heavy": 17.0}
        decay_rates  = {"light": 5.0, "moderate": 7.0,  "heavy": 6.0}
        peak_durations = {"light": 5, "moderate": 8,  "heavy": 12}
        front_rise_rate  = rise_rates[strength]
        front_decay_rate = decay_rates[strength]
        peak_duration    = peak_durations[strength]
        front_active = True
        events.append(f"Weather: {strength} rain front expected around lap {front_arrival_lap}")

    if weather == "wet":
        if random.random() < 0.50:
            dry_start = max(3, total_laps // 4)
            dry_end   = max(dry_start + 1, total_laps - 5)
            front_arrival_lap = random.randint(dry_start, dry_end)
            front_decay_rate  = random.uniform(4.0, 8.0)
            rain_decreasing   = True
            front_active      = True

    # ── Lap-by-lap simulation ────────────────────────────────────────────────
    for lap in range(1, total_laps + 1):
        lap_times: Dict[str, float] = {}   # did -> this lap's raw time (excludes pit time)
        lap_snapshots: Dict[str, dict] = {}  # temporary per-lap data before position is known
        lap_had_incident: bool = False

        # ── Per-lap weather drift ────────────────────────────────────────────
        prev_lap_rain_prob = rain_prob
        if warning_cooldown > 0:
            warning_cooldown -= 1

        if front_active:
            if not rain_decreasing and lap >= front_arrival_lap:
                delta = max(0.0, random.gauss(front_rise_rate, front_rise_rate * 0.35))
                rain_prob = min(100.0, rain_prob + delta)
                if rain_prob > peak_rain_prob:
                    peak_rain_prob = rain_prob
                if rain_prob >= 80:
                    laps_above_peak += 1
                    if laps_above_peak >= peak_duration:
                        rain_decreasing = True
                else:
                    laps_above_peak = 0
            elif rain_decreasing:
                if not (weather == "wet" and lap < front_arrival_lap):
                    delta = max(0.0, random.gauss(front_decay_rate, front_decay_rate * 0.3))
                    rain_prob = max(0.0, rain_prob - delta)

        # Track episode reset (below 60 for 3+ laps resets thresholds for next episode)
        if rain_prob < 60:
            episode_below_60_count += 1
            if episode_below_60_count >= 3 and any(thresholds_crossed.values()):
                thresholds_crossed = {k: False for k in thresholds_crossed}
                player_ignored_warning = False
                weather_sc_fired = False
        else:
            episode_below_60_count = 0

        # Emit weather event strings
        if front_active:
            if rain_prob >= 55 and prev_lap_rain_prob < 55:
                events.append(f"Lap {lap}: Weather front approaching — rain possible")
                weather_summary.append(f"Lap {lap}: Weather front approaching")
            elif rain_prob >= 65 and prev_lap_rain_prob < 65:
                events.append(f"Lap {lap}: Track turning damp — conditions deteriorating")
                weather_summary.append(f"Lap {lap}: Track turning damp")
            elif rain_prob >= 92 and prev_lap_rain_prob < 92:
                events.append(f"Lap {lap}: HEAVY RAIN — standing water on track")
                weather_summary.append(f"Lap {lap}: HEAVY RAIN")
            if rain_decreasing:
                if rain_prob < 70 and prev_lap_rain_prob >= 70:
                    events.append(f"Lap {lap}: Rain easing — conditions improving")
                    weather_summary.append(f"Lap {lap}: Rain easing")
                elif rain_prob < 55 and prev_lap_rain_prob >= 55:
                    events.append(f"Lap {lap}: Track drying — slick tyres becoming viable")
                    weather_summary.append(f"Lap {lap}: Track drying")

        for did, state in states.items():
            if state.dnf:
                continue

            entry = entry_map[did]
            driver = entry.driver
            car = entry.car

            # ── Incident check ──────────────────────────────────────────
            mech_prob = (100 - car.reliability) / 100 * 0.0015
            ctrl_prob = (100 - driver.car_control) / 100 * 0.0008
            if random.random() < mech_prob + ctrl_prob:
                state.dnf = True
                state.dnf_reason = random.choice(DNF_REASONS)
                state.dnf_lap = lap
                lap_had_incident = True
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
                    lap_had_incident = True
                    events.append(f"Lap {lap}: {driver.name} retires — {state.dnf_reason}")
                    continue

            # ── Compute lap time ────────────────────────────────────────
            base = _base_lap_time(entry, circuit, rain_prob)

            fuel_delta = (state.fuel_load / 100.0) * 2.8

            wear_frac = min(1.0, state.tyre_age / max(1, life))
            compound_delta = _weather_compound_delta(state.tyre_compound, rain_prob)
            tyre_delta = wear_frac ** 2 * 4.5 + compound_delta

            stability = (driver.consistency + driver.mental) / 200.0
            lap_sigma = 0.25 * (1.0 + (1.0 - stability))
            lap_noise = random.gauss(0, lap_sigma)

            lap_time = base + fuel_delta + tyre_delta + lap_noise

            # ── SC / VSC pace penalty ────────────────────────────────
            if sc_state == "SC":
                lap_time *= 1.40
            elif sc_state == "VSC":
                lap_time *= 1.30

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
                "rain_prob": rain_prob,
            }

            # ── Update fuel & tyre age ──────────────────────────────────
            state.tyre_age += 1
            state.fuel_load = max(0.0, state.fuel_load - 100.0 / total_laps)
            state.pit_this_lap = False

            # ── Pit stop ────────────────────────────────────────────────
            if lap in pit_schedules.get(did, {}):
                next_compound = pit_schedules[did][lap]
                old_compound = state.tyre_compound
                stationary_s = round(2.0 + (90 - car.pit_crew) * 0.05 + random.gauss(0, 0.15), 2)
                stationary_s = max(1.8, stationary_s)
                total_pit_s = circuit.pit_lane_loss + stationary_s
                state.total_race_time += total_pit_s
                state.tyre_age = 0
                state.tyre_compound = next_compound
                state.stint_index += 1
                state.pit_this_lap = True
                pit_recovery_laps_left[did] = 2
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

        # ── Safety Car / VSC deployment & effects ───────────────────────
        if lap_had_incident and sc_state is None and lap < total_laps - 3:
            deployed = _check_safety_car()
            if deployed == "SC":
                sc_state = "SC"
                sc_laps_remaining = random.randint(3, 5)
                sc_lap_count = 0
                events.append(f"Lap {lap}: SAFETY CAR DEPLOYED")
            elif deployed == "VSC":
                sc_state = "VSC"
                sc_laps_remaining = random.randint(3, 5)
                sc_lap_count = 0
                events.append(f"Lap {lap}: VIRTUAL SAFETY CAR DEPLOYED")

        # ── Weather-triggered Safety Car ──────────────────────────────
        if sc_state is None and not weather_sc_fired and lap < total_laps - 3:
            rain_delta_this_lap = rain_prob - prev_lap_rain_prob
            if rain_delta_this_lap > 15:
                if random.random() < 0.30:
                    sc_state = "SC"
                    sc_laps_remaining = random.randint(3, 5)
                    sc_lap_count = 0
                    weather_sc_fired = True
                    events.append(f"Lap {lap}: SAFETY CAR — sudden heavy rain")
            elif rain_prob > 90 and prev_lap_rain_prob <= 90:
                if random.random() < 0.35:
                    sc_state = "SC"
                    sc_laps_remaining = random.randint(3, 5)
                    sc_lap_count = 0
                    weather_sc_fired = True
                    events.append(f"Lap {lap}: SAFETY CAR — aquaplaning risk")

        if sc_state is not None:
            active_sc = [d for d, s in states.items() if not s.dnf]
            active_sc.sort(key=lambda d: states[d].total_race_time)

            # ── Gap compression ──────────────────────────────────────────
            if sc_state == "SC":
                if sc_lap_count == 0:
                    # Deployment lap: compress gaps by 50%
                    if active_sc:
                        prev_t = states[active_sc[0]].total_race_time
                        for _did in active_sc[1:]:
                            gap = states[_did].total_race_time - prev_t
                            new_gap = max(0.15, gap * 0.50)
                            states[_did].total_race_time = prev_t + new_gap
                            prev_t = states[_did].total_race_time
                else:
                    # Lap 2+: hard-cap each consecutive gap to 1.0s
                    if active_sc:
                        prev_t = states[active_sc[0]].total_race_time
                        for _did in active_sc[1:]:
                            gap = states[_did].total_race_time - prev_t
                            new_gap = min(gap, 1.0)
                            states[_did].total_race_time = prev_t + new_gap
                            prev_t = states[_did].total_race_time
            elif sc_state == "VSC" and sc_lap_count == 0:
                # VSC deployment lap: mild 25% compression as cars respond to delta signal
                # Lap 2+: no compression — cars maintain existing gaps
                if active_sc:
                    prev_t = states[active_sc[0]].total_race_time
                    for _did in active_sc[1:]:
                        gap = states[_did].total_race_time - prev_t
                        new_gap = max(0.15, gap * 0.75)
                        states[_did].total_race_time = prev_t + new_gap
                        prev_t = states[_did].total_race_time

            # ── SC / VSC pit window (open every SC/VSC lap) ─────────────
            # AI pit probability decays each lap; player is always asked
            if sc_state == "SC":
                ai_pit_prob = [0.70, 0.25, 0.10][min(sc_lap_count, 2)]
            else:  # VSC
                ai_pit_prob = [0.20, 0.10][min(sc_lap_count, 1)]

            # Resolve player decisions via callback if provided (first SC lap only)
            sc_decisions: Dict[str, Optional[RaceStrategy]] = {}
            if sc_pit_callback and player_team_id and sc_lap_count == 0:
                player_infos = []
                pos_lookup = {did: pos + 1 for pos, did in enumerate(active_sc)}
                sc_forecast = _generate_weather_forecast(
                    rain_prob, rain_decreasing, front_rise_rate, front_decay_rate,
                    front_arrival_lap, lap,
                )
                sc_trend = "falling" if rain_decreasing else ("rising" if (not rain_decreasing and lap >= front_arrival_lap and front_rise_rate > 0) else "stable")
                for _did, _state in states.items():
                    if _state.dnf:
                        continue
                    if entry_map[_did].team_id == player_team_id:
                        pos_idx = pos_lookup.get(_did, 1) - 1  # 0-based
                        gap_ahead = (
                            round(states[_did].total_race_time - states[active_sc[pos_idx - 1]].total_race_time, 2)
                            if pos_idx > 0 else None
                        )
                        gap_behind = (
                            round(states[active_sc[pos_idx + 1]].total_race_time - states[_did].total_race_time, 2)
                            if pos_idx < len(active_sc) - 1 else None
                        )
                        player_infos.append({
                            "id": _did,
                            "name": entry_map[_did].driver.name,
                            "compound": _state.tyre_compound,
                            "tyre_age": _state.tyre_age,
                            "position": pos_lookup.get(_did, 0),
                            "circuit_wear": circuit.tire_wear,
                            "laps_remaining": total_laps - lap,
                            "driver_obj": entry_map[_did].driver,
                            "car_obj": entry_map[_did].car,
                            "circuit_obj": circuit,
                            "weather": weather,
                            "gap_ahead": gap_ahead,
                            "gap_behind": gap_behind,
                            "sc_type": sc_state,
                            "sc_laps_remaining": sc_laps_remaining,
                            "rain_prob": rain_prob,
                            "forecast": sc_forecast,
                            "trend": sc_trend,
                        })
                if player_infos:
                    sc_decisions = sc_pit_callback(lap, total_laps, player_infos)

            pitted_on_sc: set = set()
            for _did, _state in states.items():
                if _state.dnf:
                    continue

                is_player = player_team_id and entry_map[_did].team_id == player_team_id

                if is_player:
                    sc_strat = sc_decisions.get(_did)   # RaceStrategy or None
                    should_pit = sc_strat is not None
                elif lap > 5:
                    should_pit = random.random() < ai_pit_prob
                else:
                    should_pit = False

                if should_pit:
                    _entry = entry_map[_did]
                    _car = _entry.car
                    _driver = _entry.driver
                    if is_player and sc_strat is not None:
                        next_cmp = sc_strat.stints[0].compound.lower()
                        # Rebuild future pit schedule from new strategy
                        pit_schedules[_did] = {}
                        stint_lap = lap
                        for i, stint in enumerate(sc_strat.stints[:-1]):
                            stint_lap += stint.laps
                            pit_schedules[_did][stint_lap] = sc_strat.stints[i + 1].compound.lower()
                    else:
                        next_cmp = "medium"
                        future_pits = {fl: c for fl, c in pit_schedules.get(_did, {}).items() if fl > lap}
                        if future_pits:
                            next_fl = min(future_pits)
                            next_cmp = future_pits[next_fl]
                            del pit_schedules[_did][next_fl]
                    old_cmp = _state.tyre_compound
                    stat_s = round(2.0 + (90 - _car.pit_crew) * 0.05 + random.gauss(0, 0.15), 2)
                    stat_s = max(1.8, stat_s)
                    sc_pit_loss = circuit.pit_lane_loss * 0.5
                    total_sc_pit = sc_pit_loss + stat_s
                    _state.total_race_time += total_sc_pit
                    _state.tyre_age = 0
                    _state.tyre_compound = next_cmp
                    _state.stint_index += 1
                    pit_recovery_laps_left[_did] = 2
                    pitted_on_sc.add(_did)
                    events.append(
                        f"Lap {lap}: {_driver.name} pits under SC ({next_cmp}, {total_sc_pit:.1f}s)"
                    )
                    pit_stop_log.append(PitStop(
                        driver_name=_driver.name,
                        team_name=_entry.team_name,
                        team_color=_entry.team_color,
                        lap=lap,
                        old_compound=old_cmp,
                        new_compound=next_cmp,
                        stationary_time=stat_s,
                        pit_lane_loss=sc_pit_loss,
                        total_time=round(total_sc_pit, 2),
                    ))

            sc_laps_remaining -= 1
            sc_lap_count += 1
            if sc_laps_remaining <= 0:
                events.append(f"Lap {lap}: Racing resumes")
                sc_state = None
                sc_lap_count = 0

        # ── Weather callback (player decision at key thresholds) ─────────
        if weather_callback and sc_state is None and player_team_id:
            threshold = None

            if rain_prob >= 92 and not thresholds_crossed["wet"]:
                threshold = "wet"
                thresholds_crossed["wet"] = True
            elif rain_prob >= 65 and not thresholds_crossed["damp"] and not thresholds_crossed["wet"]:
                threshold = "damp"
                thresholds_crossed["damp"] = True
            elif (rain_prob >= 55 and not player_ignored_warning
                  and not thresholds_crossed["warning"] and warning_cooldown == 0):
                threshold = "warning"
                thresholds_crossed["warning"] = True
            elif (rain_decreasing and rain_prob < 65 and prev_lap_rain_prob >= 65
                  and peak_rain_prob > 70 and not thresholds_crossed["drying"]):
                threshold = "drying"
                thresholds_crossed["drying"] = True

            if threshold:
                forecast = _generate_weather_forecast(
                    rain_prob, rain_decreasing, front_rise_rate, front_decay_rate,
                    front_arrival_lap, lap,
                )
                trend = "falling" if rain_decreasing else ("rising" if front_active else "stable")

                _active_sorted = [d for d, s in states.items() if not s.dnf]
                _active_sorted.sort(key=lambda d: states[d].total_race_time)
                _pos_lookup = {d: p + 1 for p, d in enumerate(_active_sorted)}

                player_infos_w: list = []
                for _did, _state in states.items():
                    if _state.dnf:
                        continue
                    if entry_map[_did].team_id == player_team_id:
                        player_infos_w.append({
                            "id": _did,
                            "name": entry_map[_did].driver.name,
                            "compound": _state.tyre_compound,
                            "tyre_age": _state.tyre_age,
                            "position": _pos_lookup.get(_did, 0),
                            "circuit_wear": circuit.tire_wear,
                            "laps_remaining": total_laps - lap,
                            "driver_obj": entry_map[_did].driver,
                            "car_obj": entry_map[_did].car,
                            "circuit_obj": circuit,
                        })

                if player_infos_w:
                    weather_meta: dict = {}
                    decisions_w = weather_callback(
                        lap, total_laps, threshold, player_infos_w,
                        rain_prob, forecast, trend, weather_meta,
                    )

                    if threshold == "warning":
                        if weather_meta.get("ignored_warning"):
                            player_ignored_warning = True
                        elif all(v is None for v in decisions_w.values()):
                            # Player waited — re-arm warning after 3 laps
                            thresholds_crossed["warning"] = False
                            warning_cooldown = 3

                    # Apply pit decisions for player drivers
                    for _did, _state in states.items():
                        if _state.dnf:
                            continue
                        if entry_map[_did].team_id != player_team_id:
                            continue
                        w_strat = decisions_w.get(_did)
                        if w_strat is not None:
                            _entry = entry_map[_did]
                            _car = _entry.car
                            _driver = _entry.driver
                            next_cmp = w_strat.stints[0].compound.lower()
                            pit_schedules[_did] = {}
                            stint_lap = lap
                            for _i, _stint in enumerate(w_strat.stints[:-1]):
                                stint_lap += _stint.laps
                                pit_schedules[_did][stint_lap] = w_strat.stints[_i + 1].compound.lower()
                            old_cmp = _state.tyre_compound
                            stat_s = round(2.0 + (90 - _car.pit_crew) * 0.05 + random.gauss(0, 0.15), 2)
                            stat_s = max(1.8, stat_s)
                            total_w_pit = circuit.pit_lane_loss + stat_s
                            _state.total_race_time += total_w_pit
                            _state.tyre_age = 0
                            _state.tyre_compound = next_cmp
                            _state.stint_index += 1
                            pit_recovery_laps_left[_did] = 2
                            events.append(
                                f"Lap {lap}: {_driver.name} pits for weather ({next_cmp}, {total_w_pit:.1f}s)"
                            )
                            pit_stop_log.append(PitStop(
                                driver_name=_driver.name,
                                team_name=_entry.team_name,
                                team_color=_entry.team_color,
                                lap=lap,
                                old_compound=old_cmp,
                                new_compound=next_cmp,
                                stationary_time=stat_s,
                                pit_lane_loss=float(circuit.pit_lane_loss),
                                total_time=round(total_w_pit, 2),
                            ))

        # ── AI mid-race weather pit re-evaluation ────────────────────────
        if rain_prob >= 65 and prev_lap_rain_prob < 65:
            from engine.tyres import ai_should_pit_for_weather
            for _did, _state in states.items():
                if _state.dnf:
                    continue
                if player_team_id and entry_map[_did].team_id == player_team_id:
                    continue
                if _state.tyre_compound in ("intermediate", "wet"):
                    continue
                laps_rem = total_laps - lap
                if ai_should_pit_for_weather(_state, entry_map[_did], circuit, rain_prob, laps_rem):
                    _entry = entry_map[_did]
                    _car = _entry.car
                    _driver = _entry.driver
                    next_cmp = "intermediate" if rain_prob < 82 else "wet"
                    old_cmp = _state.tyre_compound
                    stat_s = round(2.0 + (90 - _car.pit_crew) * 0.05 + random.gauss(0, 0.15), 2)
                    stat_s = max(1.8, stat_s)
                    total_w_pit = circuit.pit_lane_loss + stat_s
                    _state.total_race_time += total_w_pit
                    _state.tyre_age = 0
                    _state.tyre_compound = next_cmp
                    _state.stint_index += 1
                    pit_recovery_laps_left[_did] = 2
                    pit_schedules[_did] = {}
                    events.append(
                        f"Lap {lap}: {_driver.name} pits for weather ({next_cmp}, {total_w_pit:.1f}s)"
                    )
                    pit_stop_log.append(PitStop(
                        driver_name=_driver.name,
                        team_name=_entry.team_name,
                        team_color=_entry.team_color,
                        lap=lap,
                        old_compound=old_cmp,
                        new_compound=next_cmp,
                        stationary_time=stat_s,
                        pit_lane_loss=float(circuit.pit_lane_loss),
                        total_time=round(total_w_pit, 2),
                    ))

        # ── Overtaking pass ─────────────────────────────────────────────
        # Sort active drivers by total race time (lowest = leader)
        active = [did for did, s in states.items() if not s.dnf]
        active.sort(key=lambda d: states[d].total_race_time)

        # Overtaking suppressed under SC / VSC
        if sc_state is None:
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
                                lap_had_incident = True
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
                        overtakes_made[behind_did] += 1

                        new_pos = i
                        if new_pos <= 10:
                            events.append(
                                f"Lap {lap}: {entry_map[behind_did].driver.name} overtakes "
                                f"{entry_map[ahead_did].driver.name} for P{new_pos}"
                            )

                    else:
                        # Failed overtake attempt — defender held their position
                        defenses_made[ahead_did] += 1

                i -= 1

        # ── Record lap data (position now known after overtaking) ────────
        active.sort(key=lambda d: states[d].total_race_time)

        # ── Strategy-gained position credit ─────────────────────────────────
        if sc_state is None:
            for pos_idx, did in enumerate(active, 1):
                curr_pos = pos_idx
                prev_pos = prev_positions.get(did)
                if pit_recovery_laps_left[did] > 0:
                    pit_recovery_laps_left[did] -= 1
                if prev_pos is None:
                    continue
                if lap_snapshots.get(did, {}).get("pitted", False):
                    continue
                if pit_recovery_laps_left[did] > 0:
                    continue
                positions_gained = prev_pos - curr_pos
                if positions_gained > 0:
                    overtakes_made[did] += positions_gained
        else:
            # Drain cooldowns even under SC so they don't carry over
            for did in active:
                if pit_recovery_laps_left[did] > 0:
                    pit_recovery_laps_left[did] -= 1

        # Update prev_positions unconditionally (SC reorders still need tracking)
        for pos_idx, did in enumerate(active, 1):
            prev_positions[did] = pos_idx

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
                    rain_prob=s.get("rain_prob", 0.0),
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
        overtakes_made=overtakes_made,
        defenses_made=defenses_made,
        peak_rain_prob=peak_rain_prob,
        weather_summary=weather_summary,
    )
