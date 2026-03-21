from __future__ import annotations

import random
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from models.driver import Driver
    from engine.race import RaceResult


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

AGE_MULT = {
    "prospect": 1.40,
    "prime":    1.00,
    "veteran":  0.55,
    "legend":   0.20,
}

DECLINE_CHANCE = {"veteran": 0.08, "legend": 0.20}
DECLINE_STATS = {"pace", "qualifying_pace"}

# qualifying_pace gets full quali boost; mental gets half
QUALI_STAT_BONUS = {"qualifying_pace": 1.0, "mental": 0.5}

GLOBAL_SCALE = 0.10


def apply_development(
    results: List[RaceResult],
    drivers: Dict[str, Driver],
    grid: Optional[List[str]] = None,
) -> tuple:
    """Apply post-race stat development to all drivers.

    Returns (changes, xp_gains) where:
      changes   = {driver_id: {stat: int_delta}}
      xp_gains  = {driver_id: {stat: float}} — raw XP added this race per stat
    """
    from engine.race import RaceResult  # local import to avoid circular at module level

    # Build race-result lookup: driver_id -> RaceResult
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

        driver_changes: Dict[str, int] = {}
        driver_xp_gains: Dict[str, float] = {}

        for stat, growth_rate in STAT_GROWTH_RATE.items():
            current = getattr(driver, stat)

            # Veteran/legend decline check
            if driver.age_group in DECLINE_CHANCE and stat in DECLINE_STATS:
                if random.random() < DECLINE_CHANCE[driver.age_group]:
                    new_val = max(50, current - 1)
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

            # Accumulate into persistent XP pool; trigger +1 when pool crosses 1.0
            driver_xp_gains[stat] = raw_xp
            driver.xp[stat] = driver.xp.get(stat, 0.0) + raw_xp
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
