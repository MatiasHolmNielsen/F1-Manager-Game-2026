"""Backward-compat re-exports for callers that import from engine.race_physics.

All logic has moved to engine/core/lap_time.py and engine/core/overtaking.py.
"""
from __future__ import annotations

from engine.core.lap_time import _base_lap_time  # noqa: F401
from engine.core.overtaking import _attempt_overtake, OVERTAKE_THRESHOLD, BATTLE_RANGE_S  # noqa: F401
