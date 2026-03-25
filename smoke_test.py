"""
Full-race smoke test — runs a complete race using real game data (all 20
drivers, all circuits, real tyre allocations) with no UI callbacks.

Run:  python smoke_test.py

Checks every assertion the game loop implicitly relies on, prints a human-
readable report of any failures, and exits non-zero on error.
"""
import random
import sys

random.seed(42)

from game.loader import load_drivers, load_teams, load_circuits
from engine.race import (
    RaceEntry, RaceReport, simulate_race, simulate_qualifying, ai_strategy,
)
from engine.tyres import DEFAULT_TYRE_ALLOCATION
from engine.core.tyres import TyreAllocation
from engine.development import apply_development

# ── Load real data ────────────────────────────────────────────────────────────
drivers  = load_drivers()
teams    = load_teams(drivers)
circuits = load_circuits()

PLAYER_TEAM_ID = list(teams.keys())[0]   # Red Bull (first team) as "player"
player_team = teams[PLAYER_TEAM_ID]

failures = []
warnings = []

def check(cond, msg):
    if not cond:
        failures.append(msg)

def warn(cond, msg):
    if not cond:
        warnings.append(msg)

# ── Run races across all circuits, both weathers ──────────────────────────────
circuits_to_test = circuits[:3]  # first 3 circuits is enough for a smoke pass
weathers_to_test = ["dry", "wet", "mixed"]

for circuit in circuits_to_test:
    for weather in weathers_to_test:
        label = f"{circuit.name} / {weather}"

        # ── Build entries (exactly as game/loop.py does) ──────────────────
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

        # ── Qualifying grid ───────────────────────────────────────────────
        try:
            quali_results = simulate_qualifying(entries, circuit, weather)
            grid = [qr.driver.id for qr in quali_results]
        except Exception as e:
            failures.append(f"[{label}] simulate_qualifying raised: {e}")
            continue

        check(len(grid) == len(entries),
              f"[{label}] grid length {len(grid)} != entries {len(entries)}")

        # ── Player tyre allocation ────────────────────────────────────────
        player_alloc = {
            did: dict(DEFAULT_TYRE_ALLOCATION)
            for did in player_team.driver_ids
            if did in drivers
        }

        # ── Strategies ───────────────────────────────────────────────────
        strategies = {}
        for entry in entries:
            strategies[entry.driver.id] = ai_strategy(entry, circuit, weather)

        # ── Simulate race (no callbacks) ──────────────────────────────────
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

        # ── Validate RaceReport structure ─────────────────────────────────
        check(isinstance(report, RaceReport),
              f"[{label}] did not return RaceReport")
        check(isinstance(report.events, list),
              f"[{label}] events is not a list")
        check(isinstance(report.pit_stops, list),
              f"[{label}] pit_stops is not a list")
        check(isinstance(report.lap_data, dict),
              f"[{label}] lap_data is not a dict")
        check(isinstance(report.weather_summary, list),
              f"[{label}] weather_summary is not a list")
        check(isinstance(report.peak_rain_prob, (int, float)),
              f"[{label}] peak_rain_prob is not numeric")
        check(0 <= report.peak_rain_prob <= 100,
              f"[{label}] peak_rain_prob out of range: {report.peak_rain_prob}")

        # ── Results integrity ─────────────────────────────────────────────
        check(len(report.results) == len(entries),
              f"[{label}] results has {len(report.results)} entries, expected {len(entries)}")

        positions = sorted(r.position for r in report.results)
        check(positions == list(range(1, len(entries) + 1)),
              f"[{label}] positions not contiguous 1..n: {positions}")

        p1_results = [r for r in report.results if r.position == 1]
        check(len(p1_results) == 1,
              f"[{label}] {len(p1_results)} drivers in P1")
        if p1_results:
            check(p1_results[0].time_gap == 0.0,
                  f"[{label}] P1 time_gap is {p1_results[0].time_gap}, expected 0.0")

        finishers = [r for r in report.results if not r.dnf]
        for r in finishers:
            check(r.time_gap >= 0.0,
                  f"[{label}] finisher {r.driver.name} has negative gap {r.time_gap}")


        # DNF drivers get 0 points and 0 gap
        for r in report.results:
            if r.dnf:
                check(r.points == 0,
                      f"[{label}] DNF driver {r.driver.name} has {r.points} points")
                check(r.time_gap == 0.0,
                      f"[{label}] DNF driver {r.driver.name} has non-zero gap {r.time_gap}")

        # ── Fastest lap ───────────────────────────────────────────────────
        fl_drivers = [r for r in report.results if r.fastest_lap]
        check(len(fl_drivers) <= 1,
              f"[{label}] {len(fl_drivers)} drivers flagged fastest_lap")
        check(report.fastest_lap_time > 0,
              f"[{label}] fastest_lap_time={report.fastest_lap_time} <= 0")

        # ── Pit stops ─────────────────────────────────────────────────────
        from engine.race_models import PitStop
        for ps in report.pit_stops:
            check(isinstance(ps, PitStop),
                  f"[{label}] pit stop entry is not a PitStop: {type(ps)}")
            check(ps.stationary_time > 0,
                  f"[{label}] pit stop stationary_time={ps.stationary_time} <= 0")
            check(ps.total_time > 0,
                  f"[{label}] pit stop total_time={ps.total_time} <= 0")
            check(ps.lap >= 1,
                  f"[{label}] pit stop on lap {ps.lap} < 1")

        # ── Lap data ──────────────────────────────────────────────────────
        for did, laps in report.lap_data.items():
            check(did in {e.driver.id for e in entries},
                  f"[{label}] lap_data has unknown driver {did}")
            for rec in laps:
                if not rec.dnf:
                    check(rec.lap_time > 0,
                          f"[{label}] {did} lap {rec.lap} time={rec.lap_time} <= 0")
                check(rec.lap >= 1,
                      f"[{label}] {did} has lap record with lap={rec.lap}")

        # ── apply_development doesn't crash ──────────────────────────────
        try:
            gains, xp_gains = apply_development(report.results, drivers,
                                                 grid=grid, report=report)
            check(isinstance(gains, dict),
                  f"[{label}] apply_development gains is not a dict")
        except Exception as e:
            failures.append(f"[{label}] apply_development raised: {e}")

        # ── Points system sanity ──────────────────────────────────────────
        from engine.race_models import POINTS_SYSTEM
        for r in finishers:
            expected = POINTS_SYSTEM.get(r.position, 0)
            if r.fastest_lap and r.position <= 10:
                expected += 1
            check(r.points == expected,
                  f"[{label}] {r.driver.name} P{r.position} fl={r.fastest_lap}: "
                  f"points={r.points} expected={expected}")

        print(f"  OK  {label:45s}  "
              f"{len(finishers):2d} finishers  "
              f"{len(report.results)-len(finishers):2d} DNFs  "
              f"{len(report.pit_stops):3d} pits  "
              f"peak_rain={report.peak_rain_prob:.0f}")

# ── Extra: verify TyreAllocation round-trips correctly ───────────────────────
alloc = TyreAllocation.from_dict(DEFAULT_TYRE_ALLOCATION)
before = dict(alloc.sets)
alloc.consume("soft")
check(alloc.sets["soft"] == before["soft"] - 1,
      f"TyreAllocation.consume() didn't decrement: {alloc.sets}")
alloc2 = alloc.copy()
alloc2.consume("medium")
check(alloc.sets["medium"] == before["medium"],
      "TyreAllocation.copy() is not independent")

# ── Extra: simulate a full season (all 24 circuits, dry, AI-only) ─────────────
print("\nRunning full dry season (all circuits, AI only, seed=0)…")
random.seed(0)
season_failures = 0
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
        print(f"  Race {i:2d}/24 {circuit.name[:30]:30s} OK")
    except Exception as e:
        failures.append(f"[Full season race {i} {circuit.name}] {e}")
        season_failures += 1
        print(f"  Race {i:2d}/24 {circuit.name[:30]:30s} FAILED: {e}")

# ── Report ────────────────────────────────────────────────────────────────────
print()
if warnings:
    print(f"WARNINGS ({len(warnings)}):")
    for w in warnings:
        print(f"  WARN  {w}")
    print()

if failures:
    print(f"FAILURES ({len(failures)}):")
    for f in failures:
        print(f"  FAIL  {f}")
    sys.exit(1)
else:
    total_checks = (len(circuits_to_test) * len(weathers_to_test))
    print(f"All checks passed ({total_checks * 3} circuits×weathers + full season).")
    sys.exit(0)
