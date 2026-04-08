"""
Tests for engine/core/safety_car.py
Covers check_safety_car(), should_trigger_weather_sc(), should_recommend_sc_pit(), and constants.
"""
import random
import unittest
from dataclasses import dataclass

from engine.core.safety_car import (
    check_safety_car,
    should_trigger_weather_sc,
    should_recommend_sc_pit,
    SC_PROBABILITY,
    VSC_PROBABILITY,
    SC_LAP_TIME_MULTIPLIER,
    VSC_LAP_TIME_MULTIPLIER,
    SC_DURATION_MIN,
    SC_DURATION_MAX,
    SC_PIT_TYRE_AGE_FRAC,
    WEATHER_SC_DELTA_THRESHOLD,
    WEATHER_SC_SUDDEN_PROB,
    WEATHER_SC_AQUAPLANE_THRESH,
    WEATHER_SC_AQUAPLANE_PROB,
)
from engine.core.weather import WeatherState


# ── Constants ────────────────────────────────────────────────────────────────

class TestSafetyCarConstants(unittest.TestCase):
    """Verify that all constants have expected values."""

    def test_sc_probability(self):
        self.assertAlmostEqual(SC_PROBABILITY, 0.50)

    def test_vsc_probability(self):
        self.assertAlmostEqual(VSC_PROBABILITY, 0.25)

    def test_sc_lap_time_multiplier(self):
        self.assertAlmostEqual(SC_LAP_TIME_MULTIPLIER, 1.40)

    def test_vsc_lap_time_multiplier(self):
        self.assertAlmostEqual(VSC_LAP_TIME_MULTIPLIER, 1.30)

    def test_sc_duration_min(self):
        self.assertEqual(SC_DURATION_MIN, 3)

    def test_sc_duration_max(self):
        self.assertEqual(SC_DURATION_MAX, 5)

    def test_sc_pit_tyre_age_frac(self):
        self.assertAlmostEqual(SC_PIT_TYRE_AGE_FRAC, 0.55)

    def test_weather_sc_delta_threshold(self):
        self.assertEqual(WEATHER_SC_DELTA_THRESHOLD, 15)

    def test_weather_sc_sudden_prob(self):
        self.assertAlmostEqual(WEATHER_SC_SUDDEN_PROB, 0.30)

    def test_weather_sc_aquaplane_thresh(self):
        self.assertEqual(WEATHER_SC_AQUAPLANE_THRESH, 90)

    def test_weather_sc_aquaplane_prob(self):
        self.assertAlmostEqual(WEATHER_SC_AQUAPLANE_PROB, 0.35)


# ── check_safety_car ─────────────────────────────────────────────────────────

class TestCheckSafetyCarReturnType(unittest.TestCase):
    """Verify return value types and values."""

    def test_returns_str_or_none(self):
        """Should return "SC", "VSC", or None."""
        random.seed(42)
        for _ in range(100):
            result = check_safety_car()
            self.assertIn(result, ["SC", "VSC", None])

    def test_never_returns_other_strings(self):
        """Should only return exactly "SC", "VSC", or None."""
        random.seed(123)
        results = {check_safety_car() for _ in range(500)}
        allowed = {"SC", "VSC", None}
        self.assertTrue(results.issubset(allowed))


class TestCheckSafetyCarProbability(unittest.TestCase):
    """Verify probability distribution over many rolls."""

    def test_sc_frequency_approximately_correct(self):
        """Over 1000 rolls, "SC" should appear ~50% of the time."""
        random.seed(0)
        rolls = [check_safety_car() for _ in range(1000)]
        sc_count = sum(1 for r in rolls if r == "SC")
        frequency = sc_count / 1000

        # Allow tolerance of ±5% from expected 50%
        self.assertGreater(frequency, 0.45)
        self.assertLess(frequency, 0.55)

    def test_vsc_frequency_approximately_correct(self):
        """Over 1000 rolls, "VSC" should appear ~25% of the time."""
        random.seed(1)
        rolls = [check_safety_car() for _ in range(1000)]
        vsc_count = sum(1 for r in rolls if r == "VSC")
        frequency = vsc_count / 1000

        # Allow tolerance of ±3% from expected 25%
        self.assertGreater(frequency, 0.22)
        self.assertLess(frequency, 0.28)

    def test_none_frequency_approximately_correct(self):
        """Over 1000 rolls, None should appear ~25% of the time."""
        random.seed(2)
        rolls = [check_safety_car() for _ in range(1000)]
        none_count = sum(1 for r in rolls if r is None)
        frequency = none_count / 1000

        # Allow tolerance of ±3% from expected 25%
        self.assertGreater(frequency, 0.22)
        self.assertLess(frequency, 0.28)

    def test_sc_and_vsc_mutually_exclusive(self):
        """On any single roll, cannot get both SC and VSC."""
        random.seed(3)
        for _ in range(500):
            result = check_safety_car()
            # Only one of the three outcomes per roll
            self.assertIn(result, ["SC", "VSC", None])


# ── should_trigger_weather_sc ────────────────────────────────────────────────

class TestShouldTriggerWeatherSc(unittest.TestCase):
    """Test weather-triggered safety car logic."""

    def _make_state(self, **kwargs):
        """Create a WeatherState with defaults."""
        defaults = dict(
            rain_prob=50.0,
            weather_sc_fired=False,
        )
        defaults.update(kwargs)
        return WeatherState(**defaults)

    def test_returns_none_when_sc_already_fired(self):
        """If weather_sc_fired=True, always return None regardless of conditions."""
        state = self._make_state(weather_sc_fired=True)
        random.seed(0)
        # Even with large rain delta and aquaplaning conditions
        result = should_trigger_weather_sc(state, rain_prob=95.0, prev_rain_prob=50.0, lap=10, total_laps=50)
        self.assertIsNone(result)

    def test_returns_none_in_last_three_laps(self):
        """If lap >= total_laps - 3, return None (safety car won't deploy near end)."""
        state = self._make_state()
        total_laps = 50
        # Test all last-3 lap scenarios
        for lap in [47, 48, 49]:
            result = should_trigger_weather_sc(state, rain_prob=95.0, prev_rain_prob=10.0, lap=lap, total_laps=total_laps)
            self.assertIsNone(result)

    def test_returns_none_before_last_three_laps(self):
        """If lap < total_laps - 3, SC *can* be triggered (depending on conditions)."""
        state = self._make_state()
        total_laps = 50
        # Lap 46 is before the final 3
        self.assertLess(46, total_laps - 3)
        # With enough rain delta, should have a chance to return "SC" (depends on random roll)
        # We test by running many times and checking that at least some return "SC"
        random.seed(42)
        results = []
        for _ in range(100):
            result = should_trigger_weather_sc(
                state, rain_prob=95.0, prev_rain_prob=10.0, lap=46, total_laps=total_laps
            )
            results.append(result)
        # Should see at least some "SC" results (not all None)
        self.assertTrue(any(r == "SC" for r in results))

    def test_large_rain_delta_triggers_sc(self):
        """Rain delta > WEATHER_SC_DELTA_THRESHOLD (15) can trigger SC."""
        state = self._make_state()
        # Delta = 70 - 20 = 50, far exceeds threshold of 15
        random.seed(42)
        results = []
        for _ in range(100):
            result = should_trigger_weather_sc(
                state, rain_prob=70.0, prev_rain_prob=20.0, lap=10, total_laps=50
            )
            results.append(result)
        # Should see at least some "SC" (based on WEATHER_SC_SUDDEN_PROB=0.30 chance)
        self.assertTrue(any(r == "SC" for r in results))

    def test_small_rain_delta_no_trigger(self):
        """Rain delta <= threshold should not trigger SC from delta alone."""
        state = self._make_state()
        # Delta = 14, below threshold of 15, and rain still below aquaplane threshold
        random.seed(0)
        result = should_trigger_weather_sc(
            state, rain_prob=40.0, prev_rain_prob=26.0, lap=10, total_laps=50
        )
        self.assertIsNone(result)

    def test_aquaplaning_threshold_triggers_sc(self):
        """Crossing aquaplane threshold (90) can trigger SC."""
        state = self._make_state()
        # Rain crosses from 85 to 95, crossing WEATHER_SC_AQUAPLANE_THRESH=90
        random.seed(42)
        results = []
        for _ in range(100):
            result = should_trigger_weather_sc(
                state, rain_prob=95.0, prev_rain_prob=85.0, lap=10, total_laps=50
            )
            results.append(result)
        # Should see some "SC" results due to aquaplaning (WEATHER_SC_AQUAPLANE_PROB=0.35)
        self.assertTrue(any(r == "SC" for r in results))

    def test_below_aquaplane_no_aquaplane_trigger(self):
        """If rain stays below aquaplane threshold, aquaplaning trigger doesn't apply."""
        state = self._make_state()
        # Rain goes from 75 to 80, delta = 5, below WEATHER_SC_DELTA_THRESHOLD=15
        # Both below WEATHER_SC_AQUAPLANE_THRESH=90, so no aquaplaning trigger
        result = should_trigger_weather_sc(
            state, rain_prob=80.0, prev_rain_prob=75.0, lap=10, total_laps=50
        )
        self.assertIsNone(result)


# ── should_recommend_sc_pit ──────────────────────────────────────────────────

class TestShouldRecommendScPit(unittest.TestCase):
    """Test pit recommendation logic under safety car."""

    def test_below_threshold_no_pit(self):
        """tyre_age <= life * 0.55 should recommend no pit."""
        base_life = 20
        threshold_age = int(base_life * SC_PIT_TYRE_AGE_FRAC)  # 11
        result = should_recommend_sc_pit(tyre_age=threshold_age, base_life=base_life)
        self.assertFalse(result)

    def test_above_threshold_pit(self):
        """tyre_age > life * 0.55 should recommend pit."""
        base_life = 20
        threshold_age = int(base_life * SC_PIT_TYRE_AGE_FRAC)  # 11
        result = should_recommend_sc_pit(tyre_age=threshold_age + 1, base_life=base_life)
        self.assertTrue(result)

    def test_fresh_tyres_no_pit(self):
        """Fresh tyres (age=1) should not recommend pit."""
        result = should_recommend_sc_pit(tyre_age=1, base_life=20)
        self.assertFalse(result)

    def test_half_worn_tyres_no_pit(self):
        """Tyres at 50% wear (age=10, life=20) should not recommend pit."""
        result = should_recommend_sc_pit(tyre_age=10, base_life=20)
        self.assertFalse(result)

    def test_heavily_worn_tyres_pit(self):
        """Heavily worn tyres (age=16, life=20) should recommend pit."""
        result = should_recommend_sc_pit(tyre_age=16, base_life=20)
        self.assertTrue(result)

    def test_very_worn_tyres_pit(self):
        """Near-end-of-life tyres should definitely recommend pit."""
        result = should_recommend_sc_pit(tyre_age=25, base_life=20)
        self.assertTrue(result)

    def test_zero_life_edge_case(self):
        """If base_life=0, threshold is 0; any age > 0 recommends pit."""
        # This is an edge case; real tyres always have positive life
        result = should_recommend_sc_pit(tyre_age=0, base_life=0)
        self.assertFalse(result)

    def test_different_tyre_compounds(self):
        """Test with different tyre life values (soft vs hard)."""
        # Soft tyres: typically shorter life (e.g., 15 laps)
        soft_life = 15
        soft_threshold = soft_life * SC_PIT_TYRE_AGE_FRAC  # ~8.25
        # At age 9, should pit
        self.assertTrue(should_recommend_sc_pit(tyre_age=9, base_life=soft_life))

        # Hard tyres: typically longer life (e.g., 25 laps)
        hard_life = 25
        hard_threshold = hard_life * SC_PIT_TYRE_AGE_FRAC  # ~13.75
        # At age 14, should pit
        self.assertTrue(should_recommend_sc_pit(tyre_age=14, base_life=hard_life))

        # At age 13, should not pit
        self.assertFalse(should_recommend_sc_pit(tyre_age=13, base_life=hard_life))

    def test_returns_bool(self):
        """Always returns a boolean."""
        for age in [0, 5, 10, 20, 50]:
            result = should_recommend_sc_pit(tyre_age=age, base_life=20)
            self.assertIsInstance(result, bool)


if __name__ == "__main__":
    unittest.main()
