"""Pure lap time and overtake calculations.
# Functions: _base_lap_time:12  _attempt_overtake:42
"""
from __future__ import annotations

import random

from engine.race_models import RaceEntry, OVERTAKE_THRESHOLD, BATTLE_RANGE_S
from engine.core.weather import wet_weather_weight as _effective_wet_weight


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
