"""Overtaking constants and attempt logic.

Extracted from engine/race_physics.py and engine/race_models.py.
"""
from __future__ import annotations

import random

from engine.race_models import RaceEntry

OVERTAKE_THRESHOLD = 0.5   # seconds/lap faster needed before an attempt is considered
BATTLE_RANGE_S = 1.0       # max gap (seconds) between cars for an overtake to be possible


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
