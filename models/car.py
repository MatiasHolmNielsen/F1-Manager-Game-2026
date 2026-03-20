import math
from dataclasses import dataclass

UPGRADE_AMOUNT = 5  # points gained per upgrade

UPGRADE_COSTS: dict = {
    "engine": 15,
    "aerodynamics": 12,
    "mechanical_grip": 10,
    "reliability": 8,
    "tire_deg": 10,
    "braking": 9,
    "pit_crew": 7,
}


@dataclass
class Car:
    team_id: str
    engine: int          # 0-100: straight-line power output
    aerodynamics: int    # 0-100: downforce / high-speed cornering
    mechanical_grip: int # 0-100: low-speed base grip (slow corners, traction)
    reliability: int     # 0-100: DNF resistance
    tire_deg: int        # 0-100: how gentle the car is on tyres (higher = less deg)
    braking: int         # 0-100: brake performance — matters at heavy-braking circuits
    pit_crew: int        # 60-90: pit stop execution speed and precision

    @property
    def overall(self) -> int:
        return int(
            (self.engine + self.aerodynamics + self.mechanical_grip
             + self.reliability + self.tire_deg + self.braking + self.pit_crew) / 7
        )

    def upgrade(self, attribute: str) -> None:
        current = getattr(self, attribute)
        setattr(self, attribute, min(100, current + UPGRADE_AMOUNT))


def upgrade_cost(attr: str, current_value: int) -> int:
    """Exponential cost scaling — cheap at low values, expensive near the cap.

    Formula: base × e^((current - 70) / 25)
      value 70  → 1.0× base
      value 80  → 1.5× base
      value 90  → 2.2× base
      value 95  → 2.7× base
    """
    base = UPGRADE_COSTS[attr]
    return max(base, round(base * math.exp((current_value - 70) / 25)))
