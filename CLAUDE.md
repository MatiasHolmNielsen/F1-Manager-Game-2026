# F1 Manager — Claude Instructions

## Current State
Refactor complete. Codebase is clean and structured.
228 tests passing. Do not copy any patterns outside of engine/core/.

## Absolute Rules
- ONE concern per session. If you notice other problems, note them, don't fix them.
- Never refactor AND add features in the same task
- Always leave the game in a runnable state after each session
- Commit after every completed task
- All new logic needs a corresponding test

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
Refactor complete as of [today's date].
simulate_race() is a ~30-line orchestrator — keep it that way.
All new race logic goes into the appropriate named sub-function.
Never add concerns back into simulate_race() itself.

## What "Done" Looks Like for Each Module
- Pure functions where possible
- No imports from UI
- Has a corresponding test file