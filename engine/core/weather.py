"""Single source of truth for all weather simulation logic.

Consolidated from:
  engine/weather.py        — all existing functions (check_safety_car, compound_pace_delta,
                             wet_weather_weight, generate_weather_forecast)
  engine/race.py           — WeatherState dataclass, front initialisation, per-lap rain drift,
                             threshold detection, weather-triggered SC logic, event messages
  game/ui/weather_sc.py    — pure logic only: trim_strategy_to_remaining,
                             should_recommend_sc_pit

No UI imports. Pure functions only.
Race-wiring happens in Session 5 — race.py calls here instead of inline logic.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from engine.race_models import SC_PROBABILITY, VSC_PROBABILITY
from engine.tyres import COMPOUND_PACE_DELTA, TYRE_LIFE_BASE, TyreStint, RaceStrategy


# ── Named constants for rain intensity thresholds ────────────────────────────
# These values appear as magic numbers throughout the old code. Named here once.
#
#  RAIN_WARNING   = 55   slicks start accruing penalty; player "warning" alert fires
#  RAIN_DAMP      = 65   track "damp"; intermediates becoming competitive
#  RAIN_WET_ONSET = 80   wets start paying off; SC aquaplaning risk begins
#  RAIN_HEAVY     = 92   full wet conditions; standing water on circuit

RAIN_WARNING:     int = 55
RAIN_DAMP:        int = 65
RAIN_WET_ONSET:   int = 80
RAIN_HEAVY:       int = 92

# ── Weather-triggered Safety Car constants ───────────────────────────────────
WEATHER_SC_DELTA_THRESHOLD:   int   = 15    # lap-over-lap rain rise that may trigger SC
WEATHER_SC_SUDDEN_PROB:       float = 0.30  # probability of SC on sudden heavy rain
WEATHER_SC_AQUAPLANE_THRESH:  int   = 90    # rain_prob that can trigger aquaplaning SC
WEATHER_SC_AQUAPLANE_PROB:    float = 0.35  # probability at the aquaplaning threshold

# ── SC strategy recommendation ───────────────────────────────────────────────
SC_PIT_TYRE_AGE_FRAC: float = 0.55   # recommend pit if tyre_age > life * this


# ── WeatherState dataclass ───────────────────────────────────────────────────

@dataclass
class WeatherState:
    """All mutable weather tracking state for a single race simulation.

    Replaces the ~15 scattered local variables in simulate_race().
    Passed to step_rain_probability() each lap; mutated in-place.
    """
    rain_prob:               float
    wet_start:               bool  = False  # race started in wet conditions
    front_active:            bool  = False
    front_arrival_lap:       int   = 0
    front_rise_rate:         float = 0.0
    front_decay_rate:        float = 0.0
    peak_duration:           int   = 0
    laps_above_peak:         int   = 0
    rain_decreasing:         bool  = False
    peak_rain_prob:          float = 0.0
    episode_below_60_count:  int   = 0
    # Four decision thresholds; reset after 3 dry laps
    thresholds_crossed: Dict[str, bool] = field(default_factory=lambda: {
        "warning": False, "damp": False, "wet": False, "drying": False,
    })
    player_ignored_warning:  bool = False
    weather_sc_fired:        bool = False
    warning_cooldown:        int  = 0


# ── Internal helper ──────────────────────────────────────────────────────────

def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


# ── Safety car roll ──────────────────────────────────────────────────────────

def check_safety_car() -> Optional[str]:
    """Roll for safety car deployment on an incident. Returns 'SC', 'VSC', or None."""
    roll = random.random()
    if roll < SC_PROBABILITY:
        return "SC"
    if roll < SC_PROBABILITY + VSC_PROBABILITY:
        return "VSC"
    return None


# ── Compound pace delta ──────────────────────────────────────────────────────

def compound_pace_delta(compound: str, rain_prob: float) -> float:
    """Per-lap pace delta (seconds) for a compound at the current track wetness.

    Positive values mean slower (penalty). Negative values mean faster bonus.
    Mirrors the old _weather_compound_delta() with named threshold constants.
    """
    base = COMPOUND_PACE_DELTA.get(compound, 0.0)

    if compound in ("soft", "medium", "hard"):
        if rain_prob <= RAIN_WARNING:
            return base
        elif rain_prob <= RAIN_DAMP:
            t = (rain_prob - RAIN_WARNING) / 10
            return base + _lerp(0.0, 2.0, t)
        elif rain_prob <= RAIN_WET_ONSET:
            t = (rain_prob - RAIN_DAMP) / 15
            return base + _lerp(2.0, 5.0, t)
        elif rain_prob <= RAIN_HEAVY:
            t = (rain_prob - RAIN_WET_ONSET) / 12
            return base + _lerp(5.0, 9.0, t)
        else:
            t = (rain_prob - RAIN_HEAVY) / 8
            return base + _lerp(9.0, 12.5, t)

    elif compound == "intermediate":
        # Optimal window: 40–92% rain_prob
        if rain_prob <= 40:
            return 6.0
        elif rain_prob <= RAIN_DAMP:
            t = (rain_prob - 40) / 25
            return _lerp(6.0, 0.2, t)
        elif rain_prob <= RAIN_HEAVY:
            return 0.2
        else:
            t = (rain_prob - RAIN_HEAVY) / 8
            return _lerp(0.2, 2.7, t)

    elif compound == "wet":
        # Wet tyre optimal window starts around 82%+
        # Breakpoints 55/70/82 are specific to wet tyre curve, not general thresholds
        if rain_prob <= RAIN_WARNING:
            return 12.0
        elif rain_prob <= 70:
            t = (rain_prob - RAIN_WARNING) / 15
            return _lerp(12.0, 3.0, t)
        elif rain_prob <= 82:
            t = (rain_prob - 70) / 12
            return _lerp(3.0, 0.8, t)
        else:
            return 0.8

    return base


# ── Wet-weather driver stat weight ───────────────────────────────────────────

def wet_weather_weight(rain_prob: float) -> float:
    """Scale the wet_weather driver stat weight from 0 → 0.85 as rain_prob rises 40 → 100.

    Mirrors the old _effective_wet_weight().
    """
    if rain_prob <= 40:
        return 0.0
    elif rain_prob <= RAIN_DAMP:
        t = (rain_prob - 40) / 25
        return _lerp(0.0, 0.30, t)
    elif rain_prob <= RAIN_WET_ONSET:
        t = (rain_prob - RAIN_DAMP) / 15
        return _lerp(0.30, 0.60, t)
    else:
        t = min(1.0, (rain_prob - RAIN_WET_ONSET) / 20)
        return _lerp(0.60, 0.85, t)


# ── Weather forecast ─────────────────────────────────────────────────────────

def generate_weather_forecast(
    rain_prob: float,
    rain_decreasing: bool,
    rise_rate: float,
    decay_rate: float,
    front_arrival_lap: int,
    current_lap: int,
) -> List[float]:
    """Simulate next 15 laps of rain probability with increasing uncertainty.

    Mirrors the old _generate_weather_forecast().
    """
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


# ── Weather front initialisation ─────────────────────────────────────────────

def init_weather_state(weather: str, circuit, total_laps: int) -> WeatherState:
    """Initialise WeatherState for a race. May schedule an incoming or clearing rain front.

    Extracted from simulate_race() lines 157–195.
    """
    rain_prob = 85.0 if weather == "wet" else 0.0
    state = WeatherState(
        rain_prob=rain_prob,
        peak_rain_prob=rain_prob,
        wet_start=(weather == "wet"),
    )

    if weather == "dry" and random.random() * 100 < circuit.weather_chance:
        earliest = max(3, int(total_laps * 0.15))
        latest   = max(earliest + 1, min(total_laps - 5, int(total_laps * 0.85)))
        state.front_arrival_lap = random.randint(earliest, latest)
        strength = random.choices(["light", "moderate", "heavy"], weights=[40, 40, 20])[0]
        rise_rates     = {"light": 5.5,  "moderate": 10.0, "heavy": 17.0}
        decay_rates    = {"light": 5.0,  "moderate": 7.0,  "heavy": 6.0}
        peak_durations = {"light": 5,    "moderate": 8,    "heavy": 12}
        state.front_rise_rate  = rise_rates[strength]
        state.front_decay_rate = decay_rates[strength]
        state.peak_duration    = peak_durations[strength]
        state.front_active     = True

    if weather == "wet" and random.random() < 0.50:
        dry_start = max(3, total_laps // 4)
        dry_end   = max(dry_start + 1, total_laps - 5)
        state.front_arrival_lap = random.randint(dry_start, dry_end)
        state.front_decay_rate  = random.uniform(4.0, 8.0)
        state.rain_decreasing   = True
        state.front_active      = True

    return state


# ── Per-lap rain drift ────────────────────────────────────────────────────────

def step_rain_probability(state: WeatherState, lap: int) -> Tuple[float, List[str]]:
    """Advance rain probability one lap. Mutates state in-place.

    Returns (prev_rain_prob, event_messages).
    event_messages are plain-text strings suitable for the race events log.

    Extracted from simulate_race() lines 204–251.

    Note: race.py also populates weather_summary (a shorter subset of event_messages).
    When wiring in Session 5, pass the returned messages to both events and
    weather_summary as appropriate.
    """
    prev = state.rain_prob

    if state.warning_cooldown > 0:
        state.warning_cooldown -= 1

    if state.front_active:
        if not state.rain_decreasing and lap >= state.front_arrival_lap:
            delta = max(0.0, random.gauss(state.front_rise_rate, state.front_rise_rate * 0.35))
            state.rain_prob = min(100.0, state.rain_prob + delta)
            if state.rain_prob > state.peak_rain_prob:
                state.peak_rain_prob = state.rain_prob
            if state.rain_prob >= RAIN_WET_ONSET:
                state.laps_above_peak += 1
                if state.laps_above_peak >= state.peak_duration:
                    state.rain_decreasing = True
            else:
                state.laps_above_peak = 0
        elif state.rain_decreasing:
            # For a wet-start race, don't decay until the drying front arrives
            if not (state.wet_start and lap < state.front_arrival_lap):
                delta = max(0.0, random.gauss(state.front_decay_rate, state.front_decay_rate * 0.3))
                state.rain_prob = max(0.0, state.rain_prob - delta)

    # Reset thresholds once it's been below 60% for 3 consecutive laps
    if state.rain_prob < 60:
        state.episode_below_60_count += 1
        if state.episode_below_60_count >= 3 and any(state.thresholds_crossed.values()):
            state.thresholds_crossed = {k: False for k in state.thresholds_crossed}
            state.player_ignored_warning = False
            state.weather_sc_fired = False
    else:
        state.episode_below_60_count = 0

    msgs = weather_event_messages(lap, state.rain_prob, prev, state.rain_decreasing, state.front_active)
    return prev, msgs


# ── Weather event messages ────────────────────────────────────────────────────

def weather_event_messages(
    lap: int,
    rain_prob: float,
    prev_rain_prob: float,
    rain_decreasing: bool,
    front_active: bool,
) -> List[str]:
    """Plain-text race event strings for weather threshold crossings this lap.

    Extracted from simulate_race() lines 235–251.
    Returns an empty list if no threshold was crossed.
    """
    if not front_active:
        return []
    msgs: List[str] = []
    # Rising thresholds — only one fires per lap (elif chain mirrors original)
    if rain_prob >= RAIN_WARNING and prev_rain_prob < RAIN_WARNING:
        msgs.append(f"Lap {lap}: Weather front approaching — rain possible")
    elif rain_prob >= RAIN_DAMP and prev_rain_prob < RAIN_DAMP:
        msgs.append(f"Lap {lap}: Track turning damp — conditions deteriorating")
    elif rain_prob >= RAIN_HEAVY and prev_rain_prob < RAIN_HEAVY:
        msgs.append(f"Lap {lap}: HEAVY RAIN — standing water on track")
    # Falling thresholds checked independently
    if rain_decreasing:
        if rain_prob < 70 and prev_rain_prob >= 70:
            msgs.append(f"Lap {lap}: Rain easing — conditions improving")
        elif rain_prob < RAIN_WARNING and prev_rain_prob >= RAIN_WARNING:
            msgs.append(f"Lap {lap}: Track drying — slick tyres becoming viable")
    return msgs


# ── Rain trend ────────────────────────────────────────────────────────────────

def get_rain_trend(state: WeatherState, lap: int) -> str:
    """Return 'rising', 'falling', or 'stable' for the current rain trajectory.

    Extracted from the inline trend calculation in simulate_race() (two occurrences).
    """
    if state.rain_decreasing:
        return "falling"
    if state.front_active and lap >= state.front_arrival_lap and state.front_rise_rate > 0:
        return "rising"
    return "stable"


# ── Threshold detection ───────────────────────────────────────────────────────

def detect_weather_threshold(
    state: WeatherState,
    rain_prob: float,
    prev_rain_prob: float,
) -> Optional[str]:
    """Determine if rain has crossed a strategy-decision threshold this lap.

    Returns 'warning', 'damp', 'wet', 'drying', or None.
    Does NOT mutate state — caller updates thresholds_crossed after acting.

    Extracted from simulate_race() lines 526–539.
    """
    tc = state.thresholds_crossed
    if rain_prob >= RAIN_HEAVY and not tc["wet"]:
        return "wet"
    if rain_prob >= RAIN_DAMP and not tc["damp"] and not tc["wet"]:
        return "damp"
    if (rain_prob >= RAIN_WARNING
            and not state.player_ignored_warning
            and not tc["warning"]
            and state.warning_cooldown == 0):
        return "warning"
    if (state.rain_decreasing
            and rain_prob < RAIN_DAMP
            and prev_rain_prob >= RAIN_DAMP
            and state.peak_rain_prob > 70
            and not tc["drying"]):
        return "drying"
    return None


# ── Weather-triggered Safety Car ──────────────────────────────────────────────

def should_trigger_weather_sc(
    state: WeatherState,
    rain_prob: float,
    prev_rain_prob: float,
    lap: int,
    total_laps: int,
) -> Optional[str]:
    """Check if sudden rain change warrants deploying a safety car.

    Returns 'SC' or None. Does NOT mutate state — caller sets weather_sc_fired.

    Extracted from simulate_race() lines 365–381.
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


# ── Strategy helpers (extracted from game/ui/weather_sc.py) ──────────────────

def trim_strategy_to_remaining(strategy: RaceStrategy, remaining_laps: int) -> RaceStrategy:
    """Trim or extend a strategy so its total laps equals remaining_laps.

    Extracted from _trim_strategy_to_remaining() in game/ui/weather_sc.py.
    Pure logic — no display side-effects.
    """
    stints = list(strategy.stints)
    total = sum(s.laps for s in stints)
    if total <= remaining_laps:
        extra = remaining_laps - total
        stints[-1] = TyreStint(stints[-1].compound, stints[-1].laps + extra)
    else:
        while len(stints) > 1 and sum(s.laps for s in stints) > remaining_laps:
            stints.pop()
        used = sum(s.laps for s in stints[:-1])
        stints[-1] = TyreStint(stints[-1].compound, remaining_laps - used)
    return RaceStrategy(stints=stints, label=strategy.label)


def should_recommend_sc_pit(tyre_age: int, base_life: int) -> bool:
    """Return True if the tyre age warrants a pit recommendation under safety car.

    Extracted from the inline rec_pit calculation in show_sc_strategy_decision().
    Threshold: tyre_age > base_life * SC_PIT_TYRE_AGE_FRAC (0.55).
    """
    return tyre_age > base_life * SC_PIT_TYRE_AGE_FRAC
