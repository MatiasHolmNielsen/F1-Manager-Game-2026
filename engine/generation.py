"""Rookie driver generation for off-season roster filling."""

import random

from models.driver import Driver

FIRST_NAMES = [
    "Luca", "Marco", "Tom", "Kai", "Felix", "Jules", "Ryo", "Seb", "Hugo", "Arjun",
    "Leo", "Max", "Finn", "Nico", "Pietro", "Oliver", "Sacha", "Ayumu", "Carlos", "Jake",
]
LAST_NAMES = [
    "Müller", "Rossi", "Jensen", "Nakamura", "Dubois", "Schmidt", "Costa",
    "Williams", "Fernandez", "Kovač", "Singh", "Larsson", "Okonkwo", "Blanc",
    "Eriksen", "Tanaka", "Bianchi", "Laurent", "Huber", "Park",
]
NATIONALITIES = [
    "Italian", "French", "German", "Japanese", "British", "Spanish",
    "Australian", "Danish", "Brazilian", "Finnish", "Dutch", "Canadian",
]


def generate_rookie(existing_ids: set, season_year: int) -> Driver:
    """Generate a new rookie driver with a unique ID."""
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)

    # Build 3-letter ID from initials
    candidate = (first[0] + last[:2]).upper()
    if candidate in existing_ids:
        # Try permutations of first 3 letters of last name
        for i in range(len(last)):
            for j in range(i + 1, len(last)):
                candidate = (first[0] + last[i] + last[j]).upper()
                if candidate not in existing_ids:
                    break
            else:
                continue
            break
        else:
            # Last resort: append season digit
            candidate = (first[0] + last[:2]).upper() + str(season_year % 10)

    existing_ids.add(candidate)

    stat = lambda: random.randint(48, 68)
    potential = random.randint(78, 96)

    return Driver(
        id=candidate,
        name=f"{first} {last}",
        nationality=random.choice(NATIONALITIES),
        age=random.randint(18, 22),
        pace=stat(),
        qualifying_pace=stat(),
        consistency=stat(),
        overtaking=stat(),
        defending=stat(),
        car_control=stat(),
        aggression=random.randint(45, 85),
        wet_weather=stat(),
        tire_management=stat(),
        mental=stat(),
        experience=stat(),
        potential=potential,
        salary=max(1, round((potential - 75) / 5)),
        team_id=None,
    )
