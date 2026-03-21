import json
from pathlib import Path
from typing import Dict, List

from models.car import Car
from models.circuit import Circuit
from models.driver import Driver
from models.team import Team

DATA_DIR = Path(__file__).parent.parent / "data"


def load_drivers() -> Dict[str, Driver]:
    with open(DATA_DIR / "drivers.json") as f:
        data = json.load(f)
    return {
        d["id"]: Driver(
            id=d["id"], name=d["name"], nationality=d["nationality"],
            age=d["age"],
            pace=d["pace"], qualifying_pace=d["qualifying_pace"],
            consistency=d["consistency"],
            overtaking=d["overtaking"], defending=d["defending"], car_control=d["car_control"],
            aggression=d["aggression"],
            wet_weather=d["wet_weather"], tire_management=d["tire_management"],
            mental=d["mental"], experience=d["experience"],
            potential=d["potential"], salary=d["salary"],
            team_id=d.get("team_id"),
        )
        for d in data["drivers"]
    }


def load_teams(drivers: Dict[str, Driver]) -> Dict[str, Team]:
    with open(DATA_DIR / "teams.json") as f:
        data = json.load(f)
    teams: Dict[str, Team] = {}
    for t in data["teams"]:
        car = Car(
            team_id=t["id"],
            engine=t["car"]["engine"],
            aerodynamics=t["car"]["aerodynamics"],
            mechanical_grip=t["car"]["mechanical_grip"],
            reliability=t["car"]["reliability"],
            tire_deg=t["car"]["tire_deg"],
            braking=t["car"]["braking"],
            pit_crew=t["car"]["pit_crew"],
        )
        teams[t["id"]] = Team(
            id=t["id"], name=t["name"], short_name=t["short_name"],
            color=t["color"], budget=float(t["budget"]), car=car,
            driver_ids=list(t["driver_ids"]),
        )
    return teams


def load_circuits() -> List[Circuit]:
    with open(DATA_DIR / "circuits.json") as f:
        data = json.load(f)
    return [
        Circuit(
            id=c["id"], name=c["name"], country=c["country"], flag=c["flag"],
            length_km=c["length_km"], corners=c["corners"],
            overtaking_difficulty=c["overtaking_difficulty"],
            weather_chance=c["weather_chance"], tire_wear=c["tire_wear"],
            pit_lane_loss=c["pit_lane_loss"],
        )
        for c in data["circuits"]
    ]
