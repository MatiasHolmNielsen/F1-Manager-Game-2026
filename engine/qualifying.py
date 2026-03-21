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


@dataclass
class KnockoutQualiResult:
    q1: List[QualiResult]        # all 20, session-relative deltas
    q2: List[QualiResult]        # top 15, session-relative deltas
    q3: List[QualiResult]        # top 10, session-relative deltas
    final_grid: List[QualiResult]  # positions 1–20, absolute grid order


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


def _entries_for_results(results: List[QualiResult], all_entries: List) -> List:
    entry_map = {e.driver.id: e for e in all_entries}
    return [entry_map[r.driver.id] for r in results if r.driver.id in entry_map]


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


def simulate_knockout_qualifying(
    entries: List,
    circuit,
    weather: str = "dry",
) -> KnockoutQualiResult:
    """Simulate Q1/Q2/Q3 knockout qualifying and return all sessions plus final grid."""
    # Q1 — all 20 drivers
    q1 = simulate_qualifying(entries, circuit, weather)

    # Q2 — top 15 from Q1
    q2_entries = _entries_for_results(q1[:15], entries)
    q2 = simulate_qualifying(q2_entries, circuit, weather)

    # Q3 — top 10 from Q2
    q3_entries = _entries_for_results(q2[:10], entries)
    q3 = simulate_qualifying(q3_entries, circuit, weather)

    # Assemble final grid: P1–10 from Q3, P11–15 from Q2, P16–20 from Q1
    final_grid: List[QualiResult] = []
    for r in q3:
        final_grid.append(r)  # positions already 1–10

    for i, r in enumerate(q2[10:15], 11):
        final_grid.append(QualiResult(
            position=i,
            driver=r.driver,
            team_id=r.team_id,
            team_name=r.team_name,
            team_color=r.team_color,
            lap_time_delta=r.lap_time_delta,
        ))

    for i, r in enumerate(q1[15:20], 16):
        final_grid.append(QualiResult(
            position=i,
            driver=r.driver,
            team_id=r.team_id,
            team_name=r.team_name,
            team_color=r.team_color,
            lap_time_delta=r.lap_time_delta,
        ))

    return KnockoutQualiResult(q1=q1, q2=q2, q3=q3, final_grid=final_grid)
