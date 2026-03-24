"""Race simulation orchestrator.
# Functions: _execute_pit_stop:31  simulate_race:73
"""
from __future__ import annotations

import random
from typing import Callable, Dict, List, Optional

from engine.race_models import (
    RaceEntry, RaceResult, DriverLapState, DriverLapRecord,
    PitStop, RaceReport, POINTS_SYSTEM, DNF_REASONS,
    OVERTAKE_THRESHOLD, BATTLE_RANGE_S, SC_PROBABILITY, VSC_PROBABILITY,
)
from engine.weather import (
    _check_safety_car, _weather_compound_delta,
    _effective_wet_weight, _generate_weather_forecast,
)
from engine.race_physics import _base_lap_time, _attempt_overtake
from engine.tyres import (
    TYRE_COMPOUNDS, COMPOUND_PACE_DELTA, TYRE_LIFE_BASE,
    TyreStint, RaceStrategy,
    race_laps, adjusted_tyre_life, ai_strategy, suggest_strategies,
    _build_pit_schedule, _tyre_score,
)
from engine.qualifying import QualiResult, simulate_qualifying

# Re-export everything callers may import from this module
from engine.race_models import *  # noqa: F401, F403


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


# ─── Allocation helper ────────────────────────────────────────────────────────

def _best_available_cmp(live_alloc: dict, did: str, preferred: str) -> str:
    """Return preferred compound if sets remain, else compound with most sets."""
    alloc = live_alloc.get(did, {})
    if alloc.get(preferred, 0) > 0:
        return preferred
    return max(alloc, key=lambda c: alloc[c], default=preferred)


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
    """Simulate a full race lap-by-lap and return a RaceReport."""
    total_laps = race_laps(circuit)
    events: List[str] = []

    # Resolve strategies for every driver
    resolved_strategies: Dict[str, RaceStrategy] = {}
    for entry in entries:
        did = entry.driver.id
        if strategies and did in strategies:
            resolved_strategies[did] = strategies[did]
        else:
            resolved_strategies[did] = ai_strategy(entry, circuit, weather)

    entry_map: Dict[str, RaceEntry] = {e.driver.id: e for e in entries}

    pit_schedules: Dict[str, Dict[int, str]] = {
        did: _build_pit_schedule(strat)
        for did, strat in resolved_strategies.items()
    }

    def grid_pos(did: str) -> int:
        if grid and did in grid:
            return grid.index(did) + 1
        return 10

    states: Dict[str, DriverLapState] = {}
    for entry in entries:
        did = entry.driver.id
        strat = resolved_strategies[did]
        first_compound = strat.stints[0].compound if strat.stints else "medium"
        gp = grid_pos(did)
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

    live_alloc: Dict[str, Dict[str, int]] = {
        did: dict(alloc) for did, alloc in (player_allocation or {}).items()
    }

    fastest_lap_time: float = float("inf")
    fastest_lap_driver: Optional[str] = None
    driver_fastest_laps: Dict[str, float] = {}
    pit_stop_log: List[PitStop] = []
    lap_data: Dict[str, List[DriverLapRecord]] = {did: [] for did in entry_map}
    overtakes_made: Dict[str, int] = {did: 0 for did in entry_map}
    defenses_made: Dict[str, int] = {did: 0 for did in entry_map}
    prev_positions: Dict[str, int] = {did: grid_pos(did) for did in entry_map}
    pit_recovery_laps_left: Dict[str, int] = {did: 0 for did in entry_map}

    # ── Safety Car state ──────────────────────────────────────────────────────
    sc_state: Optional[str] = None
    sc_laps_remaining: int = 0
    sc_lap_count: int = 0

    # ── Weather state ─────────────────────────────────────────────────────────
    rain_prob: float = 85.0 if weather == "wet" else 0.0
    front_active: bool = False
    front_arrival_lap: int = 0
    front_rise_rate: float = 0.0
    front_decay_rate: float = 0.0
    peak_duration: int = 0
    laps_above_peak: int = 0
    rain_decreasing: bool = False
    peak_rain_prob: float = rain_prob
    weather_summary: List[str] = []
    episode_below_60_count: int = 0
    thresholds_crossed: dict = {"warning": False, "damp": False, "wet": False, "drying": False}
    player_ignored_warning: bool = False
    weather_sc_fired: bool = False
    warning_cooldown: int = 0

    if weather == "dry" and random.random() * 100 < circuit.weather_chance:
        earliest = max(3, int(total_laps * 0.15))
        latest   = max(earliest + 1, min(total_laps - 5, int(total_laps * 0.85)))
        front_arrival_lap = random.randint(earliest, latest)
        strength = random.choices(["light", "moderate", "heavy"], weights=[40, 40, 20])[0]
        rise_rates   = {"light": 5.5, "moderate": 10.0, "heavy": 17.0}
        decay_rates  = {"light": 5.0, "moderate": 7.0,  "heavy": 6.0}
        peak_durations = {"light": 5, "moderate": 8,  "heavy": 12}
        front_rise_rate  = rise_rates[strength]
        front_decay_rate = decay_rates[strength]
        peak_duration    = peak_durations[strength]
        front_active = True
        events.append(f"Weather: {strength} rain front expected around lap {front_arrival_lap}")

    if weather == "wet":
        if random.random() < 0.50:
            dry_start = max(3, total_laps // 4)
            dry_end   = max(dry_start + 1, total_laps - 5)
            front_arrival_lap = random.randint(dry_start, dry_end)
            front_decay_rate  = random.uniform(4.0, 8.0)
            rain_decreasing   = True
            front_active      = True

    # ── Lap-by-lap simulation ─────────────────────────────────────────────────
    for lap in range(1, total_laps + 1):
        lap_times: Dict[str, float] = {}
        lap_snapshots: Dict[str, dict] = {}
        lap_had_incident: bool = False
        pitted_this_lap: set = set()

        # ── Per-lap weather drift ─────────────────────────────────────────────
        prev_lap_rain_prob = rain_prob
        if warning_cooldown > 0:
            warning_cooldown -= 1

        if front_active:
            if not rain_decreasing and lap >= front_arrival_lap:
                delta = max(0.0, random.gauss(front_rise_rate, front_rise_rate * 0.35))
                rain_prob = min(100.0, rain_prob + delta)
                if rain_prob > peak_rain_prob:
                    peak_rain_prob = rain_prob
                if rain_prob >= 80:
                    laps_above_peak += 1
                    if laps_above_peak >= peak_duration:
                        rain_decreasing = True
                else:
                    laps_above_peak = 0
            elif rain_decreasing:
                if not (weather == "wet" and lap < front_arrival_lap):
                    delta = max(0.0, random.gauss(front_decay_rate, front_decay_rate * 0.3))
                    rain_prob = max(0.0, rain_prob - delta)

        if rain_prob < 60:
            episode_below_60_count += 1
            if episode_below_60_count >= 3 and any(thresholds_crossed.values()):
                thresholds_crossed = {k: False for k in thresholds_crossed}
                player_ignored_warning = False
                weather_sc_fired = False
        else:
            episode_below_60_count = 0

        if front_active:
            if rain_prob >= 55 and prev_lap_rain_prob < 55:
                events.append(f"Lap {lap}: Weather front approaching — rain possible")
                weather_summary.append(f"Lap {lap}: Weather front approaching")
            elif rain_prob >= 65 and prev_lap_rain_prob < 65:
                events.append(f"Lap {lap}: Track turning damp — conditions deteriorating")
                weather_summary.append(f"Lap {lap}: Track turning damp")
            elif rain_prob >= 92 and prev_lap_rain_prob < 92:
                events.append(f"Lap {lap}: HEAVY RAIN — standing water on track")
                weather_summary.append(f"Lap {lap}: HEAVY RAIN")
            if rain_decreasing:
                if rain_prob < 70 and prev_lap_rain_prob >= 70:
                    events.append(f"Lap {lap}: Rain easing — conditions improving")
                    weather_summary.append(f"Lap {lap}: Rain easing")
                elif rain_prob < 55 and prev_lap_rain_prob >= 55:
                    events.append(f"Lap {lap}: Track drying — slick tyres becoming viable")
                    weather_summary.append(f"Lap {lap}: Track drying")

        for did, state in states.items():
            if state.dnf:
                continue

            entry = entry_map[did]
            driver = entry.driver
            car = entry.car

            # ── Incident check ────────────────────────────────────────────────
            mech_prob = (100 - car.reliability) / 100 * 0.0015
            ctrl_prob = (100 - driver.car_control) / 100 * 0.0008
            if random.random() < mech_prob + ctrl_prob:
                state.dnf = True
                state.dnf_reason = random.choice(DNF_REASONS)
                state.dnf_lap = lap
                lap_had_incident = True
                events.append(f"Lap {lap}: {driver.name} retires — {state.dnf_reason}")
                continue

            # ── Tyre life & puncture ──────────────────────────────────────────
            life = adjusted_tyre_life(state.tyre_compound, circuit, car, driver)
            if state.tyre_age > life:
                overrun_laps = state.tyre_age - life
                puncture_prob = min(0.05, overrun_laps * 0.008)
                if random.random() < puncture_prob:
                    state.dnf = True
                    state.dnf_reason = random.choice(["Tyre failure", "Puncture"])
                    state.dnf_lap = lap
                    lap_had_incident = True
                    events.append(f"Lap {lap}: {driver.name} retires — {state.dnf_reason}")
                    continue

            # ── Compute lap time ──────────────────────────────────────────────
            base = _base_lap_time(entry, circuit, rain_prob)
            fuel_delta = (state.fuel_load / 100.0) * 2.8
            wear_frac = min(1.0, state.tyre_age / max(1, life))
            compound_delta = _weather_compound_delta(state.tyre_compound, rain_prob)
            tyre_delta = wear_frac ** 2 * 4.5 + compound_delta

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

            lap_times[did] = lap_time
            state.total_race_time += lap_time

            if lap_time < fastest_lap_time:
                fastest_lap_time = lap_time
                fastest_lap_driver = did
            if lap_time < driver_fastest_laps.get(did, float("inf")):
                driver_fastest_laps[did] = lap_time

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

            # ── Scheduled pit stop ────────────────────────────────────────────
            if lap in pit_schedules.get(did, {}):
                next_cmp = pit_schedules[did][lap]
                is_player_driver = player_team_id and entry_map[did].team_id == player_team_id
                if is_player_driver and live_alloc.get(did):
                    actual_cmp = _best_available_cmp(live_alloc, did, next_cmp)
                    if actual_cmp != next_cmp:
                        events.append(f"Lap {lap}: {entry.driver.name} — no {next_cmp} sets left, switching to {actual_cmp}")
                    next_cmp = actual_cmp
                old_cmp = state.tyre_compound
                _execute_pit_stop(
                    did, next_cmp, old_cmp, state, entry, circuit, lap,
                    pit_stop_log, events, pitted_this_lap, pit_recovery_laps_left,
                )
                if is_player_driver and did in live_alloc:
                    live_alloc[did][next_cmp] = max(0, live_alloc[did].get(next_cmp, 0) - 1)
                state.pit_this_lap = True
                if did in lap_snapshots:
                    lap_snapshots[did]["pitted"] = True

        # ── Safety Car / VSC deployment ───────────────────────────────────────
        if lap_had_incident and sc_state is None and lap < total_laps - 3:
            deployed = _check_safety_car()
            if deployed == "SC":
                sc_state = "SC"
                sc_laps_remaining = random.randint(3, 5)
                sc_lap_count = 0
                events.append(f"Lap {lap}: SAFETY CAR DEPLOYED")
            elif deployed == "VSC":
                sc_state = "VSC"
                sc_laps_remaining = random.randint(3, 5)
                sc_lap_count = 0
                events.append(f"Lap {lap}: VIRTUAL SAFETY CAR DEPLOYED")

        # ── Weather-triggered Safety Car ──────────────────────────────────────
        if sc_state is None and not weather_sc_fired and lap < total_laps - 3:
            rain_delta_this_lap = rain_prob - prev_lap_rain_prob
            if rain_delta_this_lap > 15:
                if random.random() < 0.30:
                    sc_state = "SC"
                    sc_laps_remaining = random.randint(3, 5)
                    sc_lap_count = 0
                    weather_sc_fired = True
                    events.append(f"Lap {lap}: SAFETY CAR — sudden heavy rain")
            elif rain_prob > 90 and prev_lap_rain_prob <= 90:
                if random.random() < 0.35:
                    sc_state = "SC"
                    sc_laps_remaining = random.randint(3, 5)
                    sc_lap_count = 0
                    weather_sc_fired = True
                    events.append(f"Lap {lap}: SAFETY CAR — aquaplaning risk")

        if sc_state is not None:
            active_sc = [d for d, s in states.items() if not s.dnf]
            active_sc.sort(key=lambda d: states[d].total_race_time)

            # ── Gap compression ───────────────────────────────────────────────
            if sc_state == "SC":
                if sc_lap_count == 0:
                    if active_sc:
                        prev_t = states[active_sc[0]].total_race_time
                        for _did in active_sc[1:]:
                            gap = states[_did].total_race_time - prev_t
                            new_gap = max(0.15, gap * 0.50)
                            states[_did].total_race_time = prev_t + new_gap
                            prev_t = states[_did].total_race_time
                else:
                    if active_sc:
                        prev_t = states[active_sc[0]].total_race_time
                        for _did in active_sc[1:]:
                            gap = states[_did].total_race_time - prev_t
                            states[_did].total_race_time = prev_t + min(gap, 2.0)
                            prev_t = states[_did].total_race_time
            elif sc_state == "VSC" and sc_lap_count == 0:
                if active_sc:
                    prev_t = states[active_sc[0]].total_race_time
                    for _did in active_sc[1:]:
                        gap = states[_did].total_race_time - prev_t
                        new_gap = max(0.15, gap * 0.75)
                        states[_did].total_race_time = prev_t + new_gap
                        prev_t = states[_did].total_race_time

            # ── SC/VSC pit window ─────────────────────────────────────────────
            if sc_state == "SC":
                ai_pit_prob = [0.70, 0.25, 0.10][min(sc_lap_count, 2)]
            else:
                ai_pit_prob = [0.20, 0.10][min(sc_lap_count, 1)]

            sc_decisions: Dict[str, Optional[RaceStrategy]] = {}
            if sc_pit_callback and player_team_id and sc_lap_count == 0:
                player_infos = []
                pos_lookup = {did: pos + 1 for pos, did in enumerate(active_sc)}
                sc_forecast = _generate_weather_forecast(
                    rain_prob, rain_decreasing, front_rise_rate, front_decay_rate,
                    front_arrival_lap, lap,
                )
                sc_trend = "falling" if rain_decreasing else (
                    "rising" if (not rain_decreasing and lap >= front_arrival_lap and front_rise_rate > 0)
                    else "stable"
                )
                for _did, _state in states.items():
                    if _state.dnf:
                        continue
                    if entry_map[_did].team_id == player_team_id:
                        pos_idx = pos_lookup.get(_did, 1) - 1
                        gap_ahead = (
                            round(states[_did].total_race_time - states[active_sc[pos_idx - 1]].total_race_time, 2)
                            if pos_idx > 0 else None
                        )
                        gap_behind = (
                            round(states[active_sc[pos_idx + 1]].total_race_time - states[_did].total_race_time, 2)
                            if pos_idx < len(active_sc) - 1 else None
                        )
                        player_infos.append({
                            "id": _did,
                            "name": entry_map[_did].driver.name,
                            "compound": _state.tyre_compound,
                            "tyre_age": _state.tyre_age,
                            "position": pos_lookup.get(_did, 0),
                            "circuit_wear": circuit.tire_wear,
                            "laps_remaining": total_laps - lap,
                            "driver_obj": entry_map[_did].driver,
                            "car_obj": entry_map[_did].car,
                            "circuit_obj": circuit,
                            "weather": weather,
                            "gap_ahead": gap_ahead,
                            "gap_behind": gap_behind,
                            "sc_type": sc_state,
                            "sc_laps_remaining": sc_laps_remaining,
                            "rain_prob": rain_prob,
                            "forecast": sc_forecast,
                            "trend": sc_trend,
                            "allocation": dict(live_alloc.get(_did, {})),
                        })
                if player_infos:
                    sc_decisions = sc_pit_callback(lap, total_laps, player_infos)

            pitted_on_sc: set = set()
            for _did, _state in states.items():
                if _state.dnf:
                    continue

                is_player = player_team_id and entry_map[_did].team_id == player_team_id

                if is_player:
                    sc_strat = sc_decisions.get(_did)
                    should_pit = sc_strat is not None
                elif lap > 5:
                    should_pit = random.random() < ai_pit_prob
                else:
                    should_pit = False

                if should_pit:
                    _entry = entry_map[_did]
                    if is_player and sc_strat is not None:
                        next_cmp = sc_strat.stints[0].compound.lower()
                        if live_alloc.get(_did):
                            actual_cmp = _best_available_cmp(live_alloc, _did, next_cmp)
                            if actual_cmp != next_cmp:
                                events.append(f"Lap {lap}: {_entry.driver.name} — no {next_cmp} sets left under SC, switching to {actual_cmp}")
                            next_cmp = actual_cmp
                        pit_schedules[_did] = {}
                        stint_lap = lap
                        for i, stint in enumerate(sc_strat.stints[:-1]):
                            stint_lap += stint.laps
                            pit_schedules[_did][stint_lap] = sc_strat.stints[i + 1].compound.lower()
                    else:
                        next_cmp = "medium"
                        future_pits = {fl: c for fl, c in pit_schedules.get(_did, {}).items() if fl > lap}
                        if future_pits:
                            next_fl = min(future_pits)
                            next_cmp = future_pits[next_fl]
                            del pit_schedules[_did][next_fl]
                    _execute_pit_stop(
                        _did, next_cmp, _state.tyre_compound, _state, _entry, circuit, lap,
                        pit_stop_log, events, pitted_this_lap, pit_recovery_laps_left,
                        event_suffix=f" under {sc_state}",
                    )
                    if is_player and _did in live_alloc:
                        live_alloc[_did][next_cmp] = max(0, live_alloc[_did].get(next_cmp, 0) - 1)
                    pitted_on_sc.add(_did)
                    if _did in lap_snapshots:
                        lap_snapshots[_did]["pitted"] = True

            sc_laps_remaining -= 1
            sc_lap_count += 1
            if sc_laps_remaining <= 0:
                events.append(f"Lap {lap}: Racing resumes")
                sc_state = None
                sc_lap_count = 0

        # ── Weather callback ──────────────────────────────────────────────────
        if weather_callback and sc_state is None and player_team_id:
            threshold = None

            if rain_prob >= 92 and not thresholds_crossed["wet"]:
                threshold = "wet"
                thresholds_crossed["wet"] = True
            elif rain_prob >= 65 and not thresholds_crossed["damp"] and not thresholds_crossed["wet"]:
                threshold = "damp"
                thresholds_crossed["damp"] = True
            elif (rain_prob >= 55 and not player_ignored_warning
                  and not thresholds_crossed["warning"] and warning_cooldown == 0):
                threshold = "warning"
                thresholds_crossed["warning"] = True
            elif (rain_decreasing and rain_prob < 65 and prev_lap_rain_prob >= 65
                  and peak_rain_prob > 70 and not thresholds_crossed["drying"]):
                threshold = "drying"
                thresholds_crossed["drying"] = True

            if threshold:
                forecast = _generate_weather_forecast(
                    rain_prob, rain_decreasing, front_rise_rate, front_decay_rate,
                    front_arrival_lap, lap,
                )
                trend = "falling" if rain_decreasing else ("rising" if front_active else "stable")

                _active_sorted = [d for d, s in states.items() if not s.dnf]
                _active_sorted.sort(key=lambda d: states[d].total_race_time)
                _pos_lookup = {d: p + 1 for p, d in enumerate(_active_sorted)}

                player_infos_w: list = []
                for _did, _state in states.items():
                    if _state.dnf:
                        continue
                    if entry_map[_did].team_id == player_team_id:
                        player_infos_w.append({
                            "id": _did,
                            "name": entry_map[_did].driver.name,
                            "compound": _state.tyre_compound,
                            "tyre_age": _state.tyre_age,
                            "position": _pos_lookup.get(_did, 0),
                            "circuit_wear": circuit.tire_wear,
                            "laps_remaining": total_laps - lap,
                            "driver_obj": entry_map[_did].driver,
                            "car_obj": entry_map[_did].car,
                            "circuit_obj": circuit,
                            "allocation": dict(live_alloc.get(_did, {})),
                        })

                if player_infos_w:
                    weather_meta: dict = {}
                    decisions_w = weather_callback(
                        lap, total_laps, threshold, player_infos_w,
                        rain_prob, forecast, trend, weather_meta,
                    )

                    if threshold == "warning":
                        if weather_meta.get("ignored_warning"):
                            player_ignored_warning = True
                        elif all(v is None for v in decisions_w.values()):
                            thresholds_crossed["warning"] = False
                            warning_cooldown = 3

                    for _did, _state in states.items():
                        if _state.dnf:
                            continue
                        if entry_map[_did].team_id != player_team_id:
                            continue
                        w_strat = decisions_w.get(_did)
                        if w_strat is not None:
                            _entry = entry_map[_did]
                            next_cmp = w_strat.stints[0].compound.lower()
                            if live_alloc.get(_did):
                                actual_cmp = _best_available_cmp(live_alloc, _did, next_cmp)
                                if actual_cmp != next_cmp:
                                    events.append(f"Lap {lap}: {_entry.driver.name} — no {next_cmp} sets left for weather, switching to {actual_cmp}")
                                next_cmp = actual_cmp
                            pit_schedules[_did] = {}
                            stint_lap = lap
                            for _i, _stint in enumerate(w_strat.stints[:-1]):
                                stint_lap += _stint.laps
                                pit_schedules[_did][stint_lap] = w_strat.stints[_i + 1].compound.lower()
                            _execute_pit_stop(
                                _did, next_cmp, _state.tyre_compound, _state, _entry, circuit, lap,
                                pit_stop_log, events, pitted_this_lap, pit_recovery_laps_left,
                                event_suffix=" for weather",
                            )
                            if _did in live_alloc:
                                live_alloc[_did][next_cmp] = max(0, live_alloc[_did].get(next_cmp, 0) - 1)
                            if _did in lap_snapshots:
                                lap_snapshots[_did]["pitted"] = True

        # ── AI mid-race weather pit ───────────────────────────────────────────
        if rain_prob >= 65 and prev_lap_rain_prob < 65:
            from engine.tyres import ai_should_pit_for_weather
            for _did, _state in states.items():
                if _state.dnf:
                    continue
                if player_team_id and entry_map[_did].team_id == player_team_id:
                    continue
                if _state.tyre_compound in ("intermediate", "wet"):
                    continue
                laps_rem = total_laps - lap
                if ai_should_pit_for_weather(_state, entry_map[_did], circuit, rain_prob, laps_rem):
                    _entry = entry_map[_did]
                    next_cmp = "intermediate" if rain_prob < 82 else "wet"
                    old_cmp = _state.tyre_compound
                    _execute_pit_stop(
                        _did, next_cmp, old_cmp, _state, _entry, circuit, lap,
                        pit_stop_log, events, pitted_this_lap, pit_recovery_laps_left,
                        event_suffix=" for weather",
                    )
                    if _did in lap_snapshots:
                        lap_snapshots[_did]["pitted"] = True
                    pit_schedules[_did] = {}

        # ── Overtaking pass ───────────────────────────────────────────────────
        active = [did for did, s in states.items() if not s.dnf]
        active.sort(key=lambda d: states[d].total_race_time)

        if sc_state is None:
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
                        for did, label in [(behind_did, entry_map[behind_did].driver.name),
                                           (ahead_did,  entry_map[ahead_did].driver.name)]:
                            if random.random() < 0.40:
                                states[did].dnf = True
                                states[did].dnf_reason = "Collision"
                                lap_had_incident = True
                                events.append(f"Lap {lap}: {label} retires after collision!")
                            else:
                                damage_s = round(random.uniform(15.0, 35.0), 1)
                                states[did].total_race_time += damage_s
                                events.append(f"Lap {lap}: {label} carries collision damage (+{damage_s}s)")

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

        # ── Record lap data ───────────────────────────────────────────────────
        active.sort(key=lambda d: states[d].total_race_time)

        prev_pos_to_driver = {pos: d for d, pos in prev_positions.items()}
        if sc_state is None:
            for pos_idx, did in enumerate(active, 1):
                curr_pos = pos_idx
                prev_pos = prev_positions.get(did)
                if pit_recovery_laps_left[did] > 0:
                    pit_recovery_laps_left[did] -= 1
                if prev_pos is None:
                    continue
                if lap_snapshots.get(did, {}).get("pitted", False):
                    continue
                if pit_recovery_laps_left[did] > 0:
                    continue
                positions_gained = prev_pos - curr_pos
                if positions_gained > 0:
                    valid_gains = sum(
                        1 for p in range(curr_pos, prev_pos)
                        if prev_pos_to_driver.get(p) not in pitted_this_lap
                    )
                    if valid_gains > 0:
                        overtakes_made[did] += valid_gains
        else:
            for did in active:
                if pit_recovery_laps_left[did] > 0:
                    pit_recovery_laps_left[did] -= 1

        for pos_idx, did in enumerate(active, 1):
            prev_positions[did] = pos_idx

        for pos_idx, did in enumerate(active, 1):
            if did in lap_snapshots:
                s = lap_snapshots[did]
                lap_data[did].append(DriverLapRecord(
                    lap=lap,
                    lap_time=s["lap_time"],
                    compound=s["compound"],
                    tyre_age=s["tyre_age"],
                    wear_pct=s["wear_pct"],
                    fuel_load=s["fuel_load"],
                    position=pos_idx,
                    pitted=s["pitted"],
                    rain_prob=s.get("rain_prob", 0.0),
                    sc_active=sc_state,
                ))
        for did, state in states.items():
            if state.dnf and state.dnf_lap == lap and did not in lap_snapshots:
                lap_data[did].append(DriverLapRecord(
                    lap=lap, lap_time=0.0, compound=state.tyre_compound,
                    tyre_age=state.tyre_age, wear_pct=0.0, fuel_load=0.0,
                    position=0, dnf=True,
                ))

    # ── Build final results ───────────────────────────────────────────────────
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
            grid_position=grid_pos(did),
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
            grid_position=grid_pos(did),
        ))

    if fastest_lap_driver and fastest_lap_driver in finisher_dids:
        fl_pos = finisher_dids.index(fastest_lap_driver) + 1
        for r in results:
            if r.driver.id == fastest_lap_driver:
                r.fastest_lap = True
                if fl_pos <= 10:
                    r.points += 1
                break

    return RaceReport(
        results=results,
        events=events,
        pit_stops=pit_stop_log,
        fastest_lap_time=fastest_lap_time if fastest_lap_time < float("inf") else 0.0,
        driver_fastest_laps=driver_fastest_laps,
        lap_data=lap_data,
        overtakes_made=overtakes_made,
        defenses_made=defenses_made,
        peak_rain_prob=peak_rain_prob,
        weather_summary=weather_summary,
    )
