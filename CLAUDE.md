# F1 Manager — Claude Instructions

## Current State
Codebase is mid-refactor. Expect mixed patterns — do not copy old patterns.
Target architecture: docs/architecture.md (to be created)

## Absolute Rules
- ONE concern per session. If you notice other problems, note them, don't fix them.
- Never refactor AND add features in the same task
- engine/race.py is READ-ONLY until further notice — extract from it, never edit it
- Always leave the game in a runnable state after each session
- Commit after every completed extraction

## Target Structure (where we're going)
engine/
  core/
    weather.py       ← single source of truth for weather
    tyres.py         ← all tyre logic, no UI imports
    dnf.py           ← all DNF probability logic
    overtaking.py    ← position swap logic
  race.py            ← will shrink as we extract
game/
  loop.py            ← will slim down over time

## What "Done" Looks Like for Each Module
- Pure functions where possible
- No imports from UI
- Has a corresponding test file
```

---

## 🗓️ Your Exact Session Plan

### Session 1 — Weather (safest, most isolated)
```
"Create engine/core/weather.py
Consolidate ALL weather logic from these 4 files:
  - engine/weather.py
  - engine/race_physics.py (weather parts only)
  - engine/race.py (weather parts only)  
  - ui/weather_sc.py (logic parts only, not UI)

Rules:
- No UI imports in the new file
- Pure functions only
- Don't change race.py yet — just identify what it can later call
- Don't fix anything else you notice"
```

### Session 2 — DNF (small, self-contained)
```
"Create engine/core/dnf.py
Consolidate ALL DNF probability logic from:
  - any file containing dnf probabilities or failure rates

Single function: calculate_dnf_probability(driver, car, conditions) → float
Don't touch race.py yet"
```

### Session 3 — Tyres (more complex, do after 1 & 2)
```
"Create engine/core/tyres.py
Consolidate tyre allocation and degradation from:
  - engine/tyres.py
  - any tyre logic in engine/race.py

Encapsulate mutable tyre state into a TyreState dataclass.
No UI imports. Don't wire it into race.py yet."
```

### Session 4 — Tests for all three
```
"Write tests for:
  - engine/core/weather.py
  - engine/core/dnf.py  
  - engine/core/tyres.py

Don't touch race.py or any other files"
```

### Session 5 — Wire race.py to new modules
```
"Now update engine/race.py to call the new core modules.
Replace inline weather/dnf/tyre logic with calls to engine/core/
Do NOT change simulation outcomes — pure refactor"
```

### Session 6 — Begin splitting simulate_race()
Only after sessions 1–5 are committed and tests pass.

---

## ⚠️ One Warning

The audit flagged this:
> *"Callback closures make simulate_race() untestable in isolation"*

When you get to Session 5, tackle this specifically:
```
"Replace sc_pit_callback and weather_callback closure 
dependencies with explicit parameters or a context object.
Goal: simulate_race() should be callable in a test with no UI."