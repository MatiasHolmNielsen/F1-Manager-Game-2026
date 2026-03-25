"""Single source of truth for all tyre logic.

Consolidated from:
  engine/tyres.py  — all compounds, life tables, strategy generation, AI logic
  engine/race.py   — TyreState (tyre_compound/tyre_age/stint_index fields),
                     TyreAllocation (_best_available_cmp + live_alloc dict),
                     tyre_wear_delta (wear_frac² × 4.5 formula, line 290)

New additions:
  TyreState      — mutable per-driver tyre tracking, replaces bare fields in
                   DriverLapState (tyre_compound, tyre_age, stint_index)
  TyreAllocation — validated per-driver set counts, replaces live_alloc dict
  tyre_wear_delta — named function for the quadratic wear-time formula

No UI imports. Pure functions / dataclasses only.
Race-wiring happens in Session 5 — race.py calls here instead of inline logic.

NOTE (Session 5): ai_should_pit_for_weather imports compound_pace_delta from
engine.core.weather. When engine.core.weather is updated to import from this
module, replace that import with a direct call to compound_pace_delta() defined
locally to avoid any circular dependency risk.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from engine.race_models import RaceEntry


# ── Compound definitions ─────────────────────────────────────────────────────

TYRE_COMPOUNDS: Dict[str, dict] = {
    "hard":         {"pace_bonus": -0.5, "color": "white",  "symbol": "H", "rain": False},
    "medium":       {"pace_bonus":  0.0, "color": "yellow", "symbol": "M", "rain": False},
    "soft":         {"pace_bonus":  0.8, "color": "red",    "symbol": "S", "rain": False},
    "intermediate": {"pace_bonus":  1.5, "color": "green",  "symbol": "I", "rain": True},
    "wet":          {"pace_bonus":  3.0, "color": "blue",   "symbol": "W", "rain": True},
}

# Per-lap pace delta (seconds) on a dry track at zero rain probability.
# Negative = faster than medium baseline.
COMPOUND_PACE_DELTA: Dict[str, float] = {
    "soft":         -0.5,
    "medium":        0.0,
    "hard":          0.3,
    "intermediate":  0.2,
    "wet":           0.8,
}

# Base tyre life in laps, by compound and circuit wear level.
TYRE_LIFE_BASE: Dict[str, Dict[str, int]] = {
    "low":    {"hard": 40, "medium": 26, "soft": 20},
    "medium": {"hard": 30, "medium": 19, "soft": 15},
    "high":   {"hard": 20, "medium": 13, "soft": 11},
}

DEFAULT_TYRE_ALLOCATION: Dict[str, int] = {
    "soft": 2, "medium": 2, "hard": 2, "intermediate": 2, "wet": 2,
}

# Quadratic wear model: time penalty = wear_frac² × this constant.
# At 100% worn: +4.5 s/lap penalty. Extracted from simulate_race() line 290.
TYRE_WEAR_TIME_SCALE: float = 4.5


# ── Helpers ──────────────────────────────────────────────────────────────────

def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class TyreStint:
    compound: str   # "hard" | "medium" | "soft" | "intermediate" | "wet"
    laps: int


@dataclass
class RaceStrategy:
    stints: List[TyreStint]
    label: str = ""


@dataclass
class TyreState:
    """Mutable per-driver tyre tracking state.

    Encapsulates the tyre_compound, tyre_age, and stint_index fields that are
    currently scattered inside DriverLapState in race_models.py.

    Replaces bare field access in simulate_race() with named operations.
    """
    compound: str
    age: int = 0
    stint_index: int = 0

    def pit(self, new_compound: str) -> None:
        """Perform a pit stop: change compound, reset age, advance stint index."""
        self.compound = new_compound
        self.age = 0
        self.stint_index += 1

    def tick(self) -> None:
        """Advance one lap: increment tyre age."""
        self.age += 1

    def wear_fraction(self, tyre_life: int) -> float:
        """0.0 → 1.0 wear fraction, capped at 1.0 for overrun tyres."""
        return min(1.0, self.age / max(1, tyre_life))


@dataclass
class TyreAllocation:
    """Per-driver tyre set allocation with validated consume/query operations.

    Replaces the bare live_alloc[did] dict in simulate_race() and the
    _best_available_cmp() helper in race.py.
    """
    sets: Dict[str, int] = field(default_factory=lambda: dict(DEFAULT_TYRE_ALLOCATION))

    @classmethod
    def default(cls) -> "TyreAllocation":
        """Return allocation with one full set of every compound."""
        return cls(sets=dict(DEFAULT_TYRE_ALLOCATION))

    @classmethod
    def from_dict(cls, d: Dict[str, int]) -> "TyreAllocation":
        """Create from a plain compound→count dict (e.g. from save data)."""
        return cls(sets=dict(d))

    def available(self, compound: str) -> int:
        """How many sets of this compound remain."""
        return self.sets.get(compound, 0)

    def consume(self, compound: str) -> None:
        """Decrement set count for compound (floor 0)."""
        self.sets[compound] = max(0, self.sets.get(compound, 0) - 1)

    def best_available(self, preferred: str) -> str:
        """Return preferred if sets remain, else the compound with the most sets.

        Mirrors _best_available_cmp() from engine/race.py lines 75–80.
        """
        if self.sets.get(preferred, 0) > 0:
            return preferred
        if not self.sets:
            return preferred
        return max(self.sets, key=lambda c: self.sets[c])

    def has_any(self) -> bool:
        """True if at least one set of any compound remains."""
        return any(v > 0 for v in self.sets.values())

    def copy(self) -> "TyreAllocation":
        """Shallow copy — sets dict is new, values are ints (immutable)."""
        return TyreAllocation(sets=dict(self.sets))


# ── Tyre life ─────────────────────────────────────────────────────────────────

def race_laps(circuit) -> int:
    """Standard F1 race distance: ~305 km."""
    return round(305 / circuit.length_km)


def adjusted_tyre_life(
    compound: str, circuit, car, driver, rain_prob: float = 0.0
) -> int:
    """Return how many laps a compound lasts for this car/driver combo.

    Driver factor: ×0.60–×1.40  (tire_management 0–100)
    Car factor:    ×0.70–×1.30  (tire_deg 0–100)
    Rain effect:   inters/wets scale with rain_prob; slicks unaffected by rain here
                   (rain pace penalty handled separately by compound_pace_delta).
    """
    if compound == "intermediate":
        # ~12 L dry → ~38 L optimal at 65%+ rain
        t = min(1.0, rain_prob / 65)
        base = int(_lerp(12, 38, t))
    elif compound == "wet":
        # ~12 L dry → ~47 L in heavy rain
        t = min(1.0, rain_prob / 100)
        base = int(_lerp(12, 47, t))
    else:
        base = TYRE_LIFE_BASE[circuit.tire_wear][compound]

    driver_factor = 0.6 + driver.tire_management / 100 * 0.8
    car_factor    = 0.7 + car.tire_deg / 100 * 0.6
    return max(3, int(base * driver_factor * car_factor))


def _working_life(
    compound: str, circuit, car, driver, rain_prob: float = 0.0
) -> int:
    """The 'working' stint length — laps before degradation becomes costly.

    70–82% of full tyre life depending on circuit wear level.
    """
    full_life = adjusted_tyre_life(compound, circuit, car, driver, rain_prob=rain_prob)
    frac = {"low": 0.82, "medium": 0.76, "high": 0.70}[circuit.tire_wear]
    return max(3, int(full_life * frac))


# ── Tyre wear delta ───────────────────────────────────────────────────────────

def tyre_wear_delta(tyre_age: int, tyre_life: int) -> float:
    """Time penalty (seconds/lap) from tyre wear alone for this lap.

    Quadratic model: penalty = wear_fraction² × TYRE_WEAR_TIME_SCALE.
    Does NOT include compound pace delta (use compound_pace_delta() for that).

    Extracted from simulate_race() line 290:
        wear_frac = min(1.0, state.tyre_age / max(1, life))
        tyre_delta = wear_frac ** 2 * 4.5 + compound_delta
    """
    wear_frac = min(1.0, tyre_age / max(1, tyre_life))
    return wear_frac ** 2 * TYRE_WEAR_TIME_SCALE


# ── Strategy scoring ──────────────────────────────────────────────────────────

def tyre_score(strategy: RaceStrategy, circuit, weather: str, car, driver) -> float:
    """Convert a full race strategy into a performance score contribution.

    Rewards good compound choice; penalises overruns and extra pit stops.
    Mirrors _tyre_score() from engine/tyres.py.
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

    num_stops = len(strategy.stints) - 1
    pit_time = 2.0 + (90 - car.pit_crew) * 0.05   # 2.0–3.5 s
    total_pit_penalty = num_stops * (pit_time / 1.2)

    return stint_contributions - total_pit_penalty


# ── Strategy building ─────────────────────────────────────────────────────────

def _fill_smart(
    stints: List[TyreStint],
    remaining: int,
    filler: str,
    circuit,
    car,
    driver,
    rain_prob: float = 0.0,
) -> List[TyreStint]:
    """Append stints of `filler` compound using working life per stint.

    Last stint may run to full life + 10% to avoid a tiny trailing stub.
    """
    full_life = adjusted_tyre_life(filler, circuit, car, driver, rain_prob=rain_prob)
    work_life = _working_life(filler, circuit, car, driver, rain_prob=rain_prob)
    while remaining > 0:
        if remaining <= int(full_life * 1.10):
            stints.append(TyreStint(filler, remaining))
            remaining = 0
        else:
            stints.append(TyreStint(filler, work_life))
            remaining -= work_life
    return stints


def build_pit_schedule(strategy: RaceStrategy) -> Dict[int, str]:
    """Return {lap_number: next_compound} for each planned pit stop.

    Mirrors _build_pit_schedule() from engine/tyres.py.
    """
    schedule: Dict[int, str] = {}
    lap = 0
    for i, stint in enumerate(strategy.stints[:-1]):
        lap += stint.laps
        schedule[lap] = strategy.stints[i + 1].compound
    return schedule


def suggest_strategies(
    circuit, weather: str, car, driver, rain_prob: float = 0.0
) -> List[RaceStrategy]:
    """Return 4 labelled preset strategies for the given conditions."""
    total = race_laps(circuit)

    if weather == "wet":
        inter_work = _working_life("intermediate", circuit, car, driver, rain_prob=rain_prob)
        wet_work   = _working_life("wet",          circuit, car, driver, rain_prob=rain_prob)
        inter_split = min(inter_work, total // 2)
        wet_split   = min(wet_work,   total // 2)
        return [
            RaceStrategy(
                stints=_fill_smart([], total, "intermediate", circuit, car, driver, rain_prob=rain_prob),
                label="Intermediates",
            ),
            RaceStrategy(
                stints=_fill_smart([], total, "wet", circuit, car, driver, rain_prob=rain_prob),
                label="Full Wets",
            ),
            RaceStrategy(
                stints=_fill_smart(
                    [TyreStint("intermediate", inter_split)],
                    total - inter_split, "wet", circuit, car, driver, rain_prob=rain_prob,
                ),
                label="Inter → Wet",
            ),
            RaceStrategy(
                stints=_fill_smart(
                    [TyreStint("wet", wet_split)],
                    total - wet_split, "intermediate", circuit, car, driver, rain_prob=rain_prob,
                ),
                label="Wet → Inter",
            ),
        ]

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


# ── AI strategy selection ─────────────────────────────────────────────────────

def ai_strategy(entry: "RaceEntry", circuit, weather: str) -> RaceStrategy:
    """Choose a strategy heuristically for an AI driver."""
    car    = entry.car
    driver = entry.driver

    if weather == "wet":
        strategies = suggest_strategies(circuit, weather, car, driver)
        base = 0 if circuit.weather_chance < 60 else 1
        idx  = max(0, min(len(strategies) - 1, base + random.randint(-1, 1)))
        return strategies[idx]

    strategies = suggest_strategies(circuit, weather, car, driver)

    if car.tire_deg > 80 and driver.tire_management > 75:
        idx = 2    # Conservative
    elif car.tire_deg < 70 or driver.tire_management < 65:
        idx = 3    # 2-Stop
    else:
        idx = random.randint(0, 1)   # Aggressive or Balanced

    idx = max(0, min(len(strategies) - 1, idx + random.randint(-1, 1)))
    return strategies[idx]


def ai_should_pit_for_weather(
    state, entry, circuit, rain_prob: float, laps_remaining: int
) -> bool:
    """Return True if an AI driver should pit for wet-weather tyres right now.

    Uses compound_pace_delta from engine.core.weather (new source of truth).
    NOTE Session 5: if engine.core.weather imports from engine.core.tyres,
    replace this import with a local call to avoid circular dependency.
    """
    # Lazy import to avoid circular once engine.core.weather → engine.core.tyres
    from engine.core.weather import compound_pace_delta
    current_penalty = compound_pace_delta(state.tyre_compound, rain_prob)
    laps_ahead   = min(laps_remaining, 15)
    expected_loss = current_penalty * laps_ahead
    pit_cost      = circuit.pit_lane_loss + 2.5
    return expected_loss > pit_cost * 1.2


# ── Allocation helper (standalone) ───────────────────────────────────────────

def best_available_compound(
    allocation: Dict[str, int], preferred: str
) -> str:
    """Return preferred compound if sets remain, else the compound with most sets.

    Accepts a plain dict for backwards compatibility with code that has not yet
    migrated to TyreAllocation. Mirrors _best_available_cmp() from race.py.
    """
    if allocation.get(preferred, 0) > 0:
        return preferred
    if not allocation:
        return preferred
    return max(allocation, key=lambda c: allocation[c])
