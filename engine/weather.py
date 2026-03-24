"""Weather simulation: rain probability drift, SC rolls, compound deltas.
# Functions: _check_safety_car:12  _lerp:22  _weather_compound_delta:26  _effective_wet_weight:74  _generate_weather_forecast:89
"""
from __future__ import annotations

import random
from typing import List, Optional

from engine.race_models import SC_PROBABILITY, VSC_PROBABILITY


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
    """Simulate next 15 laps of rain probability with increasing uncertainty."""
    noise_by_offset = [4, 4, 10, 10, 12, 18, 18, 20, 22, 22, 26, 26, 30, 30, 32]
    forecast: List[float] = []
    prob = rain_prob
    for i in range(15):
        if rain_decreasing:
            rate = decay_rate
            prob = max(0.0, prob - max(0.0, random.gauss(rate, rate * 0.3)))
        elif current_lap + i >= front_arrival_lap and rise_rate > 0:
            rate = rise_rate
            prob = min(100.0, prob + max(0.0, random.gauss(rate, rate * 0.35)))
        noise = random.gauss(0, noise_by_offset[i])
        forecast.append(max(0.0, min(100.0, prob + noise)))
    return forecast
