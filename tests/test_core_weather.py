"""Tests for engine/core/weather.py"""
import random
import unittest

from engine.core.weather import (
    _lerp,
    check_safety_car,
    compound_pace_delta,
    wet_weather_weight,
    generate_weather_forecast,
    WeatherState,
    init_weather_state,
    step_rain_probability,
    weather_event_messages,
    get_rain_trend,
    detect_weather_threshold,
    should_trigger_weather_sc,
    trim_strategy_to_remaining,
    should_recommend_sc_pit,
    RAIN_WARNING, RAIN_DAMP, RAIN_WET_ONSET, RAIN_HEAVY,
    WEATHER_SC_DELTA_THRESHOLD, WEATHER_SC_AQUAPLANE_THRESH,
    SC_PIT_TYRE_AGE_FRAC,
)
from engine.core.tyres import TyreStint, RaceStrategy
from engine.weather import (
    _weather_compound_delta as old_compound_delta,
    _effective_wet_weight as old_wet_weight,
)


class FakeCircuit:
    weather_chance = 0
    length_km = 5.3
    tire_wear = "medium"
    overtaking_difficulty = 50
    pit_lane_loss = 22.0


class FakeCircuitWet(FakeCircuit):
    weather_chance = 100


# ── _lerp ─────────────────────────────────────────────────────────────────────

class TestLerp(unittest.TestCase):
    def test_at_zero(self):
        self.assertAlmostEqual(_lerp(0, 10, 0.0), 0.0)

    def test_at_one(self):
        self.assertAlmostEqual(_lerp(0, 10, 1.0), 10.0)

    def test_midpoint(self):
        self.assertAlmostEqual(_lerp(0, 10, 0.5), 5.0)

    def test_negative_range(self):
        self.assertAlmostEqual(_lerp(10, 0, 0.25), 7.5)


# ── check_safety_car ──────────────────────────────────────────────────────────

class TestCheckSafetyCar(unittest.TestCase):
    def test_return_values(self):
        results = {check_safety_car() for _ in range(500)}
        self.assertTrue(results.issubset({"SC", "VSC", None}))

    def test_distribution(self):
        random.seed(0)
        counts = {"SC": 0, "VSC": 0, None: 0}
        for _ in range(10_000):
            counts[check_safety_car()] += 1
        # SC ≈ 50%, VSC ≈ 25%, None ≈ 25%
        self.assertAlmostEqual(counts["SC"] / 10_000, 0.50, delta=0.03)
        self.assertAlmostEqual(counts["VSC"] / 10_000, 0.25, delta=0.03)


# ── compound_pace_delta ───────────────────────────────────────────────────────

class TestCompoundPaceDelta(unittest.TestCase):
    RAIN_VALUES = [0, 20, 40, 50, 55, 60, 65, 70, 75, 80, 85, 90, 92, 95, 100]
    COMPOUNDS   = ["soft", "medium", "hard", "intermediate", "wet"]

    def test_parity_with_old_function(self):
        for cmp in self.COMPOUNDS:
            for rp in self.RAIN_VALUES:
                with self.subTest(compound=cmp, rain=rp):
                    self.assertAlmostEqual(
                        compound_pace_delta(cmp, rp),
                        old_compound_delta(cmp, rp),
                        places=9,
                    )

    def test_slick_no_penalty_when_dry(self):
        from engine.core.tyres import COMPOUND_PACE_DELTA
        for cmp in ("soft", "medium", "hard"):
            with self.subTest(compound=cmp):
                self.assertAlmostEqual(
                    compound_pace_delta(cmp, 0), COMPOUND_PACE_DELTA[cmp]
                )

    def test_slick_penalty_increases_with_rain(self):
        p_dry  = compound_pace_delta("soft", 0)
        p_damp = compound_pace_delta("soft", 70)
        p_wet  = compound_pace_delta("soft", 100)
        self.assertLess(p_dry, p_damp)
        self.assertLess(p_damp, p_wet)

    def test_intermediate_optimal_window(self):
        # Intermediates are fastest between RAIN_DAMP and RAIN_HEAVY
        p_dry  = compound_pace_delta("intermediate", 0)
        p_opt  = compound_pace_delta("intermediate", 75)
        self.assertGreater(p_dry, p_opt)

    def test_wet_tyre_optimal_at_heavy_rain(self):
        p_dry  = compound_pace_delta("wet", 0)
        p_heavy = compound_pace_delta("wet", 100)
        self.assertGreater(p_dry, p_heavy)

    def test_unknown_compound_returns_zero(self):
        self.assertEqual(compound_pace_delta("unknown_cmp", 50), 0.0)


# ── wet_weather_weight ────────────────────────────────────────────────────────

class TestWetWeatherWeight(unittest.TestCase):
    RAIN_VALUES = [0, 20, 40, 50, 60, 65, 70, 80, 90, 100]

    def test_parity_with_old_function(self):
        for rp in self.RAIN_VALUES:
            with self.subTest(rain=rp):
                self.assertAlmostEqual(
                    wet_weather_weight(rp), old_wet_weight(rp), places=9
                )

    def test_zero_at_low_rain(self):
        self.assertEqual(wet_weather_weight(0), 0.0)
        self.assertEqual(wet_weather_weight(40), 0.0)

    def test_increases_monotonically(self):
        prev = 0.0
        for rp in range(40, 101, 5):
            w = wet_weather_weight(rp)
            self.assertGreaterEqual(w, prev)
            prev = w

    def test_capped_near_085(self):
        self.assertLessEqual(wet_weather_weight(100), 0.85 + 1e-9)
        self.assertGreater(wet_weather_weight(100), 0.80)


# ── generate_weather_forecast ─────────────────────────────────────────────────

class TestGenerateWeatherForecast(unittest.TestCase):
    def _call(self, rain_prob=50.0, rain_decreasing=False, rise_rate=8.0,
              decay_rate=6.0, front_arrival_lap=5, current_lap=1):
        return generate_weather_forecast(
            rain_prob, rain_decreasing, rise_rate, decay_rate,
            front_arrival_lap, current_lap,
        )

    def test_returns_15_values(self):
        self.assertEqual(len(self._call()), 15)

    def test_all_values_in_range(self):
        random.seed(42)
        for _ in range(20):
            for v in self._call():
                self.assertGreaterEqual(v, 0.0)
                self.assertLessEqual(v, 100.0)

    def test_rising_trend_positive_average(self):
        random.seed(1)
        fc = self._call(rain_prob=30, rise_rate=12, rain_decreasing=False, current_lap=1, front_arrival_lap=1)
        self.assertGreater(sum(fc) / len(fc), 30)

    def test_falling_trend_decreasing_average(self):
        random.seed(2)
        fc = self._call(rain_prob=80, rain_decreasing=True, decay_rate=8)
        self.assertLess(sum(fc) / len(fc), 80)


# ── WeatherState ──────────────────────────────────────────────────────────────

class TestWeatherState(unittest.TestCase):
    def test_default_thresholds(self):
        ws = WeatherState(rain_prob=0.0)
        self.assertEqual(
            ws.thresholds_crossed,
            {"warning": False, "damp": False, "wet": False, "drying": False},
        )

    def test_wet_start_defaults(self):
        ws = WeatherState(rain_prob=85.0, wet_start=True)
        self.assertTrue(ws.wet_start)
        self.assertEqual(ws.rain_prob, 85.0)

    def test_thresholds_are_independent_per_instance(self):
        ws1 = WeatherState(rain_prob=0.0)
        ws2 = WeatherState(rain_prob=0.0)
        ws1.thresholds_crossed["wet"] = True
        self.assertFalse(ws2.thresholds_crossed["wet"])


# ── init_weather_state ────────────────────────────────────────────────────────

class TestInitWeatherState(unittest.TestCase):
    def test_dry_no_chance(self):
        random.seed(0)
        circuit = FakeCircuit()   # weather_chance = 0
        ws = init_weather_state("dry", circuit, 50)
        self.assertEqual(ws.rain_prob, 0.0)
        self.assertFalse(ws.front_active)
        self.assertFalse(ws.wet_start)

    def test_wet_start(self):
        random.seed(0)
        ws = init_weather_state("wet", FakeCircuit(), 50)
        self.assertEqual(ws.rain_prob, 85.0)
        self.assertTrue(ws.wet_start)

    def test_dry_with_guaranteed_rain(self):
        random.seed(42)
        circuit = FakeCircuitWet()   # weather_chance = 100
        ws = init_weather_state("dry", circuit, 50)
        self.assertTrue(ws.front_active)
        self.assertGreater(ws.front_rise_rate, 0)
        earliest = max(3, int(50 * 0.15))
        latest   = max(earliest + 1, min(50 - 5, int(50 * 0.85)))
        self.assertGreaterEqual(ws.front_arrival_lap, earliest)
        self.assertLessEqual(ws.front_arrival_lap, latest)

    def test_wet_may_schedule_drying_front(self):
        # With seed that triggers the 50% chance
        random.seed(0)
        count_active = sum(
            init_weather_state("wet", FakeCircuit(), 50).front_active
            for _ in range(100)
        )
        # Should be active roughly 50% of the time
        self.assertGreater(count_active, 30)
        self.assertLess(count_active, 70)


# ── step_rain_probability ─────────────────────────────────────────────────────

class TestStepRainProbability(unittest.TestCase):
    def _state_with_rising_front(self, lap_offset=0):
        ws = WeatherState(rain_prob=0.0)
        ws.front_active = True
        ws.front_arrival_lap = 1
        ws.front_rise_rate = 10.0
        ws.front_decay_rate = 5.0
        ws.peak_duration = 5
        return ws

    def test_returns_prev_and_messages(self):
        ws = WeatherState(rain_prob=30.0)
        ws.front_active = True
        ws.front_arrival_lap = 1
        ws.front_rise_rate = 8.0
        random.seed(0)
        prev, msgs = step_rain_probability(ws, lap=1)
        self.assertIsInstance(prev, float)
        self.assertIsInstance(msgs, list)

    def test_prev_is_pre_step_value(self):
        ws = WeatherState(rain_prob=42.0)
        ws.front_active = True
        ws.front_rise_rate = 5.0
        ws.front_arrival_lap = 1
        random.seed(1)
        prev, _ = step_rain_probability(ws, lap=1)
        self.assertAlmostEqual(prev, 42.0)

    def test_rain_prob_stays_in_range(self):
        random.seed(99)
        ws = WeatherState(rain_prob=95.0)
        ws.front_active = True
        ws.front_arrival_lap = 1
        ws.front_rise_rate = 20.0
        for lap in range(1, 20):
            step_rain_probability(ws, lap)
            self.assertGreaterEqual(ws.rain_prob, 0.0)
            self.assertLessEqual(ws.rain_prob, 100.0)

    def test_cooldown_decrements(self):
        ws = WeatherState(rain_prob=0.0, warning_cooldown=3)
        step_rain_probability(ws, lap=1)
        self.assertEqual(ws.warning_cooldown, 2)

    def test_threshold_reset_after_3_dry_laps(self):
        ws = WeatherState(rain_prob=40.0)
        ws.thresholds_crossed["wet"] = True
        ws.episode_below_60_count = 0
        # Three laps below 60
        for lap in range(1, 4):
            step_rain_probability(ws, lap)
        self.assertFalse(any(ws.thresholds_crossed.values()))

    def test_no_rise_before_front_arrival(self):
        ws = WeatherState(rain_prob=0.0)
        ws.front_active = True
        ws.front_arrival_lap = 20
        ws.front_rise_rate = 10.0
        random.seed(0)
        for lap in range(1, 10):
            step_rain_probability(ws, lap)
        # Rain should remain 0 until lap 20
        self.assertEqual(ws.rain_prob, 0.0)


# ── weather_event_messages ────────────────────────────────────────────────────

class TestWeatherEventMessages(unittest.TestCase):
    def test_no_front_returns_empty(self):
        msgs = weather_event_messages(5, 60, 54, False, front_active=False)
        self.assertEqual(msgs, [])

    def test_approaching_at_warning_threshold(self):
        msgs = weather_event_messages(5, RAIN_WARNING + 1, RAIN_WARNING - 1, False, True)
        self.assertTrue(any("approaching" in m for m in msgs))

    def test_damp_at_damp_threshold(self):
        msgs = weather_event_messages(8, RAIN_DAMP + 1, RAIN_DAMP - 1, False, True)
        self.assertTrue(any("damp" in m.lower() for m in msgs))

    def test_heavy_rain_at_heavy_threshold(self):
        msgs = weather_event_messages(12, RAIN_HEAVY + 1, RAIN_HEAVY - 1, False, True)
        self.assertTrue(any("HEAVY RAIN" in m for m in msgs))

    def test_only_one_rising_threshold_fires(self):
        # Crossing from 64 to 93 in one lap: only damp fires (first elif)
        msgs = weather_event_messages(5, 93, 64, False, True)
        self.assertEqual(len([m for m in msgs if "HEAVY" in m or "damp" in m.lower() or "approaching" in m]), 1)

    def test_drying_message_when_falling_below_warning(self):
        msgs = weather_event_messages(20, RAIN_WARNING - 1, RAIN_WARNING + 1, True, True)
        self.assertTrue(any("drying" in m.lower() for m in msgs))

    def test_easing_message_when_falling_below_70(self):
        msgs = weather_event_messages(15, 69, 71, True, True)
        self.assertTrue(any("easing" in m.lower() for m in msgs))

    def test_no_message_when_no_crossing(self):
        msgs = weather_event_messages(5, 50, 48, False, True)
        self.assertEqual(msgs, [])


# ── get_rain_trend ────────────────────────────────────────────────────────────

class TestGetRainTrend(unittest.TestCase):
    def test_falling(self):
        ws = WeatherState(rain_prob=70.0, rain_decreasing=True)
        self.assertEqual(get_rain_trend(ws, lap=10), "falling")

    def test_rising(self):
        ws = WeatherState(rain_prob=20.0)
        ws.front_active = True
        ws.front_arrival_lap = 5
        ws.front_rise_rate = 8.0
        self.assertEqual(get_rain_trend(ws, lap=10), "rising")

    def test_stable_before_front_arrival(self):
        ws = WeatherState(rain_prob=0.0)
        ws.front_active = True
        ws.front_arrival_lap = 20
        ws.front_rise_rate = 8.0
        self.assertEqual(get_rain_trend(ws, lap=5), "stable")

    def test_stable_no_front(self):
        ws = WeatherState(rain_prob=0.0)
        self.assertEqual(get_rain_trend(ws, lap=1), "stable")


# ── detect_weather_threshold ──────────────────────────────────────────────────

class TestDetectWeatherThreshold(unittest.TestCase):
    def _fresh_state(self):
        return WeatherState(rain_prob=0.0)

    def test_warning_at_threshold(self):
        ws = self._fresh_state()
        self.assertEqual(detect_weather_threshold(ws, RAIN_WARNING + 1, RAIN_WARNING - 1), "warning")

    def test_damp_when_warning_already_crossed(self):
        ws = self._fresh_state()
        ws.thresholds_crossed["warning"] = True
        self.assertEqual(detect_weather_threshold(ws, RAIN_DAMP + 1, RAIN_DAMP - 1), "damp")

    def test_damp_without_warning(self):
        # Damp fires independently if crossed before warning (e.g. fast rain rise)
        ws = self._fresh_state()
        self.assertEqual(detect_weather_threshold(ws, RAIN_DAMP + 1, RAIN_DAMP - 1), "damp")

    def test_wet_at_heavy_rain(self):
        ws = self._fresh_state()
        ws.thresholds_crossed.update({"warning": True, "damp": True})
        self.assertEqual(detect_weather_threshold(ws, RAIN_HEAVY + 1, RAIN_HEAVY - 1), "wet")

    def test_drying_when_falling_below_damp(self):
        ws = WeatherState(rain_prob=64.0, rain_decreasing=True, peak_rain_prob=80.0)
        ws.thresholds_crossed.update({"warning": True, "damp": True})
        self.assertEqual(
            detect_weather_threshold(ws, RAIN_DAMP - 1, RAIN_DAMP + 1), "drying"
        )

    def test_none_after_threshold_marked(self):
        ws = self._fresh_state()
        ws.thresholds_crossed["warning"] = True
        ws.thresholds_crossed["damp"] = True
        ws.thresholds_crossed["wet"] = True
        self.assertIsNone(detect_weather_threshold(ws, RAIN_HEAVY + 5, RAIN_HEAVY))

    def test_warning_suppressed_by_cooldown(self):
        ws = self._fresh_state()
        ws.warning_cooldown = 2
        self.assertIsNone(detect_weather_threshold(ws, RAIN_WARNING + 5, RAIN_WARNING - 1))

    def test_warning_suppressed_when_ignored(self):
        ws = self._fresh_state()
        ws.player_ignored_warning = True
        self.assertIsNone(detect_weather_threshold(ws, RAIN_WARNING + 5, RAIN_WARNING - 1))

    def test_does_not_mutate_state(self):
        ws = self._fresh_state()
        before = dict(ws.thresholds_crossed)
        detect_weather_threshold(ws, RAIN_WARNING + 5, RAIN_WARNING - 1)
        self.assertEqual(ws.thresholds_crossed, before)


# ── should_trigger_weather_sc ─────────────────────────────────────────────────

class TestShouldTriggerWeatherSc(unittest.TestCase):
    def _fresh_state(self):
        return WeatherState(rain_prob=50.0)

    def test_returns_none_if_already_fired(self):
        ws = self._fresh_state()
        ws.weather_sc_fired = True
        self.assertIsNone(should_trigger_weather_sc(ws, 80, 60, lap=5, total_laps=50))

    def test_returns_none_in_final_laps(self):
        ws = self._fresh_state()
        result = should_trigger_weather_sc(ws, 80, 60, lap=48, total_laps=50)
        self.assertIsNone(result)

    def test_sc_on_sudden_large_delta(self):
        random.seed(0)
        ws = self._fresh_state()
        triggered = any(
            should_trigger_weather_sc(
                ws, 80, 80 - WEATHER_SC_DELTA_THRESHOLD - 1, lap=10, total_laps=50
            ) == "SC"
            for _ in range(100)
        )
        self.assertTrue(triggered)

    def test_sc_on_aquaplane_crossing(self):
        random.seed(3)
        ws = self._fresh_state()
        triggered = any(
            should_trigger_weather_sc(
                ws,
                WEATHER_SC_AQUAPLANE_THRESH + 1,
                WEATHER_SC_AQUAPLANE_THRESH - 1,
                lap=10, total_laps=50,
            ) == "SC"
            for _ in range(100)
        )
        self.assertTrue(triggered)

    def test_does_not_mutate_state(self):
        ws = self._fresh_state()
        ws.weather_sc_fired = False
        should_trigger_weather_sc(ws, 95, 70, lap=5, total_laps=50)
        self.assertFalse(ws.weather_sc_fired)


# ── trim_strategy_to_remaining ────────────────────────────────────────────────

class TestTrimStrategyToRemaining(unittest.TestCase):
    def _strat(self):
        return RaceStrategy(stints=[TyreStint("soft", 10), TyreStint("medium", 10)])

    def test_trim_reduces_total(self):
        result = trim_strategy_to_remaining(self._strat(), 15)
        self.assertEqual(sum(s.laps for s in result.stints), 15)

    def test_extend_increases_total(self):
        result = trim_strategy_to_remaining(self._strat(), 25)
        self.assertEqual(sum(s.laps for s in result.stints), 25)

    def test_exact_match_unchanged(self):
        result = trim_strategy_to_remaining(self._strat(), 20)
        self.assertEqual(sum(s.laps for s in result.stints), 20)

    def test_trim_removes_stints(self):
        strat = RaceStrategy(stints=[
            TyreStint("soft", 10), TyreStint("medium", 10), TyreStint("hard", 10)
        ])
        result = trim_strategy_to_remaining(strat, 12)
        total = sum(s.laps for s in result.stints)
        self.assertEqual(total, 12)

    def test_does_not_mutate_original(self):
        s = self._strat()
        trim_strategy_to_remaining(s, 15)
        self.assertEqual(sum(st.laps for st in s.stints), 20)

    def test_label_preserved(self):
        s = RaceStrategy(stints=[TyreStint("soft", 20)], label="My Strategy")
        result = trim_strategy_to_remaining(s, 15)
        self.assertEqual(result.label, "My Strategy")


# ── should_recommend_sc_pit ───────────────────────────────────────────────────

class TestShouldRecommendScPit(unittest.TestCase):
    def test_recommend_when_over_threshold(self):
        # 12 > 20 * 0.55 = 11.0
        self.assertTrue(should_recommend_sc_pit(12, 20))

    def test_no_recommend_at_threshold(self):
        # 11 == 20 * 0.55 = 11.0 (not strictly greater)
        self.assertFalse(should_recommend_sc_pit(11, 20))

    def test_no_recommend_below_threshold(self):
        self.assertFalse(should_recommend_sc_pit(5, 20))

    def test_threshold_constant_is_correct(self):
        self.assertAlmostEqual(SC_PIT_TYRE_AGE_FRAC, 0.55)


if __name__ == "__main__":
    unittest.main()
