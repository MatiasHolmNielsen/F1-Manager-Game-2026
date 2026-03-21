# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Game

```bash
pip install -r requirements.txt
python main.py
```

No build step or test suite exists — the game runs interactively via the terminal.

## Architecture Overview

This is a terminal-based F1 manager simulator using Python dataclasses and the [Rich](https://github.com/Textualize/rich) library for UI.

### Layer separation

| Layer | Location | Role |
|---|---|---|
| Entry point | `main.py` | 3-line shim — just calls `game.main()` |
| Game loop & UI | `game/` | Season flow, rendering, menus, finances, off-season |
| Simulation engines | `engine/` | Race, qualifying, tyre, development, rookie generation |
| Data models | `models/` | Pure dataclasses, no logic beyond computed properties |
| Config data | `data/*.json` | Driver/team/circuit definitions — easy to tweak |

### `game/` package

| File | Responsibility |
|---|---|
| `loop.py` | `main()`, `show_welcome()`, `show_team_selection()` — the full season/race loop |
| `loader.py` | `load_drivers()`, `load_teams()`, `load_circuits()` — reads `data/*.json` |
| `ui.py` | All Rich rendering: race results, standings, development, strategy menus, animations |
| `management.py` | Pre-race hub: car upgrade menu, in-season driver market |
| `finances.py` | `_apply_race_finances()` — prize money, ops costs, DNF repair charges |
| `offseason.py` | `_run_offseason()` — constructor prizes, car degradation, retirements, driver market |

### Data flow

1. `game/loop.py:main()` calls `game/loader.py` to load all data into model objects.
2. Player picks a team; season loop begins.
3. Each race: `management_menu` → qualifying (`engine/qualifying.py`) → strategy selection (`engine/tyres.py`) → race simulation (`engine/race.py`) → display results (`game/ui.py`).
4. `engine/development.py` runs post-race to award XP and bump driver stats.
5. Off-season: `game/offseason.py` handles prizes, degradation, retirements, transfers, AI upgrades, rookie generation (`engine/generation.py`).

### Models (`models/`)

- **Driver**: 11 performance stats (0–100), `potential` ceiling, fractional `xp` pools per stat, `age`/`salary`. `overall` is a weighted sum. Age groups (prospect/prime/veteran/legend) affect development rates.
- **Car**: 7 attributes including `pit_crew`. Upgrade costs scale exponentially near the cap (~2.7× at 95).
- **Team**: Container for budget, 2 driver IDs, a Car, and championship points.
- **Circuit**: Track characteristics (`overtaking_difficulty`, `weather_chance`, `tire_wear`, `pit_lane_loss`). Computed `aero_weight`/`engine_weight` drive how car attributes affect lap times.

### Race engine (`engine/race.py`)

The largest and most complex file. Key systems:

- **Race**: Lap-by-lap loop — tyre deg, fuel load, driver fatigue, incidents (DNFs), and position battles (overtaking logic gated by pace delta vs. `overtaking_difficulty`).
- **Tyre system** (`engine/tyres.py`): 5 compounds (Hard/Medium/Soft/Intermediate/Wet). Lap life = `base × driver_tire_mgmt_factor × car_tire_deg_factor`. `suggest_strategies()` generates 4 preset strategies for the player; `ai_strategy()` handles AI drivers.
- **Qualifying** (`engine/qualifying.py`): Single-lap simulation per driver; weather-sensitive.

### Driver development (`engine/development.py`)

Post-race XP is calculated from finishing position, qualifying position, places gained, age group, and potential. XP pools accumulate fractionally per stat; a stat only increments when its pool crosses 1.0. Veterans/legends have a chance to lose `pace` points each race.

### Rookie generation (`engine/generation.py`)

Generates drivers with random stats (48–68), potential (78–96), and a salary linked to potential. Used during off-season transfers.

## Key Constants & Scaling

- Race distance is always ~305 km; lap count = `round(305 / circuit.length_km)`.
- Car upgrade base cost per attribute is defined in `models/car.py`; cost multiplier = `1 + max(0, (current - 70) / 10) ** 1.5`.
- XP weights per stat and per-race multipliers are tables in `engine/development.py` — adjust these to tune progression speed.
- Driver `overall` weights are in `models/driver.py` — `pace` is 25%, `experience` 9%, `qualifying_pace` 8%, etc.
