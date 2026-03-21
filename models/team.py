from dataclasses import dataclass, field
from typing import List, Optional

from .car import Car


@dataclass
class Team:
    id: str
    name: str
    short_name: str
    color: str      # rich color name
    budget: float   # M€ available for upgrades / signings
    car: Car
    driver_ids: List[str] = field(default_factory=list)
    points: int = 0
    sponsor_id: Optional[str] = None
