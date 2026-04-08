"""
Tests for engine/core/overtaking.py
Covers _attempt_overtake() and overtaking-related constants.
"""
import random
import unittest
from dataclasses import dataclass

from engine.core.overtaking import (
    _attempt_overtake,
    OVERTAKE_THRESHOLD,
    BATTLE_RANGE_S,
)
from engine.race_models import RaceEntry


# ── Test fixtures ────────────────────────────────────────────────────────────

@dataclass
class MockDriver:
    """Typical driver for overtaking tests."""
    pace: int = 75
    overtaking: int = 70
    defending: int = 70
    aggression: int = 50


@dataclass
class MockCar:
    """Typical car."""
    aerodynamics: int = 75
    engine: int = 75
    mechanical_grip: int = 75


@dataclass
class MockCircuit:
    """Typical circuit."""
    overtaking_difficulty: int = 50
    length_km: float = 5.793


def _make_entry(driver=None, car=None, team_id="t1"):
    """Create a RaceEntry for testing."""
    return RaceEntry(
        driver=driver or MockDriver(),
        car=car or MockCar(),
        team_id=team_id,
        team_name="Test Team",
        team_color="#FF0000",
    )


# ── Constants ────────────────────────────────────────────────────────────────

class TestOvertakingConstants(unittest.TestCase):
    """Verify overtaking-related constants."""

    def test_overtake_threshold(self):
        self.assertAlmostEqual(OVERTAKE_THRESHOLD, 0.5)

    def test_battle_range(self):
        self.assertAlmostEqual(BATTLE_RANGE_S, 1.0)


# ── _attempt_overtake ────────────────────────────────────────────────────────

class TestAttemptOvertakeReturnType(unittest.TestCase):
    """Test return type and structure."""

    def test_returns_tuple_of_two_bools(self):
        """Should return a tuple (success: bool, collision: bool)."""
        random.seed(42)
        faster = _make_entry(driver=MockDriver(pace=90))
        slower = _make_entry(driver=MockDriver(pace=60), team_id="t2")
        circuit = MockCircuit()

        result = _attempt_overtake(faster, slower, circuit, speed_delta=1.5)

        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        success, collision = result
        self.assertIsInstance(success, bool)
        self.assertIsInstance(collision, bool)

    def test_collision_and_success_mutually_exclusive(self):
        """Cannot have both collision=True and success=True."""
        random.seed(0)
        faster = _make_entry()
        slower = _make_entry(team_id="t2")
        circuit = MockCircuit()

        for _ in range(500):
            success, collision = _attempt_overtake(faster, slower, circuit, speed_delta=1.5)
            if collision:
                self.assertFalse(success, "collision=True must imply success=False")

    def test_collision_false_allows_any_success(self):
        """When collision=False, success can be True or False."""
        random.seed(1)
        faster = _make_entry()
        slower = _make_entry(team_id="t2")
        circuit = MockCircuit()

        results = [_attempt_overtake(faster, slower, circuit, speed_delta=1.5) for _ in range(500)]
        non_collision_results = [r for r in results if not r[1]]

        # Should see both success=True and success=False when collision=False
        successes = [success for success, collision in non_collision_results if collision is False]
        self.assertTrue(any(successes), "Should see some successful overtakes")
        self.assertTrue(any(not s for s in successes), "Should see some failed overtakes (without collision)")


class TestAttemptOvertakeAggression(unittest.TestCase):
    """Test aggression impact on collision probability."""

    def test_high_aggression_both_sides_increases_collision(self):
        """High aggression on both attacker and defender increases collision probability."""
        circuit = MockCircuit()

        # Peaceful drivers
        peaceful_attacker = MockDriver(pace=90, aggression=10, overtaking=70, defending=50)
        peaceful_defender = MockDriver(pace=60, aggression=10, overtaking=50, defending=70)
        peaceful_faster = _make_entry(driver=peaceful_attacker)
        peaceful_slower = _make_entry(driver=peaceful_defender, team_id="t2")

        # Aggressive drivers
        aggressive_attacker = MockDriver(pace=90, aggression=100, overtaking=70, defending=50)
        aggressive_defender = MockDriver(pace=60, aggression=100, overtaking=50, defending=70)
        aggressive_faster = _make_entry(driver=aggressive_attacker)
        aggressive_slower = _make_entry(driver=aggressive_defender, team_id="t2")

        random.seed(42)
        peaceful_collisions = sum(
            1 for _ in range(500)
            if _attempt_overtake(peaceful_faster, peaceful_slower, circuit, speed_delta=1.5)[1]
        )

        random.seed(42)
        aggressive_collisions = sum(
            1 for _ in range(500)
            if _attempt_overtake(aggressive_faster, aggressive_slower, circuit, speed_delta=1.5)[1]
        )

        # Aggressive drivers should collide more often
        self.assertGreater(aggressive_collisions, peaceful_collisions)

    def test_zero_aggression_means_no_collision(self):
        """Drivers with zero aggression should never collide."""
        circuit = MockCircuit()
        peaceful_attacker = MockDriver(pace=90, aggression=0)
        peaceful_defender = MockDriver(pace=60, aggression=0)
        faster = _make_entry(driver=peaceful_attacker)
        slower = _make_entry(driver=peaceful_defender, team_id="t2")

        random.seed(0)
        results = [_attempt_overtake(faster, slower, circuit, speed_delta=1.5) for _ in range(200)]
        collisions = sum(1 for _, collision in results if collision)

        self.assertEqual(collisions, 0)

    def test_max_aggression_both_sides_frequent_collisions(self):
        """Max aggression on both sides should produce frequent collisions."""
        circuit = MockCircuit()
        max_aggression_attacker = MockDriver(pace=90, aggression=100)
        max_aggression_defender = MockDriver(pace=60, aggression=100)
        faster = _make_entry(driver=max_aggression_attacker)
        slower = _make_entry(driver=max_aggression_defender, team_id="t2")

        random.seed(0)
        results = [_attempt_overtake(faster, slower, circuit, speed_delta=1.5) for _ in range(500)]
        collisions = sum(1 for _, collision in results if collision)
        collision_rate = collisions / 500

        # Should see collisions at a notable rate (though not all, as formula caps at 0.95)
        self.assertGreater(collision_rate, 0.01)


class TestAttemptOvertakeOvertakingSkill(unittest.TestCase):
    """Test overtaking stat impact on success rate."""

    def test_high_overtaking_stat_increases_success(self):
        """High overtaking stat should increase success rate."""
        circuit = MockCircuit(overtaking_difficulty=50)

        # Poor overtaker
        poor_attacker = MockDriver(pace=90, overtaking=20, defending=50, aggression=50)
        defender = MockDriver(pace=60, overtaking=50, defending=70, aggression=50)
        poor_faster = _make_entry(driver=poor_attacker)
        slower = _make_entry(driver=defender, team_id="t2")

        # Good overtaker
        good_attacker = MockDriver(pace=90, overtaking=95, defending=50, aggression=50)
        good_faster = _make_entry(driver=good_attacker)

        random.seed(42)
        poor_successes = sum(
            1 for success, collision in (
                _attempt_overtake(poor_faster, slower, circuit, speed_delta=1.5)
                for _ in range(500)
            ) if success and not collision
        )

        random.seed(42)
        good_successes = sum(
            1 for success, collision in (
                _attempt_overtake(good_faster, slower, circuit, speed_delta=1.5)
                for _ in range(500)
            ) if success and not collision
        )

        # Good overtaker should succeed more often
        self.assertGreater(good_successes, poor_successes)

    def test_zero_overtaking_stat_low_success(self):
        """Zero overtaking stat should result in very low success rate."""
        circuit = MockCircuit()
        zero_overtaker = MockDriver(pace=90, overtaking=0, defending=50, aggression=10)
        defender = MockDriver(pace=60, overtaking=50, defending=70, aggression=10)
        faster = _make_entry(driver=zero_overtaker)
        slower = _make_entry(driver=defender, team_id="t2")

        random.seed(0)
        results = [_attempt_overtake(faster, slower, circuit, speed_delta=1.5) for _ in range(300)]
        successes = sum(1 for success, collision in results if success and not collision)
        success_rate = successes / 300

        # With 0 overtaking and no aggression collision, success should be rare
        self.assertLess(success_rate, 0.1)


class TestAttemptOvertakeDefendingSkill(unittest.TestCase):
    """Test defending stat impact on success rate."""

    def test_high_defending_stat_reduces_overtake_success(self):
        """Strong defender should make overtaking harder."""
        circuit = MockCircuit()
        attacker = MockDriver(pace=90, overtaking=70, defending=50, aggression=50)

        # Weak defender
        weak_defender = MockDriver(pace=60, overtaking=50, defending=10, aggression=50)
        faster = _make_entry(driver=attacker)
        slow_weak = _make_entry(driver=weak_defender, team_id="t2")

        # Strong defender
        strong_defender = MockDriver(pace=60, overtaking=50, defending=95, aggression=50)
        slow_strong = _make_entry(driver=strong_defender, team_id="t2")

        random.seed(42)
        weak_defense_successes = sum(
            1 for success, collision in (
                _attempt_overtake(faster, slow_weak, circuit, speed_delta=1.5)
                for _ in range(500)
            ) if success and not collision
        )

        random.seed(42)
        strong_defense_successes = sum(
            1 for success, collision in (
                _attempt_overtake(faster, slow_strong, circuit, speed_delta=1.5)
                for _ in range(500)
            ) if success and not collision
        )

        # Weak defender should be overtaken more often
        self.assertGreater(weak_defense_successes, strong_defense_successes)


class TestAttemptOvertakeCircuitDifficulty(unittest.TestCase):
    """Test circuit overtaking difficulty impact."""

    def test_easy_overtaking_circuit_higher_success(self):
        """Easy-to-overtake circuits should have higher success rate."""
        easy_circuit = MockCircuit(overtaking_difficulty=20)
        hard_circuit = MockCircuit(overtaking_difficulty=80)

        attacker = MockDriver(pace=90, overtaking=70, defending=50, aggression=50)
        defender = MockDriver(pace=60, overtaking=50, defending=70, aggression=50)
        faster = _make_entry(driver=attacker)
        slower = _make_entry(driver=defender, team_id="t2")

        random.seed(42)
        easy_successes = sum(
            1 for success, collision in (
                _attempt_overtake(faster, slower, easy_circuit, speed_delta=1.5)
                for _ in range(500)
            ) if success and not collision
        )

        random.seed(42)
        hard_successes = sum(
            1 for success, collision in (
                _attempt_overtake(faster, slower, hard_circuit, speed_delta=1.5)
                for _ in range(500)
            ) if success and not collision
        )

        # Easy circuit should have more successful overtakes
        self.assertGreater(easy_successes, hard_successes)


class TestAttemptOvertakeSpeedDelta(unittest.TestCase):
    """Test speed delta (performance advantage) impact."""

    def test_large_speed_delta_increases_success(self):
        """Larger performance gap should increase overtake success."""
        circuit = MockCircuit()
        attacker = MockDriver(pace=90, overtaking=70, defending=50, aggression=50)
        defender = MockDriver(pace=60, overtaking=50, defending=70, aggression=50)
        faster = _make_entry(driver=attacker)
        slower = _make_entry(driver=defender, team_id="t2")

        # Small gap
        random.seed(42)
        small_gap_successes = sum(
            1 for success, collision in (
                _attempt_overtake(faster, slower, circuit, speed_delta=0.3)
                for _ in range(500)
            ) if success and not collision
        )

        # Large gap
        random.seed(42)
        large_gap_successes = sum(
            1 for success, collision in (
                _attempt_overtake(faster, slower, circuit, speed_delta=2.0)
                for _ in range(500)
            ) if success and not collision
        )

        # Larger gap should result in more successes
        self.assertGreater(large_gap_successes, small_gap_successes)

    def test_zero_speed_delta_low_success(self):
        """With equal pace, overtake success should be low."""
        circuit = MockCircuit()
        attacker = MockDriver(pace=80, overtaking=70, defending=50, aggression=50)
        defender = MockDriver(pace=80, overtaking=50, defending=70, aggression=50)
        faster = _make_entry(driver=attacker)
        slower = _make_entry(driver=defender, team_id="t2")

        random.seed(0)
        results = [_attempt_overtake(faster, slower, circuit, speed_delta=0.0) for _ in range(500)]
        successes = sum(1 for success, collision in results if success and not collision)
        success_rate = successes / 500

        # Equal pace should have minimal successful overtakes
        self.assertLess(success_rate, 0.2)


class TestAttemptOvertakeEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def test_very_small_speed_delta(self):
        """Even tiny speed deltas should produce valid results."""
        circuit = MockCircuit()
        faster = _make_entry()
        slower = _make_entry(team_id="t2")

        random.seed(0)
        result = _attempt_overtake(faster, slower, circuit, speed_delta=0.01)
        success, collision = result

        self.assertIsInstance(success, bool)
        self.assertIsInstance(collision, bool)

    def test_very_large_speed_delta(self):
        """Very large speed deltas should still produce valid results."""
        circuit = MockCircuit()
        faster = _make_entry()
        slower = _make_entry(team_id="t2")

        random.seed(0)
        result = _attempt_overtake(faster, slower, circuit, speed_delta=5.0)
        success, collision = result

        self.assertIsInstance(success, bool)
        self.assertIsInstance(collision, bool)

    def test_easy_circuit_extreme_overtaker(self):
        """Master overtaker on an easy circuit should almost always succeed (without collision)."""
        easy_circuit = MockCircuit(overtaking_difficulty=10)
        master_attacker = MockDriver(pace=90, overtaking=100, defending=50, aggression=5)
        cautious_defender = MockDriver(pace=60, overtaking=50, defending=50, aggression=5)
        faster = _make_entry(driver=master_attacker)
        slower = _make_entry(driver=cautious_defender, team_id="t2")

        random.seed(0)
        results = [_attempt_overtake(faster, slower, easy_circuit, speed_delta=2.0) for _ in range(500)]
        successes = sum(1 for success, collision in results if success and not collision)
        success_rate = successes / 500

        # Should see very high success rate
        self.assertGreater(success_rate, 0.7)

    def test_hard_circuit_poor_overtaker(self):
        """Poor overtaker on hard circuit should rarely succeed."""
        hard_circuit = MockCircuit(overtaking_difficulty=90)
        poor_attacker = MockDriver(pace=90, overtaking=10, defending=50, aggression=10)
        defender = MockDriver(pace=60, overtaking=50, defending=70, aggression=10)
        faster = _make_entry(driver=poor_attacker)
        slower = _make_entry(driver=defender, team_id="t2")

        random.seed(0)
        results = [_attempt_overtake(faster, slower, hard_circuit, speed_delta=1.0) for _ in range(500)]
        successes = sum(1 for success, collision in results if success and not collision)
        success_rate = successes / 500

        # Should see very low success rate
        self.assertLess(success_rate, 0.2)


if __name__ == "__main__":
    unittest.main()
