"""Pure dataclasses and constants for the race engine.
# Classes: RaceEntry:32  RaceResult:41  DriverLapState:56  DriverLapRecord:69  PitStop:83  RaceReport:96
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


POINTS_SYSTEM = {
    1: 25, 2: 18, 3: 15, 4: 12, 5: 10,
    6: 8,  7: 6,  8: 4,  9: 2,  10: 1,
}

DNF_REASONS = [
    "Engine failure",
    "Gearbox failure",
    "Hydraulic issue",
    "Suspension failure",
    "Brake failure",
    "Collision damage",
    "Electrical fault",
    "Power unit failure",
]

@dataclass
class RaceEntry:
    driver: object
    car: object
    team_id: str
    team_name: str
    team_color: str


@dataclass
class RaceResult:
    position: int
    driver: object
    team_id: str
    team_name: str
    team_color: str
    time_gap: float     # seconds behind leader (0.0 for P1)
    points: int
    fastest_lap: bool = False
    dnf: bool = False
    dnf_reason: str = ""
    grid_position: int = 0


@dataclass
class DriverLapState:
    total_race_time: float
    fuel_load: float
    tyre_compound: str
    tyre_age: int
    stint_index: int
    dnf: bool
    dnf_reason: str
    pit_this_lap: bool
    dnf_lap: int = 0


@dataclass
class DriverLapRecord:
    lap: int
    lap_time: float
    compound: str
    tyre_age: int
    wear_pct: float
    fuel_load: float
    position: int
    pitted: bool = False
    dnf: bool = False
    rain_prob: float = 0.0
    sc_active: Optional[str] = None   # "SC", "VSC", or None


@dataclass
class PitStop:
    driver_name: str
    team_name: str
    team_color: str
    lap: int
    old_compound: str
    new_compound: str
    stationary_time: float
    pit_lane_loss: float
    total_time: float


@dataclass
class RaceReport:
    results: List[RaceResult]
    events: List[str]
    pit_stops: List[PitStop]
    fastest_lap_time: float = 0.0
    driver_fastest_laps: Dict[str, float] = field(default_factory=dict)
    lap_data: Dict[str, List[DriverLapRecord]] = field(default_factory=dict)
    overtakes_made: Dict[str, int] = field(default_factory=dict)
    defenses_made: Dict[str, int] = field(default_factory=dict)
    peak_rain_prob: float = 0.0
    weather_summary: List[str] = field(default_factory=list)
