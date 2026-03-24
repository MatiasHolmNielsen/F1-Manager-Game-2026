"""Save / load game state to a single JSON slot."""
import json
import os
import sys
from typing import Optional


def _save_path() -> str:
    # When frozen by PyInstaller, save next to the .exe, not inside the temp bundle.
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "save.json")
    return os.path.join(os.path.dirname(__file__), "..", "save.json")


SAVE_PATH = _save_path()

DRIVER_MUTABLE = [
    "age", "pace", "qualifying_pace", "consistency", "overtaking", "defending",
    "car_control", "wet_weather", "tire_management", "mental", "experience",
    "aggression", "potential", "salary", "team_id", "xp",
]
CAR_ATTRS = ["engine", "aerodynamics", "mechanical_grip", "reliability", "tire_deg", "braking", "pit_crew"]


def save_exists() -> bool:
    return os.path.isfile(SAVE_PATH)


def save_game(season_year, player_team_id, race_num,
              season_poles, season_fastest_laps, season_podiums,
              driver_pts, team_pts, drivers, teams) -> None:
    data = {
        "season_year": season_year,
        "player_team_id": player_team_id,
        "race_num": race_num,
        "season_poles": season_poles,
        "season_fastest_laps": season_fastest_laps,
        "season_podiums": season_podiums,
        "driver_pts": driver_pts,
        "team_pts": team_pts,
        "drivers": {
            did: {f: getattr(d, f) for f in DRIVER_MUTABLE}
            for did, d in drivers.items()
        },
        "teams": {
            tid: {
                "budget": t.budget,
                "sponsor_id": t.sponsor_id,
                "driver_ids": list(t.driver_ids),
                "car": {a: getattr(t.car, a) for a in CAR_ATTRS},
            }
            for tid, t in teams.items()
        },
    }
    with open(SAVE_PATH, "w") as f:
        json.dump(data, f, indent=2)


def load_game() -> Optional[dict]:
    if not save_exists():
        return None
    with open(SAVE_PATH) as f:
        return json.load(f)


def apply_save(data: dict, drivers: dict, teams: dict) -> None:
    """Patch already-loaded driver/team objects with saved mutable state."""
    for did, fields in data["drivers"].items():
        if did in drivers:
            for f, v in fields.items():
                setattr(drivers[did], f, v)
    for tid, tdata in data["teams"].items():
        if tid in teams:
            t = teams[tid]
            t.budget = tdata["budget"]
            t.sponsor_id = tdata.get("sponsor_id")
            t.driver_ids = tdata["driver_ids"]
            for a, v in tdata["car"].items():
                setattr(t.car, a, v)
