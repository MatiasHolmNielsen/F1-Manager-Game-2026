# F1 Manager Game 2026 — Comprehensive Code Audit

## 1. File/Folder Map

### Core Entry Point
- **`main.py`** (21 lines) — Orchestrates startup: welcome screen, load/new game decision, passes to game loop

### Models (Data Classes)
- **`models/driver.py`** — Driver dataclass with 11 performance stats + development fields; calculates overall rating via weighted formula
- **`models/team.py`** — Team dataclass with car, budget, driver IDs, sponsor ID, points accumulation
- **`models/car.py`** — Car dataclass with 7 attributes; upgrade mechanics with exponential cost scaling; `upgrade_cost()` function
- **`models/circuit.py`** — Circuit dataclass with 8 properties; computes aero/engine weight ratios and tire wear factor
- **`models/sponsor.py`** — Sponsor dataclass with race payment, bonus type, and bonus amount

### Game Engine (Race Simulation)
- **`engine/race_models.py`** (110 lines) — Pure dataclasses and constants: RaceEntry, RaceResult, DriverLapState, DriverLapRecord, PitStop, RaceReport; POINTS_SYSTEM, DNF_REASONS, safety car probabilities
- **`engine/race_physics.py`** (68 lines) — `_base_lap_time()` and `_attempt_overtake()`: calculates lap times from driver/car/circuit/weather; overtake success and collision logic
- **`engine/weather.py`** (111 lines) — Weather simulation: `_check_safety_car()`, rain probability interpolation, compound performance deltas, wet weather weight scaling, 15-lap forecast generation
- **`engine/tyres.py`** (299 lines) — Tire compounds, strategy generation, life calculations; `adjusted_tyre_life()`, `suggest_strategies()` (4 presets), `ai_strategy()`, `_tyre_score()`, pit schedule building
- **`engine/qualifying.py`** (132 lines) — `_qualifying_score()` and knockout Q1/Q2/Q3 simulation; final grid assembly
- **`engine/development.py`** (207 lines) — Post-race stat growth: `apply_development()` applies XP to all drivers; age multipliers (prospect 2.0×, prime 1.15×, veteran 0.5×, legend 0.15×); performance bonuses for overtakes/defenses/fastest lap
- **`engine/generation.py`** (68 lines) — `generate_rookie()` creates new drivers with random names, ages 18–22, stats 48–68
- **`engine/race.py`** (812 lines) — **MAIN RACE LOOP**: `simulate_race()` orchestrates lap-by-lap simulation, safety car deployment, weather drifts, pit stops, overtaking, DNFs, lap data collection

### Game Loop & Flow
- **`game/loop.py`** (300+ lines) — Main season loop: `show_welcome()`, team selection, race-by-race flow (qualifying → strategy → race → finances → development → standings), auto-save, off-season transitions
- **`game/loader.py`** (92 lines) — JSON data loading: `load_drivers()`, `load_teams()`, `load_circuits()`, `load_sponsors()`; PyInstaller-aware `_base_dir()`
- **`game/save_load.py`** (80 lines) — Single-slot save/load: `save_exists()`, `save_game()`, `load_game()`, `apply_save()`; PyInstaller-aware path handling

### Game Management & Economy
- **`game/management.py`** (230 lines) — Pre-race menus: `upgrade_car_menu()`, `driver_market_menu()`, `management_menu()` (browse team, upgrade, sign free agents, view standings)
- **`game/finances.py`** (156 lines) — `_apply_race_finances()`: prize money by position (P1 €4.0M–P20 €0.05M), milestone bonuses (pole €1.5M, FL €1.0M, podium €0.5M), sponsor income & bonuses, DNF repairs (−€6.0M), ops cost (−€2.0M)
- **`game/offseason.py`** (250+ lines) — Off-season flow: constructor prize payout (P1 €80M–P10 €5M), salary deduction, driver retirements (42+→65%, 40+→40%, 38+→18%, 35+→5%), car degradation (−2–5 pts/attr, floor 60), AI driver signing, AI car upgrades, rookie generation, player market, sponsor renewal

### UI & Display
- **`game/ui/helpers.py`** (72 lines) — Formatting utilities: `fmt_lap_time()`, `stat_bar()`, `_xp_bar()`, `_rain_bar()`, `_delta_str()`, `_fmt_stint()`, `_fmt_strategy()`; console singleton
- **`game/ui/race_display.py`** (300+ lines) — Race results table, pit stop stats, race events, lap analysis per driver; detailed DNF/gap/FL annotations
- **`game/ui/quali_strategy.py`** (400+ lines) — Knockout Q1/Q2/Q3 session display; animated qualifying; strategy menu with custom builder; pit panel with tyre life hints, allocation tracking
- **`game/ui/weather_sc.py`** (300+ lines) — Mid-race interactive prompts: safety car strategy decisions (pit/stay), weather threshold alerts (warning/damp/wet/drying), 15-lap rain forecasts, recommendation engine
- **`game/ui/race_flow.py`** (350+ lines) — Circuit briefing, race transition summaries, sponsor selection, race animation with progress bars
- **`game/ui/overview.py`** (300+ lines) — Team overview tables, driver development tracking (XP pools + stat changes), championship standings
- **`game/ui/__init__.py`** — Re-exports all UI functions for backwards compatibility

### Data Files
- **`data/drivers.json`** — 20 F1 2026 drivers with all stats, ages, potentials, salaries, current teams
- **`data/teams.json`** — 10 teams with car attributes, budgets, driver rosters
- **`data/circuits.json`** — 24 circuits with length, corners, tire wear, weather chance, overtaking difficulty, pit lane loss
- **`data/sponsors.json`** — Sponsors with race payments, bonus triggers (win/podium/fastest_lap/top5), amounts

### Configuration & Metadata
- **`requirements.txt`** — Single dependency: `rich>=13.0.0`
- **`CLAUDE.md`** — Project documentation: file map, key tuning constants, build instructions, data flow

---

## 2. Complexity Tangles & Architectural Issues

### A. `engine/race.py` (812 lines) — Massive Monolith

**Problem**: The `simulate_race()` function is a single 700+ line block handling 15+ distinct concerns:
- Initial state setup (lines 96–150)
- Weather front logic (lines 158–196)
- Per-lap orchestration (lines 198–751):
  - Weather probability drift (204–251)
  - Incident detection (261–283)
  - Lap time calculation (286–309)
  - Scheduled pit stops (331–350)
  - Safety car deployment (352–520)
  - Weather callback UI (523–612)
  - AI weather pitting (614–636)
  - Overtaking logic (638–696)
  - Lap data recording (698–751)
- Final results assembly (753–811)

**Why it's convoluted**:
- Deep nesting (5+ levels) in weather & SC sections
- Intermingled state mutations (`pit_recovery_laps_left`, `thresholds_crossed`, `sc_state` updates)
- Callback-driven UI decisions that branch code paths (`sc_pit_callback`, `weather_callback`)
- Complex orchestration of pit schedules, lap times, position tracking

**Impact**: Hard to isolate bugs, difficult to test individual race mechanics, fragile refactoring.

---

### B. `engine/weather.py` — Implicit Coupling via Magic Numbers

The `_weather_compound_delta()` function has hardcoded rain probability thresholds (40, 55, 65, 80, 92, 100) without explanation. No constants, no documentation of why 55 is "medium-wet transition" vs. 65 "damp" vs. 92 "heavy rain."

**Problem**: Understanding rain behavior requires reading all 5 conditional branches and cross-referencing `_effective_wet_weight()` logic separately.

---

### C. `game/ui/quali_strategy.py` (400+ lines) — Strategy Builder Complexity

The `_custom_strategy()` function has nested loop-state machines:
- Outer loop: restarts from stint count selection
- Inner loop: per-stint builder with context-aware hints
- Lap allocation validation, tyre life display, manual allocation editor

**Readability issue**: Hard to follow the flow; unclear when to break vs. continue vs. restart.

---

### D. `game/loop.py` — Season Loop Gluing

Lines 147–320+ constitute the main race loop with inline imports and callback orchestration. Each race branches into 8+ display/decision steps (management → qualifying → strategy → race → finances → development → standings → offseason), making the control flow hard to follow.

**Problem**: No abstraction layer. The loop directly calls UI functions which call engine functions. Makes it hard to change event ordering or add conditional skips.

---

### E. `engine/tyres.py` — Tyre Life Calculation Scattered

Three separate functions calculate tyre life under different conditions:
- `adjusted_tyre_life()`: base life × driver_factor × car_factor
- `_working_life()`: 70–82% of full life depending on wear level
- `_fill_smart()`: uses working life to build stints intelligently

**Problem**: Logic duplication. If you change the base life formula, you must update all three. No single source of truth for "how long should this stint be?"

---

### Secondary Issues

1. **`game/ui/race_display.py` — Lap Analysis Sorting**: Builds ordered list with player team first, then others by position. References `team.id` vs. `player_team_id` inconsistently.
2. **`game/management.py` — Driver Seat Replacement**: Uses `team.driver_ids[seat_idx]` with hardcoded 1/2 choice. If a team ever has 3+ drivers, this breaks.
3. **`engine/race.py` — `pit_recovery_laps_left`**: Tracks 2-lap cooldown after pits, updated in multiple places. State scattered; could cause synchronization bugs.
4. **`engine/development.py` — Potential Overflow**: Accumulates XP fractionally. Integer division of XP pools could cause rounding surprises.

---

## 3. Dependency Graph

```
main.py
 ├→ game/loop.py (main())
 │   ├→ game/loader.py (load_drivers, load_teams, load_circuits, load_sponsors)
 │   ├→ game/save_load.py (apply_save, save_game)
 │   ├→ game/management.py (management_menu)
 │   │   ├→ models/car.py (upgrade_cost)
 │   │   ├→ models/driver.py
 │   │   ├→ models/team.py
 │   │   └→ game/ui/... (show_team_overview, show_standings)
 │   ├→ engine/qualifying.py (simulate_knockout_qualifying)
 │   │   └→ engine/race_models.py (RaceEntry, QualiResult)
 │   ├→ game/ui/quali_strategy.py (show_strategy_menu, show_strategy_summary)
 │   │   ├→ engine/tyres.py (suggest_strategies, _tyre_score, race_laps)
 │   │   ├→ models/circuit.py
 │   │   └→ game/ui/helpers.py
 │   ├→ engine/race.py (simulate_race)
 │   │   ├→ engine/race_models.py (RaceEntry, RaceResult, ...)
 │   │   ├→ engine/race_physics.py (_base_lap_time, _attempt_overtake)
 │   │   ├→ engine/weather.py (_check_safety_car, _weather_compound_delta, ...)
 │   │   ├→ engine/tyres.py (TyreStint, RaceStrategy, race_laps, ai_strategy, ...)
 │   │   └→ game/ui/weather_sc.py (callbacks: sc_pit_callback, weather_callback)
 │   ├→ game/ui/race_flow.py (run_race_with_animation)
 │   │   └→ engine/race.py (simulate_race)
 │   ├→ game/finances.py (_apply_race_finances)
 │   ├→ engine/development.py (apply_development)
 │   ├→ game/ui/overview.py (show_standings, show_driver_development)
 │   └→ game/offseason.py (_run_offseason)
 │       ├→ engine/generation.py (generate_rookie)
 │       └→ models/car.py (upgrade_cost, UPGRADE_COSTS)
 │
 └→ game/save_load.py (save_exists, load_game)
     └→ models/driver.py, models/team.py (for apply_save)

models/__init__.py (empty)
game/__init__.py (re-exports main from loop)
game/ui/__init__.py (re-exports all UI functions)
engine/__init__.py (empty)
```

### Coupling Analysis
- **Tight Coupling**: `engine/race.py` directly imports and calls 5 engine modules + `weather_sc.py` callbacks
- **Callback Coupling**: `sc_pit_callback` and `weather_callback` in `race.py` create hidden dependencies on `ui/weather_sc.py`
- **Import Spread**: `game/loop.py` imports from 10+ modules; central orchestrator but high fan-out
- **Circular Risk**: None detected; `engine/tyres.py` imports `weather.py` and vice versa (safe, no cycles)

---

## 4. Homeless Code & Responsibilities Confusion

### A. Weather Logic Scattered (4 modules)
- `engine/weather.py` — rain probability drift, compound deltas, SC probability
- `engine/race_physics.py` — wet weather stat influence
- `engine/race.py` — weather callback orchestration, 150+ lines of weather state management
- `game/ui/weather_sc.py` — rain bar rendering, forecast display, strategy decisions

**Problem**: Adding a new weather feature requires changes in 4 places.

---

### B. Strategy Logic Scattered (3 modules)
- `engine/tyres.py` — strategy generation, AI strategy selection
- `game/ui/quali_strategy.py` — player strategy custom builder, strategy menu
- `engine/race.py` — pit schedule building from strategy, strategy execution

**Problem**: Strategy is a "model" concern, a "UI concern", and an "engine concern" simultaneously.

---

### C. Tyre Allocation Management (4 modules)
- `game/loop.py` — initializes allocation
- `engine/race.py` — reads and updates allocation on pits
- `game/ui/weather_sc.py` — displays allocation
- `game/ui/quali_strategy.py` — allows editing allocation in custom strategy

**Problem**: Mutable state flowing through 4 modules; no encapsulation, no validation.

---

### D. DNF Logic Scattered
- `engine/race.py` — mechanical failure, tyre failure, collision
- `engine/race_models.py` — `DNF_REASONS` constant list
- `game/ui/race_display.py` — DNF display with reason
- `game/offseason.py` — age-based retirements (adjacent concept)

**Problem**: No cohesive "failure event" model. Each DNF type is hardcoded with ad-hoc probability.

---

### E. Quick-Skip Mode Tangled in Season Loop
`game/loop.py` lines 217–265 have a "quick skip" feature branching code:
- `quick = pit_choice == "Q"`
- Finances and development logic referenced in two paths

**Problem**: Feature logic is tangled with screen flow; hard to reason about what happens in quick-skip mode.

---

## 5. Code Quality Red Flags

### A. Missing Type Hints
Most functions lack type hints beyond model dataclasses:
- `game/loop.py:main(save_data=None)` — should be `Optional[Dict]`
- `engine/race.py:simulate_race()` — no hints for callbacks
- `game/ui/race_flow.py` functions mix Dict, List with no structure

### B. Deep Nesting
`engine/race.py` has sections with 5–6 levels of indentation. Example:
```python
for lap in range(1, total_laps + 1):     # level 1
    for did, state in states.items():     # level 2
        if state.dnf: continue           # level 3
        if state.tyre_age > life:         # level 3
            if random.random() < prob:    # level 4
                if random.random() < 0.40:  # level 5
```

### C. Magic Numbers
| Location | Value | Meaning |
|----------|-------|---------|
| `weather.py` | 55, 65, 80, 92 | Rain intensity thresholds |
| `race_models.py` | 0.50, 0.25 | SC/VSC probabilities |
| `race.py` | 2 (laps) | Pit recovery cooldown |
| `race_physics.py` | 0.50, 0.048 | Lap time formula constants |

### D. Global Mutable State via Callbacks
`simulate_race()` accepts `sc_pit_callback` and `weather_callback` which mutate external state via closures over `live_alloc` and `player_team`. Race engine and UI are tightly coupled; testing `simulate_race` in isolation is hard.

### E. Inconsistent Error Handling
- No exceptions for invalid strategies (>4 stints, >total_laps)
- Silent failures if driver's allocation runs out of tyre sets
- No validation that pit stops are within track bounds

---

## 6. Untested / High-Risk Areas

1. **`engine/race.py` overtaking logic** — Complex position swapping; easy to create duplicate positions
2. **Weather callback UI flow** — Edge case: what if player ignores warning 3 times?
3. **Pit allocation depletion** — Falls back to "best available compound" but doesn't validate set count
4. **Save/load with midseason changes** — Does `apply_save` handle new rookies correctly?
5. **Season end off-season** — Does the loop properly handle all 24 circuits?

---

## 7. Performance Concerns

1. **Weather forecast generation**: Generates 15-lap forecast with Gaussian noise every lap — O(n×15) Gaussian samples. Wasteful if forecast could be cached.
2. **Overtaking pass**: Iterates backward through all drivers each lap — O(n²) worst case. Negligible at 20 drivers but inelegant.
3. **Lap data recording**: Appends a `DriverLapRecord` per driver per lap — 20 drivers × 50 laps = 1000 records. Fine currently.

---

## 8. Documentation Gaps

1. **`engine/race_physics.py`** — No explanation of lap time formula constants (0.50, 0.048, etc.)
2. **`engine/development.py`** — `STAT_GROWTH_RATE` and `AGE_MULT` tables lack rationale
3. **`engine/weather.py`** — Rain probability thresholds (40, 55, 65, 80, 92) lack rationale
4. **`game/finances.py`** — Why ops_cost is −€2.0M exactly; tuning doc missing
5. **Pit crew stat** (60–90 range) — Why this 30-point range while other car attrs are 0–100?

---

## 9. Summary Table

| Category | Severity | Count | Examples |
|----------|----------|-------|---------|
| Monolithic Functions | High | 1 | `simulate_race()` 812 lines |
| Scattered Responsibilities | High | 5 | Weather, strategy, DNF, allocation, UI state |
| Missing Type Hints | Medium | 15+ | Most functions in `game/ui` |
| Magic Numbers | Medium | 10+ | Weather thresholds, pit cooldown |
| Deep Nesting | Medium | 8+ | Race loop, weather callback |
| Global Callbacks | High | 2 | `sc_pit_callback`, `weather_callback` |
| Untested Edge Cases | High | 5 | Overtaking, weather callback, allocation depletion |
| Documentation Gaps | Low | 15+ | Constants, formulas, tuning rationale |

---

## 10. Recommendations for Future Refactoring

1. **Split `simulate_race()`** into sub-methods:
   - `_init_race_state()`
   - `_run_lap()` (per-lap logic, returns events)
   - `_assemble_results()`

2. **Extract weather state** into a `WeatherManager` class owning all rain/SC state

3. **Introduce Strategy pattern** for pit decisions (SC pit, weather pit, scheduled pit)

4. **Encapsulate tyre allocation** in a `TyreAllocation` class with validation

5. **Replace callbacks** with event-driven architecture (Observer pattern) for UI updates

6. **Add named constants** for all magic numbers, linked to tuning doc

7. **Add type hints** throughout; use `Protocol` for callback signatures

---

*Generated: 2026-03-25 | Total lines of code: ~5,141 | Maintainability Index: ~55/100*
