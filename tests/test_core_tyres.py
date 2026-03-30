"""Tests for engine/core/tyres.py"""
import random
import unittest

from engine.core.tyres import (
    TYRE_COMPOUNDS,
    COMPOUND_PACE_DELTA,
    TYRE_LIFE_BASE,
    DEFAULT_TYRE_ALLOCATION,
    TYRE_WEAR_TIME_SCALE,
    TyreStint,
    RaceStrategy,
    TyreState,
    TyreAllocation,
    race_laps,
    adjusted_tyre_life,
    tyre_wear_delta,
    tyre_score,
    build_pit_schedule,
    suggest_strategies,
    ai_strategy,
    best_available_compound,
)

# ── Shared fixtures ───────────────────────────────────────────────────────────

class FakeCar:
    tire_deg = 75; pit_crew = 80
    aerodynamics = 70; engine = 72; mechanical_grip = 68
    reliability = 80


class FakeDriver:
    tire_management = 70; car_control = 75
    pace = 80; consistency = 75; mental = 70
    experience = 65; wet_weather = 60
    aggression = 50; overtaking = 70; defending = 65


class FakeCircuit:
    tire_wear = "medium"; weather_chance = 30
    overtaking_difficulty = 50; length_km = 5.3
    aero_weight = 0.4; engine_weight = 0.3
    pit_lane_loss = 22.0


class FakeCircuitLow(FakeCircuit):
    tire_wear = "low"


class FakeCircuitHigh(FakeCircuit):
    tire_wear = "high"


class FakeEntry:
    def __init__(self):
        self.car = FakeCar()
        self.driver = FakeDriver()


# ── Constants parity ──────────────────────────────────────────────────────────

class TestConstantsParity(unittest.TestCase):
    def test_default_allocation_has_all_compounds(self):
        self.assertEqual(set(DEFAULT_TYRE_ALLOCATION.keys()),
                         {"soft", "medium", "hard", "intermediate", "wet"})

    def test_tyre_wear_time_scale(self):
        self.assertAlmostEqual(TYRE_WEAR_TIME_SCALE, 6.0)

    def test_tyre_compounds_keys(self):
        self.assertEqual(set(TYRE_COMPOUNDS.keys()),
                         {"soft", "medium", "hard", "intermediate", "wet"})


# ── TyreStint & RaceStrategy ──────────────────────────────────────────────────

class TestTyreStintAndStrategy(unittest.TestCase):
    def test_tyre_stint_fields(self):
        ts = TyreStint("soft", 15)
        self.assertEqual(ts.compound, "soft")
        self.assertEqual(ts.laps, 15)

    def test_race_strategy_default_label(self):
        rs = RaceStrategy(stints=[TyreStint("medium", 30)])
        self.assertEqual(rs.label, "")

    def test_race_strategy_with_label(self):
        rs = RaceStrategy(stints=[], label="Test")
        self.assertEqual(rs.label, "Test")


# ── TyreState ─────────────────────────────────────────────────────────────────

class TestTyreState(unittest.TestCase):
    def test_initial_state(self):
        ts = TyreState(compound="soft")
        self.assertEqual(ts.compound, "soft")
        self.assertEqual(ts.age, 0)
        self.assertEqual(ts.stint_index, 0)

    def test_tick_increments_age(self):
        ts = TyreState(compound="medium")
        ts.tick()
        ts.tick()
        self.assertEqual(ts.age, 2)

    def test_pit_resets_age(self):
        ts = TyreState(compound="soft", age=15)
        ts.pit("medium")
        self.assertEqual(ts.age, 0)

    def test_pit_changes_compound(self):
        ts = TyreState(compound="soft")
        ts.pit("hard")
        self.assertEqual(ts.compound, "hard")

    def test_pit_increments_stint_index(self):
        ts = TyreState(compound="soft", stint_index=0)
        ts.pit("medium")
        ts.pit("hard")
        self.assertEqual(ts.stint_index, 2)

    def test_wear_fraction_zero_new_tyre(self):
        ts = TyreState(compound="soft", age=0)
        self.assertAlmostEqual(ts.wear_fraction(20), 0.0)

    def test_wear_fraction_half_worn(self):
        ts = TyreState(compound="medium", age=10)
        self.assertAlmostEqual(ts.wear_fraction(20), 0.5)

    def test_wear_fraction_fully_worn(self):
        ts = TyreState(compound="hard", age=20)
        self.assertAlmostEqual(ts.wear_fraction(20), 1.0)

    def test_wear_fraction_capped_at_one(self):
        ts = TyreState(compound="soft", age=50)
        self.assertAlmostEqual(ts.wear_fraction(20), 1.0)

    def test_wear_fraction_zero_life_no_error(self):
        ts = TyreState(compound="medium", age=0)
        self.assertAlmostEqual(ts.wear_fraction(0), 0.0)


# ── TyreAllocation ────────────────────────────────────────────────────────────

class TestTyreAllocation(unittest.TestCase):
    def test_default_matches_constant(self):
        alloc = TyreAllocation.default()
        self.assertEqual(alloc.sets, DEFAULT_TYRE_ALLOCATION)

    def test_from_dict_deep_copies(self):
        d = {"soft": 3, "medium": 1}
        alloc = TyreAllocation.from_dict(d)
        d["soft"] = 99
        self.assertEqual(alloc.available("soft"), 3)

    def test_available_returns_count(self):
        alloc = TyreAllocation.default()
        self.assertEqual(alloc.available("soft"), DEFAULT_TYRE_ALLOCATION["soft"])

    def test_available_unknown_compound_is_zero(self):
        alloc = TyreAllocation.default()
        self.assertEqual(alloc.available("supersoft"), 0)

    def test_consume_decrements(self):
        alloc = TyreAllocation.default()
        before = alloc.available("medium")
        alloc.consume("medium")
        self.assertEqual(alloc.available("medium"), before - 1)

    def test_consume_floors_at_zero(self):
        alloc = TyreAllocation.from_dict({"soft": 0})
        alloc.consume("soft")
        self.assertEqual(alloc.available("soft"), 0)

    def test_best_available_returns_preferred_if_available(self):
        alloc = TyreAllocation.from_dict({"soft": 2, "medium": 1})
        self.assertEqual(alloc.best_available("soft"), "soft")

    def test_best_available_falls_back_when_exhausted(self):
        alloc = TyreAllocation.from_dict({"soft": 0, "medium": 3, "hard": 1})
        self.assertEqual(alloc.best_available("soft"), "medium")

    def test_best_available_empty_dict_returns_preferred(self):
        alloc = TyreAllocation.from_dict({})
        self.assertEqual(alloc.best_available("medium"), "medium")

    def test_has_any_true_with_sets(self):
        self.assertTrue(TyreAllocation.default().has_any())

    def test_has_any_false_when_all_exhausted(self):
        alloc = TyreAllocation.from_dict({"soft": 0, "medium": 0})
        self.assertFalse(alloc.has_any())

    def test_copy_is_independent(self):
        alloc = TyreAllocation.default()
        copy = alloc.copy()
        copy.consume("soft")
        self.assertEqual(alloc.available("soft"), DEFAULT_TYRE_ALLOCATION["soft"])

    def test_copy_has_same_values(self):
        alloc = TyreAllocation.default()
        copy = alloc.copy()
        self.assertEqual(alloc.sets, copy.sets)


# ── race_laps ─────────────────────────────────────────────────────────────────

class TestRaceLaps(unittest.TestCase):
    def test_typical_circuit(self):
        # 5.3 km circuit → 305/5.3 ≈ 57 laps
        self.assertEqual(race_laps(FakeCircuit()), round(305 / 5.3))

    def test_monaco_length(self):
        class Monaco:
            length_km = 3.337
        self.assertAlmostEqual(race_laps(Monaco()), round(305 / 3.337))

    def test_spa_length(self):
        class Spa:
            length_km = 7.004
        self.assertAlmostEqual(race_laps(Spa()), round(305 / 7.004))


# ── adjusted_tyre_life ────────────────────────────────────────────────────────

class TestAdjustedTyreLife(unittest.TestCase):
    car = FakeCar()
    driver = FakeDriver()
    circuit = FakeCircuit()

    def test_minimum_life_is_3(self):
        class FragileDriver:
            tire_management = 0
        class FragileCar:
            tire_deg = 0
        life = adjusted_tyre_life("soft", FakeCircuitHigh(), FragileCar(), FragileDriver())
        self.assertGreaterEqual(life, 3)

    def test_high_wear_circuit_shorter_life(self):
        low = adjusted_tyre_life("medium", FakeCircuitLow(), self.car, self.driver)
        high = adjusted_tyre_life("medium", FakeCircuitHigh(), self.car, self.driver)
        self.assertGreater(low, high)

    def test_better_tire_management_longer_life(self):
        class GoodDriver:
            tire_management = 100
        class BadDriver:
            tire_management = 0
        good = adjusted_tyre_life("medium", self.circuit, self.car, GoodDriver())
        bad  = adjusted_tyre_life("medium", self.circuit, self.car, BadDriver())
        self.assertGreater(good, bad)

    def test_intermediates_longer_in_rain(self):
        dry = adjusted_tyre_life("intermediate", self.circuit, self.car, self.driver, rain_prob=0)
        wet = adjusted_tyre_life("intermediate", self.circuit, self.car, self.driver, rain_prob=80)
        self.assertGreater(wet, dry)


# ── tyre_wear_delta ───────────────────────────────────────────────────────────

class TestTyreWearDelta(unittest.TestCase):
    def test_zero_on_new_tyre(self):
        self.assertAlmostEqual(tyre_wear_delta(0, 20), 0.0)

    def test_max_at_full_wear(self):
        self.assertAlmostEqual(tyre_wear_delta(20, 20), TYRE_WEAR_TIME_SCALE)

    def test_quadratic_at_half_wear(self):
        # (0.5)² × 6.0 = 1.5
        self.assertAlmostEqual(tyre_wear_delta(10, 20), 0.25 * TYRE_WEAR_TIME_SCALE)

    def test_capped_when_overrun(self):
        self.assertAlmostEqual(tyre_wear_delta(100, 20), TYRE_WEAR_TIME_SCALE)

    def test_monotonically_increasing_to_life(self):
        prev = 0.0
        for age in range(0, 21):
            delta = tyre_wear_delta(age, 20)
            self.assertGreaterEqual(delta, prev)
            prev = delta

    def test_zero_life_no_error(self):
        # Should not divide by zero
        result = tyre_wear_delta(0, 0)
        self.assertAlmostEqual(result, 0.0)


# ── tyre_score ────────────────────────────────────────────────────────────────

class TestTyreScore(unittest.TestCase):
    car = FakeCar()
    driver = FakeDriver()
    circuit = FakeCircuit()

    def _strat(self, stints):
        return RaceStrategy(stints=[TyreStint(c, l) for c, l in stints])

    def test_empty_strategy_returns_zero(self):
        s = RaceStrategy(stints=[])
        self.assertAlmostEqual(tyre_score(s, self.circuit, "dry", self.car, self.driver), 0.0)

    def test_overrun_penalised(self):
        normal = self._strat([("medium", 15), ("hard", 20)])
        overrun = self._strat([("medium", 50), ("hard", 10)])   # massive overrun
        s_normal = tyre_score(normal, self.circuit, "dry", self.car, self.driver)
        s_overrun = tyre_score(overrun, self.circuit, "dry", self.car, self.driver)
        self.assertGreater(s_normal, s_overrun)

    def test_rain_compound_on_dry_penalised(self):
        dry = self._strat([("medium", 30), ("hard", 27)])
        wet = self._strat([("intermediate", 30), ("wet", 27)])
        s_dry = tyre_score(dry, self.circuit, "dry", self.car, self.driver)
        s_wet = tyre_score(wet, self.circuit, "dry", self.car, self.driver)
        self.assertGreater(s_dry, s_wet)


# ── build_pit_schedule ────────────────────────────────────────────────────────

class TestBuildPitSchedule(unittest.TestCase):
    def test_single_stint_no_pits(self):
        s = RaceStrategy(stints=[TyreStint("medium", 57)])
        self.assertEqual(build_pit_schedule(s), {})

    def test_two_stints_one_pit(self):
        s = RaceStrategy(stints=[TyreStint("soft", 20), TyreStint("hard", 37)])
        self.assertEqual(build_pit_schedule(s), {20: "hard"})

    def test_three_stints_two_pits(self):
        s = RaceStrategy(stints=[
            TyreStint("soft", 15), TyreStint("medium", 20), TyreStint("hard", 22)
        ])
        self.assertEqual(build_pit_schedule(s), {15: "medium", 35: "hard"})


# ── suggest_strategies ────────────────────────────────────────────────────────

class TestSuggestStrategies(unittest.TestCase):
    car = FakeCar()
    driver = FakeDriver()
    circuit = FakeCircuit()

    def test_returns_four_strategies(self):
        random.seed(0)
        strats = suggest_strategies(self.circuit, "dry", self.car, self.driver)
        self.assertEqual(len(strats), 4)

    def test_each_strategy_totals_race_laps(self):
        random.seed(0)
        total = race_laps(self.circuit)
        strats = suggest_strategies(self.circuit, "dry", self.car, self.driver)
        for s in strats:
            with self.subTest(label=s.label):
                self.assertEqual(sum(st.laps for st in s.stints), total)

    def test_wet_race_returns_rain_compounds(self):
        random.seed(0)
        strats = suggest_strategies(self.circuit, "wet", self.car, self.driver)
        for s in strats:
            for stint in s.stints:
                self.assertIn(stint.compound, ("intermediate", "wet"),
                              f"{s.label} uses {stint.compound}")

    def test_labels_are_distinct(self):
        random.seed(0)
        strats = suggest_strategies(self.circuit, "dry", self.car, self.driver)
        labels = [s.label for s in strats]
        self.assertEqual(len(labels), len(set(labels)))

    def test_all_stints_have_positive_laps(self):
        random.seed(0)
        strats = suggest_strategies(self.circuit, "dry", self.car, self.driver)
        for s in strats:
            for stint in s.stints:
                self.assertGreater(stint.laps, 0, f"{s.label}: {stint}")


# ── best_available_compound ───────────────────────────────────────────────────

class TestBestAvailableCompound(unittest.TestCase):
    def test_returns_preferred_if_available(self):
        alloc = {"soft": 2, "medium": 1}
        self.assertEqual(best_available_compound(alloc, "soft"), "soft")

    def test_falls_back_when_preferred_exhausted(self):
        alloc = {"soft": 0, "medium": 3, "hard": 1}
        self.assertEqual(best_available_compound(alloc, "soft"), "medium")

    def test_empty_dict_returns_preferred(self):
        self.assertEqual(best_available_compound({}, "medium"), "medium")

    def test_all_zero_returns_max_key(self):
        # max() on all-zero values just picks one — shouldn't crash
        alloc = {"soft": 0, "medium": 0}
        result = best_available_compound(alloc, "hard")
        self.assertIn(result, alloc)

    def test_mirrors_tyre_allocation_best_available(self):
        d = {"soft": 0, "medium": 2, "hard": 1}
        alloc_obj = TyreAllocation.from_dict(d)
        self.assertEqual(
            best_available_compound(d, "soft"),
            alloc_obj.best_available("soft"),
        )


if __name__ == "__main__":
    unittest.main()
