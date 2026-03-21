from dataclasses import dataclass


@dataclass
class Sponsor:
    id: str
    name: str
    industry: str
    race_payment: float      # €M guaranteed per race
    bonus_type: str          # "none" | "podium" | "win" | "fastest_lap" | "top5_finish"
    bonus_amount: float      # €M per trigger (0 if bonus_type == "none")
    description: str
