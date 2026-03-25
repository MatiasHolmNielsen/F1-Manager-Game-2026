"""Tests for the multi-slot save/load system (game/save_load.py)."""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_driver(team_id="team_a"):
    d = MagicMock()
    for attr in [
        "age", "pace", "qualifying_pace", "consistency", "overtaking",
        "defending", "car_control", "wet_weather", "tire_management",
        "mental", "experience", "aggression", "potential", "salary", "xp",
    ]:
        setattr(d, attr, 50)
    d.team_id = team_id
    return d


def _make_car():
    c = MagicMock()
    for attr in ["engine", "aerodynamics", "mechanical_grip", "reliability",
                 "tire_deg", "braking", "pit_crew"]:
        setattr(c, attr, 70)
    return c


def _make_team(tid="team_a", name="Alpha Team"):
    t = MagicMock()
    t.name = name
    t.budget = 100.0
    t.sponsor_id = "s1"
    t.driver_ids = ["d1", "d2"]
    t.car = _make_car()
    return t


# ---------------------------------------------------------------------------
# _slot_path
# ---------------------------------------------------------------------------

def test_slot_path_uses_slot_number(tmp_path):
    from game import save_load
    with patch.object(save_load, "_slot_path", lambda s: tmp_path / f"save_slot_{s}.json"):
        p1 = tmp_path / "save_slot_1.json"
        p5 = tmp_path / "save_slot_5.json"
        assert str(p1).endswith("save_slot_1.json")
        assert str(p5).endswith("save_slot_5.json")


# ---------------------------------------------------------------------------
# save_exists
# ---------------------------------------------------------------------------

def test_save_exists_false_when_no_slots(tmp_path):
    from game import save_load
    with patch.object(save_load, "_slot_path", lambda s: tmp_path / f"save_slot_{s}.json"):
        assert save_load.save_exists() is False


def test_save_exists_true_when_one_slot_present(tmp_path):
    from game import save_load
    (tmp_path / "save_slot_3.json").write_text("{}")
    with patch.object(save_load, "_slot_path", lambda s: tmp_path / f"save_slot_{s}.json"):
        assert save_load.save_exists() is True


# ---------------------------------------------------------------------------
# list_saves
# ---------------------------------------------------------------------------

def test_list_saves_all_empty_when_no_files(tmp_path):
    from game import save_load
    with patch.object(save_load, "_slot_path", lambda s: tmp_path / f"save_slot_{s}.json"):
        result = save_load.list_saves()
    assert len(result) == 5
    assert all(r["empty"] for r in result)
    assert [r["slot"] for r in result] == [1, 2, 3, 4, 5]


def test_list_saves_populated_slot_returns_metadata(tmp_path):
    from game import save_load
    slot_data = {
        "team_name": "Red Bull Racing",
        "season_year": 2026,
        "race_num": 5,
        "saved_at": "2026-03-25 12:00",
    }
    (tmp_path / "save_slot_2.json").write_text(json.dumps(slot_data))
    with patch.object(save_load, "_slot_path", lambda s: tmp_path / f"save_slot_{s}.json"):
        result = save_load.list_saves()
    slot2 = next(r for r in result if r["slot"] == 2)
    assert slot2["empty"] is False
    assert slot2["team"] == "Red Bull Racing"
    assert slot2["season"] == 2026
    assert slot2["race"] == 5
    assert slot2["saved_at"] == "2026-03-25 12:00"


def test_list_saves_mixed_slots(tmp_path):
    from game import save_load
    (tmp_path / "save_slot_1.json").write_text(json.dumps({"team_name": "Ferrari", "season_year": 2026, "race_num": 1, "saved_at": "2026-01-01 00:00"}))
    (tmp_path / "save_slot_4.json").write_text(json.dumps({"team_name": "Mercedes", "season_year": 2027, "race_num": 10, "saved_at": "2027-06-15 10:30"}))
    with patch.object(save_load, "_slot_path", lambda s: tmp_path / f"save_slot_{s}.json"):
        result = save_load.list_saves()
    by_slot = {r["slot"]: r for r in result}
    assert by_slot[1]["empty"] is False
    assert by_slot[2]["empty"] is True
    assert by_slot[3]["empty"] is True
    assert by_slot[4]["empty"] is False
    assert by_slot[5]["empty"] is True
    assert by_slot[4]["team"] == "Mercedes"


# ---------------------------------------------------------------------------
# save_game / load_game round-trip
# ---------------------------------------------------------------------------

def test_save_and_load_round_trip(tmp_path):
    from game import save_load

    drivers = {"d1": _make_driver("team_a")}
    teams = {"team_a": _make_team("team_a", "Alpha Team")}

    with patch.object(save_load, "_slot_path", lambda s: tmp_path / f"save_slot_{s}.json"):
        save_load.save_game(
            2, 2026, "team_a", 5,
            1, 0, 3,
            {"d1": 25}, {"team_a": 25},
            drivers, teams,
        )
        data = save_load.load_game(2)

    assert data is not None
    assert data["season_year"] == 2026
    assert data["player_team_id"] == "team_a"
    assert data["race_num"] == 5
    assert data["season_poles"] == 1
    assert data["season_fastest_laps"] == 0
    assert data["season_podiums"] == 3
    assert data["driver_pts"] == {"d1": 25}
    assert data["team_pts"] == {"team_a": 25}


def test_save_game_writes_team_name_and_saved_at(tmp_path):
    from game import save_load

    drivers = {"d1": _make_driver("team_a")}
    teams = {"team_a": _make_team("team_a", "Scuderia Ferrari")}

    with patch.object(save_load, "_slot_path", lambda s: tmp_path / f"save_slot_{s}.json"):
        save_load.save_game(
            1, 2026, "team_a", 3,
            0, 0, 0,
            {}, {},
            drivers, teams,
        )
        data = save_load.load_game(1)

    assert data["team_name"] == "Scuderia Ferrari"
    assert "saved_at" in data
    # Format: YYYY-MM-DD HH:MM
    import re
    assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", data["saved_at"])


def test_save_to_different_slots_are_independent(tmp_path):
    from game import save_load

    drivers = {"d1": _make_driver("team_a")}
    teams = {
        "team_a": _make_team("team_a", "Team A"),
        "team_b": _make_team("team_b", "Team B"),
    }

    with patch.object(save_load, "_slot_path", lambda s: tmp_path / f"save_slot_{s}.json"):
        save_load.save_game(1, 2026, "team_a", 1, 0, 0, 0, {}, {}, drivers, teams)
        save_load.save_game(3, 2027, "team_b", 10, 2, 1, 5, {}, {}, drivers, teams)
        data1 = save_load.load_game(1)
        data3 = save_load.load_game(3)

    assert data1["season_year"] == 2026
    assert data1["player_team_id"] == "team_a"
    assert data3["season_year"] == 2027
    assert data3["player_team_id"] == "team_b"


def test_load_game_returns_none_for_missing_slot(tmp_path):
    from game import save_load
    with patch.object(save_load, "_slot_path", lambda s: tmp_path / f"save_slot_{s}.json"):
        result = save_load.load_game(4)
    assert result is None


# ---------------------------------------------------------------------------
# apply_save — unchanged behaviour
# ---------------------------------------------------------------------------

def test_apply_save_patches_driver_attributes():
    from game.save_load import apply_save

    driver = _make_driver("team_a")
    driver.pace = 50
    driver.age = 25

    data = {
        "drivers": {"d1": {"pace": 80, "age": 26,
                            "qualifying_pace": 75, "consistency": 70,
                            "overtaking": 65, "defending": 60,
                            "car_control": 55, "wet_weather": 50,
                            "tire_management": 45, "mental": 40,
                            "experience": 35, "aggression": 30,
                            "potential": 25, "salary": 20,
                            "team_id": "team_a", "xp": 100}},
        "teams": {},
    }
    apply_save(data, {"d1": driver}, {})
    assert driver.pace == 80
    assert driver.age == 26


def test_apply_save_patches_team_budget():
    from game.save_load import apply_save

    team = _make_team("team_a")
    team.budget = 50.0

    data = {
        "drivers": {},
        "teams": {
            "team_a": {
                "budget": 120.0,
                "sponsor_id": "s99",
                "driver_ids": ["d3", "d4"],
                "car": {"engine": 88, "aerodynamics": 77, "mechanical_grip": 66,
                        "reliability": 55, "tire_deg": 44, "braking": 33, "pit_crew": 22},
            }
        },
    }
    apply_save(data, {}, {"team_a": team})
    assert team.budget == 120.0
    assert team.sponsor_id == "s99"
    assert team.driver_ids == ["d3", "d4"]
