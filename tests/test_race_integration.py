"""Integration test: simulate_race() with no UI callbacks.

Proves that Session 5 wiring is correct — the race engine runs end-to-end
without any UI interaction when callbacks are None.
"""
import random
import unittest
from dataclasses import dataclass

from engine.race import simulate_race, RaceReport
from engine.race_models import RaceEntry
from game.loader import load_circuits


# ── Real circuit fixture ───────────────────────────────────────────────────────

def _get_circuit():
    """Return a real Circuit object (Monza) loaded from data/."""
    circuits = {c.id: c for c in load_circuits()}
    return circuits.get("monza") or circuits[next(iter(circuits))]


# ── Minimal stubs ─────────────────────────────────────────────────────────────

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
        return (
            self.engine * 0.25
            + self.aerodynamics * 0.20
            + self.mechanical_grip * 0.18
            + self.reliability * 0.12
            + self.tire_deg * 0.10
            + self.braking * 0.08
            + self.pit_crew * 0.07
        )


@dataclass
class StubDriver:
    id: str
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
        return (
            self.pace * 0.25
            + self.consistency * 0.18
            + self.experience * 0.09
            + self.car_control * 0.09
            + self.wet_weather * 0.08
            + self.overtaking * 0.08
            + self.defending * 0.07
            + self.tire_management * 0.07
            + self.aggression * 0.05
            + self.mental * 0.04
        )


def _make_entries(n: int = 6, team_id: str = "t1") -> list:
    """Create n RaceEntry stubs with unique driver IDs."""
    entries = []
    for i in range(n):
        driver = StubDriver(id=f"d{i}", team_id=team_id)
        car = StubCar(team_id=team_id)
        entries.append(
            RaceEntry(
                driver=driver,
                car=car,
                team_id=team_id,
                team_name="Test Team",
                team_color="#FF0000",
            )
        )
    return entries


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestSimulateRaceNoCallbacks(unittest.TestCase):
    """simulate_race() must complete without UI callbacks."""

    def setUp(self):
        self.circuit = _get_circuit()
        self.entries = _make_entries(6)

    def test_returns_race_report(self):
        random.seed(42)
        report = simulate_race(self.entries, self.circuit, weather="dry")
        self.assertIsInstance(report, RaceReport)

    def test_results_length_equals_entries(self):
        random.seed(1)
        report = simulate_race(self.entries, self.circuit, weather="dry")
        self.assertEqual(len(report.results), len(self.entries))

    def test_p1_has_zero_gap(self):
        random.seed(2)
        report = simulate_race(self.entries, self.circuit, weather="dry")
        p1 = next(r for r in report.results if r.position == 1)
        self.assertEqual(p1.time_gap, 0.0)

    def test_positions_are_unique_1_to_n(self):
        random.seed(3)
        report = simulate_race(self.entries, self.circuit, weather="dry")
        positions = sorted(r.position for r in report.results)
        self.assertEqual(positions, list(range(1, len(self.entries) + 1)))

    def test_wet_race_completes(self):
        random.seed(10)
        report = simulate_race(self.entries, self.circuit, weather="wet")
        self.assertIsInstance(report, RaceReport)
        self.assertGreater(len(report.results), 0)

    def test_events_is_list(self):
        random.seed(4)
        report = simulate_race(self.entries, self.circuit, weather="dry")
        self.assertIsInstance(report.events, list)

    def test_peak_rain_prob_in_range(self):
        random.seed(5)
        report = simulate_race(self.entries, self.circuit, weather="dry")
        self.assertGreaterEqual(report.peak_rain_prob, 0)
        self.assertLessEqual(report.peak_rain_prob, 100)

    def test_pit_stops_list_present(self):
        random.seed(6)
        report = simulate_race(self.entries, self.circuit, weather="dry")
        self.assertIsInstance(report.pit_stops, list)

    def test_lap_data_present(self):
        random.seed(7)
        report = simulate_race(self.entries, self.circuit, weather="dry")
        self.assertIsInstance(report.lap_data, dict)

    def test_fastest_lap_time_is_positive(self):
        random.seed(8)
        report = simulate_race(self.entries, self.circuit, weather="dry")
        self.assertGreater(report.fastest_lap_time, 0)

    def test_no_callbacks_means_no_exception(self):
        """Explicit check: passing None for both callbacks must not raise."""
        random.seed(9)
        try:
            simulate_race(
                self.entries, self.circuit,
                weather="dry",
                sc_pit_callback=None,
                weather_callback=None,
            )
        except Exception as exc:
            self.fail(f"simulate_race raised {exc!r} with no callbacks")

    def test_deterministic_with_same_seed(self):
        circuit = _get_circuit()
        random.seed(99)
        r1 = simulate_race(_make_entries(4), circuit, weather="dry")
        random.seed(99)
        r2 = simulate_race(_make_entries(4), circuit, weather="dry")
        pos1 = [r.driver.id for r in sorted(r1.results, key=lambda x: x.position)]
        pos2 = [r.driver.id for r in sorted(r2.results, key=lambda x: x.position)]
        self.assertEqual(pos1, pos2)


class TestSimulateRaceGridOrder(unittest.TestCase):
    def test_custom_grid_accepted(self):
        random.seed(20)
        entries = _make_entries(4)
        grid = [e.driver.id for e in reversed(entries)]
        report = simulate_race(entries, _get_circuit(), weather="dry", grid=grid)
        self.assertIsInstance(report, RaceReport)

    def test_player_team_id_accepted(self):
        random.seed(21)
        entries = _make_entries(4)
        report = simulate_race(
            entries, _get_circuit(), weather="dry", player_team_id="t1"
        )
        self.assertIsInstance(report, RaceReport)


class TestSimulateRaceMultipleWeathers(unittest.TestCase):
    def _run(self, weather: str, seed: int = 0):
        random.seed(seed)
        return simulate_race(_make_entries(6), _get_circuit(), weather=weather)

    def test_dry(self):
        self.assertIsInstance(self._run("dry", 30), RaceReport)

    def test_wet(self):
        self.assertIsInstance(self._run("wet", 31), RaceReport)

    def test_mixed(self):
        self.assertIsInstance(self._run("mixed", 32), RaceReport)


if __name__ == "__main__":
    unittest.main()
