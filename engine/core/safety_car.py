"""Safety car and virtual safety car logic.

Consolidated from engine/core/weather.py and engine/race_models.py.
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from engine.core.weather import WeatherState

# ── SC deployment probabilities ──────────────────────────────────────────────
SC_PROBABILITY  = 0.50     # chance of full Safety Car on incident
VSC_PROBABILITY = 0.25     # additional chance of Virtual Safety Car on incident

# ── Weather-triggered Safety Car constants ───────────────────────────────────
WEATHER_SC_DELTA_THRESHOLD:   int   = 15    # lap-over-lap rain rise that may trigger SC
WEATHER_SC_SUDDEN_PROB:       float = 0.30  # probability of SC on sudden heavy rain
WEATHER_SC_AQUAPLANE_THRESH:  int   = 90    # rain_prob that can trigger aquaplaning SC
WEATHER_SC_AQUAPLANE_PROB:    float = 0.35  # probability at the aquaplaning threshold

# ── SC strategy recommendation ───────────────────────────────────────────────
SC_PIT_TYRE_AGE_FRAC: float = 0.55   # recommend pit if tyre_age > life * this

# ── SC lap time and duration ─────────────────────────────────────────────────
SC_LAP_TIME_MULTIPLIER  = 1.40
VSC_LAP_TIME_MULTIPLIER = 1.30
SC_DURATION_MIN = 3
SC_DURATION_MAX = 5


def check_safety_car() -> Optional[str]:
    """Roll for safety car deployment on an incident. Returns 'SC', 'VSC', or None."""
    roll = random.random()
    if roll < SC_PROBABILITY:
        return "SC"
    if roll < SC_PROBABILITY + VSC_PROBABILITY:
        return "VSC"
    return None


def should_trigger_weather_sc(
    state: WeatherState,
    rain_prob: float,
    prev_rain_prob: float,
    lap: int,
    total_laps: int,
) -> Optional[str]:
    """Check if sudden rain change warrants deploying a safety car.

    Returns 'SC' or None. Does NOT mutate state — caller sets weather_sc_fired.
    """
    if state.weather_sc_fired or lap >= total_laps - 3:
        return None
    rain_delta = rain_prob - prev_rain_prob
    if rain_delta > WEATHER_SC_DELTA_THRESHOLD:
        if random.random() < WEATHER_SC_SUDDEN_PROB:
            return "SC"
    if rain_prob > WEATHER_SC_AQUAPLANE_THRESH and prev_rain_prob <= WEATHER_SC_AQUAPLANE_THRESH:
        if random.random() < WEATHER_SC_AQUAPLANE_PROB:
            return "SC"
    return None


def should_recommend_sc_pit(tyre_age: int, base_life: int) -> bool:
    """Return True if the tyre age warrants a pit recommendation under safety car.

    Threshold: tyre_age > base_life * SC_PIT_TYRE_AGE_FRAC (0.55).
    """
    return tyre_age > base_life * SC_PIT_TYRE_AGE_FRAC
