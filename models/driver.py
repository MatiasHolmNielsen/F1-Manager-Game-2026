from dataclasses import dataclass
from typing import Optional


@dataclass
class Driver:
    id: str
    name: str
    nationality: str
    age: int
    speed: int          # 0-100: raw one-lap pace
    consistency: int    # 0-100: performs near best every lap
    overtaking: int     # 0-100: passing and defending ability
    wet_weather: int    # 0-100: rain performance
    experience: int     # 0-100: reduces errors
    salary: int         # M€ per season
    team_id: Optional[str] = None

    @property
    def overall(self) -> int:
        return int(
            self.speed * 0.35
            + self.consistency * 0.25
            + self.overtaking * 0.20
            + self.wet_weather * 0.10
            + self.experience * 0.10
        )
