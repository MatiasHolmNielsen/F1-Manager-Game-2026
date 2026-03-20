from __future__ import annotations

import random
from dataclasses import dataclass, field
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


def simulate_race(
    entries: List[RaceEntry],
    circuit: Circuit,
    weather: str = "dry",
) -> List[RaceResult]:
    """Simulate a full race and return results sorted by finishing position."""
    scored = [
        (entry, _performance_score(entry, circuit, weather))
        for entry in entries
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    results: List[RaceResult] = []
    leader_score: Optional[float] = None

    for entry, score in scored:
        # DNF probability scales inversely with reliability
        dnf_prob = max(0.005, (100 - entry.car.reliability) / 100 * 0.25)
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

    # Assign positions: finishers first, then DNFs
    finishers = [r for r in results if not r.dnf]
    dnfs = [r for r in results if r.dnf]

    for i, r in enumerate(finishers, 1):
        r.position = i
        r.points = POINTS_SYSTEM.get(i, 0)

    for i, r in enumerate(dnfs, len(finishers) + 1):
        r.position = i

    # Fastest lap bonus point (goes to race leader if in top 10)
    if finishers:
        finishers[0].fastest_lap = True
        if finishers[0].position <= 10:
            finishers[0].points += 1

    return finishers + dnfs


def _performance_score(
    entry: RaceEntry,
    circuit: Circuit,
    weather: str,
) -> float:
    """Calculate a performance score for a driver+car at a specific circuit."""
    driver = entry.driver
    car = entry.car

    aero_w = circuit.aero_weight
    engine_w = circuit.engine_weight

    # Car performance (50% of total score)
    car_score = (car.aerodynamics * aero_w + car.engine * engine_w) * 0.5

    # Driver performance (40% of total score)
    if weather == "wet":
        eff_speed = driver.speed * 0.30 + driver.wet_weather * 0.70
    else:
        eff_speed = driver.speed

    driver_score = (
        eff_speed * 0.50
        + driver.consistency * 0.25
        + driver.experience * 0.15
        + driver.overtaking * 0.10
    ) * 0.4

    # Tire management bonus (10% of total score)
    tire_bonus = (car.tire_management / 100) * 10 * (1.0 / circuit.tire_wear_factor)

    # Randomness — less consistent drivers have higher variance
    variance_mult = 1.0 + (100 - driver.consistency) / 150
    randomness = random.gauss(0, 3.0 * variance_mult)

    return car_score + driver_score + tire_bonus + randomness
