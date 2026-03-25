"""Shared formatting helpers and the console singleton.
# Functions: fmt_lap_time:10  stat_bar:17  _xp_bar:29  _rain_bar:36  _delta_str:49  _fmt_stint:62  _fmt_strategy:68
#            show_team_creator:74  show_slot_picker:84
"""
from __future__ import annotations

import random
from typing import Dict, List, Tuple

from rich.console import Console
from rich import box
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from engine.core.tyres import TYRE_COMPOUNDS

from models.team import Team
from models.car import Car

console = Console()


def fmt_lap_time(seconds: float) -> str:
    """Format seconds as M:SS.mmm."""
    mins = int(seconds // 60)
    secs = seconds - mins * 60
    return f"{mins}:{secs:06.3f}"


def stat_bar(value: int, width: int = 12) -> str:
    filled = int(value / 100 * width)
    bar = "█" * filled + "░" * (width - filled)
    if value >= 85:
        color = "green"
    elif value >= 70:
        color = "yellow"
    else:
        color = "red"
    return f"[{color}]{bar}[/{color}] [dim]{value}[/dim]"


def _xp_bar(xp: float, width: int = 10) -> str:
    filled = int(xp * width)
    bar = "█" * filled + "░" * (width - filled)
    pct = int(xp * 100)
    return f"[cyan]{bar}[/cyan] [dim]{pct:>3}%[/dim]"


def _rain_bar(prob: float, width: int = 10) -> str:
    """Render a rain probability as a coloured bar with percentage."""
    filled = max(0, min(width, round(prob / 100 * width)))
    color = "blue" if prob >= 65 else ("cyan" if prob >= 45 else "dim")
    bar = "█" * filled + "░" * (width - filled)
    marker = ""
    if prob >= 92:
        marker = " [dim]← wet[/dim]"
    elif prob >= 65:
        marker = " [dim]← damp[/dim]"
    return f"[{color}]{bar}[/{color}] {prob:.0f}%{marker}"


def _delta_str(grid_position: int, race_position: int) -> str:
    """Format grid-to-race position delta for race results table."""
    if grid_position <= 0:
        return ""
    delta = grid_position - race_position
    if delta > 0:
        return f"[green]+{delta}[/green]"
    elif delta == 0:
        return "[dim]—[/dim]"
    else:
        return f"[red]{delta}[/red]"


def _fmt_stint(stint) -> str:
    """Rich-formatted compound symbol with lap count, e.g. [red]S[/red](14)."""
    info = TYRE_COMPOUNDS[stint.compound]
    return f"[{info['color']}]{info['symbol']}[/{info['color']}]({stint.laps})"


def _fmt_strategy(strategy) -> str:
    return " → ".join(_fmt_stint(s) for s in strategy.stints)


# ---------------------------------------------------------------------------
# Team creator
# ---------------------------------------------------------------------------

_TEAM_COLORS: List[str] = [
    "red", "green", "blue", "yellow", "magenta", "cyan", "white",
    "bright_red", "bright_green", "bright_blue", "bright_yellow",
    "bright_magenta", "bright_cyan", "orange3", "gold3", "purple",
]


def _prompt(label: str) -> str:
    """Print a prompt label and return stripped input."""
    console.print(f"[bold]{label}[/bold] ", end="")
    return input().strip()


def _prompt_int(label: str, lo: int, hi: int) -> int:
    """Prompt for an integer in [lo, hi], re-prompting on invalid input."""
    while True:
        raw = _prompt(f"{label} [{lo}–{hi}]:")
        if raw.isdigit() or (raw.startswith("-") and raw[1:].isdigit()):
            val = int(raw)
            if lo <= val <= hi:
                return val
        console.print(f"[red]  Please enter a number between {lo} and {hi}.[/red]")


def _clamp(val: int, lo: int = 1, hi: int = 100) -> int:
    return max(lo, min(hi, val))


def _derive_car_stat(overall: int) -> int:
    """Derive a single car stat from overall rating with ±3 variance, clamped 1–100."""
    return _clamp(overall + random.randint(-3, 3))


def _collect_team_details(drivers: Dict[str, "Driver"]) -> Tuple["Team", List[str]]:
    """Single pass through all team-creation prompts. Returns (Team, [driver_id_1, driver_id_2])."""

    # ── Step 1: Team name ────────────────────────────────────────────────
    console.print(Rule("[dim]Step 1 of 7 — Team name[/dim]"))
    team_name = ""
    while not (2 <= len(team_name) <= 30):
        team_name = _prompt("Team name (2–30 chars):")
        if not (2 <= len(team_name) <= 30):
            console.print("[red]  Must be 2–30 characters.[/red]")

    # ── Step 2: Short name ───────────────────────────────────────────────
    console.print(Rule("[dim]Step 2 of 7 — Short name[/dim]"))
    short_name = ""
    while not (2 <= len(short_name) <= 6):
        raw = _prompt("Short name (2–6 chars, e.g. APX):")
        short_name = raw.upper()
        if not (2 <= len(short_name) <= 6):
            console.print("[red]  Must be 2–6 characters.[/red]")

    # ── Step 3: Color ────────────────────────────────────────────────────
    console.print(Rule("[dim]Step 3 of 7 — Team color[/dim]"))
    for idx, color in enumerate(_TEAM_COLORS, 1):
        console.print(f"  [{color}]{idx:>2}. {color}[/{color}]")
    color_choice = _prompt_int("Pick a color number", 1, len(_TEAM_COLORS))
    chosen_color = _TEAM_COLORS[color_choice - 1]

    # ── Step 4: Car overall rating ───────────────────────────────────────
    console.print(Rule("[dim]Step 4 of 7 — Car overall rating[/dim]"))
    console.print("[dim]  (55 = backmarker, 92 = top team)[/dim]")
    car_overall = _prompt_int("Car overall rating", 55, 92)

    # ── Step 5: Budget ───────────────────────────────────────────────────
    console.print(Rule("[dim]Step 5 of 7 — Budget[/dim]"))
    budget = _prompt_int("Starting budget in M€", 50, 300)

    # ── Step 6: Driver 1 ─────────────────────────────────────────────────
    console.print(Rule("[dim]Step 6 of 7 — Driver 1[/dim]"))
    # Show drivers not already on a full 2-driver team.
    team_counts: Dict[str, int] = {}
    for d in drivers.values():
        if d.team_id:
            team_counts[d.team_id] = team_counts.get(d.team_id, 0) + 1

    free_drivers: List[Tuple[str, "Driver"]] = [
        (did, d) for did, d in drivers.items()
        if d.team_id is None or team_counts.get(d.team_id, 0) < 2
    ]

    for idx, (did, d) in enumerate(free_drivers, 1):
        console.print(f"  {idx:>2}. [{chosen_color}]{d.name}[/{chosen_color}]  [dim]OVR {d.overall}[/dim]")
    d1_idx = _prompt_int("Select Driver 1", 1, len(free_drivers))
    driver1_id, driver1 = free_drivers[d1_idx - 1]

    # ── Step 7: Driver 2 ─────────────────────────────────────────────────
    console.print(Rule("[dim]Step 7 of 7 — Driver 2[/dim]"))
    remaining: List[Tuple[str, "Driver"]] = [
        (did, d) for did, d in free_drivers if did != driver1_id
    ]
    for idx, (did, d) in enumerate(remaining, 1):
        console.print(f"  {idx:>2}. [{chosen_color}]{d.name}[/{chosen_color}]  [dim]OVR {d.overall}[/dim]")
    d2_idx = _prompt_int("Select Driver 2", 1, len(remaining))
    driver2_id, driver2 = remaining[d2_idx - 1]

    # ── Build objects ────────────────────────────────────────────────────
    car = Car(
        team_id="custom_team",
        engine=_derive_car_stat(car_overall),
        aerodynamics=_derive_car_stat(car_overall),
        mechanical_grip=_derive_car_stat(car_overall),
        reliability=_derive_car_stat(car_overall),
        tire_deg=_derive_car_stat(car_overall),
        braking=_derive_car_stat(car_overall),
        pit_crew=_clamp(car_overall + random.randint(-3, 3), 60, 90),
    )

    team = Team(
        id="custom_team",
        name=team_name,
        short_name=short_name,
        color=chosen_color,
        budget=float(budget),
        car=car,
        driver_ids=[driver1_id, driver2_id],
        sponsor_id=None,
    )

    return team, [driver1_id, driver2_id], chosen_color, driver1, driver2, car_overall


def show_team_creator(drivers: Dict[str, "Driver"]) -> Tuple["Team", List[str]]:
    """Collect custom team details from the player. Returns (Team, [driver_id_1, driver_id_2])."""
    while True:
        console.print(
            Panel(
                "[bold yellow]Let's build your team from scratch.[/bold yellow]",
                title="[bold]CREATE YOUR TEAM[/bold]",
                border_style="yellow",
            )
        )

        team, driver_ids, chosen_color, driver1, driver2, car_overall = _collect_team_details(drivers)

        # ── Confirmation summary ─────────────────────────────────────────
        console.print(Rule("[dim]Summary[/dim]"))
        summary_lines = [
            f"  Team name   : [{chosen_color}]{team.name}[/{chosen_color}]",
            f"  Short name  : [{chosen_color}]{team.short_name}[/{chosen_color}]",
            f"  Color       : [{chosen_color}]{chosen_color}[/{chosen_color}]",
            f"  Car overall : [bold]{car_overall}[/bold]  [dim](engine {team.car.engine} / aero {team.car.aerodynamics} / grip {team.car.mechanical_grip} / rel {team.car.reliability} / deg {team.car.tire_deg} / brk {team.car.braking} / pit {team.car.pit_crew})[/dim]",
            f"  Budget      : [bold]{int(team.budget)} M€[/bold]",
            f"  Driver 1    : [{chosen_color}]{driver1.name}[/{chosen_color}]  [dim]OVR {driver1.overall}[/dim]",
            f"  Driver 2    : [{chosen_color}]{driver2.name}[/{chosen_color}]  [dim]OVR {driver2.overall}[/dim]",
        ]
        console.print(
            Panel(
                "\n".join(summary_lines),
                title="[bold]Your Team[/bold]",
                border_style=chosen_color,
            )
        )

        confirm = _prompt("Confirm? [Y/n]:").lower()
        if confirm in ("", "y", "yes"):
            return team, driver_ids

        console.print("[dim]Starting over...[/dim]\n")


# ---------------------------------------------------------------------------
# Save / load slot picker
# ---------------------------------------------------------------------------

def show_slot_picker(slots_info: List[dict], mode: str = "load") -> int:
    """Display save slot picker. Returns chosen slot (1-5) or 0 if cancelled."""
    title = "SAVE GAME" if mode == "save" else "LOAD GAME"

    occupied: set[int] = {s["slot"] for s in slots_info if not s.get("empty", True)}

    while True:
        table = Table(
            box=box.DOUBLE_EDGE,
            show_header=True,
            header_style="bold",
        )
        table.add_column("#", width=3, justify="center")
        table.add_column("Team", min_width=20)
        table.add_column("Season", width=8, justify="center")
        table.add_column("Race", width=6, justify="center")
        table.add_column("Saved", min_width=18)

        for slot in slots_info:
            slot_num = str(slot["slot"])
            if slot.get("empty", True):
                table.add_row(
                    slot_num,
                    "[dim italic]— empty —[/dim italic]",
                    "",
                    "",
                    "",
                )
            else:
                table.add_row(
                    slot_num,
                    slot["team"],
                    str(slot["season"]),
                    str(slot["race"]),
                    slot["saved_at"],
                )

        console.print(
            Panel(
                table,
                title=f"[bold]{title}[/bold]",
                border_style="red",
                box=box.DOUBLE_EDGE,
            )
        )
        console.print("[dim]0 · Cancel[/dim]")

        console.print("[bold]Slot:[/bold] ", end="")
        raw = input().strip()

        if raw == "0":
            return 0

        if not raw.isdigit() or not (1 <= int(raw) <= 5):
            console.print("[red]  Please enter a slot number 1–5, or 0 to cancel.[/red]")
            continue

        chosen = int(raw)

        if mode == "load":
            if chosen not in occupied:
                console.print(f"[red]  Slot {chosen} is empty. Choose an occupied slot.[/red]")
                continue
            return chosen

        # mode == "save"
        if chosen in occupied:
            console.print(
                f"[yellow]Slot {chosen} already has a save. Overwrite? [y/N][/yellow]",
                end=" ",
            )
            confirm = input().strip().lower()
            if confirm not in ("y", "yes"):
                continue

        return chosen
