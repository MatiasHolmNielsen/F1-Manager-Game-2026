from dataclasses import dataclass

UPGRADE_AMOUNT = 5  # points per upgrade

UPGRADE_COSTS: dict = {
    "engine": 15,
    "aerodynamics": 12,
    "reliability": 8,
    "tire_management": 10,
}


@dataclass
class Car:
    team_id: str
    engine: int           # 0-100: straight-line speed
    aerodynamics: int     # 0-100: cornering performance
    reliability: int      # 0-100: DNF resistance
    tire_management: int  # 0-100: tire wear rate

    @property
    def overall(self) -> int:
        return int(
            (self.engine + self.aerodynamics + self.reliability + self.tire_management) / 4
        )

    def upgrade(self, attribute: str) -> None:
        current = getattr(self, attribute)
        setattr(self, attribute, min(100, current + UPGRADE_AMOUNT))
