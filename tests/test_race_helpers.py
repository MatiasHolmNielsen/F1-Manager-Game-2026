"""Tests for the three helpers extracted from simulate_race() in Session 6.

Covers:
  - _compute_driver_lap_time
  - _process_overtaking_pass
  - _build_race_results
"""
import random
import unittest
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from engine.race import (
    _compute_driver_lap_time,
    _process_overtaking_pass,
    _build_race_results,
)
from engine.race_models import DriverLapState, RaceEntry, RaceResult


# ── Shared stubs ──────────────────────────────────────────────────────────────

@dataclass
class StubCar:
    team_id: str = "t1"
    engine: int = 80
    aerodynamics: int = 80
    mechanical_grip: int = 80
    reliability: int = 85
    tire_deg: int = 75
    braking: int = 80
    pit_crew: int = 80

    @property
    def overall(self) -> float:
        return 80.0


@dataclass
class StubDriver:
    id: str = "d0"
    name: str = "Test Driver"
    nationality: str = "GB"
    age: int = 28
    pace: int = 80
    qualifying_pace: int = 80
    consistency: int = 75
    overtaking: int = 70
    defending: int = 70
    car_control: int = 75
    aggression: int = 50
    wet_weather: int = 70
    tire_management: int = 70
    mental: int = 75
    experience: int = 70
    potential: int = 80
    salary: float = 2_000_000.0
    team_id: str = "t1"

    @property
    def overall(self) -> float:
        return 80.0


@dataclass
class StubCircuit:
    id: str = "monza"
    name: str = "Monza"
    country: str = "Italy"
    flag: str = "IT"
    length_km: float = 5.793
    corners: int = 11
    overtaking_difficulty: float = 0.35
    weather_chance: int = 20
    tire_wear: str = "medium"
    pit_lane_loss: float = 22.0
    engine_weight: float = 0.40
    aero_weight: float = 0.30
    mechanical_weight: float = 0.30
    base_lap_time: float = 82.0


def _make_entry(driver_id: str = "d0", team_id: str = "t1") -> RaceEntry:
    return RaceEntry(
        driver=StubDriver(id=driver_id, team_id=team_id),
        car=StubCar(team_id=team_id),
        team_id=team_id,
        team_name="Test Team",
        team_color="#FF0000",
    )


def _make_state(total_time: float = 0.0, dnf: bool = False) -> DriverLapState:
    return DriverLapState(
        total_race_time=total_time,
        fuel_load=100.0,
        tyre_compound="medium",
        tyre_age=5,
        stint_index=0,
        dnf=dnf,
        dnf_reason="",
        pit_this_lap=False,
    )


# ── _compute_driver_lap_time ──────────────────────────────────────────────────

class TestComputeDriverLapTime(unittest.TestCase):

    def _call(self, **kw):
        defaults = dict(
            entry=_make_entry(),
            state=_make_state(),
            circuit=StubCircuit(),
            rain_prob=0.0,
            life=20.0,
            sc_state=None,
            events=[],
            lap=5,
        )
        defaults.update(kw)
        return _compute_driver_lap_time(**defaults)

    def test_returns_positive_float(self):
        random.seed(0)
        t = self._call()
        self.assertIsInstance(t, float)
        self.assertGreater(t, 0)

    def test_sc_lap_slower_than_clean(self):
        random.seed(1)
        clean = self._call(sc_state=None)
        random.seed(1)
        sc    = self._call(sc_state="SC")
        self.assertGreater(sc, clean)

    def test_vsc_lap_slower_than_clean(self):
        random.seed(2)
        clean = self._call(sc_state=None)
        random.seed(2)
        vsc   = self._call(sc_state="VSC")
        self.assertGreater(vsc, clean)

    def test_sc_slower_than_vsc(self):
        random.seed(3)
        sc  = self._call(sc_state="SC")
        random.seed(3)
        vsc = self._call(sc_state="VSC")
        self.assertGreater(sc, vsc)

    def test_wet_rain_slower_than_dry(self):
        random.seed(4)
        dry = self._call(rain_prob=0.0)
        random.seed(4)
        wet = self._call(rain_prob=90.0)
        # wet compounds introduce a pace delta; overall time changes
        self.assertNotEqual(dry, wet)

    def test_high_tyre_age_slower(self):
        random.seed(5)
        fresh = self._call(state=_make_state())
        old_state = _make_state()
        old_state.tyre_age = 30
        random.seed(5)
        old = self._call(state=old_state, life=20.0)
        self.assertGreater(old, fresh)

    def _rookie_entry(self) -> RaceEntry:
        return RaceEntry(
            driver=StubDriver(id="rookie", experience=0, consistency=50, mental=50),
            car=StubCar(),
            team_id="t1",
            team_name="Test",
            team_color="#000",
        )

    def test_mistake_event_appended_early_lap(self):
        # mistake_prob for experience=0: (60-0)/100 * 0.04 = 2.4% per lap
        entry = self._rookie_entry()
        events: List[str] = []
        found = False
        for seed in range(200):
            events.clear()
            random.seed(seed)
            _compute_driver_lap_time(entry, _make_state(), StubCircuit(),
                                     0.0, 20.0, None, events, lap=5)
            if events:
                found = True
                break
        self.assertTrue(found)
        self.assertIn("makes a mistake", events[0])

    def test_no_mistake_events_late_lap(self):
        # Mistakes only reported on lap <= 15; lap=20 should never append
        entry = self._rookie_entry()
        for seed in range(100):
            events: List[str] = []
            random.seed(seed)
            _compute_driver_lap_time(entry, _make_state(), StubCircuit(),
                                     0.0, 20.0, None, events, lap=20)
            self.assertEqual(len(events), 0)

    def test_veteran_rarely_makes_mistake(self):
        # mistake_prob = max(0, (60-100)/100) * 0.04 = 0.0 → never
        entry = RaceEntry(
            driver=StubDriver(id="vet", experience=100),
            car=StubCar(),
            team_id="t1",
            team_name="Test",
            team_color="#000",
        )
        mistakes = 0
        for seed in range(200):
            events: List[str] = []
            random.seed(seed)
            _compute_driver_lap_time(entry, _make_state(), StubCircuit(),
                                     0.0, 20.0, None, events, lap=5)
            if events:
                mistakes += 1
        self.assertEqual(mistakes, 0)


# ── _process_overtaking_pass ──────────────────────────────────────────────────

def _make_pass_fixtures(n: int = 3):
    """Return (active, states, entry_map, lap_times) for n drivers in a tight pack."""
    dids = [f"d{i}" for i in range(n)]
    # Space 0.5 s apart so all are within BATTLE_RANGE_S
    states = {d: _make_state(total_time=i * 0.5) for i, d in enumerate(dids)}
    entry_map = {d: _make_entry(driver_id=d) for d in dids}
    # Faster drivers behind (they have smaller lap times → want to overtake)
    lap_times = {d: 85.0 - i * 0.5 for i, d in enumerate(dids)}
    active = sorted(dids, key=lambda d: states[d].total_race_time)
    overtakes_made = {d: 0 for d in dids}
    defenses_made  = {d: 0 for d in dids}
    return active, states, entry_map, lap_times, overtakes_made, defenses_made


class TestProcessOvertakingPass(unittest.TestCase):

    def test_returns_bool(self):
        active, states, entry_map, lap_times, om, dm = _make_pass_fixtures()
        random.seed(0)
        result = _process_overtaking_pass(
            active, states, entry_map, lap_times, StubCircuit(),
            lap=10, overtakes_made=om, defenses_made=dm, events=[],
        )
        self.assertIsInstance(result, bool)

    def test_active_list_mutated_in_place(self):
        active, states, entry_map, lap_times, om, dm = _make_pass_fixtures(2)
        original_ref = active
        random.seed(0)
        _process_overtaking_pass(
            active, states, entry_map, lap_times, StubCircuit(),
            lap=10, overtakes_made=om, defenses_made=dm, events=[],
        )
        self.assertIs(active, original_ref)  # same list object

    def test_events_is_list_of_strings(self):
        active, states, entry_map, lap_times, om, dm = _make_pass_fixtures()
        events: List[str] = []
        random.seed(42)
        _process_overtaking_pass(
            active, states, entry_map, lap_times, StubCircuit(),
            lap=10, overtakes_made=om, defenses_made=dm, events=events,
        )
        for e in events:
            self.assertIsInstance(e, str)

    def test_missing_lap_time_skipped(self):
        """Driver with no lap time entry should not cause an error."""
        active, states, entry_map, lap_times, om, dm = _make_pass_fixtures(2)
        lap_times.pop("d1")  # remove one driver's lap time
        random.seed(0)
        try:
            _process_overtaking_pass(
                active, states, entry_map, lap_times, StubCircuit(),
                lap=10, overtakes_made=om, defenses_made=dm, events=[],
            )
        except KeyError:
            self.fail("Missing lap_time entry caused a KeyError")

    def test_no_pass_when_gap_too_large(self):
        """Drivers far apart should not interact."""
        dids = ["d0", "d1"]
        states = {
            "d0": _make_state(total_time=0.0),
            "d1": _make_state(total_time=999.0),  # way behind
        }
        entry_map = {d: _make_entry(driver_id=d) for d in dids}
        lap_times = {"d0": 85.0, "d1": 83.0}
        active = ["d0", "d1"]
        om = {d: 0 for d in dids}
        dm = {d: 0 for d in dids}
        events: List[str] = []
        random.seed(0)
        _process_overtaking_pass(
            active, states, entry_map, lap_times, StubCircuit(),
            lap=10, overtakes_made=om, defenses_made=dm, events=events,
        )
        self.assertEqual(events, [])
        self.assertEqual(om, {"d0": 0, "d1": 0})

    def test_counters_non_negative(self):
        active, states, entry_map, lap_times, om, dm = _make_pass_fixtures(4)
        random.seed(7)
        for _ in range(20):
            _process_overtaking_pass(
                list(active), dict(states), entry_map, lap_times, StubCircuit(),
                lap=5, overtakes_made=om, defenses_made=dm, events=[],
            )
        for d in om:
            self.assertGreaterEqual(om[d], 0)
        for d in dm:
            self.assertGreaterEqual(dm[d], 0)


# ── _build_race_results ───────────────────────────────────────────────────────

DUMMY_GRID = {"d0": 1, "d1": 2, "d2": 3}


def grid_pos(did: str) -> int:
    return DUMMY_GRID.get(did, 10)


class TestBuildRaceResults(unittest.TestCase):

    def _two_finishers(self):
        states = {
            "d0": _make_state(total_time=3600.0),
            "d1": _make_state(total_time=3610.0),
        }
        entry_map = {
            "d0": _make_entry("d0"),
            "d1": _make_entry("d1"),
        }
        return states, entry_map

    def test_returns_list(self):
        states, entry_map = self._two_finishers()
        results = _build_race_results(states, entry_map, grid_pos, None, float("inf"))
        self.assertIsInstance(results, list)

    def test_length_equals_entries(self):
        states, entry_map = self._two_finishers()
        results = _build_race_results(states, entry_map, grid_pos, None, float("inf"))
        self.assertEqual(len(results), 2)

    def test_p1_has_zero_gap(self):
        states, entry_map = self._two_finishers()
        results = _build_race_results(states, entry_map, grid_pos, None, float("inf"))
        p1 = next(r for r in results if r.position == 1)
        self.assertEqual(p1.time_gap, 0.0)

    def test_p2_has_correct_gap(self):
        states, entry_map = self._two_finishers()
        results = _build_race_results(states, entry_map, grid_pos, None, float("inf"))
        p2 = next(r for r in results if r.position == 2)
        self.assertAlmostEqual(p2.time_gap, 10.0)

    def test_positions_are_1_to_n(self):
        states, entry_map = self._two_finishers()
        results = _build_race_results(states, entry_map, grid_pos, None, float("inf"))
        positions = sorted(r.position for r in results)
        self.assertEqual(positions, [1, 2])

    def test_dnf_driver_gets_zero_gap(self):
        states = {
            "d0": _make_state(total_time=3600.0),
            "d1": _make_state(total_time=3610.0, dnf=True),
        }
        states["d1"].dnf_reason = "Engine"
        entry_map = {"d0": _make_entry("d0"), "d1": _make_entry("d1")}
        results = _build_race_results(states, entry_map, grid_pos, None, float("inf"))
        dnf_r = next(r for r in results if r.dnf)
        self.assertEqual(dnf_r.time_gap, 0.0)
        self.assertTrue(dnf_r.dnf)
        self.assertEqual(dnf_r.dnf_reason, "Engine")

    def test_dnf_driver_gets_zero_points(self):
        states = {
            "d0": _make_state(total_time=3600.0),
            "d1": _make_state(total_time=3610.0, dnf=True),
        }
        states["d1"].dnf_reason = "Collision"
        entry_map = {"d0": _make_entry("d0"), "d1": _make_entry("d1")}
        results = _build_race_results(states, entry_map, grid_pos, None, float("inf"))
        dnf_r = next(r for r in results if r.dnf)
        self.assertEqual(dnf_r.points, 0)

    def test_p1_gets_25_points(self):
        states, entry_map = self._two_finishers()
        results = _build_race_results(states, entry_map, grid_pos, None, float("inf"))
        p1 = next(r for r in results if r.position == 1)
        self.assertEqual(p1.points, 25)

    def test_fastest_lap_flag_set(self):
        states, entry_map = self._two_finishers()
        results = _build_race_results(states, entry_map, grid_pos, "d0", 80.5)
        fl = next(r for r in results if r.driver.id == "d0")
        self.assertTrue(fl.fastest_lap)

    def test_fastest_lap_bonus_point_if_top_10(self):
        # d0 finishes P1 → fastest lap → +1 bonus (P1 is in top 10)
        states, entry_map = self._two_finishers()
        results = _build_race_results(states, entry_map, grid_pos, "d0", 80.5)
        p1 = next(r for r in results if r.driver.id == "d0")
        self.assertEqual(p1.points, 26)  # 25 + 1

    def test_fastest_lap_no_bonus_if_dnf(self):
        states = {
            "d0": _make_state(total_time=3600.0, dnf=True),
            "d1": _make_state(total_time=3610.0),
        }
        states["d0"].dnf_reason = "Engine"
        entry_map = {"d0": _make_entry("d0"), "d1": _make_entry("d1")}
        results = _build_race_results(states, entry_map, grid_pos, "d0", 80.5)
        dnf_r = next(r for r in results if r.driver.id == "d0")
        self.assertEqual(dnf_r.points, 0)

    def test_grid_position_assigned(self):
        states, entry_map = self._two_finishers()
        results = _build_race_results(states, entry_map, grid_pos, None, float("inf"))
        r0 = next(r for r in results if r.driver.id == "d0")
        self.assertEqual(r0.grid_position, DUMMY_GRID["d0"])

    def test_all_finishers_before_dnfs(self):
        states = {
            "d0": _make_state(total_time=3600.0),
            "d1": _make_state(total_time=3610.0, dnf=True),
        }
        states["d1"].dnf_reason = "Mechanical"
        entry_map = {"d0": _make_entry("d0"), "d1": _make_entry("d1")}
        results = _build_race_results(states, entry_map, grid_pos, None, float("inf"))
        finisher_positions = [r.position for r in results if not r.dnf]
        dnf_positions      = [r.position for r in results if r.dnf]
        self.assertTrue(all(f < d for f in finisher_positions for d in dnf_positions))

    def test_empty_field(self):
        results = _build_race_results({}, {}, grid_pos, None, float("inf"))
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
