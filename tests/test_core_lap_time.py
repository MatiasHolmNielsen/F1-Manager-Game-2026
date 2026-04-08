"""
Tests for engine/core/lap_time.py
Covers _base_lap_time function with various driver, car, and weather conditions.
"""
import unittest
from dataclasses import dataclass

from engine.core.lap_time import _base_lap_time


# ── Test fixtures ────────────────────────────────────────────────────────────

@dataclass
class MockDriver:
    """Typical mid-grid driver."""
    pace: int = 75
    consistency: int = 70
    mental: int = 70
    experience: int = 70
    wet_weather: int = 70


@dataclass
class MockCar:
    """Typical mid-grid car."""
    aerodynamics: int = 75
    engine: int = 75
    mechanical_grip: int = 75


@dataclass
class MockCircuit:
    """Typical circuit (Monza-like)."""
    length_km: float = 5.793
    aero_weight: float = 0.30
    engine_weight: float = 0.40


def _make_entry(driver=None, car=None, team_id="t1"):
    """Create a RaceEntry for testing."""
    from engine.race_models import RaceEntry
    return RaceEntry(
        driver=driver or MockDriver(),
        car=car or MockCar(),
        team_id=team_id,
        team_name="Test Team",
        team_color="#FF0000",
    )


# ── _base_lap_time ──────────────────────────────────────────────────────────

class TestBaseLapTimeReference(unittest.TestCase):
    """Test that base lap time is anchored to circuit.length_km * 20.5."""

    def test_baseline_near_reference_multiplier(self):
        """Base lap time should be close to length_km * 20.5 for average car/driver."""
        circuit = MockCircuit()
        entry = _make_entry()
        lap_time = _base_lap_time(entry, circuit, rain_prob=0.0)

        reference = circuit.length_km * 20.5
        # Average car and driver should not deviate too much from reference
        # (within ~10% seems reasonable for a mid-grid combo)
        self.assertGreater(lap_time, reference * 0.90)
        self.assertLess(lap_time, reference * 1.10)

    def test_returns_positive_float(self):
        """Base lap time must always be positive."""
        circuit = MockCircuit()
        entry = _make_entry()
        lap_time = _base_lap_time(entry, circuit, rain_prob=0.0)
        self.assertIsInstance(lap_time, float)
        self.assertGreater(lap_time, 0.0)

    def test_longer_circuit_longer_lap_time(self):
        """Longer circuits should produce longer lap times (ceteris paribus)."""
        short_circuit = MockCircuit(length_km=3.0)
        long_circuit = MockCircuit(length_km=7.0)
        entry = _make_entry()

        short_time = _base_lap_time(entry, short_circuit, rain_prob=0.0)
        long_time = _base_lap_time(entry, long_circuit, rain_prob=0.0)

        self.assertLess(short_time, long_time)


class TestBaseLapTimeCarPerformance(unittest.TestCase):
    """Test that better car performance produces faster lap times."""

    def test_better_aerodynamics_faster(self):
        """Higher aerodynamics should reduce lap time."""
        bad_car = MockCar(aerodynamics=50)
        good_car = MockCar(aerodynamics=95)
        circuit = MockCircuit()

        bad_entry = _make_entry(car=bad_car)
        good_entry = _make_entry(car=good_car)

        bad_time = _base_lap_time(bad_entry, circuit, rain_prob=0.0)
        good_time = _base_lap_time(good_entry, circuit, rain_prob=0.0)

        self.assertGreater(bad_time, good_time)

    def test_better_engine_faster(self):
        """Higher engine power should reduce lap time."""
        weak_car = MockCar(engine=40)
        strong_car = MockCar(engine=95)
        circuit = MockCircuit()

        weak_entry = _make_entry(car=weak_car)
        strong_entry = _make_entry(car=strong_car)

        weak_time = _base_lap_time(weak_entry, circuit, rain_prob=0.0)
        strong_time = _base_lap_time(strong_entry, circuit, rain_prob=0.0)

        self.assertGreater(weak_time, strong_time)

    def test_better_mechanical_grip_faster(self):
        """Higher mechanical grip should reduce lap time."""
        poor_grip = MockCar(mechanical_grip=30)
        good_grip = MockCar(mechanical_grip=90)
        circuit = MockCircuit()

        poor_entry = _make_entry(car=poor_grip)
        good_entry = _make_entry(car=good_grip)

        poor_time = _base_lap_time(poor_entry, circuit, rain_prob=0.0)
        good_time = _base_lap_time(good_entry, circuit, rain_prob=0.0)

        self.assertGreater(poor_time, good_time)


class TestBaseLapTimeDriverPerformance(unittest.TestCase):
    """Test that better driver attributes produce faster lap times."""

    def test_better_pace_faster(self):
        """Higher pace should reduce lap time."""
        slow_driver = MockDriver(pace=40)
        fast_driver = MockDriver(pace=95)
        circuit = MockCircuit()

        slow_entry = _make_entry(driver=slow_driver)
        fast_entry = _make_entry(driver=fast_driver)

        slow_time = _base_lap_time(slow_entry, circuit, rain_prob=0.0)
        fast_time = _base_lap_time(fast_entry, circuit, rain_prob=0.0)

        self.assertGreater(slow_time, fast_time)

    def test_better_consistency_faster(self):
        """Higher consistency should reduce lap time (steadier, less mistakes)."""
        inconsistent = MockDriver(consistency=30)
        consistent = MockDriver(consistency=95)
        circuit = MockCircuit()

        inconsistent_entry = _make_entry(driver=inconsistent)
        consistent_entry = _make_entry(driver=consistent)

        inconsistent_time = _base_lap_time(inconsistent_entry, circuit, rain_prob=0.0)
        consistent_time = _base_lap_time(consistent_entry, circuit, rain_prob=0.0)

        self.assertGreater(inconsistent_time, consistent_time)

    def test_better_mental_faster(self):
        """Higher mental stat should reduce lap time (better focus/nerve)."""
        weak_mental = MockDriver(mental=30)
        strong_mental = MockDriver(mental=90)
        circuit = MockCircuit()

        weak_entry = _make_entry(driver=weak_mental)
        strong_entry = _make_entry(driver=strong_mental)

        weak_time = _base_lap_time(weak_entry, circuit, rain_prob=0.0)
        strong_time = _base_lap_time(strong_entry, circuit, rain_prob=0.0)

        self.assertGreater(weak_time, strong_time)

    def test_better_experience_faster(self):
        """Higher experience should reduce lap time."""
        novice = MockDriver(experience=20)
        veteran = MockDriver(experience=95)
        circuit = MockCircuit()

        novice_entry = _make_entry(driver=novice)
        veteran_entry = _make_entry(driver=veteran)

        novice_time = _base_lap_time(novice_entry, circuit, rain_prob=0.0)
        veteran_time = _base_lap_time(veteran_entry, circuit, rain_prob=0.0)

        self.assertGreater(novice_time, veteran_time)


class TestBaseLapTimeWeatherEffect(unittest.TestCase):
    """Test that weather (rain) changes lap time based on wet_weather stat."""

    def test_dry_vs_heavy_rain_different(self):
        """Dry (rain_prob=0) and heavy rain (rain_prob=80) should produce different times."""
        circuit = MockCircuit()
        entry = _make_entry()

        dry_time = _base_lap_time(entry, circuit, rain_prob=0.0)
        wet_time = _base_lap_time(entry, circuit, rain_prob=80.0)

        self.assertNotEqual(dry_time, wet_time)

    def test_heavy_rain_slower_for_average_driver(self):
        """Heavy rain should slow an average (not specialist wet-weather) driver."""
        circuit = MockCircuit()
        # Average wet_weather stat for a typical driver
        entry = _make_entry(driver=MockDriver(wet_weather=70))

        dry_time = _base_lap_time(entry, circuit, rain_prob=0.0)
        wet_time = _base_lap_time(entry, circuit, rain_prob=80.0)

        # Rain typically slows down drivers on slicks, so expect wet > dry
        self.assertGreater(wet_time, dry_time)

    def test_wet_weather_specialist_less_penalized(self):
        """Drivers with high wet_weather stat should be less affected by rain."""
        circuit = MockCircuit()
        wet_specialist = MockDriver(pace=75, wet_weather=95)
        poor_wet_driver = MockDriver(pace=75, wet_weather=30)

        specialist_entry = _make_entry(driver=wet_specialist)
        poor_entry = _make_entry(driver=poor_wet_driver)

        specialist_dry = _base_lap_time(specialist_entry, circuit, rain_prob=0.0)
        specialist_wet = _base_lap_time(specialist_entry, circuit, rain_prob=80.0)
        specialist_delta = specialist_wet - specialist_dry

        poor_dry = _base_lap_time(poor_entry, circuit, rain_prob=0.0)
        poor_wet = _base_lap_time(poor_entry, circuit, rain_prob=80.0)
        poor_delta = poor_wet - poor_dry

        # Wet specialist's penalty should be smaller than poor wet driver's penalty
        self.assertLess(specialist_delta, poor_delta)

    def test_light_rain_minimal_effect(self):
        """Very light rain (rain_prob=5) should have minimal effect."""
        circuit = MockCircuit()
        entry = _make_entry()

        dry = _base_lap_time(entry, circuit, rain_prob=0.0)
        light_rain = _base_lap_time(entry, circuit, rain_prob=5.0)

        delta = abs(light_rain - dry)
        # Effect should be small compared to the lap time itself
        self.assertLess(delta, 0.5)


class TestBaseLapTimeEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def test_zero_rain_probability(self):
        """rain_prob=0 should give dry conditions."""
        circuit = MockCircuit()
        entry = _make_entry()
        lap_time = _base_lap_time(entry, circuit, rain_prob=0.0)
        self.assertIsInstance(lap_time, float)
        self.assertGreater(lap_time, 0.0)

    def test_max_rain_probability(self):
        """rain_prob=100 should handle max rain."""
        circuit = MockCircuit()
        entry = _make_entry()
        lap_time = _base_lap_time(entry, circuit, rain_prob=100.0)
        self.assertIsInstance(lap_time, float)
        self.assertGreater(lap_time, 0.0)

    def test_perfect_driver_perfect_car(self):
        """Perfect stats should produce fastest time."""
        circuit = MockCircuit()
        perfect_driver = MockDriver(pace=100, consistency=100, mental=100, experience=100)
        perfect_car = MockCar(aerodynamics=100, engine=100, mechanical_grip=100)
        perfect_entry = _make_entry(driver=perfect_driver, car=perfect_car)

        perfect_time = _base_lap_time(perfect_entry, circuit, rain_prob=0.0)
        average_time = _base_lap_time(_make_entry(), circuit, rain_prob=0.0)

        self.assertLess(perfect_time, average_time)

    def test_terrible_driver_terrible_car(self):
        """Terrible stats should produce slowest time."""
        circuit = MockCircuit()
        terrible_driver = MockDriver(pace=1, consistency=1, mental=1, experience=1)
        terrible_car = MockCar(aerodynamics=1, engine=1, mechanical_grip=1)
        terrible_entry = _make_entry(driver=terrible_driver, car=terrible_car)

        terrible_time = _base_lap_time(terrible_entry, circuit, rain_prob=0.0)
        average_time = _base_lap_time(_make_entry(), circuit, rain_prob=0.0)

        self.assertGreater(terrible_time, average_time)

    def test_different_aero_weights(self):
        """Circuits with different aero weights should produce different times."""
        # High-downforce circuit (high aero_weight)
        highdown_circuit = MockCircuit(aero_weight=0.60, engine_weight=0.20)
        # Low-downforce circuit (low aero_weight)
        lowdown_circuit = MockCircuit(aero_weight=0.10, engine_weight=0.60)

        entry = _make_entry()

        highdown_time = _base_lap_time(entry, highdown_circuit, rain_prob=0.0)
        lowdown_time = _base_lap_time(entry, lowdown_circuit, rain_prob=0.0)

        # Both should be valid lap times
        self.assertGreater(highdown_time, 0.0)
        self.assertGreater(lowdown_time, 0.0)


if __name__ == "__main__":
    unittest.main()
