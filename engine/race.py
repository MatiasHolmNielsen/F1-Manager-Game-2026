from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, TYPE_CHECKING

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

TYRE_COMPOUNDS = {
    "hard":         {"pace_bonus": -2.0, "color": "white",  "symbol": "H", "rain": False},
    "medium":       {"pace_bonus":  0.0, "color": "yellow", "symbol": "M", "rain": False},
    "soft":         {"pace_bonus":  3.0, "color": "red",    "symbol": "S", "rain": False},
    "intermediate": {"pace_bonus":  1.5, "color": "green",  "symbol": "I", "rain": True},
    "wet":          {"pace_bonus":  3.0, "color": "blue",   "symbol": "W", "rain": True},
}

# Base tyre life in laps per compound per circuit wear level
TYRE_LIFE_BASE = {
    "low":    {"hard": 40, "medium": 26, "soft": 18},
    "medium": {"hard": 30, "medium": 19, "soft": 13},
    "high":   {"hard": 20, "medium": 13, "soft": 9},
}
# Intermediate: 28 laps base;  Wet: 35 laps base (weather-dependent, not circuit wear)


@dataclass
class TyreStint:
    compound: str   # "hard" | "medium" | "soft" | "intermediate" | "wet"
    laps: int


@dataclass
class RaceStrategy:
    stints: List[TyreStint]
    label: str = ""


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
class QualiResult:
    position: int
    driver: Driver
    team_id: str
    team_name: str
    team_color: str
    lap_time_delta: float   # gap to pole in seconds (0.000 for P1)


# ─── Tyre / Strategy helpers ──────────────────────────────────────────────────

def race_laps(circuit) -> int:
    """Standard F1 race distance: ~305 km."""
    return round(305 / circuit.length_km)


def adjusted_tyre_life(compound: str, circuit, car, driver) -> int:
    """
    Return how many laps a compound lasts for this car/driver combo.

    Driver factor: ×0.60–×1.40  (tire_management 0–100)
    Car factor:    ×0.70–×1.30  (tire_deg 0–100)
    """
    if compound == "intermediate":
        base = 28
    elif compound == "wet":
        base = 35
    else:
        base = TYRE_LIFE_BASE[circuit.tire_wear][compound]

    driver_factor = 0.6 + driver.tire_management / 100 * 0.8
    car_factor = 0.7 + car.tire_deg / 100 * 0.6
    return max(3, int(base * driver_factor * car_factor))


def _tyre_score(strategy: RaceStrategy, circuit, weather: str, car, driver) -> float:
    """
    Convert a full race strategy into a performance score contribution.

    Rewards good compound choice and penalises overruns and pit stops.
    """
    total_laps = sum(s.laps for s in strategy.stints)
    if total_laps == 0:
        return 0.0

    stint_contributions = 0.0
    for stint in strategy.stints:
        compound = stint.compound
        life = adjusted_tyre_life(compound, circuit, car, driver)
        info = TYRE_COMPOUNDS[compound]
        compound_bonus = info["pace_bonus"]
        is_rain = info["rain"]

        # Wrong-compound penalties
        if is_rain and weather == "dry":
            avg_bonus = compound_bonus - 12.0
        elif not is_rain and weather == "wet":
            avg_bonus = compound_bonus - 10.0
        elif stint.laps <= life:
            avg_bonus = compound_bonus
        else:
            overrun_frac = (stint.laps - life) / life
            avg_bonus = compound_bonus - (overrun_frac * 8.0)

        stint_contributions += avg_bonus * (stint.laps / total_laps)

    # Pit stop time penalty (each stop after the first stint)
    num_stops = len(strategy.stints) - 1
    pit_time = 3.5 - (car.pit_crew / 100) * 1.3   # 2.2s–3.5s range
    score_penalty_per_stop = pit_time / 1.2
    total_pit_penalty = num_stops * score_penalty_per_stop

    return stint_contributions - total_pit_penalty


def suggest_strategies(circuit, weather: str, car, driver) -> List[RaceStrategy]:
    """Return 3–4 labelled preset strategies for the given conditions."""
    total = race_laps(circuit)

    if weather == "wet":
        inter_life = adjusted_tyre_life("intermediate", circuit, car, driver)
        split = min(inter_life, total // 2)
        return [
            RaceStrategy(stints=[TyreStint("intermediate", total)], label="Intermediate Only"),
            RaceStrategy(stints=[TyreStint("wet", total)],          label="Wet Only"),
            RaceStrategy(
                stints=[TyreStint("intermediate", split), TyreStint("wet", total - split)],
                label="Inter → Wet",
            ),
        ]

    hard_life   = adjusted_tyre_life("hard",   circuit, car, driver)
    medium_life = adjusted_tyre_life("medium", circuit, car, driver)
    soft_life   = adjusted_tyre_life("soft",   circuit, car, driver)

    # Aggressive: S → H
    soft_laps = max(1, min(soft_life, total // 3))
    aggressive = RaceStrategy(
        stints=[TyreStint("soft", soft_laps), TyreStint("hard", total - soft_laps)],
        label="Aggressive",
    )

    # Medium Start: M → S
    half = total // 2
    balanced = RaceStrategy(
        stints=[TyreStint("medium", half), TyreStint("soft", total - half)],
        label="Medium Start",
    )

    # Conservative: H → S
    hard_laps = max(1, min(hard_life, (total * 2) // 3))
    conservative = RaceStrategy(
        stints=[TyreStint("hard", hard_laps), TyreStint("soft", total - hard_laps)],
        label="Conservative",
    )

    # 2-Stop: S → M → M
    soft_2 = max(1, min(soft_life, total // 4))
    remaining = total - soft_2
    m1, m2 = remaining // 2, remaining - remaining // 2
    two_stop = RaceStrategy(
        stints=[TyreStint("soft", soft_2), TyreStint("medium", m1), TyreStint("medium", m2)],
        label="2-Stop",
    )

    return [aggressive, balanced, conservative, two_stop]


def ai_strategy(entry: RaceEntry, circuit, weather: str) -> RaceStrategy:
    """Choose a strategy heuristically for an AI driver."""
    car = entry.car
    driver = entry.driver

    if weather == "wet":
        compound = "wet" if circuit.weather_chance >= 60 else "intermediate"
        return RaceStrategy(
            stints=[TyreStint(compound, race_laps(circuit))],
            label="Intermediate Only" if compound == "intermediate" else "Wet Only",
        )

    strategies = suggest_strategies(circuit, weather, car, driver)

    # Heuristic: conservative teams prefer 1-stop hard/soft, others vary
    if car.tire_deg > 80 and driver.tire_management > 75:
        idx = 2  # Conservative
    elif car.tire_deg < 70 or driver.tire_management < 65:
        idx = 3  # 2-Stop to avoid overrun
    else:
        idx = random.randint(0, 1)  # Aggressive or Balanced

    # Small random nudge
    idx = max(0, min(len(strategies) - 1, idx + random.randint(-1, 1)))
    return strategies[idx]


# ─── Qualifying ───────────────────────────────────────────────────────────────

def _qualifying_score(entry: RaceEntry, circuit, weather: str) -> float:
    """One-lap qualifying performance score."""
    driver = entry.driver
    car = entry.car

    aero_w = circuit.aero_weight
    engine_w = circuit.engine_weight
    mech_w = 1.0 - aero_w

    car_score = (
        car.aerodynamics   * aero_w   * 0.50
        + car.engine       * engine_w * 0.50
        + car.mechanical_grip * mech_w * 0.15
    ) * 0.45

    if weather == "wet":
        eff_quali = driver.qualifying_pace * 0.20 + driver.wet_weather * 0.80
    else:
        eff_quali = driver.qualifying_pace

    driver_score = (
        eff_quali            * 0.65
        + driver.mental      * 0.20
        + driver.consistency * 0.15
    ) * 0.55

    stability = (driver.consistency + driver.mental) / 200
    randomness = random.gauss(0, 1.2 * (1.0 + (1.0 - stability)))

    return car_score + driver_score + randomness


def simulate_qualifying(
    entries: List[RaceEntry],
    circuit,
    weather: str = "dry",
) -> List[QualiResult]:
    """Simulate a qualifying session and return results sorted by position (P1 first)."""
    scored = [(entry, _qualifying_score(entry, circuit, weather)) for entry in entries]
    scored.sort(key=lambda x: x[1], reverse=True)

    pole_score = scored[0][1]
    results: List[QualiResult] = []
    for pos, (entry, score) in enumerate(scored, 1):
        delta = (pole_score - score) * 0.08 + random.uniform(0.001, 0.120) if pos > 1 else 0.0
        results.append(QualiResult(
            position=pos,
            driver=entry.driver,
            team_id=entry.team_id,
            team_name=entry.team_name,
            team_color=entry.team_color,
            lap_time_delta=round(delta, 3),
        ))
    return results


# ─── Race ─────────────────────────────────────────────────────────────────────

def _performance_score(
    entry: RaceEntry,
    circuit,
    weather: str,
    grid_position: int = 10,
    strategy: Optional[RaceStrategy] = None,
) -> float:
    """
    Calculate a performance score for a driver+car at a circuit.

    Score breakdown:
      48% — car performance (engine, aero, mechanical grip, braking)
       7% — tyre management / strategy
      45% — driver performance (pace, consistency, racecraft, mental, experience)
    """
    driver = entry.driver
    car = entry.car

    aero_w = circuit.aero_weight
    engine_w = circuit.engine_weight
    mech_w = 1.0 - aero_w

    # ── Car performance (48%) ───────────────────────────────────────
    car_base = (
        car.aerodynamics  * aero_w   * 0.50
        + car.engine      * engine_w * 0.50
        + car.mechanical_grip * mech_w * 0.15
    )
    overtake_chance = (100 - circuit.overtaking_difficulty) / 100
    braking_bonus = car.braking * 0.05 * overtake_chance

    car_score = car_base * 0.48 + braking_bonus

    # ── Tyre score (7%) ─────────────────────────────────────────────
    if strategy:
        tire_score = _tyre_score(strategy, circuit, weather, car, driver)
    else:
        # Fallback: medium/medium default (no strategy selected)
        combined_tyre = car.tire_deg * 0.40 + driver.tire_management * 0.60
        tire_score = (combined_tyre / 100) * 12 / circuit.tire_wear_factor

    # ── Driver performance (45%) ────────────────────────────────────
    if weather == "wet":
        eff_pace = driver.pace * 0.15 + driver.wet_weather * 0.85
    else:
        eff_pace = driver.pace

    driver_score = (
        eff_pace             * 0.40
        + driver.consistency * 0.20
        + driver.racecraft   * 0.18
        + driver.mental      * 0.12
        + driver.experience  * 0.10
    ) * 0.45

    # Grid position bonus — front-runners get clean air
    grid_bonus = 3.5 - (grid_position - 1) * (5.5 / 19)

    # ── Randomness ──────────────────────────────────────────────────
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
) -> List[RaceResult]:
    """Simulate a full race and return results sorted by finishing position."""
    scored = [
        (entry, _performance_score(
            entry, circuit, weather,
            grid_position=(grid.index(entry.driver.id) + 1 if grid and entry.driver.id in grid else 10),
            strategy=(strategies.get(entry.driver.id) if strategies else None),
        ))
        for entry in entries
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    results: List[RaceResult] = []
    leader_score: Optional[float] = None

    for entry, score in scored:
        gp = grid.index(entry.driver.id) + 1 if grid and entry.driver.id in grid else 0
        driver_safety = 1.0 - (entry.driver.racecraft / 100) * 0.20
        dnf_prob = max(0.005, (100 - entry.car.reliability) / 100 * 0.25 * driver_safety)
        dnf = random.random() < dnf_prob

        if dnf:
            results.append(RaceResult(
                position=0,
                driver=entry.driver,
                team_id=entry.team_id,
                team_name=entry.team_name,
                team_color=entry.team_color,
                time_gap=0.0,
                points=0,
                dnf=True,
                dnf_reason=random.choice(DNF_REASONS),
                grid_position=gp,
            ))
            continue

        if leader_score is None:
            leader_score = score
            gap = 0.0
        else:
            gap = round((leader_score - score) * 1.2 + random.uniform(0.1, 1.5), 3)

        results.append(RaceResult(
            position=0,
            driver=entry.driver,
            team_id=entry.team_id,
            team_name=entry.team_name,
            team_color=entry.team_color,
            time_gap=gap,
            points=0,
            grid_position=gp,
        ))

    # Assign positions — finishers first, DNFs after
    finishers = [r for r in results if not r.dnf]
    dnfs = [r for r in results if r.dnf]

    for i, r in enumerate(finishers, 1):
        r.position = i
        r.points = POINTS_SYSTEM.get(i, 0)

    for i, r in enumerate(dnfs, len(finishers) + 1):
        r.position = i

    # Fastest lap bonus (race leader, if in top 10)
    if finishers:
        finishers[0].fastest_lap = True
        if finishers[0].position <= 10:
            finishers[0].points += 1

    return finishers + dnfs
