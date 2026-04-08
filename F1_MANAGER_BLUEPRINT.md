# F1 Manager Game — Architecture & Logic Blueprint

This document captures all simulation formulas, data schemas, system responsibilities, and architectural decisions from the current working game. It is intended as the foundation for rebuilding the project with a cleaner, more professional structure.

---

## Recommended Project Structure

```
f1-manager/
├── data/
│   ├── drivers.json           ← all driver stats
│   ├── teams.json             ← all team/car stats
│   ├── circuits.json          ← all circuit properties
│   └── sponsors.json          ← sponsor definitions
│
├── models/
│   ├── driver.py              ← Driver dataclass (pure data, no logic)
│   ├── team.py                ← Team dataclass
│   ├── car.py                 ← Car dataclass
│   ├── circuit.py             ← Circuit dataclass + aero_weight/engine_weight properties
│   └── sponsor.py             ← Sponsor dataclass
│
├── engine/
│   ├── core/
│   │   ├── lap_time.py        ← base lap time, fuel delta, tyre wear delta, noise, mistakes
│   │   ├── weather.py         ← rain fronts, thresholds, compound pace delta, wet_weather weight
│   │   ├── safety_car.py      ← SC/VSC state, trigger logic, duration, pit heuristics
│   │   ├── tyres.py           ← compounds, tyre life, strategies, AI pit decisions
│   │   ├── dnf.py             ← mechanical/tyre/collision/retirement probabilities
│   │   └── overtaking.py      ← overtake attempt formula, collision roll, position swap
│   ├── race_models.py         ← RaceEntry, RaceResult, DriverLapState, RaceReport, constants
│   ├── race.py                ← simulate_race() orchestrator — imports from core/ only
│   └── qualifying.py          ← qualifying simulation
│
├── game/
│   ├── loop.py                ← season flow, race execution, save/load orchestration
│   ├── management.py          ← pre-race team management menus
│   ├── finances.py            ← prize money, sponsorship payouts
│   ├── offseason.py           ← off-season events, driver retirements, development
│   ├── save_load.py           ← JSON game state persistence
│   ├── loader.py              ← JSON → model loading
│   └── ui/
│       ├── race_flow.py       ← race weekend flow, circuit briefing, animation wrapper
│       ├── race_display.py    ← lap-by-lap live display, standings table
│       ├── weather_sc.py      ← SC/weather pit decision UI menus
│       ├── quali_strategy.py  ← qualifying and race strategy selection menus
│       ├── overview.py        ← championship standings, team overview HUD
│       └── helpers.py         ← console utilities (colors, tables, prompts)
│
├── tests/
│   ├── test_core_lap_time.py
│   ├── test_core_weather.py
│   ├── test_core_safety_car.py
│   ├── test_core_tyres.py
│   ├── test_core_dnf.py
│   ├── test_core_overtaking.py
│   ├── test_race_integration.py
│   └── smoke_test.py
│
├── saves/                     ← JSON save files (auto-created)
├── main.py                    ← entry point
└── requirements.txt           ← rich, click (terminal UI)
```

**Key improvement over the current project:** each system in `engine/core/` is a single-concern module. `engine/race.py` is a pure orchestrator — no inline physics or probability formulas.

---

## Layer Architecture & Import Rules

```
models/         ← pure dataclasses only. No imports from engine/ or game/
engine/core/    ← pure functions/dataclasses only. No UI imports. No game/ imports.
engine/race.py  ← imports from engine/core/ and engine/race_models.py only
engine/qualifying.py ← same as race.py
game/loop.py    ← imports from engine/ + game/ui/ + models/
game/ui/        ← imports from engine/race_models.py + models/ only
                   NEVER import directly from engine/core/ in UI
```

---

## Data Schemas

### drivers.json
```json
{
  "drivers": [
    {
      "id":               "VER",          // 3-letter abbreviation (string)
      "name":             "Max Verstappen",
      "nationality":      "Dutch",
      "age":              28,             // integer
      "pace":             96,             // 0–100: sustained race pace
      "qualifying_pace":  99,             // 0–100: one-lap speed
      "consistency":      95,             // 0–100: lap-to-lap variance (higher = less variance)
      "overtaking":       97,             // 0–100: attack ability in wheel-to-wheel
      "defending":        94,             // 0–100: defense ability
      "car_control":      92,             // 0–100: incident/spin avoidance
      "wet_weather":      90,             // 0–100: rain performance
      "tire_management":  88,             // 0–100: tyre preservation (affects tyre life)
      "mental":           97,             // 0–100: performance under pressure
      "experience":       92,             // 0–100: circuit knowledge (affects mistakes)
      "aggression":       92,             // 0–100: wheel-to-wheel intensity (affects collision risk)
      "potential":        99,             // 0–100: development ceiling
      "salary":           55,             // M€ per season
      "team_id":          "red_bull"
    }
  ]
}
```

### teams.json
```json
{
  "teams": [
    {
      "id":          "red_bull",
      "name":        "Oracle Red Bull Racing",
      "short_name":  "Red Bull",
      "color":       "blue",             // rich library color name
      "budget":      120,                // M€ available this season
      "car": {
        "engine":          90,           // 0–100: straight-line speed
        "aerodynamics":    92,           // 0–100: cornering downforce
        "mechanical_grip": 89,           // 0–100: mechanical traction
        "reliability":     86,           // 0–100: DNF resistance (higher = fewer failures)
        "tire_deg":        88,           // 0–100: tyre gentleness (higher = tyres last longer)
        "braking":         90,           // 0–100: braking stability
        "pit_crew":        88            // 60–100: pit stop speed (affects stationary time)
      },
      "driver_ids": ["VER", "HAD"]
    }
  ]
}
```

### circuits.json
```json
{
  "circuits": [
    {
      "id":                   "bahrain",
      "name":                 "Bahrain Grand Prix",
      "country":              "Bahrain",
      "flag":                 "🇧🇭",
      "length_km":            5.412,
      "corners":              15,        // used to derive aero_weight (see Circuit model)
      "overtaking_difficulty": 30,       // 0–100: higher = harder to pass
      "weather_chance":        5,        // 0–100: % probability of rain during race
      "tire_wear":             "high",   // "low" | "medium" | "high"
      "pit_lane_loss":         22        // seconds (pit entry + traversal + exit)
    }
  ]
}
```

**Note:** `aero_weight` and `engine_weight` are computed properties, not stored in JSON:
```python
aero_weight   = round(max(0.20, min(0.80, corners / 90)), 2)
engine_weight = round(1.0 - aero_weight, 2)
```

### sponsors.json
```json
{
  "sponsors": [
    {
      "id":            "grand_prix_media",
      "name":          "Grand Prix Media",
      "industry":      "Broadcasting",
      "race_payment":  2.0,             // M€ paid per race
      "bonus_type":    "none",          // "none" | "podium" | "win" | "points" | ...
      "bonus_amount":  0,               // M€ bonus if condition met
      "description":   "..."
    }
  ]
}
```

---

## System Module: Lap Time (`engine/core/lap_time.py`)

All lap time components assembled in `_compute_driver_lap_time()`:

```
lap_time = base + fuel_delta + tyre_delta + random_noise + sc_multiplier + mistakes
```

### Base Lap Time
```python
ref_lap_time = circuit.length_km * 20.5

# Car performance delta (negative = faster)
car_delta = -(
    car.aerodynamics      * aero_w   * 0.50
    + car.engine          * engine_w * 0.50
    + car.mechanical_grip * mech_w   * 0.15   # mech_w = 1.0 - aero_w
) * 0.048

# Driver performance delta (rain-adjusted)
wet_w    = wet_weather_weight(rain_prob)       # see Weather module
eff_pace = driver.pace * (1.0 - wet_w) + driver.wet_weather * wet_w

driver_delta = -(
    eff_pace             * 0.40
    + driver.consistency * 0.20
    + driver.mental      * 0.12
    + driver.experience  * 0.10
) * 0.022

base = ref_lap_time + car_delta + driver_delta
```

### Fuel Delta
```python
fuel_delta = (fuel_load / 100.0) * 2.8    # +2.8s per 100 kg of fuel
```
Fuel load starts at 100.0 and decreases each lap.

### Tyre Wear Delta
```python
wear_frac  = min(1.0, tyre_age / max(1, tyre_life))
tyre_delta = wear_frac ** 2 * 6.0 + compound_pace_delta(compound, rain_prob)
```
At 100% worn: +6.0 s/lap from wear alone (before compound delta).

### Lap Noise
```python
stability = (driver.consistency + driver.mental) / 200.0
lap_sigma = 0.25 * (1.0 + (1.0 - stability))
noise = random.gauss(0, lap_sigma)
```

### SC/VSC Multiplier
```python
if sc_state == "SC":   lap_time *= 1.40
if sc_state == "VSC":  lap_time *= 1.30
```

### Driver Mistakes
```python
mistake_prob = max(0.0, (60.0 - driver.experience) / 100.0) * 0.04
if random.random() < mistake_prob:
    lap_time += random.uniform(1.5, 4.0)   # seconds lost
```

---

## System Module: Weather (`engine/core/weather.py`)

### Rain Threshold Constants
```python
RAIN_WARNING   = 55    # slicks start accruing penalty; player warning fires
RAIN_DAMP      = 65    # track damp; intermediates competitive
RAIN_WET_ONSET = 80    # wets start paying off
RAIN_HEAVY     = 92    # full wet; standing water
```

### WeatherState Fields
```python
@dataclass
class WeatherState:
    rain_prob:              float          # current rain probability 0–100
    wet_start:              bool  = False  # race started wet
    front_active:           bool  = False  # a rain front is scheduled
    front_arrival_lap:      int   = 0      # lap the front arrives/starts decaying
    front_rise_rate:        float = 0.0    # laps/s rise per lap
    front_decay_rate:       float = 0.0    # laps/s decay per lap
    peak_duration:          int   = 0      # laps to stay at peak before decaying
    laps_above_peak:        int   = 0      # counter for peak phase
    rain_decreasing:        bool  = False  # currently drying
    peak_rain_prob:         float = 0.0    # highest rain_prob seen this episode
    episode_below_60_count: int   = 0      # laps below 60% (resets thresholds at 3)
    thresholds_crossed:     dict  = {"warning": False, "damp": False, "wet": False, "drying": False}
    player_ignored_warning: bool  = False
    weather_sc_fired:       bool  = False
    warning_cooldown:       int   = 0
```

### Rain Front Initialisation
```python
# Dry race — random rain front
if weather == "dry" and random() * 100 < circuit.weather_chance:
    arrival_lap = randint(max(3, total_laps*0.15), max(..., total_laps*0.85))
    strength    = choices(["light","moderate","heavy"], weights=[40,40,20])

    rise_rates     = {"light": 5.5,  "moderate": 10.0, "heavy": 17.0}
    decay_rates    = {"light": 5.0,  "moderate": 7.0,  "heavy": 6.0}
    peak_durations = {"light": 5,    "moderate": 8,    "heavy": 12}

# Wet race — 50% chance of drying front mid-race
if weather == "wet" and random() < 0.50:
    drying_lap       = randint(total_laps//4, total_laps-5)
    decay_rate       = uniform(4.0, 8.0)
    rain_decreasing  = True
```

### Per-Lap Rain Step
```python
# Rising phase
delta = max(0.0, gauss(rise_rate, rise_rate * 0.35))
rain_prob = min(100.0, rain_prob + delta)

# Decaying phase
delta = max(0.0, gauss(decay_rate, decay_rate * 0.30))
rain_prob = max(0.0, rain_prob - delta)

# Reset thresholds after 3 laps below 60%
if rain_prob < 60:
    episode_below_60_count += 1
    if episode_below_60_count >= 3:
        reset all thresholds_crossed to False
```

### Compound Pace Delta (seconds/lap, positive = slower)
```python
# Slick compounds (soft/medium/hard)
# base dry delta: soft=-0.5, medium=0.0, hard=+0.3
if rain_prob <= 55:  return base
if rain_prob <= 65:  return base + lerp(0.0, 2.0,  t)   # t = (rain-55)/10
if rain_prob <= 80:  return base + lerp(2.0, 5.0,  t)   # t = (rain-65)/15
if rain_prob <= 92:  return base + lerp(5.0, 9.0,  t)   # t = (rain-80)/12
else:                return base + lerp(9.0, 12.5, t)   # t = (rain-92)/8

# Intermediate — optimal window 40–92%
if rain_prob <= 40:  return 6.0
if rain_prob <= 65:  return lerp(6.0, 0.2, t)           # t = (rain-40)/25
if rain_prob <= 92:  return 0.2
else:                return lerp(0.2, 2.7, t)           # t = (rain-92)/8

# Wet tyre — optimal 82%+
if rain_prob <= 55:  return 12.0
if rain_prob <= 70:  return lerp(12.0, 3.0, t)          # t = (rain-55)/15
if rain_prob <= 82:  return lerp(3.0,  0.8, t)          # t = (rain-70)/12
else:                return 0.8
```

### Wet-Weather Driver Stat Weight
Scales how much `wet_weather` stat replaces `pace` stat:
```python
if rain_prob <= 40:  return 0.0
if rain_prob <= 65:  return lerp(0.0,  0.30, t)    # t = (rain-40)/25
if rain_prob <= 80:  return lerp(0.30, 0.60, t)    # t = (rain-65)/15
else:                return lerp(0.60, 0.85, t)    # t = min(1, (rain-80)/20)
```

### Weather Forecast (15-lap lookahead)
Noise increases with distance:
```python
noise_by_offset = [4, 4, 10, 10, 12, 18, 18, 20, 22, 22, 26, 26, 30, 30, 32]
```
Each lap projected forward using rise/decay rate + `gauss(0, noise)`.

### Decision Thresholds
Fired once per rain episode (reset after 3 laps below 60%):
- `"warning"` — rain_prob crosses 55 (while player hasn't ignored warning and cooldown = 0)
- `"damp"`    — rain_prob crosses 65
- `"wet"`     — rain_prob crosses 92
- `"drying"`  — rain_prob falls below 65, peak was > 70

---

## System Module: Safety Car (`engine/core/safety_car.py`)

### State
```python
@dataclass
class SafetyCarState:
    active:         bool          = False
    type:           Optional[str] = None     # "SC" or "VSC"
    laps_remaining: int           = 0
    trigger_reason: str           = ""
```

### SC/VSC Roll (on any incident — DNF, collision)
```python
SC_PROBABILITY  = 0.50    # chance of full Safety Car
VSC_PROBABILITY = 0.25    # additional chance of Virtual Safety Car
# combined: 50% SC, 25% VSC, 25% no deployment
```

### Duration
```python
sc_laps_remaining = random.randint(3, 5)
```

### Lap Time Multiplier
```python
SC:  * 1.40
VSC: * 1.30
```

### Weather-Triggered SC
```python
WEATHER_SC_DELTA_THRESHOLD  = 15    # rain rise per lap that may trigger SC
WEATHER_SC_SUDDEN_PROB      = 0.30  # probability of SC on sudden rain spike
WEATHER_SC_AQUAPLANE_THRESH = 90    # rain_prob that can trigger aquaplaning SC
WEATHER_SC_AQUAPLANE_PROB   = 0.35  # probability at aquaplaning threshold

# Only fires once per rain episode (weather_sc_fired flag prevents repeats)
# Does not trigger in last 3 laps of race
```

### SC Pit Recommendation Threshold
```python
recommend_pit = tyre_age > tyre_life * 0.55
```

### AI Weather Pit Decision
```python
current_penalty = compound_pace_delta(compound, rain_prob)
expected_loss   = current_penalty * min(laps_remaining, 15)
pit_cost        = circuit.pit_lane_loss + 2.5
should_pit      = expected_loss > pit_cost * 1.2
```

---

## System Module: Tyres (`engine/core/tyres.py`)

### Compound Definitions
| Compound     | Dry pace delta | Color  | Symbol | Rain compound |
|--------------|----------------|--------|--------|---------------|
| soft         | −0.5 s/lap     | red    | S      | No            |
| medium       | 0.0 s/lap      | yellow | M      | No            |
| hard         | +0.3 s/lap     | white  | H      | No            |
| intermediate | +0.2 s/lap     | green  | I      | Yes           |
| wet          | +0.8 s/lap     | blue   | W      | Yes           |

*(Dry pace delta is on a dry track at zero rain. Under rain, use compound_pace_delta() from weather module.)*

### Base Tyre Life (laps)
| Compound | Low wear | Medium wear | High wear |
|----------|----------|-------------|-----------|
| hard     | 50       | 38          | 25        |
| medium   | 34       | 25          | 16        |
| soft     | 24       | 18          | 12        |

Rain compound life is dynamic:
```python
# intermediate: 15 laps dry → 52 laps at 65%+ rain
base = lerp(15, 52, min(1.0, rain_prob / 65))

# wet: 15 laps dry → 62 laps at 100% rain
base = lerp(15, 62, min(1.0, rain_prob / 100))
```

### Adjusted Tyre Life (with driver/car factors)
```python
driver_factor = 0.6 + driver.tire_management / 100 * 0.8    # range: 0.60–1.40
car_factor    = 0.7 + car.tire_deg             / 100 * 0.6  # range: 0.70–1.30
life = max(3, int(base * driver_factor * car_factor))
```

### Working Life (before degradation becomes costly)
```python
frac = {"low": 0.82, "medium": 0.76, "high": 0.70}[circuit.tire_wear]
working_life = max(3, int(full_life * frac))
```

### Default Tyre Allocation
Each driver starts with 2 sets of every compound:
```python
{"soft": 2, "medium": 2, "hard": 2, "intermediate": 2, "wet": 2}
```

### TyreAllocation.best_available(preferred)
```
1. If preferred compound has sets remaining → return preferred
2. If preferred is a rain compound → try the other rain compound first
3. Fall back to compound with most sets remaining
```

### Pit Schedule
Built from `RaceStrategy(stints=[TyreStint(compound, laps), ...])`:
```python
# Returns {lap_number: next_compound}
# lap_number = cumulative laps after each stint except the last
```

### Strategy Presets (dry)
Using working life per stint, `_fill_smart()` fills remaining laps:
- **Aggressive**: S (working) → M (working) → H (fill)
- **Balanced**: M (working) → H (fill)
- **Conservative**: H (working) → M (fill)
- **2-Stop**: S (short = total//4) → M (working) → H (fill)

### Strategy Presets (wet start)
- **Intermediates**: full race on inters
- **Full Wets**: full race on wets
- **Inter → Wet**: first half inters, then wets
- **Wet → Inter**: first half wets, then inters

### Tyre Score Formula (for strategy comparison)
```python
for each stint:
    if rain compound on dry race:    avg_bonus = pace_bonus - 12.0
    elif slick compound on wet race: avg_bonus = pace_bonus - 10.0
    elif stint.laps <= tyre_life:    avg_bonus = pace_bonus
    else:
        overrun_frac = (stint.laps - life) / life
        avg_bonus    = pace_bonus - overrun_frac * 12.0
    contribution += avg_bonus * (stint.laps / total_laps)

pit_time  = 2.0 + (90 - car.pit_crew) * 0.05    # 2.0–3.5 s stationary time
pit_penalty = num_stops * (pit_time / 1.2)
score = contribution - pit_penalty
```

### AI Strategy Selection
```python
if car.tire_deg > 80 and driver.tire_management > 75:
    base_idx = 2    # Conservative
elif car.tire_deg < 70 or driver.tire_management < 65:
    base_idx = 3    # 2-Stop
else:
    base_idx = randint(0, 1)    # Aggressive or Balanced

# Apply small random variation: idx ± 1 (clamped to valid range)
```

---

## System Module: DNF (`engine/core/dnf.py`)

### Mechanical DNF (per lap)
```python
MECH_FAILURE_RATE = 0.0015
CTRL_LOSS_RATE    = 0.0008

mech_prob = (100 - car.reliability)    / 100 * 0.0015
ctrl_prob = (100 - driver.car_control) / 100 * 0.0008
total_prob = mech_prob + ctrl_prob
```
Example: reliability=86, car_control=92 → ~0.000297/lap ≈ 0.03% per lap.

### Tyre Failure (per lap, only when past rated life)
```python
TYRE_OVERRUN_RATE     = 0.008    # probability gain per overrun lap
TYRE_OVERRUN_MAX_PROB = 0.05     # cap at 5% per lap

if tyre_age <= tyre_life:
    prob = 0.0
else:
    overrun_laps = tyre_age - tyre_life
    prob = min(0.05, overrun_laps * 0.008)
```

### Collision Probability (during overtake duel)
```python
COLLISION_AGGRESSION_SCALE = 0.025

collision_prob = (attacker.aggression / 100) * (defender.aggression / 100) * 0.025
```

### Collision Outcome
```python
COLLISION_RETIRE_PROB   = 0.40       # probability of retirement
COLLISION_DAMAGE_MIN_S  = 15.0       # minimum damage time penalty
COLLISION_DAMAGE_MAX_S  = 35.0       # maximum damage time penalty

# For each car involved:
if random() < 0.40:
    → retire (dnf = True)
else:
    → damage_seconds = uniform(15.0, 35.0)    # added to total race time
```

### DNF Reason Pool
```
Engine failure, Gearbox failure, Hydraulic issue, Suspension failure,
Brake failure, Collision damage, Electrical fault, Power unit failure
```

### Off-Season Driver Retirement Probability
```python
RETIREMENT_AGE_PROBS = [
    (42, 0.65),    # age 42+: 65% chance of retiring
    (40, 0.40),    # age 40+: 40%
    (38, 0.18),    # age 38+: 18%
    (35, 0.05),    # age 35+: 5%
]
# Below 35: 0% (first matching bracket is used)
```

---

## System Module: Overtaking (`engine/core/overtaking.py`)

### Attempt Conditions (both must be true)
```python
BATTLE_RANGE_S      = 1.0    # max gap (seconds) for an overtake to be possible
OVERTAKE_THRESHOLD  = 0.5    # minimum speed advantage (s/lap) required to attempt

gap         = states[behind].total_race_time - states[ahead].total_race_time
speed_delta = lap_times[ahead] - lap_times[behind]   # positive = behind car is faster

if gap <= 1.0 and speed_delta >= 0.5:
    attempt_overtake(...)
```

### Overtake Success Formula
```python
circuit_factor  = (100 - circuit.overtaking_difficulty) / 100
overtake_chance = (speed_delta / 0.8) * (attacker.overtaking / 100) * (1 + attacker.aggression / 200) * circuit_factor
defend_factor   = (defender.defending * 0.7 + defender.aggression * 0.3) / 200
effective_chance = overtake_chance * (1.0 - defend_factor)
effective_chance = clamp(effective_chance, 0.0, 0.95)
```

### Collision Roll (checked before success roll)
```python
collision_prob = (attacker.aggression / 100) * (defender.aggression / 100) * 0.025
if random() < collision_prob:
    → collision event (no position change, apply collision outcomes to both drivers)
```

### On Successful Overtake
Position swap using time midpoint:
```python
mid = (time_ahead + time_behind) / 2.0
states[behind].total_race_time = mid - 0.25
states[ahead].total_race_time  = mid + 0.25
# swap positions in active[] list
```

---

## Race Orchestrator (`engine/race.py`)

### Signature
```python
simulate_race(
    entries:           List[RaceEntry],
    circuit:           Circuit,
    weather:           str,                    # "dry" | "wet"
    grid:              List[str],              # driver ids in grid order
    strategies:        Dict[str, RaceStrategy],
    player_team_id:    str,
    player_allocation: Dict[str, TyreAllocation],
    sc_pit_callback:   Optional[Callable],
    weather_callback:  Optional[Callable],
    lap_callback:      Optional[Callable],
) -> RaceReport
```

### Lap Loop Pseudocode
```
setup:
  total_laps      = round(305 / circuit.length_km)
  weather_state   = init_weather_state(weather, circuit, total_laps)   # weather.py
  pit_schedules   = {did: build_pit_schedule(strategies[did]) ...}     # tyres.py
  sc_state        = SafetyCarState()                                    # safety_car.py
  fuel_load       = 100.0 per driver
  pit_recovery    = {} (2 laps of reduced pace after a pit stop)

for lap in 1 .. total_laps:

  # 1. Weather step
  prev_rain, msgs = step_rain_probability(weather_state, lap)           # weather.py
  rain_prob = weather_state.rain_prob

  # 2. Safety car — weather trigger
  sc_type = should_trigger_weather_sc(weather_state, rain_prob, prev_rain, lap, total_laps)
  if sc_type: activate SC, set sc_laps_remaining = randint(3, 5)

  # 3. Strategy threshold — fire callback for player pit decisions
  threshold = detect_weather_threshold(weather_state, rain_prob, prev_rain)
  if threshold and weather_callback:
    new_strategies = weather_callback(threshold, weather_state, lap)
    update strategies / pit schedules

  # 4. SC management
  if sc_state.active:
    sc_laps_remaining -= 1
    if sc_laps_remaining <= 0: deactivate SC

  # 5. Per-driver lap
  for each driver did (in current race order, skip DNF):

    # Pit stop
    if lap in pit_schedules[did]:
      execute_pit_stop(did, next_compound, ...)
      stat_s = max(1.8, gauss(2.0 + (90 - pit_crew) * 0.05, 0.15))
      total_time = circuit.pit_lane_loss + stat_s
      add total_time to driver race time

    # DNF check
    reason = roll_mechanical_dnf(driver, car)                           # dnf.py
    if not reason: reason = roll_tyre_dnf(tyre_age, tyre_life)          # dnf.py
    if reason: mark driver DNF, check_safety_car() for SC deployment

    # Lap time
    lap_time = compute_lap_time(...)                                     # lap_time.py
      = base + fuel_delta + tyre_delta + compound_delta + noise + sc_multiplier + mistakes

    # Tyre age + fuel
    tyre_age  += 1
    fuel_load -= fuel_per_lap   # approx: 100 / total_laps

  # 6. Overtaking
  collision_dnf = process_overtaking_pass(active, states, ...)          # overtaking.py
  if collision_dnf: check_safety_car() for SC deployment

  # 7. SC pit recommendation
  if sc_state.active and sc_pit_callback:
    recommendations = {did: recommend_pit if tyre_age > tyre_life*0.55}
    new_strategies = sc_pit_callback(lap, recommendations)

  # 8. AI weather pit
  for each AI driver:
    if ai_should_pit_for_weather(state, entry, circuit, rain_prob, remaining):
      override pit schedule to pit this lap

  # 9. Lap callback (live mode only)
  if lap_callback: lap_callback(lap, standings_snapshot, events_this_lap)

return _build_race_results(states, ...)
```

---

## Callback Interface

All three callbacks are `Optional` — the engine runs completely headlessly when they are `None`.

### `weather_callback`
Fired when rain crosses a decision threshold (`"warning"`, `"damp"`, `"wet"`, `"drying"`).
```python
def weather_callback(
    threshold:     str,           # "warning" | "damp" | "wet" | "drying"
    weather_state: WeatherState,
    lap:           int,
) -> Dict[str, RaceStrategy]:     # driver_id → new strategy (or empty dict to keep current)
```

### `sc_pit_callback`
Fired each lap a Safety Car is active, with pit recommendations.
```python
def sc_pit_callback(
    lap:             int,
    recommendations: Dict[str, bool],    # driver_id → should_pit recommendation
) -> Dict[str, RaceStrategy]:           # driver_id → new strategy override
```

### `lap_callback`
Fired at the end of each lap in live mode.
```python
def lap_callback(
    lap:              int,
    standings:        List[Tuple[str, float]],   # [(driver_id, total_race_time), ...]
    events_this_lap:  List[str],
) -> None
```

---

## Race Data Models (`engine/race_models.py`)

```python
POINTS_SYSTEM = {1:25, 2:18, 3:15, 4:12, 5:10, 6:8, 7:6, 8:4, 9:2, 10:1}
# Fastest lap: +1 point (only for finishers in top 10)

OVERTAKE_THRESHOLD = 0.5    # s/lap speed advantage needed for an attempt
BATTLE_RANGE_S     = 1.0    # max gap for overtake to be possible
SC_PROBABILITY     = 0.50   # chance of SC on incident
VSC_PROBABILITY    = 0.25   # additional chance of VSC on incident

@dataclass class RaceEntry:     driver, car, team_id, team_name, team_color
@dataclass class RaceResult:    position, driver, team_id, team_name, team_color,
                                time_gap, points, fastest_lap, dnf, dnf_reason, grid_position
@dataclass class DriverLapState: total_race_time, fuel_load, tyre_compound, tyre_age,
                                 stint_index, dnf, dnf_reason, pit_this_lap, dnf_lap
@dataclass class DriverLapRecord: lap, lap_time, compound, tyre_age, wear_pct, fuel_load,
                                  position, pitted, dnf, rain_prob, sc_active
@dataclass class PitStop:       driver_name, team_name, team_color, lap, old_compound,
                                new_compound, stationary_time, pit_lane_loss, total_time
@dataclass class RaceReport:    results, events, pit_stops, fastest_lap_time,
                                driver_fastest_laps, lap_data, overtakes_made,
                                defenses_made, peak_rain_prob, weather_summary
```

---

## Points System

```
P1:  25 pts    P6:  8 pts
P2:  18 pts    P7:  6 pts
P3:  15 pts    P8:  4 pts
P4:  12 pts    P9:  2 pts
P5:  10 pts    P10: 1 pt

Fastest lap: +1 point (only if finisher is classified in top 10)
```

---

## Test Strategy

One test file per core module. All tests in `tests/` are independently runnable (no game state, no UI):

| Test file                  | Covers                                        |
|----------------------------|-----------------------------------------------|
| `test_core_lap_time.py`    | base lap time at rain levels, fuel delta, wear delta, noise distribution, mistake probability |
| `test_core_weather.py`     | front init (dry/wet), per-lap step, threshold detection, reset logic, compound_pace_delta at all breakpoints, wet_weather_weight, forecast noise |
| `test_core_safety_car.py`  | SC/VSC trigger conditions, weather SC thresholds, duration roll, pit recommendation formula, AI pit decision |
| `test_core_tyres.py`       | adjusted_tyre_life (driver/car factors, rain compounds), working_life fractions, tyre_wear_delta, strategy presets, build_pit_schedule, best_available, TyreAllocation ops |
| `test_core_dnf.py`         | mechanical_dnf_probability, tyre_failure_probability (before/after life), collision_probability, retirement_probability (all age brackets), roll functions |
| `test_core_overtaking.py`  | attempt conditions (gap/speed thresholds), overtake_chance formula, defend_factor, collision roll, position swap math |
| `test_race_integration.py` | full `simulate_race()` dry race, wet race, SC deployment, weather transition — no UI callbacks |
| `smoke_test.py`            | full season (all circuits, offseason, driver development) — confirms game stays runnable end-to-end |

---

## Current vs New Module Mapping

| Current location | Logic | New location |
|-----------------|-------|--------------|
| `engine/race_physics.py` | `_base_lap_time()` | `engine/core/lap_time.py` |
| `engine/race_physics.py` | `_attempt_overtake()` | `engine/core/overtaking.py` |
| `engine/core/weather.py` | `check_safety_car()`, `should_trigger_weather_sc()`, SC constants | `engine/core/safety_car.py` |
| `engine/core/weather.py` | `should_recommend_sc_pit()`, `trim_strategy_to_remaining()` | `engine/core/safety_car.py` / `engine/core/tyres.py` |
| `engine/race.py` | SC state machine, SC duration, SC lap time multiplier | `engine/core/safety_car.py` |
| `engine/race.py` | overtake loop (`_process_overtaking_pass`) | `engine/core/overtaking.py` |
| `engine/race_models.py` | `OVERTAKE_THRESHOLD`, `BATTLE_RANGE_S` | `engine/core/overtaking.py` |
| `engine/race_models.py` | `SC_PROBABILITY`, `VSC_PROBABILITY` | `engine/core/safety_car.py` |
