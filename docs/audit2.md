# F1 Manager — Codebase Audit 2
_Date: 2026-03-25 — post Session 7 refactor_

---

## 1. Duplicate / Redundant Logic

### Constants (identical copies in both old and new modules)

| Constant | Old location | New location |
|----------|-------------|--------------|
| `TYRE_COMPOUNDS` | `engine/tyres.py:14-20` | `engine/core/tyres.py:35-41` |
| `COMPOUND_PACE_DELTA` | `engine/tyres.py:23-29` | `engine/core/tyres.py:45-51` |
| `TYRE_LIFE_BASE` | `engine/tyres.py:32-36` | `engine/core/tyres.py:54-58` |
| `DEFAULT_TYRE_ALLOCATION` | `engine/tyres.py:38-40` | `engine/core/tyres.py:60-62` |

### Helper function duplicated in three or four places

`_lerp()` is defined independently in:
- `engine/tyres.py:43-44`
- `engine/weather.py:22-23`
- `engine/core/tyres.py:71-72`
- `engine/core/weather.py:78-79`

### Weather functions (identical logic, renamed)

| Old (`engine/weather.py`) | New (`engine/core/weather.py`) |
|--------------------------|-------------------------------|
| `_check_safety_car()` | `check_safety_car()` |
| `_weather_compound_delta()` | `compound_pace_delta()` |
| `_effective_wet_weight()` | `wet_weather_weight()` |
| `_generate_weather_forecast()` | `generate_weather_forecast()` |

### Tyre functions (identical logic, renamed)

| Old (`engine/tyres.py`) | New (`engine/core/tyres.py`) |
|------------------------|------------------------------|
| `race_laps()` | `race_laps()` |
| `adjusted_tyre_life()` | `adjusted_tyre_life()` |
| `_working_life()` | `_working_life()` |
| `_fill_smart()` | `_fill_smart()` |
| `suggest_strategies()` | `suggest_strategies()` |
| `ai_strategy()` | `ai_strategy()` |
| `_build_pit_schedule()` | `build_pit_schedule()` |
| `_tyre_score()` | `tyre_score()` |

### Dataclasses duplicated

- `TyreStint` — identical definition in `engine/tyres.py:47-50` and `engine/core/tyres.py:77-80`
- `RaceStrategy` — identical definition in `engine/tyres.py:53-56` and `engine/core/tyres.py:83-86`

---

## 2. Dead Files

No truly dead files found. All files under `engine/` and `game/` are imported somewhere.

However, **`engine/tyres.py` and `engine/weather.py` are functionally superseded** by their `engine/core/` counterparts and exist only because UI files still import from them. They are candidates for deletion once the migration is complete.

---

## 3. Old Module Imports (`engine.weather` / `engine.tyres`)

Files still importing from the old pre-refactor modules:

| File | Old import |
|------|-----------|
| `engine/core/weather.py` | `from engine.tyres import COMPOUND_PACE_DELTA, TYRE_LIFE_BASE, TyreStint, RaceStrategy` |
| `engine/race_physics.py` | `from engine.weather import _effective_wet_weight` |
| `engine/tyres.py` | `from engine.weather import _weather_compound_delta` (lazy, inside function) |
| `game/loop.py` | `from engine.tyres import DEFAULT_TYRE_ALLOCATION` |
| `game/ui/helpers.py` | `from engine.tyres import TYRE_COMPOUNDS` |
| `game/ui/quali_strategy.py` | `from engine.tyres import TYRE_COMPOUNDS, TyreStint, RaceStrategy, race_laps, adjusted_tyre_life, suggest_strategies, _tyre_score` |
| `game/ui/quali_strategy.py` | `from engine.weather import _weather_compound_delta` |
| `game/ui/race_display.py` | `from engine.tyres import TYRE_COMPOUNDS` |
| `game/ui/race_flow.py` | `from engine.tyres import RaceStrategy, race_laps` |
| `game/ui/weather_sc.py` | `from engine.tyres import TYRE_COMPOUNDS, TYRE_LIFE_BASE, TyreStint, RaceStrategy, adjusted_tyre_life` |
| `game/ui/weather_sc.py` | `from engine.weather import _weather_compound_delta` |
| `smoke_test.py` | `from engine.tyres import DEFAULT_TYRE_ALLOCATION` |
| `tests/test_core_tyres.py` | Intentional — imports both old and new for parity tests |
| `tests/test_core_weather.py` | Intentional — imports both old and new for parity tests |

**11 active non-test files still depend on old modules.**

---

## 4. Other Refactor Leftovers

### engine/core/weather.py imports from OLD engine/tyres (incorrect direction)
`engine/core/weather.py:21` — `from engine.tyres import COMPOUND_PACE_DELTA, TYRE_LIFE_BASE, TyreStint, RaceStrategy`

The new canonical weather module should import from `engine/core/tyres`, not the old module. This is the highest-priority import to fix.

### Circular lazy import between old modules
- `engine/tyres.py:283` — imports `_weather_compound_delta` from `engine.weather` inside a function body
- `engine/weather.py:28` — imports `COMPOUND_PACE_DELTA` from `engine.tyres` inside a function body

This circular dependency is mitigated only by lazy loading; it indicates the old modules were never cleanly separated.

### Naming convention inconsistency between old and new
Old modules use leading underscores for "private" helpers (`_tyre_score`, `_build_pit_schedule`, `_check_safety_car`). New `engine/core/` modules drop the underscore for the same functions (`tyre_score`, `build_pit_schedule`, `check_safety_car`). The UI still imports the old underscore names directly.

### engine/race.py still contains inline safety-car and weather constants
`_run_lap()` in `engine/race.py` contains inline SC timing constants and weather-step logic that could be further delegated to `engine/core/weather.py`. This is a known next target (Session 8).

---

## 5. Line Counts (engine/ and game/)

### engine/

| File | Lines |
|------|------:|
| `engine/__init__.py` | 0 |
| `engine/development.py` | 206 |
| `engine/generation.py` | 67 |
| `engine/qualifying.py` | 131 |
| `engine/race.py` | 928 |
| `engine/race_models.py` | 109 |
| `engine/race_physics.py` | 67 |
| `engine/tyres.py` | 298 |
| `engine/weather.py` | 110 |
| **engine/ root subtotal** | **1,916** |
| `engine/core/__init__.py` | 0 |
| `engine/core/dnf.py` | 156 |
| `engine/core/tyres.py` | 447 |
| `engine/core/weather.py` | 422 |
| **engine/core/ subtotal** | **1,025** |
| **engine/ TOTAL** | **2,941** |

### game/

| File | Lines |
|------|------:|
| `game/__init__.py` | 1 |
| `game/finances.py` | 155 |
| `game/loader.py` | 91 |
| `game/loop.py` | 373 |
| `game/management.py` | 229 |
| `game/offseason.py` | 368 |
| `game/save_load.py` | 79 |
| **game/ root subtotal** | **1,296** |
| `game/ui/__init__.py` | 22 |
| `game/ui/helpers.py` | 71 |
| `game/ui/overview.py` | 283 |
| `game/ui/quali_strategy.py` | 400 |
| `game/ui/race_display.py` | 414 |
| `game/ui/race_flow.py` | 334 |
| `game/ui/weather_sc.py` | 338 |
| **game/ui/ subtotal** | **1,862** |
| **game/ TOTAL** | **3,158** |

### Grand Total

| Scope | Lines |
|-------|------:|
| engine/ | 2,941 |
| game/ | 3,158 |
| **engine/ + game/** | **6,099** |

---

## Summary by Severity

### Critical
- `engine/core/weather.py` imports from old `engine.tyres` instead of `engine.core.tyres` — wrong direction for the canonical module.

### High
- 9 active UI/game files still import from old `engine.tyres` / `engine.weather`. These block deletion of the old modules.
- ~408 lines of duplicate code across `engine/tyres.py` (298 lines) and `engine/weather.py` (110 lines) — entirely superseded by `engine/core/`.

### Medium
- Naming inconsistency (`_tyre_score` vs `tyre_score`, `_build_pit_schedule` vs `build_pit_schedule`).
- Circular lazy import between old modules.
- `_run_lap()` still contains inline SC/weather constants that belong in `engine/core/weather.py`.

### Recommended next step
Migrate all 9 UI files to import from `engine.core.tyres` and `engine.core.weather`, fix `engine/core/weather.py`'s own import, then delete `engine/tyres.py` and `engine/weather.py`.
