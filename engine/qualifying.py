from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from engine.race import RaceEntry


@dataclass
class QualiResult:
    position: int
    driver: object
    team_id: str
    team_name: str
    team_color: str
    lap_time_delta: float   # gap to pole in seconds (0.000 for P1)


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
