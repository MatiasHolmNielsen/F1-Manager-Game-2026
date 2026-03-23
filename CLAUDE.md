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
| Config data | `data/*.json` | Driver/team/circuit/sponsor definitions — easy to tweak |

### `game/` package

| File | Responsibility |
|---|---|
| `loop.py` | `main()`, `show_welcome()`, `show_team_selection()` — the full season/race loop |
| `loader.py` | `load_drivers()`, `load_teams()`, `load_circuits()`, `load_sponsors()` — reads `data/*.json` |
| `ui.py` | All Rich rendering: race results, standings, development, strategy menus, animations |
| `management.py` | Pre-race hub: car upgrade menu, in-season driver market |
| `finances.py` | `_apply_race_finances()` — prize money, ops costs, DNF repair charges, sponsor bonuses |
| `offseason.py` | `_run_offseason()` — constructor prizes, car degradation, retirements, driver market |

### Data flow

1. `game/loop.py:main()` calls `game/loader.py` to load all data into model objects.
2. Player picks a team and selects 1 of 4 randomly offered sponsors.
3. Each race: `management_menu` → qualifying (`engine/qualifying.py`) → strategy selection (`engine/tyres.py`) → race simulation (`engine/race.py`) → display results (`game/ui.py`).
4. `engine/development.py` runs post-race to award XP and bump driver stats.
5. Off-season: `game/offseason.py` handles prizes, degradation, retirements, transfers, AI upgrades, rookie generation (`engine/generation.py`).

### Models (`models/`)

- **Driver**: 11 performance stats (0–100), `potential` ceiling, fractional `xp` pools per stat, `age`/`salary`. `overall` is a weighted sum — `pace` 25%, `consistency` 18%, `experience` 9%, `qualifying_pace` 8%, `tire_management` 8%, `mental` 8%, `wet_weather` 7%, `overtaking` 7%, `braking` 5%, `defending` 4%, `car_control` 3%, `aggression` 3%. Age groups (prospect <25 / prime 25–34 / veteran 35–39 / legend 40+) affect development rates.
- **Car**: 7 attributes (`engine`, `aerodynamics`, `mechanical_grip`, `reliability`, `tire_deg`, `braking`, `pit_crew`). Upgrade costs scale exponentially near the cap (~2.7× at 95).
- **Team**: Container for budget, 2 driver IDs, a Car, sponsor ID, and championship points.
- **Circuit**: Track characteristics (`overtaking_difficulty`, `weather_chance`, `tire_wear`, `pit_lane_loss`). Computed `aero_weight = max(0.20, min(0.80, corners/90))` and `engine_weight = 1.0 - aero_weight` drive how car attributes affect lap times.
- **Sponsor**: `race_payment` (guaranteed M€/race) and an optional `bonus_type` (`podium` / `win` / `fastest_lap` / `top5_finish`) with `bonus_amount`.

### Race engine (`engine/race.py`)

The largest and most complex file. Key systems:

- **Race**: Lap-by-lap loop — tyre deg, fuel load, driver fatigue, incidents (DNFs), and position battles (overtaking logic gated by pace delta vs. `overtaking_difficulty`). Base lap time = `circuit.length_km × 20.5` seconds.
- **Safety Car**: `SC_PROBABILITY = 0.50` on any incident; `VSC_PROBABILITY = 0.25` (additional chance). All cars bunch up; pit windows open.
- **Tyre system** (`engine/tyres.py`): 5 compounds (Hard/Medium/Soft/Intermediate/Wet). Adjusted life = `base × driver_tire_mgmt_factor × car_tire_deg_factor`. `suggest_strategies()` generates 4 preset strategies for the player; `ai_strategy()` handles AI drivers.
- **Qualifying** (`engine/qualifying.py`): Knockout format — Q1 (all 20) → Q2 (top 15) → Q3 (top 10). Weather-sensitive; wet conditions replace 85% of `qualifying_pace` with `wet_weather`.

### Driver development (`engine/development.py`)

Post-race XP is calculated from finishing position, qualifying position, places gained, age group, and potential gap (`1.0 + ((potential - overall) / 100) * 1.5`). XP pools accumulate fractionally per stat; a stat only increments when its pool crosses 1.0. Stat growth rates vary: `experience` grows fastest (1.50×), `pace` and `qualifying_pace` grow slowest (0.65×).

**Age group XP multipliers**: prospect 2.00×, prime 1.15×, veteran 0.50×, legend 0.15×.
**Veteran/legend decline**: veteran 8% chance / legend 20% chance per race to lose 1 point from `pace` or `qualifying_pace`.
**Performance bonuses**: each overtake +0.06 overtaking XP (capped at 5/race); fastest lap +0.20 pace XP; wet-weather racing 1.8× `wet_weather` XP.

### Rookie generation (`engine/generation.py`)

Generates drivers with random stats (48–68), potential (78–96), age (18–22), and salary = `max(1, round((potential - 75) / 5))`. Used during off-season transfers.

## Key Constants & Scaling

- Race distance is always ~305 km; lap count = `round(305 / circuit.length_km)`.
- Car upgrade: +5 points per upgrade, cost = `base × e^((current - 70) / 25)` — roughly 1.0× at 70, 1.5× at 80, 2.7× at 95.
- XP weights per stat and per-race multipliers are tables in `engine/development.py` — adjust these to tune progression speed.
- Driver `overall` weights are in `models/driver.py`.
- **Race prize money**: P1 €4.0M, P2 €3.5M … P10 €0.4M; pole €1.5M; fastest lap €1.0M; podium bonus €0.5M each; DNF repair −€6.0M; ops cost −€2.0M/race.
- **Off-season constructor prizes**: P1 €80M, P2 €60M, P3 €45M … P10 €5M.
- **Retirement probability by age**: 42+ → 65%, 40+ → 40%, 38+ → 18%, 35+ → 5%.
- **Car degradation** each off-season: each attribute loses 2–5 points (floor 60; reliability floor 65).
