"""Base lap time calculation.

Extracted from engine/race_physics.py.
"""
from __future__ import annotations

from engine.race_models import RaceEntry
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
