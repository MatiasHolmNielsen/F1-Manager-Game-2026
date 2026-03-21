from __future__ import annotations

import random
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from models.driver import Driver
    from engine.race import RaceResult, RaceReport


STAT_GROWTH_RATE = {
    "experience":      1.50,
    "tire_management": 1.30,
    "consistency":     1.00,
    "mental":          1.00,
    "overtaking":      1.00,
    "defending":       1.00,
    "car_control":     1.00,
    "aggression":      0.70,
    "wet_weather":     0.90,
    "pace":            0.65,
    "qualifying_pace": 0.65,
}

POSITION_XP = {
    1: 4.0, 2: 3.2, 3: 2.8, 4: 2.4, 5: 2.0,
    6: 1.8, 7: 1.6, 8: 1.4, 9: 1.2, 10: 1.0,
    11: 0.7, 12: 0.6, 13: 0.5, 14: 0.4, 15: 0.3,
    16: 0.2, 17: 0.2, 18: 0.1, 19: 0.1, 20: 0.1,
}

# Prospects develop much faster; prime drivers also get a bump.
AGE_MULT = {
    "prospect": 2.00,   # was 1.40 — explosive growth for young rookies
    "prime":    1.15,   # was 1.00 — solid prime window (age 23–34)
    "veteran":  0.50,   # was 0.55
    "legend":   0.15,   # was 0.20
}

DECLINE_CHANCE = {"veteran": 0.08, "legend": 0.20}
DECLINE_STATS = {"pace", "qualifying_pace"}

# qualifying_pace gets full quali boost; mental gets half
QUALI_STAT_BONUS = {"qualifying_pace": 1.0, "mental": 0.5}

GLOBAL_SCALE = 0.10

# ── Performance-based XP bonuses ──────────────────────────────────────────────
# Each successful overtake boosts overtaking and aggression XP pools directly.
OVERTAKE_BONUS_PER   = 0.06   # per overtake → overtaking XP
OVERTAKE_AGG_PER     = 0.02   # per overtake → aggression XP
# Each successful defense boosts defending XP.
DEFENSE_BONUS_PER    = 0.05   # per defense → defending XP
# Driving on rain compounds multiplies wet_weather XP proportionally.
WET_WEATHER_MULT     = 1.8    # full-wet race → 1.8× wet_weather XP (was 2.5 — too aggressive)
# Cap on overtakes counted for bonus (prevents single-race stat spikes at easy overtaking tracks)
OVERTAKE_BONUS_CAP   = 5
# Fastest lap in race boosts pace/qualifying_pace.
FASTEST_LAP_BONUS    = {"pace": 0.20, "qualifying_pace": 0.15}


def apply_development(
    results: List[RaceResult],
    drivers: Dict[str, Driver],
    grid: Optional[List[str]] = None,
    report: Optional[RaceReport] = None,
) -> tuple:
    """Apply post-race stat development to all drivers.

    Returns (changes, xp_gains) where:
      changes   = {driver_id: {stat: int_delta}}
      xp_gains  = {driver_id: {stat: float}} — raw XP added this race per stat

    Performance bonuses (if report is provided):
      - Overtakes made  → extra overtaking + aggression XP
      - Defenses held   → extra defending XP
      - Rain laps driven → multiplied wet_weather XP
      - Fastest lap     → bonus pace + qualifying_pace XP
    """
    from engine.race import RaceResult  # local import to avoid circular at module level

    result_map: Dict[str, RaceResult] = {r.driver.id: r for r in results}

    changes: Dict[str, Dict[str, int]] = {}
    xp_gains: Dict[str, Dict[str, float]] = {}

    for driver_id, driver in drivers.items():
        race_result = result_map.get(driver_id)
        if race_result is None:
            continue

        age_mult = AGE_MULT[driver.age_group]
        potential_mult = 1.0 + ((driver.potential - driver.overall) / 100) * 1.5

        # Position XP
        if race_result.dnf:
            position_xp = 0.05
        else:
            position_xp = POSITION_XP.get(race_result.position, 0.1)

        # Qualifying position multiplier
        if grid and driver_id in grid:
            quali_position = grid.index(driver_id) + 1
        else:
            quali_position = 10
        # P1=1.50, P10≈1.08, P20=0.70
        quali_mult = 1.5 - (quali_position - 1) * (0.8 / 19)

        # Places gained multiplier
        if race_result.dnf:
            places_mult = 0.7
        else:
            places_gained = quali_position - race_result.position
            places_mult = max(0.5, min(1.5, 1.0 + places_gained * 0.04))

        # ── Extract performance stats from report ────────────────────────
        overtakes   = 0
        defenses    = 0
        wet_fraction = 0.0
        has_fastest_lap = race_result.fastest_lap

        if report is not None:
            overtakes = report.overtakes_made.get(driver_id, 0)
            defenses  = report.defenses_made.get(driver_id, 0)
            driver_laps = report.lap_data.get(driver_id, [])
            total_laps = len(driver_laps)
            if total_laps > 0:
                rain_laps = sum(
                    1 for rec in driver_laps
                    if rec.compound in ("intermediate", "wet")
                )
                wet_fraction = rain_laps / total_laps

        driver_changes: Dict[str, int] = {}
        driver_xp_gains: Dict[str, float] = {}

        for stat, growth_rate in STAT_GROWTH_RATE.items():
            current = getattr(driver, stat)

            # Veteran/legend decline check
            if driver.age_group in DECLINE_CHANCE and stat in DECLINE_STATS:
                if random.random() < DECLINE_CHANCE[driver.age_group]:
                    new_val = max(60, current - 1)
                    if new_val != current:
                        setattr(driver, stat, new_val)
                        driver_changes[stat] = new_val - current
                    continue

            # Qualifying boost for eligible stats
            if stat in QUALI_STAT_BONUS:
                quali_boost = (quali_mult - 1.0) * QUALI_STAT_BONUS[stat]
            else:
                quali_boost = 0.0

            raw_xp = (
                position_xp
                * potential_mult
                * age_mult
                * growth_rate
                * places_mult
                * GLOBAL_SCALE
            )
            raw_xp = raw_xp * (1 + quali_boost)

            # ── Performance bonuses (scaled by age & potential) ──────────
            perf_bonus = 0.0
            bonus_scale = age_mult * potential_mult

            capped_overtakes = min(overtakes, OVERTAKE_BONUS_CAP)
            if stat == "overtaking" and capped_overtakes > 0:
                perf_bonus += capped_overtakes * OVERTAKE_BONUS_PER * bonus_scale
            elif stat == "aggression" and capped_overtakes > 0:
                perf_bonus += capped_overtakes * OVERTAKE_AGG_PER * bonus_scale
            elif stat == "defending" and defenses > 0:
                perf_bonus += defenses * DEFENSE_BONUS_PER * bonus_scale
            elif stat == "wet_weather" and wet_fraction > 0:
                # Multiply the base wet_weather XP by how wet the race was
                raw_xp *= 1.0 + wet_fraction * (WET_WEATHER_MULT - 1.0)
            elif stat in FASTEST_LAP_BONUS and has_fastest_lap:
                perf_bonus += FASTEST_LAP_BONUS[stat] * bonus_scale

            total_xp = raw_xp + perf_bonus

            # Accumulate into persistent XP pool; trigger +1 when pool crosses 1.0
            driver_xp_gains[stat] = total_xp
            driver.xp[stat] = driver.xp.get(stat, 0.0) + total_xp
            increment = int(driver.xp[stat])
            driver.xp[stat] -= increment

            if increment <= 0:
                continue

            new_val = min(driver.potential, current + increment)
            delta = new_val - current
            if delta > 0:
                setattr(driver, stat, new_val)
                driver_changes[stat] = delta

        if driver_changes:
            changes[driver_id] = driver_changes
        if driver_xp_gains:
            xp_gains[driver_id] = driver_xp_gains

    return changes, xp_gains
