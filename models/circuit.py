from dataclasses import dataclass


@dataclass
class Circuit:
    id: str
    name: str
    country: str
    flag: str               # emoji flag
    length_km: float
    corners: int
    overtaking_difficulty: int  # 0-100: higher = harder to overtake
    weather_chance: int         # 0-100: % chance of rain
    tire_wear: str              # low / medium / high
    pit_lane_loss: int          # seconds lost driving through the pit lane (entry + traversal + exit)

    @property
    def aero_weight(self) -> float:
        """More corners = aerodynamics matter more."""
        return round(max(0.20, min(0.80, self.corners / 90)), 2)

    @property
    def engine_weight(self) -> float:
        return round(1.0 - self.aero_weight, 2)

    @property
    def tire_wear_factor(self) -> float:
        return {"low": 0.8, "medium": 1.0, "high": 1.2}[self.tire_wear]
