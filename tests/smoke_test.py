"""
Full-race smoke test — runs a complete race using real game data (all 20
drivers, all circuits, real tyre allocations) with no UI callbacks.

Run via pytest:  pytest tests/smoke_test.py -v
"""
import random

from game.loader import load_drivers, load_teams, load_circuits
from engine.race import (
    RaceEntry, RaceReport, simulate_race, simulate_qualifying, ai_strategy,
)
from engine.race_models import PitStop, POINTS_SYSTEM
from engine.core.tyres import DEFAULT_TYRE_ALLOCATION, TyreAllocation
from engine.development import apply_development


def test_smoke_races():
    random.seed(42)

    drivers  = load_drivers()
    teams    = load_teams(drivers)
    circuits = load_circuits()

    PLAYER_TEAM_ID = list(teams.keys())[0]
    player_team = teams[PLAYER_TEAM_ID]

    failures = []

    def check(cond, msg):
        if not cond:
            failures.append(msg)

    circuits_to_test = circuits[:3]
    weathers_to_test = ["dry", "wet", "mixed"]

    for circuit in circuits_to_test:
        for weather in weathers_to_test:
            label = f"{circuit.name} / {weather}"

            entries = []
            for team in teams.values():
                for did in team.driver_ids:
                    d = drivers.get(did)
                    if d:
                        entries.append(RaceEntry(
                            driver=d, car=team.car,
                            team_id=team.id, team_name=team.short_name,
                            team_color=team.color,
                        ))
            random.shuffle(entries)

            try:
                quali_results = simulate_qualifying(entries, circuit, weather)
                grid = [qr.driver.id for qr in quali_results]
            except Exception as e:
                failures.append(f"[{label}] simulate_qualifying raised: {e}")
                continue

            check(len(grid) == len(entries),
                  f"[{label}] grid length {len(grid)} != entries {len(entries)}")

            player_alloc = {
                did: dict(DEFAULT_TYRE_ALLOCATION)
                for did in player_team.driver_ids
                if did in drivers
            }

            strategies = {}
            for entry in entries:
                strategies[entry.driver.id] = ai_strategy(entry, circuit, weather)

            try:
                report = simulate_race(
                    entries, circuit, weather,
                    grid=grid,
                    strategies=strategies,
                    player_team_id=PLAYER_TEAM_ID,
                    sc_pit_callback=None,
                    weather_callback=None,
                    player_allocation=player_alloc,
                )
            except Exception as e:
                failures.append(f"[{label}] simulate_race raised: {e}")
                continue

            check(isinstance(report, RaceReport),         f"[{label}] did not return RaceReport")
            check(isinstance(report.events, list),        f"[{label}] events is not a list")
            check(isinstance(report.pit_stops, list),     f"[{label}] pit_stops is not a list")
            check(isinstance(report.lap_data, dict),      f"[{label}] lap_data is not a dict")
            check(isinstance(report.weather_summary, list), f"[{label}] weather_summary is not a list")
            check(isinstance(report.peak_rain_prob, (int, float)), f"[{label}] peak_rain_prob is not numeric")
            check(0 <= report.peak_rain_prob <= 100,      f"[{label}] peak_rain_prob out of range: {report.peak_rain_prob}")

            check(len(report.results) == len(entries),
                  f"[{label}] results has {len(report.results)} entries, expected {len(entries)}")

            positions = sorted(r.position for r in report.results)
            check(positions == list(range(1, len(entries) + 1)),
                  f"[{label}] positions not contiguous 1..n: {positions}")

            p1_results = [r for r in report.results if r.position == 1]
            check(len(p1_results) == 1, f"[{label}] {len(p1_results)} drivers in P1")
            if p1_results:
                check(p1_results[0].time_gap == 0.0,
                      f"[{label}] P1 time_gap is {p1_results[0].time_gap}, expected 0.0")

            finishers = [r for r in report.results if not r.dnf]
            for r in finishers:
                check(r.time_gap >= 0.0,
                      f"[{label}] finisher {r.driver.name} has negative gap {r.time_gap}")

            for r in report.results:
                if r.dnf:
                    check(r.points == 0,
                          f"[{label}] DNF driver {r.driver.name} has {r.points} points")
                    check(r.time_gap == 0.0,
                          f"[{label}] DNF driver {r.driver.name} has non-zero gap {r.time_gap}")

            fl_drivers = [r for r in report.results if r.fastest_lap]
            check(len(fl_drivers) <= 1,
                  f"[{label}] {len(fl_drivers)} drivers flagged fastest_lap")
            check(report.fastest_lap_time > 0,
                  f"[{label}] fastest_lap_time={report.fastest_lap_time} <= 0")

            for ps in report.pit_stops:
                check(isinstance(ps, PitStop),      f"[{label}] pit stop entry is not a PitStop: {type(ps)}")
                check(ps.stationary_time > 0,       f"[{label}] pit stop stationary_time={ps.stationary_time} <= 0")
                check(ps.total_time > 0,            f"[{label}] pit stop total_time={ps.total_time} <= 0")
                check(ps.lap >= 1,                  f"[{label}] pit stop on lap {ps.lap} < 1")

            for did, laps in report.lap_data.items():
                check(did in {e.driver.id for e in entries},
                      f"[{label}] lap_data has unknown driver {did}")
                for rec in laps:
                    if not rec.dnf:
                        check(rec.lap_time > 0,
                              f"[{label}] {did} lap {rec.lap} time={rec.lap_time} <= 0")
                    check(rec.lap >= 1,
                          f"[{label}] {did} has lap record with lap={rec.lap}")

            try:
                gains, xp_gains = apply_development(report.results, drivers,
                                                     grid=grid, report=report)
                check(isinstance(gains, dict),
                      f"[{label}] apply_development gains is not a dict")
            except Exception as e:
                failures.append(f"[{label}] apply_development raised: {e}")

            for r in finishers:
                expected = POINTS_SYSTEM.get(r.position, 0)
                if r.fastest_lap and r.position <= 10:
                    expected += 1
                check(r.points == expected,
                      f"[{label}] {r.driver.name} P{r.position} fl={r.fastest_lap}: "
                      f"points={r.points} expected={expected}")

    assert not failures, "\n" + "\n".join(failures)


def test_smoke_tyre_allocation():
    alloc = TyreAllocation.from_dict(DEFAULT_TYRE_ALLOCATION)
    before = dict(alloc.sets)
    alloc.consume("soft")
    assert alloc.sets["soft"] == before["soft"] - 1, \
        f"TyreAllocation.consume() didn't decrement: {alloc.sets}"
    alloc2 = alloc.copy()
    alloc2.consume("medium")
    assert alloc.sets["medium"] == before["medium"], \
        "TyreAllocation.copy() is not independent"


def test_smoke_full_season():
    random.seed(0)
    drivers  = load_drivers()
    teams    = load_teams(drivers)
    circuits = load_circuits()

    failures = []
    for i, circuit in enumerate(circuits, 1):
        entries = []
        for team in teams.values():
            for did in team.driver_ids:
                d = drivers.get(did)
                if d:
                    entries.append(RaceEntry(
                        driver=d, car=team.car,
                        team_id=team.id, team_name=team.short_name,
                        team_color=team.color,
                    ))
        try:
            report = simulate_race(entries, circuit, "dry",
                                   sc_pit_callback=None, weather_callback=None)
            positions = sorted(r.position for r in report.results)
            assert positions == list(range(1, len(entries) + 1)), "bad positions"
            assert report.fastest_lap_time > 0, "bad fastest lap time"
        except Exception as e:
            failures.append(f"[Race {i} {circuit.name}] {e}")

    assert not failures, "\n" + "\n".join(failures)
