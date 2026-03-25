"""Tests for engine/core/dnf.py"""
import random
import unittest

from engine.core.dnf import (
    MECH_FAILURE_RATE,
    CTRL_LOSS_RATE,
    TYRE_OVERRUN_RATE,
    TYRE_OVERRUN_MAX_PROB,
    TYRE_DNF_REASONS,
    COLLISION_RETIRE_PROB,
    COLLISION_DAMAGE_MIN_S,
    COLLISION_DAMAGE_MAX_S,
    COLLISION_AGGRESSION_SCALE,
    RETIREMENT_AGE_PROBS,
    mechanical_dnf_probability,
    tyre_failure_probability,
    collision_probability,
    retirement_probability,
    roll_mechanical_dnf,
    roll_tyre_dnf,
    roll_collision_outcome,
    roll_retirement,
)
from engine.race_models import DNF_REASONS


class FakeCar:
    """Mid-grid car: reliability=70, pit_crew=80."""
    reliability = 70
    pit_crew = 80


class FakeCarPerfect:
    """Ideal car: nothing breaks."""
    reliability = 100
    pit_crew = 90


class FakeDriver:
    """Mid-grid driver: car_control=60, aggression=50."""
    car_control = 60
    aggression = 50


class FakeDriverAggressive:
    aggression = 100


class FakeDriverPacifist:
    aggression = 0


# ── Constants ─────────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):
    def test_mech_failure_rate(self):
        self.assertAlmostEqual(MECH_FAILURE_RATE, 0.0015)

    def test_ctrl_loss_rate(self):
        self.assertAlmostEqual(CTRL_LOSS_RATE, 0.0008)

    def test_tyre_overrun_rate(self):
        self.assertAlmostEqual(TYRE_OVERRUN_RATE, 0.008)

    def test_tyre_overrun_max_prob(self):
        self.assertAlmostEqual(TYRE_OVERRUN_MAX_PROB, 0.05)

    def test_collision_retire_prob(self):
        self.assertAlmostEqual(COLLISION_RETIRE_PROB, 0.40)

    def test_collision_damage_range_ordered(self):
        self.assertLess(COLLISION_DAMAGE_MIN_S, COLLISION_DAMAGE_MAX_S)

    def test_collision_aggression_scale(self):
        self.assertAlmostEqual(COLLISION_AGGRESSION_SCALE, 0.025)

    def test_retirement_brackets_descending(self):
        ages = [age for age, _ in RETIREMENT_AGE_PROBS]
        self.assertEqual(ages, sorted(ages, reverse=True))

    def test_tyre_dnf_reasons_not_empty(self):
        self.assertGreater(len(TYRE_DNF_REASONS), 0)


# ── mechanical_dnf_probability ────────────────────────────────────────────────

class TestMechanicalDnfProbability(unittest.TestCase):
    def test_formula_matches_hand_calc(self):
        car = FakeCar()        # reliability=70
        driver = FakeDriver()  # car_control=60
        expected = (100 - 70) / 100 * MECH_FAILURE_RATE + (100 - 60) / 100 * CTRL_LOSS_RATE
        self.assertAlmostEqual(mechanical_dnf_probability(driver, car), expected)

    def test_perfect_car_and_driver(self):
        class PerfectCar:
            reliability = 100
        class PerfectDriver:
            car_control = 100
        self.assertAlmostEqual(mechanical_dnf_probability(PerfectDriver(), PerfectCar()), 0.0)

    def test_increases_with_lower_reliability(self):
        class GoodCar:
            reliability = 90
        class BadCar:
            reliability = 50
        driver = FakeDriver()
        self.assertLess(
            mechanical_dnf_probability(driver, GoodCar()),
            mechanical_dnf_probability(driver, BadCar()),
        )

    def test_increases_with_lower_car_control(self):
        class CarefulDriver:
            car_control = 90
        class ClumsiDriver:
            car_control = 40
        car = FakeCar()
        self.assertLess(
            mechanical_dnf_probability(CarefulDriver(), car),
            mechanical_dnf_probability(ClumsiDriver(), car),
        )

    def test_probability_is_positive(self):
        self.assertGreater(mechanical_dnf_probability(FakeDriver(), FakeCar()), 0.0)

    def test_probability_is_small_per_lap(self):
        # Even a terrible car should fail less than 1% per lap
        class TerribleCar:
            reliability = 0
        class TerribleDriver:
            car_control = 0
        p = mechanical_dnf_probability(TerribleDriver(), TerribleCar())
        self.assertLess(p, 0.01)


# ── tyre_failure_probability ──────────────────────────────────────────────────

class TestTyreFailureProbability(unittest.TestCase):
    def test_zero_within_life(self):
        self.assertEqual(tyre_failure_probability(10, 15), 0.0)

    def test_zero_at_exact_life(self):
        self.assertEqual(tyre_failure_probability(15, 15), 0.0)

    def test_one_overrun_lap(self):
        self.assertAlmostEqual(tyre_failure_probability(16, 15), TYRE_OVERRUN_RATE)

    def test_grows_linearly_with_overrun(self):
        for overrun in range(1, 5):
            expected = overrun * TYRE_OVERRUN_RATE
            self.assertAlmostEqual(tyre_failure_probability(15 + overrun, 15), expected)

    def test_capped_at_max(self):
        # Cap hits at ceil(TYRE_OVERRUN_MAX_PROB / TYRE_OVERRUN_RATE) overrun laps
        self.assertEqual(tyre_failure_probability(100, 15), TYRE_OVERRUN_MAX_PROB)

    def test_cap_value(self):
        # The cap should be exactly 5%
        self.assertAlmostEqual(TYRE_OVERRUN_MAX_PROB, 0.05)

    def test_zero_age_with_zero_life_edge_case(self):
        # Should not divide by zero
        self.assertEqual(tyre_failure_probability(0, 0), 0.0)


# ── collision_probability ─────────────────────────────────────────────────────

class TestCollisionProbability(unittest.TestCase):
    def test_formula_matches_hand_calc(self):
        attacker = FakeDriverAggressive()  # aggression=100
        defender = FakeDriver()            # aggression=50
        expected = (100 / 100) * (50 / 100) * COLLISION_AGGRESSION_SCALE
        self.assertAlmostEqual(collision_probability(attacker, defender), expected)

    def test_zero_aggression_means_no_collision(self):
        self.assertAlmostEqual(
            collision_probability(FakeDriverPacifist(), FakeDriver()), 0.0
        )

    def test_symmetric_for_equal_aggression(self):
        class D:
            aggression = 70
        self.assertAlmostEqual(
            collision_probability(D(), D()),
            collision_probability(D(), D()),
        )

    def test_max_aggression(self):
        expected = 1.0 * 1.0 * COLLISION_AGGRESSION_SCALE
        self.assertAlmostEqual(
            collision_probability(FakeDriverAggressive(), FakeDriverAggressive()),
            expected,
        )

    def test_probability_is_small(self):
        # Even two maximally aggressive drivers should collide < 5% of duels
        p = collision_probability(FakeDriverAggressive(), FakeDriverAggressive())
        self.assertLess(p, 0.05)


# ── retirement_probability ────────────────────────────────────────────────────

class TestRetirementProbability(unittest.TestCase):
    def test_below_35_is_zero(self):
        for age in (18, 25, 30, 34):
            with self.subTest(age=age):
                self.assertEqual(retirement_probability(age), 0.0)

    def test_age_35_bracket(self):
        self.assertAlmostEqual(retirement_probability(35), 0.05)

    def test_age_38_bracket(self):
        self.assertAlmostEqual(retirement_probability(38), 0.18)

    def test_age_40_bracket(self):
        self.assertAlmostEqual(retirement_probability(40), 0.40)

    def test_age_42_bracket(self):
        self.assertAlmostEqual(retirement_probability(42), 0.65)

    def test_very_old_uses_highest_bracket(self):
        self.assertAlmostEqual(retirement_probability(55), 0.65)

    def test_increases_with_age(self):
        probs = [retirement_probability(a) for a in (34, 35, 38, 40, 42)]
        self.assertEqual(probs, sorted(probs))

    def test_first_matching_bracket_used(self):
        # age 39: matches >=38 first (not >=40), so should be 0.18
        self.assertAlmostEqual(retirement_probability(39), 0.18)

    def test_all_brackets_covered(self):
        expected = {0.05, 0.18, 0.40, 0.65}
        actual = {prob for _, prob in RETIREMENT_AGE_PROBS}
        self.assertEqual(actual, expected)


# ── roll helpers ──────────────────────────────────────────────────────────────

class TestRollMechanicalDnf(unittest.TestCase):
    def test_returns_none_or_string(self):
        random.seed(42)
        results = {roll_mechanical_dnf(FakeDriver(), FakeCar()) for _ in range(100)}
        allowed = set(DNF_REASONS) | {None}
        self.assertTrue(results.issubset(allowed))

    def test_perfect_car_never_fails_in_sample(self):
        random.seed(0)
        class Perfect:
            reliability = 100
            car_control = 100
        results = [roll_mechanical_dnf(Perfect(), Perfect()) for _ in range(1000)]
        self.assertTrue(all(r is None for r in results))


class TestRollTyreDnf(unittest.TestCase):
    def test_no_failure_within_life(self):
        random.seed(0)
        results = [roll_tyre_dnf(10, 15) for _ in range(1000)]
        self.assertTrue(all(r is None for r in results))

    def test_returns_valid_reason_or_none_on_overrun(self):
        random.seed(7)
        results = {roll_tyre_dnf(22, 15) for _ in range(200)}
        allowed = set(TYRE_DNF_REASONS) | {None}
        self.assertTrue(results.issubset(allowed))

    def test_failure_occurs_occasionally_when_past_life(self):
        random.seed(5)
        results = [roll_tyre_dnf(22, 15) for _ in range(500)]
        self.assertTrue(any(r is not None for r in results))


class TestRollCollisionOutcome(unittest.TestCase):
    def test_return_shape(self):
        random.seed(0)
        for _ in range(20):
            retired, damage = roll_collision_outcome()
            self.assertIsInstance(retired, bool)
            self.assertIsInstance(damage, float)

    def test_damage_is_zero_when_retired(self):
        random.seed(0)
        for _ in range(200):
            retired, damage = roll_collision_outcome()
            if retired:
                self.assertEqual(damage, 0.0)

    def test_damage_in_valid_range_when_not_retired(self):
        random.seed(0)
        for _ in range(500):
            retired, damage = roll_collision_outcome()
            if not retired:
                self.assertGreaterEqual(damage, COLLISION_DAMAGE_MIN_S)
                self.assertLessEqual(damage, COLLISION_DAMAGE_MAX_S)

    def test_retire_rate_approximately_correct(self):
        random.seed(42)
        retired_count = sum(roll_collision_outcome()[0] for _ in range(2000))
        self.assertAlmostEqual(retired_count / 2000, COLLISION_RETIRE_PROB, delta=0.05)


class TestRollRetirement(unittest.TestCase):
    def test_age_below_35_always_false(self):
        random.seed(0)
        for age in (18, 25, 30, 34):
            results = [roll_retirement(age) for _ in range(200)]
            self.assertTrue(all(r is False for r in results))

    def test_age_42_retires_frequently(self):
        random.seed(1)
        results = [roll_retirement(42) for _ in range(500)]
        rate = sum(results) / 500
        self.assertAlmostEqual(rate, 0.65, delta=0.06)

    def test_higher_age_retires_more_often(self):
        random.seed(2)
        rate_35 = sum(roll_retirement(35) for _ in range(1000)) / 1000
        rate_42 = sum(roll_retirement(42) for _ in range(1000)) / 1000
        self.assertLess(rate_35, rate_42)


if __name__ == "__main__":
    unittest.main()
