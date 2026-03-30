"""Tests for game/ui/race_flow.py — specifically _prompt_pit_decisions."""
import unittest
from dataclasses import dataclass
from typing import Dict
from unittest.mock import MagicMock, patch

from engine.core.tyres import TyreStint, RaceStrategy
from engine.race_models import RaceEntry


# ── Stubs ──────────────────────────────────────────────────────────────────────

@dataclass
class _StubDriver:
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
class _StubCar:
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
class _StubCircuit:
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
        driver=_StubDriver(id=driver_id, team_id=team_id),
        car=_StubCar(team_id=team_id),
        team_id=team_id,
        team_name="Test Team",
        team_color="#FF0000",
    )


def _make_snap(
    driver_ids=("d0",),
    laps_remaining: int = 20,
    rain_prob: float = 0.0,
) -> dict:
    standings = [
        {
            "driver_id": did,
            "driver_name": f"Driver {did}",
            "is_player": True,
            "compound": "medium",
            "tyre_age": 10,
            "wear_pct": 40.0,
            "position": i + 1,
        }
        for i, did in enumerate(driver_ids)
    ]
    return {
        "standings": standings,
        "laps_remaining": laps_remaining,
        "rain_prob": rain_prob,
        "forecast": [],
        "trend": "stable",
    }


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestPromptPitDecisions(unittest.TestCase):
    """Unit tests for _prompt_pit_decisions.

    _show_pit_panel is patched out because it involves interactive Rich prompts.
    The function under test is purely responsible for:
      - looking up the correct RaceEntry from entries
      - calling _show_pit_panel with the right parameters
      - extracting stints[0].compound from the returned RaceStrategy
    """

    def _make_strategy(self, compound: str = "soft") -> RaceStrategy:
        return RaceStrategy(
            stints=[TyreStint(compound=compound, laps=20)],
            label="Test",
        )

    def _call(self, snap, entries, circuit, player_allocation, panel_return):
        from game.ui.race_flow import _prompt_pit_decisions
        with patch("game.ui.race_flow._show_pit_panel", return_value=panel_return) as mock_panel:
            result = _prompt_pit_decisions(snap, entries, circuit, player_allocation)
        return result, mock_panel

    def test_returns_compound_from_panel_strategy(self):
        """The compound returned for a driver is stints[0].compound of the panel result."""
        snap = _make_snap(driver_ids=("d0",), laps_remaining=20)
        entries = [_make_entry("d0")]
        circuit = _StubCircuit()
        allocation = {"d0": {"soft": 2, "medium": 1, "hard": 2}}
        strategy = self._make_strategy("soft")

        result, _ = self._call(snap, entries, circuit, allocation, strategy)

        self.assertEqual(result, {"d0": "soft"})

    def test_passes_remaining_laps_as_total_laps(self):
        """_show_pit_panel receives laps_remaining as total_laps, not the full race distance."""
        snap = _make_snap(driver_ids=("d0",), laps_remaining=15)
        entries = [_make_entry("d0")]
        circuit = _StubCircuit()
        allocation: Dict = {}
        strategy = self._make_strategy("hard")

        _, mock_panel = self._call(snap, entries, circuit, allocation, strategy)

        call_kwargs = mock_panel.call_args.kwargs
        self.assertEqual(call_kwargs["total_laps"], 15)

    def test_wet_weather_when_rain_prob_at_threshold(self):
        """weather='wet' is passed when rain_prob >= 50."""
        snap = _make_snap(driver_ids=("d0",), rain_prob=60.0)
        entries = [_make_entry("d0")]
        circuit = _StubCircuit()
        allocation: Dict = {}
        strategy = self._make_strategy("intermediate")

        _, mock_panel = self._call(snap, entries, circuit, allocation, strategy)

        call_kwargs = mock_panel.call_args.kwargs
        self.assertEqual(call_kwargs["weather"], "wet")

    def test_dry_weather_when_rain_prob_below_threshold(self):
        """weather='dry' is passed when rain_prob < 50."""
        snap = _make_snap(driver_ids=("d0",), rain_prob=30.0)
        entries = [_make_entry("d0")]
        circuit = _StubCircuit()
        allocation: Dict = {}
        strategy = self._make_strategy("medium")

        _, mock_panel = self._call(snap, entries, circuit, allocation, strategy)

        call_kwargs = mock_panel.call_args.kwargs
        self.assertEqual(call_kwargs["weather"], "dry")

    def test_multiple_player_drivers_all_get_decisions(self):
        """All player drivers in standings receive a pit decision."""
        snap = _make_snap(driver_ids=("d0", "d1"), laps_remaining=10)
        entries = [_make_entry("d0"), _make_entry("d1")]
        circuit = _StubCircuit()
        allocation: Dict = {}
        strategy = self._make_strategy("hard")

        result, mock_panel = self._call(snap, entries, circuit, allocation, strategy)

        self.assertEqual(mock_panel.call_count, 2)
        self.assertIn("d0", result)
        self.assertIn("d1", result)

    def test_missing_entry_is_skipped_gracefully(self):
        """If a player driver has no matching RaceEntry, they are silently skipped."""
        snap = _make_snap(driver_ids=("d0", "d_missing"), laps_remaining=10)
        entries = [_make_entry("d0")]  # d_missing not in entries
        circuit = _StubCircuit()
        allocation: Dict = {}
        strategy = self._make_strategy("soft")

        result, mock_panel = self._call(snap, entries, circuit, allocation, strategy)

        # Panel called only once (for d0), d_missing skipped
        self.assertEqual(mock_panel.call_count, 1)
        self.assertIn("d0", result)
        self.assertNotIn("d_missing", result)

    def test_title_and_border_color_are_correct(self):
        """_show_pit_panel is always called with title='PIT STRATEGY' and border_color='yellow'."""
        snap = _make_snap(driver_ids=("d0",))
        entries = [_make_entry("d0")]
        circuit = _StubCircuit()
        allocation: Dict = {}
        strategy = self._make_strategy("soft")

        _, mock_panel = self._call(snap, entries, circuit, allocation, strategy)

        call_kwargs = mock_panel.call_args.kwargs
        self.assertEqual(call_kwargs["title"], "PIT STRATEGY")
        self.assertEqual(call_kwargs["border_color"], "yellow")

    def test_allocation_passed_per_driver(self):
        """_show_pit_panel receives the allocation dict for the specific driver."""
        snap = _make_snap(driver_ids=("d0",))
        entries = [_make_entry("d0")]
        circuit = _StubCircuit()
        d0_alloc = {"soft": 3, "medium": 2, "hard": 1}
        allocation = {"d0": d0_alloc}
        strategy = self._make_strategy("soft")

        _, mock_panel = self._call(snap, entries, circuit, allocation, strategy)

        call_kwargs = mock_panel.call_args.kwargs
        self.assertEqual(call_kwargs["allocation"], d0_alloc)

    def test_empty_decisions_when_no_player_rows(self):
        """Returns empty dict when there are no player drivers in standings."""
        snap = {
            "standings": [
                {"driver_id": "ai0", "driver_name": "AI", "is_player": False,
                 "compound": "medium", "tyre_age": 5, "wear_pct": 20.0, "position": 1}
            ],
            "laps_remaining": 20,
            "rain_prob": 0.0,
            "forecast": [],
            "trend": "stable",
        }
        entries = [_make_entry("ai0")]
        circuit = _StubCircuit()
        allocation: Dict = {}
        strategy = self._make_strategy("soft")

        result, mock_panel = self._call(snap, entries, circuit, allocation, strategy)

        mock_panel.assert_not_called()
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
