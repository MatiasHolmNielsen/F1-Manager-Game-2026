"""Tyre compounds, strategy generation, and AI pit logic.
# Functions: race_laps:51  adjusted_tyre_life:56  _tyre_score:83  _working_life:123  _fill_smart:133  suggest_strategies:155  ai_strategy:248  ai_should_pit_for_weather:275  _build_pit_schedule:285
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from engine.race_models import RaceEntry


TYRE_COMPOUNDS = {
    "hard":         {"pace_bonus": -0.5, "color": "white",  "symbol": "H", "rain": False},
    "medium":       {"pace_bonus":  0.0, "color": "yellow", "symbol": "M", "rain": False},
    "soft":         {"pace_bonus":  0.8, "color": "red",    "symbol": "S", "rain": False},
    "intermediate": {"pace_bonus":  1.5, "color": "green",  "symbol": "I", "rain": True},
    "wet":          {"pace_bonus":  3.0, "color": "blue",   "symbol": "W", "rain": True},
}

# Per-lap pace delta (seconds): negative = faster than medium baseline
COMPOUND_PACE_DELTA = {
    "soft":         -0.5,
    "medium":        0.0,
    "hard":          0.3,
    "intermediate":  0.2,
    "wet":           0.8,
}

# Base tyre life in laps per compound per circuit wear level
TYRE_LIFE_BASE = {
    "low":    {"hard": 40, "medium": 26, "soft": 20},
    "medium": {"hard": 30, "medium": 19, "soft": 15},
    "high":   {"hard": 20, "medium": 13, "soft": 11},
}

DEFAULT_TYRE_ALLOCATION: Dict[str, int] = {
    "soft": 2, "medium": 2, "hard": 2, "intermediate": 2, "wet": 2,
}


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


@dataclass
class TyreStint:
    compound: str   # "hard" | "medium" | "soft" | "intermediate" | "wet"
    laps: int


@dataclass
class RaceStrategy:
    stints: List[TyreStint]
    label: str = ""


def race_laps(circuit) -> int:
    """Standard F1 race distance: ~305 km."""
    return round(305 / circuit.length_km)


def adjusted_tyre_life(compound: str, circuit, car, driver, rain_prob: float = 0.0) -> int:
    """
    Return how many laps a compound lasts for this car/driver combo.

    Driver factor: ×0.60–×1.40  (tire_management 0–100)
    Car factor:    ×0.70–×1.30  (tire_deg 0–100)
    Rain penalty: inters/wets degrade fast on wrong track conditions.
    """
    if compound == "intermediate":
        # Smooth curve: ~12L dry → ~38L optimal at 65%+ (damp/wet)
        t = min(1.0, rain_prob / 65)
        base = int(_lerp(12, 38, t))
    elif compound == "wet":
        # Smooth curve: ~12L dry → ~47L in heavy rain
        t = min(1.0, rain_prob / 100)
        base = int(_lerp(12, 47, t))
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
            avg_bonus = compound_bonus - (overrun_frac * 12.0)

        stint_contributions += avg_bonus * (stint.laps / total_laps)

    # Pit stop time penalty (each stop after the first stint)
    num_stops = len(strategy.stints) - 1
    pit_time = 2.0 + (90 - car.pit_crew) * 0.05  # 2.0s–3.5s range
    score_penalty_per_stop = pit_time / 1.2
    total_pit_penalty = num_stops * score_penalty_per_stop

    return stint_contributions - total_pit_penalty


def _working_life(compound: str, circuit, car, driver, rain_prob: float = 0.0) -> int:
    """Return the 'working' stint length — the lap count before deg becomes costly.

    Uses ~70-82% of full tyre life depending on circuit wear level.
    """
    full_life = adjusted_tyre_life(compound, circuit, car, driver, rain_prob=rain_prob)
    frac = {"low": 0.82, "medium": 0.76, "high": 0.70}[circuit.tire_wear]
    return max(3, int(full_life * frac))


def _fill_smart(
    stints: List[TyreStint], remaining: int,
    filler: str, circuit, car, driver,
    rain_prob: float = 0.0,
) -> List[TyreStint]:
    """Append stints of `filler` compound using working life per stint.

    The last stint is allowed to run to full life (or up to 110%) so we don't
    add a tiny trailing stint.
    """
    full_life = adjusted_tyre_life(filler, circuit, car, driver, rain_prob=rain_prob)
    work_life = _working_life(filler, circuit, car, driver, rain_prob=rain_prob)
    while remaining > 0:
        # If remaining fits within full life + 10% buffer, use remaining directly
        if remaining <= int(full_life * 1.10):
            stints.append(TyreStint(filler, remaining))
            remaining = 0
        else:
            stints.append(TyreStint(filler, work_life))
            remaining -= work_life
    return stints


def suggest_strategies(circuit, weather: str, car, driver, rain_prob: float = 0.0) -> List[RaceStrategy]:
    """Return 4 labelled preset strategies for the given conditions."""
    total = race_laps(circuit)

    if weather == "wet":
        inter_work = _working_life("intermediate", circuit, car, driver, rain_prob=rain_prob)
        wet_work   = _working_life("wet",          circuit, car, driver, rain_prob=rain_prob)

        inter_split = min(inter_work, total // 2)
        wet_split   = min(wet_work,   total // 2)

        return [
            # Multi-stint intermediates
            RaceStrategy(
                stints=_fill_smart([], total, "intermediate", circuit, car, driver, rain_prob=rain_prob),
                label="Intermediates",
            ),
            # Multi-stint full wets
            RaceStrategy(
                stints=_fill_smart([], total, "wet", circuit, car, driver, rain_prob=rain_prob),
                label="Full Wets",
            ),
            # Inter → Wet
            RaceStrategy(
                stints=_fill_smart(
                    [TyreStint("intermediate", inter_split)],
                    total - inter_split, "wet", circuit, car, driver, rain_prob=rain_prob,
                ),
                label="Inter → Wet",
            ),
            # Wet → Inter
            RaceStrategy(
                stints=_fill_smart(
                    [TyreStint("wet", wet_split)],
                    total - wet_split, "intermediate", circuit, car, driver, rain_prob=rain_prob,
                ),
                label="Wet → Inter",
            ),
        ]

    hard_life   = adjusted_tyre_life("hard",   circuit, car, driver)
    medium_life = adjusted_tyre_life("medium", circuit, car, driver)
    soft_life   = adjusted_tyre_life("soft",   circuit, car, driver)

    soft_work   = _working_life("soft",   circuit, car, driver)
    medium_work = _working_life("medium", circuit, car, driver)
    hard_work   = _working_life("hard",   circuit, car, driver)

    # Aggressive: S (working) → M (working) → H (fill)
    s_agg = min(soft_work, total // 3)
    m_agg = min(medium_work, (total - s_agg) // 2)
    aggressive = RaceStrategy(
        stints=_fill_smart(
            [TyreStint("soft", s_agg), TyreStint("medium", m_agg)],
            total - s_agg - m_agg, "hard", circuit, car, driver,
        ),
        label="Aggressive",
    )

    # Balanced: M (working) → H (fill)
    m_bal = min(medium_work, total // 2)
    balanced = RaceStrategy(
        stints=_fill_smart(
            [TyreStint("medium", m_bal)],
            total - m_bal, "hard", circuit, car, driver,
        ),
        label="Balanced",
    )

    # Conservative: H (working) → M (fill)
    h_con = min(hard_work, total // 2)
    conservative = RaceStrategy(
        stints=_fill_smart(
            [TyreStint("hard", h_con)],
            total - h_con, "medium", circuit, car, driver,
        ),
        label="Conservative",
    )

    # 2-Stop: S (short) → M (working) → H (fill)
    s2 = max(1, min(soft_work, total // 4))
    m2 = min(medium_work, (total - s2) // 2)
    two_stop = RaceStrategy(
        stints=_fill_smart(
            [TyreStint("soft", s2), TyreStint("medium", m2)],
            total - s2 - m2, "hard", circuit, car, driver,
        ),
        label="2-Stop",
    )

    return [aggressive, balanced, conservative, two_stop]


def ai_strategy(entry: RaceEntry, circuit, weather: str) -> RaceStrategy:
    """Choose a strategy heuristically for an AI driver."""
    car = entry.car
    driver = entry.driver

    if weather == "wet":
        strategies = suggest_strategies(circuit, weather, car, driver)
        # Prefer intermediates unless very heavy rain circuit; small random variation
        base = 0 if circuit.weather_chance < 60 else 1
        idx = max(0, min(len(strategies) - 1, base + random.randint(-1, 1)))
        return strategies[idx]

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


def ai_should_pit_for_weather(state, entry, circuit, rain_prob: float, laps_remaining: int) -> bool:
    """Return True if an AI driver should pit for wet-weather tyres right now."""
    from engine.weather import _weather_compound_delta
    current_penalty = _weather_compound_delta(state.tyre_compound, rain_prob)
    laps_ahead = min(laps_remaining, 15)
    expected_loss = current_penalty * laps_ahead
    pit_cost = circuit.pit_lane_loss + 2.5
    return expected_loss > pit_cost * 1.2


def _build_pit_schedule(strategy: RaceStrategy) -> Dict[int, str]:
    """Return {lap_number: next_compound} for each pit stop."""
    schedule: Dict[int, str] = {}
    lap = 0
    for i, stint in enumerate(strategy.stints[:-1]):
        lap += stint.laps
        schedule[lap] = strategy.stints[i + 1].compound
    return schedule
