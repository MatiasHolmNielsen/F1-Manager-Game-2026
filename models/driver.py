from dataclasses import dataclass
from typing import Optional


@dataclass
class Driver:
    id: str
    name: str
    nationality: str
    age: int

    # ── Performance stats (0-100) ──────────────────────────────────
    pace: int             # race pace — sustained lap speed over a stint
    qualifying_pace: int  # one-lap speed — extracting maximum in a single lap
    consistency: int      # lap-to-lap variance; reduces randomness in simulation
    racecraft: int        # overtaking, defending, positioning, avoiding incidents
    wet_weather: int      # performance in rain (replaces dry pace when it rains)
    tire_management: int  # tyre preservation skill — extends stint length
    mental: int           # under pressure, recovery from incidents, big-moment focus
    experience: int       # circuit knowledge, strategic awareness, fewer mistakes

    # ── Development ────────────────────────────────────────────────
    potential: int        # ceiling overall — how good this driver can become

    salary: int           # M€ per season
    team_id: Optional[str] = None

    @property
    def overall(self) -> int:
        return int(
            self.pace            * 0.25
            + self.qualifying_pace * 0.08
            + self.consistency   * 0.18
            + self.racecraft     * 0.18
            + self.wet_weather   * 0.07
            + self.tire_management * 0.08
            + self.mental        * 0.08
            + self.experience    * 0.08
        )

    @property
    def age_group(self) -> str:
        if self.age < 23:
            return "prospect"
        elif self.age < 33:
            return "prime"
        elif self.age < 38:
            return "veteran"
        else:
            return "legend"
