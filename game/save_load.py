"""Save / load game state to per-slot JSON files (5 slots)."""
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional


def _slot_path(slot: int) -> Path:
    # When frozen by PyInstaller, save next to the .exe, not inside the temp bundle.
    if getattr(sys, "frozen", False):
        base = Path(os.path.dirname(sys.executable))
    else:
        base = Path(os.path.dirname(__file__)) / ".."
    saves_dir = (base / "saves").resolve()
    saves_dir.mkdir(exist_ok=True)
    return saves_dir / f"save_slot_{slot}.json"


DRIVER_MUTABLE = [
    "age", "pace", "qualifying_pace", "consistency", "overtaking", "defending",
    "car_control", "wet_weather", "tire_management", "mental", "experience",
    "aggression", "potential", "salary", "team_id", "xp",
]
CAR_ATTRS = ["engine", "aerodynamics", "mechanical_grip", "reliability", "tire_deg", "braking", "pit_crew"]


def save_exists() -> bool:
    return any(_slot_path(s).exists() for s in range(1, 6))


def list_saves() -> List[dict]:
    result = []
    for slot in range(1, 6):
        path = _slot_path(slot)
        if path.exists():
            try:
                with open(path) as f:
                    data = json.load(f)
                result.append({
                    "slot": slot,
                    "team": data.get("team_name", "Unknown"),
                    "season": data.get("season_year"),
                    "race": data.get("race_num"),
                    "saved_at": data.get("saved_at"),
                    "empty": False,
                })
            except (json.JSONDecodeError, OSError):
                result.append({"slot": slot, "empty": True})
        else:
            result.append({"slot": slot, "empty": True})
    return result


def save_game(slot: int, season_year, player_team_id, race_num,
              season_poles, season_fastest_laps, season_podiums,
              driver_pts, team_pts, drivers, teams) -> None:
    data = {
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "team_name": teams[player_team_id].name,
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
    path = _slot_path(slot)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_game(slot: int) -> Optional[dict]:
    path = _slot_path(slot)
    if not path.exists():
        return None
    with open(path) as f:
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
