"""Race simulation orchestrator.
# Functions: _resolve_grid_pos:38  _execute_pit_stop:46  _compute_driver_lap_time:91
#            _process_overtaking_pass:117  _build_race_results:166
#            RaceContext:218  _setup_race:257  _run_lap:316  _finalise_results:559
#            simulate_race:569
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from engine.race_models import (
    RaceEntry, RaceResult, DriverLapState, DriverLapRecord,
    PitStop, RaceReport, POINTS_SYSTEM, DNF_REASONS,
    OVERTAKE_THRESHOLD, BATTLE_RANGE_S,
)
from engine.core.weather import (
    WeatherState, init_weather_state, step_rain_probability,
    detect_weather_threshold, get_rain_trend, generate_weather_forecast,
    check_safety_car, compound_pace_delta,
    WEATHER_SC_DELTA_THRESHOLD, WEATHER_SC_SUDDEN_PROB,
    WEATHER_SC_AQUAPLANE_THRESH, WEATHER_SC_AQUAPLANE_PROB,
)
from engine.core.dnf import (
    roll_mechanical_dnf, roll_tyre_dnf, roll_collision_outcome,
)
from engine.core.tyres import (
    TyreAllocation, TYRE_WEAR_TIME_SCALE,
    TyreStint, RaceStrategy, race_laps, adjusted_tyre_life,
    ai_strategy, ai_should_pit_for_weather, build_pit_schedule,
)
from engine.race_physics import _base_lap_time, _attempt_overtake
from engine.qualifying import QualiResult, simulate_qualifying  # noqa: F401 (re-export)

# Re-export everything callers may import from this module
from engine.race_models import *  # noqa: F401, F403


# ─── Grid position helper ─────────────────────────────────────────────────────

def _resolve_grid_pos(did: str, grid: Optional[List[str]]) -> int:
    """Return 1-based starting grid position for *did*, or 10 if not listed."""
    if grid and did in grid:
        return grid.index(did) + 1
    return 10


# ─── Pit stop helper ──────────────────────────────────────────────────────────

def _execute_pit_stop(
    did: str,
    next_cmp: str,
    old_cmp: str,
    state: DriverLapState,
    entry: RaceEntry,
    circuit,
    lap: int,
    pit_stop_log: list,
    events: list,
    pitted_this_lap: set,
    pit_recovery_laps_left: dict,
    event_suffix: str = "",
) -> float:
    """Perform a pit stop: update state, log it, return total pit time."""
    car = entry.car
    driver = entry.driver
    stat_s = max(1.8, round(2.0 + (90 - car.pit_crew) * 0.05 + random.gauss(0, 0.15), 2))
    total_time = circuit.pit_lane_loss + stat_s
    state.total_race_time += total_time
    state.tyre_age = 0
    state.tyre_compound = next_cmp
    state.stint_index += 1
    pit_recovery_laps_left[did] = 2
    pitted_this_lap.add(did)
    events.append(f"Lap {lap}: {driver.name} pits{event_suffix} ({next_cmp}, {total_time:.1f}s)")
    pit_stop_log.append(PitStop(
        driver_name=driver.name,
        team_name=entry.team_name,
        team_color=entry.team_color,
        lap=lap,
        old_compound=old_cmp,
        new_compound=next_cmp,
        stationary_time=stat_s,
        pit_lane_loss=float(circuit.pit_lane_loss),
        total_time=round(total_time, 2),
    ))
    return total_time


# ─── Lap time computation ─────────────────────────────────────────────────────

def _compute_driver_lap_time(
    entry: RaceEntry,
    state: DriverLapState,
    circuit,
    rain_prob: float,
    life: float,
    sc_state: Optional[str],
    events: List[str],
    lap: int,
) -> float:
    """Return the driver's lap time including fuel, tyre, SC delta, and mistakes.

    Appends a mistake event to *events* when one occurs. All other state
    mutations (total_race_time, tyre_age, fuel_load) remain the caller's
    responsibility.
    """
    driver = entry.driver
    base = _base_lap_time(entry, circuit, rain_prob)
    fuel_delta = (state.fuel_load / 100.0) * 2.8
    wear_frac = min(1.0, state.tyre_age / max(1, life))
    cmp_delta = compound_pace_delta(state.tyre_compound, rain_prob)
    tyre_delta = wear_frac ** 2 * TYRE_WEAR_TIME_SCALE + cmp_delta

    stability = (driver.consistency + driver.mental) / 200.0
    lap_sigma = 0.25 * (1.0 + (1.0 - stability))
    lap_time = base + fuel_delta + tyre_delta + random.gauss(0, lap_sigma)

    if sc_state == "SC":
        lap_time *= 1.40
    elif sc_state == "VSC":
        lap_time *= 1.30

    mistake_prob = max(0.0, (60.0 - driver.experience) / 100.0) * 0.04
    if random.random() < mistake_prob:
        mistake_time = round(random.uniform(1.5, 4.0), 1)
        lap_time += mistake_time
        if lap <= 15:
            events.append(f"Lap {lap}: {driver.name} makes a mistake, +{mistake_time}s")

    return lap_time


# ─── Overtaking pass ──────────────────────────────────────────────────────────

def _process_overtaking_pass(
    active: List[str],
    states: Dict[str, DriverLapState],
    entry_map: Dict[str, RaceEntry],
    lap_times: Dict[str, float],
    circuit,
    lap: int,
    overtakes_made: Dict[str, int],
    defenses_made: Dict[str, int],
    events: List[str],
) -> bool:
    """Process all overtaking duels for this lap.

    Mutates *states* (time swap / DNF), *active* (position swap), the counter
    dicts, and *events*. Returns True if any collision caused a retirement.
    """
    had_dnf = False
    i = len(active) - 1
    while i > 0:
        behind_did = active[i]
        ahead_did  = active[i - 1]

        if behind_did not in lap_times or ahead_did not in lap_times:
            i -= 1
            continue

        gap = states[behind_did].total_race_time - states[ahead_did].total_race_time
        if gap > BATTLE_RANGE_S:
            i -= 1
            continue

        speed_delta = lap_times[ahead_did] - lap_times[behind_did]

        if speed_delta >= OVERTAKE_THRESHOLD:
            success, collision = _attempt_overtake(
                entry_map[behind_did], entry_map[ahead_did], circuit, speed_delta
            )

            if collision:
                for did, label in [
                    (behind_did, entry_map[behind_did].driver.name),
                    (ahead_did,  entry_map[ahead_did].driver.name),
                ]:
                    retired, damage_s = roll_collision_outcome()
                    if retired:
                        states[did].dnf = True
                        states[did].dnf_reason = "Collision"
                        had_dnf = True
                        events.append(f"Lap {lap}: {label} retires after collision!")
                    else:
                        states[did].total_race_time += damage_s
                        events.append(
                            f"Lap {lap}: {label} carries collision damage (+{damage_s}s)"
                        )

            elif success:
                t_ahead  = states[ahead_did].total_race_time
                t_behind = states[behind_did].total_race_time
                mid = (t_ahead + t_behind) / 2.0
                states[behind_did].total_race_time = mid - 0.25
                states[ahead_did].total_race_time  = mid + 0.25
                active[i - 1] = behind_did
                active[i]     = ahead_did
                overtakes_made[behind_did] += 1

                new_pos = i
                if new_pos <= 10:
                    events.append(
                        f"Lap {lap}: {entry_map[behind_did].driver.name} overtakes "
                        f"{entry_map[ahead_did].driver.name} for P{new_pos}"
                    )
            else:
                defenses_made[ahead_did] += 1

        i -= 1
    return had_dnf


# ─── Result assembly ──────────────────────────────────────────────────────────

def _build_race_results(
    states: Dict[str, DriverLapState],
    entry_map: Dict[str, RaceEntry],
    grid_pos_fn: Callable[[str], int],
    fastest_lap_driver: Optional[str],
    fastest_lap_time: float,
) -> List[RaceResult]:
    """Build the ordered List[RaceResult] from settled race state.

    Pure function — constructs and returns a new list, mutates nothing in the
    caller's scope. fastest_lap bonuses are applied to freshly created objects.
    """
    finisher_dids = [did for did, s in states.items() if not s.dnf]
    dnf_dids      = [did for did, s in states.items() if s.dnf]
    finisher_dids.sort(key=lambda d: states[d].total_race_time)

    leader_time = states[finisher_dids[0]].total_race_time if finisher_dids else 0.0
    results: List[RaceResult] = []

    for pos, did in enumerate(finisher_dids, 1):
        entry = entry_map[did]
        gap = round(states[did].total_race_time - leader_time, 3)
        results.append(RaceResult(
            position=pos,
            driver=entry.driver,
            team_id=entry.team_id,
            team_name=entry.team_name,
            team_color=entry.team_color,
            time_gap=gap,
            points=POINTS_SYSTEM.get(pos, 0),
            grid_position=grid_pos_fn(did),
        ))

    for pos, did in enumerate(dnf_dids, len(finisher_dids) + 1):
        entry = entry_map[did]
        results.append(RaceResult(
            position=pos,
            driver=entry.driver,
            team_id=entry.team_id,
            team_name=entry.team_name,
            team_color=entry.team_color,
            time_gap=0.0,
            points=0,
            dnf=True,
            dnf_reason=states[did].dnf_reason,
            grid_position=grid_pos_fn(did),
        ))

    if fastest_lap_driver and fastest_lap_driver in finisher_dids:
        fl_pos = finisher_dids.index(fastest_lap_driver) + 1
        for r in results:
            if r.driver.id == fastest_lap_driver:
                r.fastest_lap = True
                if fl_pos <= 10:
                    r.points += 1
                break

    return results


# ─── Race context ─────────────────────────────────────────────────────────────

@dataclass
class RaceContext:
    """All mutable simulation state for a single race.

    Produced by _setup_race(), mutated lap-by-lap by _run_lap(), then
    consumed by _finalise_results(). Grouping these fields here allows
    each phase to be independently constructed and tested.
    """
    # Static references (set once, never replaced)
    entry_map: Dict[str, RaceEntry]

    # Per-driver mutable state
    states: Dict[str, DriverLapState]
    pit_schedules: Dict[str, Dict[int, str]]
    live_alloc: Dict[str, TyreAllocation]
    prev_positions: Dict[str, int]
    pit_recovery_laps_left: Dict[str, int]

    # Weather state (mutated by step_rain_probability each lap)
    ws: WeatherState

    # Safety Car state (persists across laps)
    sc_state: Optional[str] = None
    sc_laps_remaining: int = 0
    sc_lap_count: int = 0

    # Fastest lap tracking
    fastest_lap_time: float = float("inf")
    fastest_lap_driver: Optional[str] = None

    # Accumulators (appended to during the race)
    events: List[str] = field(default_factory=list)
    weather_summary: List[str] = field(default_factory=list)
    pit_stop_log: List[PitStop] = field(default_factory=list)
    driver_fastest_laps: Dict[str, float] = field(default_factory=dict)
    lap_data: Dict[str, List[DriverLapRecord]] = field(default_factory=dict)
    overtakes_made: Dict[str, int] = field(default_factory=dict)
    defenses_made: Dict[str, int] = field(default_factory=dict)


# ─── Setup ────────────────────────────────────────────────────────────────────

def _setup_race(
    entries: List[RaceEntry],
    circuit,
    weather: str,
    grid: Optional[List[str]],
    strategies: Optional[Dict[str, RaceStrategy]],
    player_allocation: Optional[Dict[str, Dict[str, int]]],
    total_laps: int,
) -> RaceContext:
    """Resolve strategies, initialise driver states, and return a fresh RaceContext.

    Independently callable: pass any list of RaceEntry objects and a circuit to
    get a fully initialised context ready for _run_lap().
    """
    # ── Resolve strategies ────────────────────────────────────────────────────
    resolved_strategies: Dict[str, RaceStrategy] = {}
    for entry in entries:
        did = entry.driver.id
        if strategies and did in strategies:
            resolved_strategies[did] = strategies[did]
        else:
            resolved_strategies[did] = ai_strategy(entry, circuit, weather)

    entry_map: Dict[str, RaceEntry] = {e.driver.id: e for e in entries}

    pit_schedules: Dict[str, Dict[int, str]] = {
        did: build_pit_schedule(strat)
        for did, strat in resolved_strategies.items()
    }

    # ── Driver lap states ─────────────────────────────────────────────────────
    states: Dict[str, DriverLapState] = {}
    for entry in entries:
        did = entry.driver.id
        strat = resolved_strategies[did]
        first_compound = strat.stints[0].compound if strat.stints else "medium"
        gp = _resolve_grid_pos(did, grid)
        states[did] = DriverLapState(
            total_race_time=(gp - 1) * 0.3,
            fuel_load=100.0,
            tyre_compound=first_compound,
            tyre_age=0,
            stint_index=0,
            dnf=False,
            dnf_reason="",
            pit_this_lap=False,
        )

    # ── Tyre allocation (player drivers only) ─────────────────────────────────
    live_alloc: Dict[str, TyreAllocation] = {
        did: TyreAllocation.from_dict(alloc)
        for did, alloc in (player_allocation or {}).items()
    }

    # ── Weather state ─────────────────────────────────────────────────────────
    ws = init_weather_state(weather, circuit, total_laps)

    ctx = RaceContext(
        entry_map=entry_map,
        states=states,
        pit_schedules=pit_schedules,
        live_alloc=live_alloc,
        prev_positions={did: _resolve_grid_pos(did, grid) for did in entry_map},
        pit_recovery_laps_left={did: 0 for did in entry_map},
        ws=ws,
        lap_data={did: [] for did in entry_map},
        overtakes_made={did: 0 for did in entry_map},
        defenses_made={did: 0 for did in entry_map},
    )

    # ── Front arrival announcement ─────────────────────────────────────────────
    if weather == "dry" and ws.front_active:
        _strength_label = {5.5: "light", 10.0: "moderate", 17.0: "heavy"}.get(
            ws.front_rise_rate, "moderate"
        )
        ctx.events.append(
            f"Weather: {_strength_label} rain front expected around lap {ws.front_arrival_lap}"
        )

    return ctx


# ─── Single lap ───────────────────────────────────────────────────────────────

def _run_lap(
    ctx: RaceContext,
    lap: int,
    total_laps: int,
    circuit,
    weather: str,
    player_team_id: Optional[str],
    sc_pit_callback: Optional[Callable],
    weather_callback: Optional[Callable],
) -> None:
    """Simulate one lap, mutating ctx in-place.

    Processes: weather drift, per-driver timing/incidents/pits,
    SC/VSC deployment, SC management, weather callback, AI weather
    pits, overtaking, and lap data recording.

    Independently callable: construct a RaceContext with the desired
    state and call _run_lap() directly in tests.
    """
    lap_times: Dict[str, float] = {}
    lap_snapshots: Dict[str, dict] = {}
    lap_had_incident: bool = False
    pitted_this_lap: set = set()

    # ── Per-lap weather drift ─────────────────────────────────────────────────
    prev_lap_rain_prob, wx_events = step_rain_probability(ctx.ws, lap)
    rain_prob = ctx.ws.rain_prob
    for msg in wx_events:
        ctx.events.append(msg)
        ctx.weather_summary.append(msg.rsplit(" — ", 1)[0] if " — " in msg else msg)

    for did, state in ctx.states.items():
        if state.dnf:
            continue

        entry = ctx.entry_map[did]
        driver = entry.driver
        car = entry.car

        # ── Incident check ────────────────────────────────────────────────────
        dnf_reason = roll_mechanical_dnf(driver, car)
        if dnf_reason:
            state.dnf = True
            state.dnf_reason = dnf_reason
            state.dnf_lap = lap
            lap_had_incident = True
            ctx.events.append(f"Lap {lap}: {driver.name} retires — {state.dnf_reason}")
            continue

        # ── Tyre life & puncture ──────────────────────────────────────────────
        life = adjusted_tyre_life(state.tyre_compound, circuit, car, driver)
        tyre_dnf_reason = roll_tyre_dnf(state.tyre_age, life)
        if tyre_dnf_reason:
            state.dnf = True
            state.dnf_reason = tyre_dnf_reason
            state.dnf_lap = lap
            lap_had_incident = True
            ctx.events.append(f"Lap {lap}: {driver.name} retires — {state.dnf_reason}")
            continue

        # ── Compute lap time ──────────────────────────────────────────────────
        lap_time = _compute_driver_lap_time(
            entry, state, circuit, rain_prob, life, ctx.sc_state, ctx.events, lap
        )
        wear_frac = min(1.0, state.tyre_age / max(1, life))
        lap_times[did] = lap_time
        state.total_race_time += lap_time

        if lap_time < ctx.fastest_lap_time:
            ctx.fastest_lap_time = lap_time
            ctx.fastest_lap_driver = did
        if lap_time < ctx.driver_fastest_laps.get(did, float("inf")):
            ctx.driver_fastest_laps[did] = lap_time

        lap_snapshots[did] = {
            "lap_time": lap_time,
            "compound": state.tyre_compound,
            "tyre_age": state.tyre_age,
            "wear_pct": round(wear_frac * 100, 1),
            "fuel_load": round(state.fuel_load, 1),
            "pitted": False,
            "rain_prob": rain_prob,
        }

        state.tyre_age += 1
        state.fuel_load = max(0.0, state.fuel_load - 100.0 / total_laps)
        state.pit_this_lap = False

        # ── Scheduled pit stop ────────────────────────────────────────────────
        if lap in ctx.pit_schedules.get(did, {}):
            next_cmp = ctx.pit_schedules[did][lap]
            is_player_driver = player_team_id and ctx.entry_map[did].team_id == player_team_id
            if is_player_driver and did in ctx.live_alloc:
                actual_cmp = ctx.live_alloc[did].best_available(next_cmp)
                if actual_cmp != next_cmp:
                    ctx.events.append(
                        f"Lap {lap}: {entry.driver.name} — no {next_cmp} sets left, "
                        f"switching to {actual_cmp}"
                    )
                next_cmp = actual_cmp
            old_cmp = state.tyre_compound
            _execute_pit_stop(
                did, next_cmp, old_cmp, state, entry, circuit, lap,
                ctx.pit_stop_log, ctx.events, pitted_this_lap, ctx.pit_recovery_laps_left,
            )
            if is_player_driver and did in ctx.live_alloc:
                ctx.live_alloc[did].consume(next_cmp)
            state.pit_this_lap = True
            if did in lap_snapshots:
                lap_snapshots[did]["pitted"] = True

    # ── Safety Car / VSC deployment on incident ───────────────────────────────
    if lap_had_incident and ctx.sc_state is None and lap < total_laps - 3:
        deployed = check_safety_car()
        if deployed == "SC":
            ctx.sc_state = "SC"
            ctx.sc_laps_remaining = random.randint(3, 5)
            ctx.sc_lap_count = 0
            ctx.events.append(f"Lap {lap}: SAFETY CAR DEPLOYED")
        elif deployed == "VSC":
            ctx.sc_state = "VSC"
            ctx.sc_laps_remaining = random.randint(3, 5)
            ctx.sc_lap_count = 0
            ctx.events.append(f"Lap {lap}: VIRTUAL SAFETY CAR DEPLOYED")

    # ── Weather-triggered Safety Car ──────────────────────────────────────────
    # Keep elif structure to match original random-call sequence exactly:
    # if the delta branch fires, the aquaplaning branch is NOT evaluated.
    if ctx.sc_state is None and not ctx.ws.weather_sc_fired and lap < total_laps - 3:
        rain_delta_this_lap = rain_prob - prev_lap_rain_prob
        if rain_delta_this_lap > WEATHER_SC_DELTA_THRESHOLD:
            if random.random() < WEATHER_SC_SUDDEN_PROB:
                ctx.sc_state = "SC"
                ctx.sc_laps_remaining = random.randint(3, 5)
                ctx.sc_lap_count = 0
                ctx.ws.weather_sc_fired = True
                ctx.events.append(f"Lap {lap}: SAFETY CAR — sudden heavy rain")
        elif rain_prob > WEATHER_SC_AQUAPLANE_THRESH and prev_lap_rain_prob <= WEATHER_SC_AQUAPLANE_THRESH:
            if random.random() < WEATHER_SC_AQUAPLANE_PROB:
                ctx.sc_state = "SC"
                ctx.sc_laps_remaining = random.randint(3, 5)
                ctx.sc_lap_count = 0
                ctx.ws.weather_sc_fired = True
                ctx.events.append(f"Lap {lap}: SAFETY CAR — aquaplaning risk")

    if ctx.sc_state is not None:
        active_sc = [d for d, s in ctx.states.items() if not s.dnf]
        active_sc.sort(key=lambda d: ctx.states[d].total_race_time)

        # ── Gap compression ───────────────────────────────────────────────────
        if ctx.sc_state == "SC":
            if ctx.sc_lap_count == 0:
                if active_sc:
                    prev_t = ctx.states[active_sc[0]].total_race_time
                    for _did in active_sc[1:]:
                        gap = ctx.states[_did].total_race_time - prev_t
                        new_gap = max(0.15, gap * 0.50)
                        ctx.states[_did].total_race_time = prev_t + new_gap
                        prev_t = ctx.states[_did].total_race_time
            else:
                if active_sc:
                    prev_t = ctx.states[active_sc[0]].total_race_time
                    for _did in active_sc[1:]:
                        gap = ctx.states[_did].total_race_time - prev_t
                        ctx.states[_did].total_race_time = prev_t + min(gap, 2.0)
                        prev_t = ctx.states[_did].total_race_time
        elif ctx.sc_state == "VSC" and ctx.sc_lap_count == 0:
            if active_sc:
                prev_t = ctx.states[active_sc[0]].total_race_time
                for _did in active_sc[1:]:
                    gap = ctx.states[_did].total_race_time - prev_t
                    new_gap = max(0.15, gap * 0.75)
                    ctx.states[_did].total_race_time = prev_t + new_gap
                    prev_t = ctx.states[_did].total_race_time

        # ── SC/VSC pit window ─────────────────────────────────────────────────
        if ctx.sc_state == "SC":
            ai_pit_prob = [0.70, 0.25, 0.10][min(ctx.sc_lap_count, 2)]
        else:
            ai_pit_prob = [0.20, 0.10][min(ctx.sc_lap_count, 1)]

        sc_decisions: Dict[str, Optional[RaceStrategy]] = {}
        if sc_pit_callback and player_team_id and ctx.sc_lap_count == 0:
            player_infos = []
            pos_lookup = {did: pos + 1 for pos, did in enumerate(active_sc)}
            sc_forecast = generate_weather_forecast(
                rain_prob, ctx.ws.rain_decreasing, ctx.ws.front_rise_rate,
                ctx.ws.front_decay_rate, ctx.ws.front_arrival_lap, lap,
            )
            sc_trend = get_rain_trend(ctx.ws, lap)
            for _did, _state in ctx.states.items():
                if _state.dnf:
                    continue
                if ctx.entry_map[_did].team_id == player_team_id:
                    pos_idx = pos_lookup.get(_did, 1) - 1
                    gap_ahead = (
                        round(
                            ctx.states[_did].total_race_time
                            - ctx.states[active_sc[pos_idx - 1]].total_race_time, 2
                        )
                        if pos_idx > 0 else None
                    )
                    gap_behind = (
                        round(
                            ctx.states[active_sc[pos_idx + 1]].total_race_time
                            - ctx.states[_did].total_race_time, 2
                        )
                        if pos_idx < len(active_sc) - 1 else None
                    )
                    player_infos.append({
                        "id": _did,
                        "name": ctx.entry_map[_did].driver.name,
                        "compound": _state.tyre_compound,
                        "tyre_age": _state.tyre_age,
                        "position": pos_lookup.get(_did, 0),
                        "circuit_wear": circuit.tire_wear,
                        "laps_remaining": total_laps - lap,
                        "driver_obj": ctx.entry_map[_did].driver,
                        "car_obj": ctx.entry_map[_did].car,
                        "circuit_obj": circuit,
                        "weather": weather,
                        "gap_ahead": gap_ahead,
                        "gap_behind": gap_behind,
                        "sc_type": ctx.sc_state,
                        "sc_laps_remaining": ctx.sc_laps_remaining,
                        "rain_prob": rain_prob,
                        "forecast": sc_forecast,
                        "trend": sc_trend,
                        "allocation": dict(ctx.live_alloc[_did].sets) if _did in ctx.live_alloc else {},
                    })
            if player_infos:
                sc_decisions = sc_pit_callback(lap, total_laps, player_infos)

        pitted_on_sc: set = set()
        for _did, _state in ctx.states.items():
            if _state.dnf:
                continue

            is_player = player_team_id and ctx.entry_map[_did].team_id == player_team_id

            if is_player:
                sc_strat = sc_decisions.get(_did)
                should_pit = sc_strat is not None
            elif lap > 5:
                should_pit = random.random() < ai_pit_prob
            else:
                should_pit = False

            if should_pit:
                _entry = ctx.entry_map[_did]
                if is_player and sc_strat is not None:
                    next_cmp = sc_strat.stints[0].compound.lower()
                    if _did in ctx.live_alloc:
                        actual_cmp = ctx.live_alloc[_did].best_available(next_cmp)
                        if actual_cmp != next_cmp:
                            ctx.events.append(
                                f"Lap {lap}: {_entry.driver.name} — no {next_cmp} sets left "
                                f"under SC, switching to {actual_cmp}"
                            )
                        next_cmp = actual_cmp
                    ctx.pit_schedules[_did] = {}
                    stint_lap = lap
                    for i, stint in enumerate(sc_strat.stints[:-1]):
                        stint_lap += stint.laps
                        ctx.pit_schedules[_did][stint_lap] = sc_strat.stints[i + 1].compound.lower()
                else:
                    next_cmp = "medium"
                    future_pits = {fl: c for fl, c in ctx.pit_schedules.get(_did, {}).items() if fl > lap}
                    if future_pits:
                        next_fl = min(future_pits)
                        next_cmp = future_pits[next_fl]
                        del ctx.pit_schedules[_did][next_fl]
                _execute_pit_stop(
                    _did, next_cmp, _state.tyre_compound, _state, _entry, circuit, lap,
                    ctx.pit_stop_log, ctx.events, pitted_this_lap, ctx.pit_recovery_laps_left,
                    event_suffix=f" under {ctx.sc_state}",
                )
                if is_player and _did in ctx.live_alloc:
                    ctx.live_alloc[_did].consume(next_cmp)
                pitted_on_sc.add(_did)
                if _did in lap_snapshots:
                    lap_snapshots[_did]["pitted"] = True

        ctx.sc_laps_remaining -= 1
        ctx.sc_lap_count += 1
        if ctx.sc_laps_remaining <= 0:
            ctx.events.append(f"Lap {lap}: Racing resumes")
            ctx.sc_state = None
            ctx.sc_lap_count = 0

    # ── Weather callback ──────────────────────────────────────────────────────
    if weather_callback and ctx.sc_state is None and player_team_id:
        threshold = detect_weather_threshold(ctx.ws, rain_prob, prev_lap_rain_prob)
        if threshold:
            ctx.ws.thresholds_crossed[threshold] = True

            forecast = generate_weather_forecast(
                rain_prob, ctx.ws.rain_decreasing, ctx.ws.front_rise_rate,
                ctx.ws.front_decay_rate, ctx.ws.front_arrival_lap, lap,
            )
            trend = get_rain_trend(ctx.ws, lap)

            _active_sorted = [d for d, s in ctx.states.items() if not s.dnf]
            _active_sorted.sort(key=lambda d: ctx.states[d].total_race_time)
            _pos_lookup = {d: p + 1 for p, d in enumerate(_active_sorted)}

            player_infos_w: list = []
            for _did, _state in ctx.states.items():
                if _state.dnf:
                    continue
                if ctx.entry_map[_did].team_id == player_team_id:
                    player_infos_w.append({
                        "id": _did,
                        "name": ctx.entry_map[_did].driver.name,
                        "compound": _state.tyre_compound,
                        "tyre_age": _state.tyre_age,
                        "position": _pos_lookup.get(_did, 0),
                        "circuit_wear": circuit.tire_wear,
                        "laps_remaining": total_laps - lap,
                        "driver_obj": ctx.entry_map[_did].driver,
                        "car_obj": ctx.entry_map[_did].car,
                        "circuit_obj": circuit,
                        "allocation": dict(ctx.live_alloc[_did].sets) if _did in ctx.live_alloc else {},
                    })

            if player_infos_w:
                weather_meta: dict = {}
                decisions_w = weather_callback(
                    lap, total_laps, threshold, player_infos_w,
                    rain_prob, forecast, trend, weather_meta,
                )

                if threshold == "warning":
                    if weather_meta.get("ignored_warning"):
                        ctx.ws.player_ignored_warning = True
                    elif all(v is None for v in decisions_w.values()):
                        ctx.ws.thresholds_crossed["warning"] = False
                        ctx.ws.warning_cooldown = 3

                for _did, _state in ctx.states.items():
                    if _state.dnf:
                        continue
                    if ctx.entry_map[_did].team_id != player_team_id:
                        continue
                    w_strat = decisions_w.get(_did)
                    if w_strat is not None:
                        _entry = ctx.entry_map[_did]
                        next_cmp = w_strat.stints[0].compound.lower()
                        if _did in ctx.live_alloc:
                            actual_cmp = ctx.live_alloc[_did].best_available(next_cmp)
                            if actual_cmp != next_cmp:
                                ctx.events.append(
                                    f"Lap {lap}: {_entry.driver.name} — no {next_cmp} sets "
                                    f"left for weather, switching to {actual_cmp}"
                                )
                            next_cmp = actual_cmp
                        ctx.pit_schedules[_did] = {}
                        stint_lap = lap
                        for _i, _stint in enumerate(w_strat.stints[:-1]):
                            stint_lap += _stint.laps
                            ctx.pit_schedules[_did][stint_lap] = w_strat.stints[_i + 1].compound.lower()
                        _execute_pit_stop(
                            _did, next_cmp, _state.tyre_compound, _state, _entry, circuit, lap,
                            ctx.pit_stop_log, ctx.events, pitted_this_lap, ctx.pit_recovery_laps_left,
                            event_suffix=" for weather",
                        )
                        if _did in ctx.live_alloc:
                            ctx.live_alloc[_did].consume(next_cmp)
                        if _did in lap_snapshots:
                            lap_snapshots[_did]["pitted"] = True

    # ── AI mid-race weather pit ───────────────────────────────────────────────
    if rain_prob >= 65 and prev_lap_rain_prob < 65:
        for _did, _state in ctx.states.items():
            if _state.dnf:
                continue
            if player_team_id and ctx.entry_map[_did].team_id == player_team_id:
                continue
            if _state.tyre_compound in ("intermediate", "wet"):
                continue
            laps_rem = total_laps - lap
            if ai_should_pit_for_weather(_state, ctx.entry_map[_did], circuit, rain_prob, laps_rem):
                _entry = ctx.entry_map[_did]
                next_cmp = "intermediate" if rain_prob < 82 else "wet"
                old_cmp = _state.tyre_compound
                _execute_pit_stop(
                    _did, next_cmp, old_cmp, _state, _entry, circuit, lap,
                    ctx.pit_stop_log, ctx.events, pitted_this_lap, ctx.pit_recovery_laps_left,
                    event_suffix=" for weather",
                )
                if _did in lap_snapshots:
                    lap_snapshots[_did]["pitted"] = True
                ctx.pit_schedules[_did] = {}

    # ── Overtaking pass ───────────────────────────────────────────────────────
    active = [did for did, s in ctx.states.items() if not s.dnf]
    active.sort(key=lambda d: ctx.states[d].total_race_time)

    if ctx.sc_state is None:
        if _process_overtaking_pass(
            active, ctx.states, ctx.entry_map, lap_times, circuit, lap,
            ctx.overtakes_made, ctx.defenses_made, ctx.events,
        ):
            lap_had_incident = True

    # ── Record lap data ───────────────────────────────────────────────────────
    active.sort(key=lambda d: ctx.states[d].total_race_time)

    prev_pos_to_driver = {pos: d for d, pos in ctx.prev_positions.items()}
    if ctx.sc_state is None:
        for pos_idx, did in enumerate(active, 1):
            curr_pos = pos_idx
            prev_pos = ctx.prev_positions.get(did)
            if ctx.pit_recovery_laps_left[did] > 0:
                ctx.pit_recovery_laps_left[did] -= 1
            if prev_pos is None:
                continue
            if lap_snapshots.get(did, {}).get("pitted", False):
                continue
            if ctx.pit_recovery_laps_left[did] > 0:
                continue
            positions_gained = prev_pos - curr_pos
            if positions_gained > 0:
                valid_gains = sum(
                    1 for p in range(curr_pos, prev_pos)
                    if prev_pos_to_driver.get(p) not in pitted_this_lap
                )
                if valid_gains > 0:
                    ctx.overtakes_made[did] += valid_gains
    else:
        for did in active:
            if ctx.pit_recovery_laps_left[did] > 0:
                ctx.pit_recovery_laps_left[did] -= 1

    for pos_idx, did in enumerate(active, 1):
        ctx.prev_positions[did] = pos_idx

    for pos_idx, did in enumerate(active, 1):
        if did in lap_snapshots:
            s = lap_snapshots[did]
            ctx.lap_data[did].append(DriverLapRecord(
                lap=lap,
                lap_time=s["lap_time"],
                compound=s["compound"],
                tyre_age=s["tyre_age"],
                wear_pct=s["wear_pct"],
                fuel_load=s["fuel_load"],
                position=pos_idx,
                pitted=s["pitted"],
                rain_prob=s.get("rain_prob", 0.0),
                sc_active=ctx.sc_state,
            ))
    for did, state in ctx.states.items():
        if state.dnf and state.dnf_lap == lap and did not in lap_snapshots:
            ctx.lap_data[did].append(DriverLapRecord(
                lap=lap, lap_time=0.0, compound=state.tyre_compound,
                tyre_age=state.tyre_age, wear_pct=0.0, fuel_load=0.0,
                position=0, dnf=True,
            ))


# ─── Result finalisation ──────────────────────────────────────────────────────

def _finalise_results(
    ctx: RaceContext,
    grid_pos_fn: Callable[[str], int],
) -> List[RaceResult]:
    """Build the final ordered List[RaceResult] from ctx.

    Thin wrapper around _build_race_results; independently callable in tests
    by constructing a RaceContext with settled states.
    """
    return _build_race_results(
        ctx.states, ctx.entry_map, grid_pos_fn,
        ctx.fastest_lap_driver, ctx.fastest_lap_time,
    )


# ─── Race simulation ──────────────────────────────────────────────────────────

def simulate_race(
    entries: List[RaceEntry],
    circuit,
    weather: str = "dry",
    grid: Optional[List[str]] = None,
    strategies: Optional[Dict[str, RaceStrategy]] = None,
    player_team_id: Optional[str] = None,
    sc_pit_callback: Optional[Callable] = None,
    weather_callback: Optional[Callable] = None,
    player_allocation: Optional[Dict[str, Dict[str, int]]] = None,
) -> RaceReport:
    """Simulate a full race lap-by-lap and return a RaceReport.

    Callbacks are optional — pass None for both to run without any UI
    interaction (useful for testing and AI-only races).
    """
    total_laps = race_laps(circuit)

    ctx = _setup_race(
        entries, circuit, weather, grid, strategies, player_allocation, total_laps,
    )

    for lap in range(1, total_laps + 1):
        _run_lap(
            ctx, lap, total_laps, circuit, weather,
            player_team_id, sc_pit_callback, weather_callback,
        )

    results = _finalise_results(
        ctx, lambda did: _resolve_grid_pos(did, grid),
    )

    return RaceReport(
        results=results,
        events=ctx.events,
        pit_stops=ctx.pit_stop_log,
        fastest_lap_time=ctx.fastest_lap_time if ctx.fastest_lap_time < float("inf") else 0.0,
        driver_fastest_laps=ctx.driver_fastest_laps,
        lap_data=ctx.lap_data,
        overtakes_made=ctx.overtakes_made,
        defenses_made=ctx.defenses_made,
        peak_rain_prob=ctx.ws.peak_rain_prob,
        weather_summary=ctx.weather_summary,
    )
