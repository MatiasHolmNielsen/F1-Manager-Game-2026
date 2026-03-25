# F1 Manager — Claude Instructions

## Current State
Refactor complete. Codebase is clean and structured.
228 tests passing. Do not copy any patterns outside of engine/core/.

## Absolute Rules
- ONE concern per session. If you notice other problems, note them, don't fix them.
- Never refactor AND add features in the same task
- Always leave the game in a runnable state after each session
- All new logic needs a corresponding test

## Agent Routing

Always identify the right agent before starting a task.

| Task type                              | Agent                  |
|----------------------------------------|------------------------|
| Simulation logic, physics, probability | simulation-engine-dev  |
| UI, display, terminal rendering        | ui-layer-enforcer      |
| Season flow, game state, save/load     | game-orchestrator      |
| Driver/team/circuit data, balancing    | game-data-balancer     |
| Writing or updating tests              | core-test-writer       |
| Code cleanup, removing duplication     | refactor-only          |

## Rules
- One agent per task. If a task crosses two agents, split it into two tasks.
- Never let simulation-engine-dev touch game/ui/
- Never let ui-layer-enforcer touch engine/
- Run core-test-writer after every simulation-engine-dev session — never in parallel, always after

## Parallel Rules
Safe to parallelise (zero file overlap):
- simulation-engine-dev + game-data-balancer
- ui-layer-enforcer + game-data-balancer
- ui-layer-enforcer + simulation-engine-dev (only if touching different files)

Never parallelise (shared file risk):
- simulation-engine-dev + refactor-only
- simulation-engine-dev + core-test-writer
- game-orchestrator + ui-layer-enforcer
- any two agents touching the same directory

## Structure
engine/
  core/
    weather.py       ← single source of truth for weather
    tyres.py         ← all tyre logic, no UI imports
    dnf.py           ← all DNF probability logic
  race.py            ← orchestrator only, currently being slimmed
game/
  loop.py            ← main game loop

## Status
Migration complete as of 2026-03-25.
engine/tyres.py and engine/weather.py deleted.
engine/core/ is the single source of truth for all tyre/weather/dnf logic.

## Import Rules
- Tyre logic    → engine.core.tyres
- Weather logic → engine.core.weather  
- DNF logic     → engine.core.dnf
- Never import from engine.tyres or engine.weather (deleted)

## What "Done" Looks Like for Each Module
- Pure functions where possible
- No imports from UI
- Has a corresponding test file