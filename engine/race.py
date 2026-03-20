from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List, Optional, TYPE_CHECKING

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


@dataclass
class QualiResult:
    position: int
    driver: Driver
    team_id: str
    team_name: str
    team_color: str
    lap_time_delta: float   # gap to pole in seconds (0.000 for P1)


def _qualifying_score(entry: RaceEntry, circuit: Circuit, weather: str) -> float:
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
    circuit: Circuit,
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


def simulate_race(
    entries: List[RaceEntry],
    circuit: Circuit,
    weather: str = "dry",
    grid: Optional[List[str]] = None,
) -> List[RaceResult]:
    """Simulate a full race and return results sorted by finishing position."""
    scored = [
        (entry, _performance_score(entry, circuit, weather, grid_position=(
            grid.index(entry.driver.id) + 1 if grid and entry.driver.id in grid else 10
        )))
        for entry in entries
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    results: List[RaceResult] = []
    leader_score: Optional[float] = None

    for entry, score in scored:
        # DNF chance: car reliability is the base, skilled racecraft reduces it
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


def _performance_score(
    entry: RaceEntry,
    circuit: Circuit,
    weather: str,
    grid_position: int = 10,
) -> float:
    """
    Calculate a performance score for a driver+car at a circuit.

    Score breakdown:
      48% — car performance (engine, aero, mechanical grip, braking)
       7% — tyre management (car + driver combined)
      45% — driver performance (pace, consistency, racecraft, mental, experience)
    """
    driver = entry.driver
    car = entry.car

    aero_w = circuit.aero_weight
    engine_w = circuit.engine_weight
    # mechanical grip is most useful where aero is less dominant (slow corners)
    mech_w = 1.0 - aero_w

    # ── Car performance (48%) ───────────────────────────────────────
    car_base = (
        car.aerodynamics  * aero_w   * 0.50
        + car.engine      * engine_w * 0.50
        + car.mechanical_grip * mech_w * 0.15
    )
    # Braking matters more at circuits where overtaking is possible
    # (tight braking zones are where positions are won/lost)
    overtake_chance = (100 - circuit.overtaking_difficulty) / 100
    braking_bonus = car.braking * 0.05 * overtake_chance

    car_score = car_base * 0.48 + braking_bonus

    # ── Tyre score (7%) ─────────────────────────────────────────────
    # Car tyre characteristics + driver tyre preservation skill
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

    # Grid position bonus — front-runners get clean air, backmarkers lose time
    # P1 = +3.50, P10 ≈ +0.39, P20 = -2.00
    grid_bonus = 3.5 - (grid_position - 1) * (5.5 / 19)

    # ── Randomness ──────────────────────────────────────────────────
    # Consistency + mental reduce variance; low-skill drivers are more chaotic
    stability = (driver.consistency + driver.mental) / 200
    variance = 2.5 * (1.0 + (1.0 - stability))
    randomness = random.gauss(0, variance)

    return car_score + tire_score + driver_score + grid_bonus + randomness
