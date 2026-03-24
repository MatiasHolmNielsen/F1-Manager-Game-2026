# CLAUDE.md

## Run
```bash
pip install -r requirements.txt
python main.py
```
No tests. Game runs interactively in the terminal.

## File map
| File | What to edit here |
|---|---|
| `engine/race_models.py` | Dataclasses, points system, DNF reasons |
| `engine/weather.py` | Rain drift, compound deltas, SC probability |
| `engine/race_physics.py` | Lap time formula, overtake math |
| `engine/race.py` | `simulate_race()` loop, pit stop logic |
| `engine/qualifying.py` | Q1/Q2/Q3 scores |
| `engine/tyres.py` | Compound life, strategy generation, AI strategy |
| `engine/development.py` | XP tables, stat growth, decline |
| `engine/generation.py` | Rookie stat ranges |
| `game/loop.py` | Season/race loop, team selection |
| `game/loader.py` | JSON loading |
| `game/management.py` | Car upgrade menu, driver market |
| `game/finances.py` | Race prize money, sponsor bonuses |
| `game/offseason.py` | Constructor prizes, car degradation, retirements |
| `game/ui/helpers.py` | `fmt_lap_time`, `stat_bar`, `_rain_bar`, `console` singleton |
| `game/ui/race_display.py` | Race results, pit stats, lap analysis |
| `game/ui/quali_strategy.py` | Q display, strategy menu |
| `game/ui/weather_sc.py` | SC/weather mid-race prompts |
| `game/ui/overview.py` | Team overview, standings, driver development |
| `game/ui/race_flow.py` | Circuit briefing, race transition, sponsor screen, race animation |
| `data/*.json` | Driver/team/circuit/sponsor values |

## Key tuning constants
- **Lap time base**: `circuit.length_km × 20.5` seconds (`race_physics.py`)
- **Car upgrade**: +5 pts, cost = `base × e^((current-70)/25)` (`models/car.py`)
- **Race prizes**: P1 €4.0M … P10 €0.4M; pole +€1.5M; FL +€1.0M; podium +€0.5M; DNF −€6.0M (`finances.py`)
- **Off-season prizes**: P1 €80M … P10 €5M (`offseason.py:CONSTRUCTOR_PRIZE`)
- **SC probability**: 50% on incident; VSC 25% (`race_models.py`)
- **XP multipliers**: prospect 2.0×, prime 1.15×, veteran 0.5×, legend 0.15× (`development.py:AGE_MULT`)
- **Retirement by age**: 42+→65%, 40+→40%, 38+→18%, 35+→5% (`offseason.py`)
- **Car degradation** off-season: −2–5 pts per attr, floor 60 (reliability 65) (`offseason.py`)
- **Driver overall weights**: `models/driver.py` — pace 25%, consistency 18%, experience 9% …

## Data flow
`loop.py:main()` → loader → team/sponsor selection → per-race: management_menu → qualifying → strategy_menu → simulate_race → finances → development → standings → offseason
