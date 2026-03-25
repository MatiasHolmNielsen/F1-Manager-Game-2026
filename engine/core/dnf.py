"""Single source of truth for all DNF and failure-probability logic.

Consolidated from:
  engine/race.py        — mechanical_failure_probability, tyre_failure_probability,
                          COLLISION_RETIRE_PROB, COLLISION_DAMAGE constants
  engine/race_physics.py — collision_probability (the 0.025 aggression scale)
  game/offseason.py     — retirement_probability (age-based career ending)

No UI imports. Pure functions only.
Race-wiring happens in Session 5 — race.py calls here instead of inline values.
"""
from __future__ import annotations

import random
from typing import Optional, Tuple

from engine.race_models import DNF_REASONS


# ── Per-lap mechanical & control failure rates ────────────────────────────────
# At reliability=70, car.reliability=70: (100-70)/100 * 0.0015 ≈ 0.00045/lap
# At reliability=50 (floor): (100-50)/100 * 0.0015 = 0.00075/lap
# Combined with ctrl at car_control=60: (40/100)*0.0008 = 0.00032/lap
# → Realistic range: ~0.05–0.15% per lap for a mid-grid car

MECH_FAILURE_RATE: float = 0.0015   # multiplied by (100 - car.reliability) / 100
CTRL_LOSS_RATE:    float = 0.0008   # multiplied by (100 - driver.car_control) / 100

# ── Tyre failure (overrun) ────────────────────────────────────────────────────
# Risk grows linearly at 0.8% per lap past the tyre life, capped at 5%

TYRE_OVERRUN_RATE:     float = 0.008   # probability gain per overrun lap
TYRE_OVERRUN_MAX_PROB: float = 0.05    # cap on per-lap tyre-failure probability

TYRE_DNF_REASONS = ["Tyre failure", "Puncture"]

# ── Collision outcomes ────────────────────────────────────────────────────────
# On a contact event: each car has COLLISION_RETIRE_PROB of retiring outright,
# otherwise incurs a time penalty in [COLLISION_DAMAGE_MIN_S, COLLISION_DAMAGE_MAX_S].

COLLISION_RETIRE_PROB:    float = 0.40
COLLISION_DAMAGE_MIN_S:   float = 15.0
COLLISION_DAMAGE_MAX_S:   float = 35.0

# Collision probability in a wheel-to-wheel duel, scaled by both drivers' aggression.
# collision_prob = (attacker.aggression / 100) * (defender.aggression / 100) * scale
COLLISION_AGGRESSION_SCALE: float = 0.025

# ── Off-season career-ending retirement ──────────────────────────────────────
# List of (minimum_age, probability) in descending age order.
# First matching bracket is used.

RETIREMENT_AGE_PROBS: list[tuple[int, float]] = [
    (42, 0.65),
    (40, 0.40),
    (38, 0.18),
    (35, 0.05),
]


# ── Probability functions ─────────────────────────────────────────────────────

def mechanical_dnf_probability(driver, car) -> float:
    """Per-lap probability of a mechanical or driver-control DNF.

    Combines:
      - car reliability:    lower reliability → higher failure rate
      - driver car_control: lower control → higher spin/crash rate

    Extracted from simulate_race() lines 262–263.
    """
    mech_prob = (100 - car.reliability) / 100 * MECH_FAILURE_RATE
    ctrl_prob = (100 - driver.car_control) / 100 * CTRL_LOSS_RATE
    return mech_prob + ctrl_prob


def tyre_failure_probability(tyre_age: int, tyre_life: int) -> float:
    """Per-lap probability of a tyre blowout or puncture when running past tyre life.

    Returns 0.0 if the tyre is still within its rated life.
    Grows linearly by TYRE_OVERRUN_RATE per overrun lap, capped at TYRE_OVERRUN_MAX_PROB.

    Extracted from simulate_race() lines 274–276.
    """
    if tyre_age <= tyre_life:
        return 0.0
    overrun_laps = tyre_age - tyre_life
    return min(TYRE_OVERRUN_MAX_PROB, overrun_laps * TYRE_OVERRUN_RATE)


def collision_probability(attacker, defender) -> float:
    """Probability of a contact event during an overtaking duel.

    Both drivers' aggression stats scale the chance of contact.
    Extracted from _attempt_overtake() in engine/race_physics.py (line 63).
    """
    return (attacker.aggression / 100) * (defender.aggression / 100) * COLLISION_AGGRESSION_SCALE


def retirement_probability(age: int) -> float:
    """Off-season probability that a driver retires from motorsport permanently.

    Returns the first matching bracket's probability, or 0.0 if below 35.
    Extracted from offseason.py lines 92–99.
    """
    for min_age, prob in RETIREMENT_AGE_PROBS:
        if age >= min_age:
            return prob
    return 0.0


# ── Roll helpers ──────────────────────────────────────────────────────────────
# These mirror the random.random() checks in race.py, extracted as named functions
# so they can be tested independently of the simulation loop.

def roll_mechanical_dnf(driver, car) -> Optional[str]:
    """Roll for a per-lap mechanical or control DNF.

    Returns a DNF reason string on failure, or None if the car survives.
    """
    if random.random() < mechanical_dnf_probability(driver, car):
        return random.choice(DNF_REASONS)
    return None


def roll_tyre_dnf(tyre_age: int, tyre_life: int) -> Optional[str]:
    """Roll for a per-lap tyre failure when past rated life.

    Returns a DNF reason string on failure, or None if the tyre holds.
    """
    prob = tyre_failure_probability(tyre_age, tyre_life)
    if prob > 0.0 and random.random() < prob:
        return random.choice(TYRE_DNF_REASONS)
    return None


def roll_collision_outcome() -> Tuple[bool, float]:
    """Roll the outcome for one car involved in a collision event.

    Returns (retired, damage_seconds).
    If retired=True, damage_seconds is 0.0.
    If retired=False, damage_seconds is the time penalty to add.
    """
    if random.random() < COLLISION_RETIRE_PROB:
        return True, 0.0
    damage_s = round(random.uniform(COLLISION_DAMAGE_MIN_S, COLLISION_DAMAGE_MAX_S), 1)
    return False, damage_s


def roll_retirement(age: int) -> bool:
    """Roll whether a driver retires from F1 at the end of the season.

    Extracted from offseason.py lines 91–99.
    """
    prob = retirement_probability(age)
    return prob > 0.0 and random.random() < prob
