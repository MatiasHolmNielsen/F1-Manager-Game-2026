#!/usr/bin/env python3
"""F1 Manager 2026 — Terminal Edition"""

import json
import random
import time
from pathlib import Path
from typing import Dict, List, Optional

from rich.align import Align
from rich.columns import Columns
from rich.console import Console
from rich import box
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from models.car import UPGRADE_COSTS, UPGRADE_AMOUNT, upgrade_cost
from models.car import Car
from models.circuit import Circuit
from models.driver import Driver
from models.team import Team
from engine.race import (
    RaceEntry, RaceResult, QualiResult, RaceStrategy, TyreStint,
    simulate_race, simulate_qualifying, suggest_strategies, ai_strategy,
    race_laps, adjusted_tyre_life, TYRE_COMPOUNDS,
)
from engine.development import apply_development
from engine.generation import generate_rookie

DATA_DIR = Path(__file__).parent / "data"
console = Console()


# ─── Data Loading ─────────────────────────────────────────────────────────────

def load_drivers() -> Dict[str, Driver]:
    with open(DATA_DIR / "drivers.json") as f:
        data = json.load(f)
    return {
        d["id"]: Driver(
            id=d["id"], name=d["name"], nationality=d["nationality"],
            age=d["age"],
            pace=d["pace"], qualifying_pace=d["qualifying_pace"],
            consistency=d["consistency"], racecraft=d["racecraft"],
            wet_weather=d["wet_weather"], tire_management=d["tire_management"],
            mental=d["mental"], experience=d["experience"],
            potential=d["potential"], salary=d["salary"],
            team_id=d.get("team_id"),
        )
        for d in data["drivers"]
    }


def load_teams(drivers: Dict[str, Driver]) -> Dict[str, Team]:
    with open(DATA_DIR / "teams.json") as f:
        data = json.load(f)
    teams: Dict[str, Team] = {}
    for t in data["teams"]:
        car = Car(
            team_id=t["id"],
            engine=t["car"]["engine"],
            aerodynamics=t["car"]["aerodynamics"],
            mechanical_grip=t["car"]["mechanical_grip"],
            reliability=t["car"]["reliability"],
            tire_deg=t["car"]["tire_deg"],
            braking=t["car"]["braking"],
            pit_crew=t["car"]["pit_crew"],
        )
        teams[t["id"]] = Team(
            id=t["id"], name=t["name"], short_name=t["short_name"],
            color=t["color"], budget=float(t["budget"]), car=car,
            driver_ids=list(t["driver_ids"]),
        )
    return teams


def load_circuits() -> List[Circuit]:
    with open(DATA_DIR / "circuits.json") as f:
        data = json.load(f)
    return [
        Circuit(
            id=c["id"], name=c["name"], country=c["country"], flag=c["flag"],
            length_km=c["length_km"], corners=c["corners"],
            overtaking_difficulty=c["overtaking_difficulty"],
            weather_chance=c["weather_chance"], tire_wear=c["tire_wear"],
        )
        for c in data["circuits"]
    ]


# ─── Display Helpers ──────────────────────────────────────────────────────────

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


def show_welcome() -> None:
    console.clear()
    console.print()
    console.print(
        Panel(
            Align.center(
                Text.from_markup(
                    "[bold red]F1 MANAGER 2026[/bold red]\n"
                    "[dim]Build your team. Dominate the season.[/dim]"
                )
            ),
            box=box.DOUBLE_EDGE,
            border_style="red",
            padding=(1, 6),
        )
    )
    console.print()


def show_team_selection(teams: Dict[str, Team], drivers: Dict[str, Driver]) -> str:
    console.print(Panel("[bold]SELECT YOUR TEAM[/bold]", border_style="yellow", padding=(0, 2)))

    table = Table(box=box.ROUNDED, header_style="bold yellow", show_lines=False)
    table.add_column("#", width=3, justify="center")
    table.add_column("Team", min_width=20)
    table.add_column("Car OVR", justify="center", width=8)
    table.add_column("Driver 1", min_width=22)
    table.add_column("Driver 2", min_width=22)
    table.add_column("Budget", justify="right", width=10)

    team_list = list(teams.values())
    for i, team in enumerate(team_list, 1):
        team_drivers = [drivers[did] for did in team.driver_ids if did in drivers]
        d1 = f"{team_drivers[0].name} ({team_drivers[0].overall})" if len(team_drivers) > 0 else "—"
        d2 = f"{team_drivers[1].name} ({team_drivers[1].overall})" if len(team_drivers) > 1 else "—"
        table.add_row(
            str(i),
            f"[{team.color}]{team.short_name}[/{team.color}]",
            str(team.car.overall),
            d1, d2,
            f"€{team.budget:.0f}M",
        )

    console.print(table)
    console.print()

    team_list_ids = [str(i) for i in range(1, len(team_list) + 1)]
    while True:
        choice = Prompt.ask(f"Choose your team [dim](1–{len(team_list)})[/dim]")
        if choice in team_list_ids:
            idx = int(choice) - 1
            selected = team_list[idx]
            console.print(
                f"\n[bold green]You are now managing "
                f"[{selected.color}]{selected.name}[/{selected.color}][/bold green]!\n"
            )
            return selected.id
        console.print("[red]Invalid choice.[/red]")


def show_team_overview(team: Team, drivers: Dict[str, Driver]) -> None:
    console.print()
    console.print(
        Panel(
            f"[bold {team.color}]{team.name}[/bold {team.color}]",
            subtitle=f"Budget: [bold green]€{team.budget:.1f}M[/bold green]",
            border_style=team.color,
        )
    )

    # Driver table — performance stats
    d_table = Table(title="Drivers — Performance", box=box.SIMPLE_HEAD, show_edge=False)
    d_table.add_column("Name", min_width=18)
    d_table.add_column("OVR", justify="center", width=5)
    d_table.add_column("Pace", min_width=16)
    d_table.add_column("Q.Pace", min_width=16)
    d_table.add_column("Consistency", min_width=16)
    d_table.add_column("Racecraft", min_width=16)

    # Driver table — conditions & profile
    d_table2 = Table(title="Drivers — Conditions & Profile", box=box.SIMPLE_HEAD, show_edge=False)
    d_table2.add_column("Name", min_width=18)
    d_table2.add_column("Wet", min_width=16)
    d_table2.add_column("Tire Mgmt", min_width=16)
    d_table2.add_column("Mental", min_width=16)
    d_table2.add_column("Experience", min_width=16)
    d_table2.add_column("Age / Potential", min_width=20)
    d_table2.add_column("Salary", justify="right", width=8)

    for did in team.driver_ids:
        d = drivers.get(did)
        if d:
            age_colors = {"prospect": "green", "prime": "cyan", "veteran": "yellow", "legend": "red"}
            age_color = age_colors[d.age_group]
            age_str = (
                f"[{age_color}]{d.age} ({d.age_group})[/{age_color}]  "
                f"[dim]POT [/dim][bold]{d.potential}[/bold]"
            )
            d_table.add_row(
                d.name, str(d.overall),
                stat_bar(d.pace), stat_bar(d.qualifying_pace),
                stat_bar(d.consistency), stat_bar(d.racecraft),
            )
            d_table2.add_row(
                d.name,
                stat_bar(d.wet_weather), stat_bar(d.tire_management),
                stat_bar(d.mental), stat_bar(d.experience),
                age_str, f"€{d.salary}M",
            )

    car = team.car
    c_table = Table(title="Car", box=box.SIMPLE_HEAD, show_edge=False)
    c_table.add_column("Attribute", min_width=18)
    c_table.add_column("Rating", min_width=18)
    c_table.add_row("Engine", stat_bar(car.engine))
    c_table.add_row("Aerodynamics", stat_bar(car.aerodynamics))
    c_table.add_row("Mechanical Grip", stat_bar(car.mechanical_grip))
    c_table.add_row("Reliability", stat_bar(car.reliability))
    c_table.add_row("Tyre Degradation", stat_bar(car.tire_deg))
    c_table.add_row("Braking", stat_bar(car.braking))
    c_table.add_row("Pit Crew", stat_bar(car.pit_crew))
    c_table.add_row("[bold]Overall[/bold]", f"[bold]{car.overall}[/bold]")

    console.print(d_table)
    console.print()
    console.print(d_table2)
    console.print()
    console.print(c_table)


def show_race_header(
    circuit: Circuit, race_num: int, total: int, weather: Optional[str] = None
) -> None:
    weather_str = ""
    if weather == "wet":
        weather_str = "  |  [blue]RAIN[/blue]"
    elif weather == "dry":
        weather_str = "  |  [yellow]DRY[/yellow]"

    tire_icon = {"low": "○", "medium": "◑", "high": "●"}[circuit.tire_wear]

    console.print()
    console.print(
        Panel(
            f"[dim]Race {race_num} of {total}[/dim]\n"
            f"[bold white]{circuit.name}[/bold white]  {circuit.flag}\n"
            f"[dim]{circuit.country}  •  {circuit.length_km}km  "
            f"•  {circuit.corners} corners  "
            f"•  Tire wear {tire_icon} {circuit.tire_wear}"
            f"{weather_str}[/dim]",
            border_style="yellow",
            box=box.HEAVY_HEAD,
        )
    )


def show_race_results(
    results: List[RaceResult], player_team_id: str, circuit: Circuit
) -> None:
    console.print()
    table = Table(
        title=f"RACE RESULT — {circuit.name}",
        box=box.ROUNDED,
        header_style="bold white",
        show_lines=False,
    )
    table.add_column("Pos", width=4, justify="center")
    table.add_column("±", width=5, justify="right")
    table.add_column("Driver", min_width=20)
    table.add_column("Team", min_width=18)
    table.add_column("Gap / Status", min_width=22)
    table.add_column("Pts", width=5, justify="center")
    table.add_column("FL", width=4, justify="center")

    for r in results:
        is_player = r.team_id == player_team_id
        prefix = "[bold]▶ [/bold]" if is_player else "  "

        if r.dnf:
            pos_str = "[dim]—[/dim]"
            gap_str = f"[red]DNF — {r.dnf_reason}[/red]"
            delta_str = ""
        elif r.position == 1:
            pos_str = "[bold yellow]1[/bold yellow]"
            gap_str = "[green]WINNER[/green]"
            if r.grid_position > 0:
                delta = r.grid_position - r.position
                delta_str = f"[green]+{delta}[/green]" if delta > 0 else ("[dim]—[/dim]" if delta == 0 else f"[red]{delta}[/red]")
            else:
                delta_str = ""
        else:
            pos_str = str(r.position)
            gap_str = f"+{r.time_gap:.3f}s"
            if r.grid_position > 0:
                delta = r.grid_position - r.position
                delta_str = f"[green]+{delta}[/green]" if delta > 0 else ("[dim]—[/dim]" if delta == 0 else f"[red]{delta}[/red]")
            else:
                delta_str = ""

        fl_str = "[bold yellow]FL[/bold yellow]" if r.fastest_lap else ""
        pts_str = f"[bold]{r.points}[/bold]" if r.points > 0 else ""
        name_str = f"{prefix}{r.driver.name}"
        team_str = f"[{r.team_color}]{r.team_name}[/{r.team_color}]"

        table.add_row(pos_str, delta_str, name_str, team_str, gap_str, pts_str, fl_str)

    console.print(table)


def show_standings(
    driver_pts: Dict[str, int],
    team_pts: Dict[str, int],
    drivers: Dict[str, Driver],
    teams: Dict[str, Team],
    player_team_id: str,
    top_n: int = 10,
    season_year: int = 2026,
) -> None:
    sorted_drivers = sorted(driver_pts.items(), key=lambda x: x[1], reverse=True)[:top_n]
    sorted_teams = sorted(team_pts.items(), key=lambda x: x[1], reverse=True)

    d_table = Table(title=f"DRIVERS' CHAMPIONSHIP — Season {season_year}", box=box.SIMPLE_HEAD, show_edge=False)
    d_table.add_column("Pos", width=4, justify="center")
    d_table.add_column("Driver", min_width=18)
    d_table.add_column("Team", min_width=16)
    d_table.add_column("Pts", justify="right", width=6)

    for i, (did, pts) in enumerate(sorted_drivers, 1):
        d = drivers.get(did)
        t = teams.get(d.team_id) if d and d.team_id else None
        is_player = t and t.id == player_team_id
        team_str = f"[{t.color}]{t.short_name}[/{t.color}]" if t else "—"
        name_str = f"[bold]{d.name}[/bold]" if is_player else (d.name if d else did)
        d_table.add_row(str(i), name_str, team_str, str(pts))

    c_table = Table(title=f"CONSTRUCTORS' CHAMPIONSHIP — Season {season_year}", box=box.SIMPLE_HEAD, show_edge=False)
    c_table.add_column("Pos", width=4, justify="center")
    c_table.add_column("Team", min_width=18)
    c_table.add_column("Pts", justify="right", width=6)

    for i, (tid, pts) in enumerate(sorted_teams, 1):
        t = teams.get(tid)
        is_player = tid == player_team_id
        name_str = f"[{t.color}][bold]{t.short_name}[/bold][/{t.color}]" if is_player else (
            f"[{t.color}]{t.short_name}[/{t.color}]" if t else tid
        )
        c_table.add_row(str(i), name_str, str(pts))

    console.print()
    console.print(Columns([d_table, c_table]))


# ─── Management Menu ──────────────────────────────────────────────────────────

def upgrade_car_menu(team: Team) -> None:
    attr_map = {
        "1": ("engine", "Engine Power"),
        "2": ("aerodynamics", "Aerodynamics"),
        "3": ("mechanical_grip", "Mechanical Grip"),
        "4": ("reliability", "Reliability"),
        "5": ("tire_deg", "Tyre Degradation"),
        "6": ("braking", "Braking System"),
        "7": ("pit_crew", "Pit Crew"),
    }

    while True:
        console.print()
        car = team.car
        table = Table(
            title=f"CAR UPGRADES  [dim](Budget: €{team.budget:.1f}M)[/dim]",
            box=box.SIMPLE_HEAD, show_edge=False,
        )
        table.add_column("#", width=3)
        table.add_column("Attribute", min_width=18)
        table.add_column("Current", justify="center", width=8)
        table.add_column("After", justify="center", width=6)
        table.add_column("Cost", justify="right", width=8)

        for num, (attr, label) in attr_map.items():
            current = getattr(car, attr)
            cost = upgrade_cost(attr, current)
            after = min(100, current + UPGRADE_AMOUNT)
            maxed = current >= 100
            color = "green" if team.budget >= cost and not maxed else "red"
            status = "[dim]MAXED[/dim]" if maxed else f"[{color}]€{cost}M[/{color}]"
            table.add_row(num, label, str(current), str(after), status)

        table.add_row("0", "[dim]Back[/dim]", "", "", "")
        console.print(table)

        choice = Prompt.ask("Choose", choices=["0", "1", "2", "3", "4", "5", "6", "7"])
        if choice == "0":
            break

        attr, label = attr_map[choice]
        cost = upgrade_cost(attr, getattr(team.car, attr))

        if team.budget < cost:
            console.print(f"[red]Not enough budget. Need €{cost}M, have €{team.budget:.1f}M[/red]")
        elif getattr(team.car, attr) >= 100:
            console.print("[yellow]Already maxed out![/yellow]")
        else:
            team.car.upgrade(attr)
            team.budget -= cost
            console.print(
                f"[green]✓ {label} upgraded to {getattr(team.car, attr)}. "
                f"Budget: €{team.budget:.1f}M[/green]"
            )


def driver_market_menu(
    team: Team,
    drivers: Dict[str, Driver],
    teams: Dict[str, Team],
    races_remaining: int,
    total_races: int,
) -> None:
    while True:
        free_agents = [d for d in drivers.values() if d.team_id is None]

        if not free_agents:
            console.print("[yellow]No free agents available.[/yellow]")
            return

        console.print()
        console.print(Panel("[bold]DRIVER MARKET[/bold]", border_style="cyan", padding=(0, 2)))

        fa_table = Table(title="Free Agents", box=box.SIMPLE_HEAD, show_edge=False)
        fa_table.add_column("#", width=3)
        fa_table.add_column("Name", min_width=18)
        fa_table.add_column("OVR", justify="center", width=5)
        fa_table.add_column("Pace", justify="center", width=5)
        fa_table.add_column("QPce", justify="center", width=5)
        fa_table.add_column("Con", justify="center", width=5)
        fa_table.add_column("Rcft", justify="center", width=5)
        fa_table.add_column("Wet", justify="center", width=5)
        fa_table.add_column("Tire", justify="center", width=5)
        fa_table.add_column("Men", justify="center", width=5)
        fa_table.add_column("Exp", justify="center", width=5)
        fa_table.add_column("Age", justify="center", width=5)
        fa_table.add_column("POT", justify="center", width=5)
        fa_table.add_column("Hire Cost", justify="right", width=10)

        for i, d in enumerate(free_agents, 1):
            hire_cost = round(d.salary * races_remaining / total_races, 1)
            color = "green" if team.budget >= hire_cost else "red"
            fa_table.add_row(
                str(i), d.name, str(d.overall),
                str(d.pace), str(d.qualifying_pace),
                str(d.consistency), str(d.racecraft),
                str(d.wet_weather), str(d.tire_management),
                str(d.mental), str(d.experience),
                str(d.age), str(d.potential),
                f"[{color}]€{hire_cost}M[/{color}]",
            )

        console.print(fa_table)

        console.print("[bold]Your current drivers:[/bold]")
        for slot, did in enumerate(team.driver_ids, 1):
            d = drivers.get(did)
            if d:
                console.print(f"  Seat {slot}: {d.name}  (OVR {d.overall}, €{d.salary}M/season)")

        console.print(f"\n[dim]Budget: €{team.budget:.1f}M[/dim]")
        console.print(
            "\n[dim]To hire: enter [bold]agent#-seat#[/bold] (e.g. '2-1' hires agent 2 into seat 1)"
            "  |  0 = back[/dim]"
        )

        choice = Prompt.ask("Action", default="0")
        if choice == "0":
            break

        try:
            parts = choice.split("-")
            if len(parts) != 2:
                raise ValueError
            agent_idx = int(parts[0]) - 1
            seat_idx = int(parts[1]) - 1

            if not (0 <= agent_idx < len(free_agents)):
                raise ValueError("Invalid agent")
            if not (0 <= seat_idx < len(team.driver_ids)):
                raise ValueError("Invalid seat")

            new_driver = free_agents[agent_idx]
            hire_cost = round(new_driver.salary * races_remaining / total_races, 1)

            if team.budget < hire_cost:
                console.print(f"[red]Not enough budget. Need €{hire_cost}M[/red]")
                continue

            old_id = team.driver_ids[seat_idx]
            old_driver = drivers.get(old_id)
            if old_driver:
                old_driver.team_id = None
                console.print(f"[yellow]{old_driver.name} released.[/yellow]")

            new_driver.team_id = team.id
            team.driver_ids[seat_idx] = new_driver.id
            team.budget -= hire_cost
            console.print(
                f"[green]✓ {new_driver.name} signed! Budget remaining: €{team.budget:.1f}M[/green]"
            )

        except (ValueError, IndexError):
            console.print("[red]Invalid format. Try '2-1' to put agent 2 in seat 1.[/red]")


def management_menu(
    team: Team,
    drivers: Dict[str, Driver],
    teams: Dict[str, Team],
    race_num: int,
    total_races: int,
    driver_pts: Dict[str, int],
    team_pts: Dict[str, int],
) -> None:
    while True:
        console.print()
        console.print(
            Panel(
                f"[bold]PRE-RACE MANAGEMENT[/bold]  [dim]Race {race_num}/{total_races}[/dim]\n"
                f"Budget: [bold green]€{team.budget:.1f}M[/bold green]",
                border_style=team.color,
                padding=(0, 2),
            )
        )
        console.print("  [bold cyan][1][/bold cyan] View team")
        console.print("  [bold cyan][2][/bold cyan] Upgrade car")
        console.print("  [bold cyan][3][/bold cyan] Driver market")
        console.print("  [bold cyan][4][/bold cyan] Championship standings")
        console.print("  [bold green][5][/bold green] Start race →")
        console.print()

        choice = Prompt.ask("Choice", choices=["1", "2", "3", "4", "5"])

        if choice == "1":
            show_team_overview(team, drivers)
        elif choice == "2":
            upgrade_car_menu(team)
        elif choice == "3":
            driver_market_menu(team, drivers, teams, total_races - race_num + 1, total_races)
        elif choice == "4":
            show_standings(driver_pts, team_pts, drivers, teams, team.id)
        elif choice == "5":
            break


# ─── Qualifying ───────────────────────────────────────────────────────────────

def run_qualifying_with_animation(
    entries: List[RaceEntry], circuit: Circuit, weather: str
) -> List[QualiResult]:
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task(
            f"[cyan]Qualifying — {circuit.name}...[/cyan]", total=15
        )
        for _ in range(15):
            time.sleep(0.06)
            progress.advance(task, 1)
        return simulate_qualifying(entries, circuit, weather)


def show_quali_results(
    results: List[QualiResult], player_team_id: str, circuit: Circuit
) -> None:
    console.print()
    table = Table(
        title=f"QUALIFYING — {circuit.name}",
        box=box.ROUNDED,
        header_style="bold white",
        show_lines=False,
    )
    table.add_column("Pos", width=5, justify="center")
    table.add_column("Driver", min_width=20)
    table.add_column("Team", min_width=18)
    table.add_column("Gap", min_width=12, justify="right")

    for r in results:
        is_player = r.team_id == player_team_id
        prefix = "[bold]▶ [/bold]" if is_player else "  "
        name_str = f"{prefix}{r.driver.name}"
        team_str = f"[{r.team_color}]{r.team_name}[/{r.team_color}]"

        if r.position == 1:
            pos_str = "[bold yellow]P1[/bold yellow]"
            gap_str = "[bold cyan]POLE POSITION[/bold cyan]"
        elif r.position <= 3:
            pos_str = f"[bold green]P{r.position}[/bold green]"
            gap_str = f"+{r.lap_time_delta:.3f}s"
        elif r.position >= 11:
            pos_str = f"[dim]P{r.position}[/dim]"
            gap_str = f"[dim]+{r.lap_time_delta:.3f}s[/dim]"
        else:
            pos_str = f"P{r.position}"
            gap_str = f"+{r.lap_time_delta:.3f}s"

        table.add_row(pos_str, name_str, team_str, gap_str)

    console.print(table)


_DEV_STATS = [
    ("pace",            "Pace"),
    ("qualifying_pace", "Qualifying"),
    ("consistency",     "Consistency"),
    ("racecraft",       "Racecraft"),
    ("wet_weather",     "Wet Weather"),
    ("tire_management", "Tyre Mgmt"),
    ("mental",          "Mental"),
    ("experience",      "Experience"),
]


def _xp_bar(xp: float, width: int = 10) -> str:
    filled = int(xp * width)
    bar = "█" * filled + "░" * (width - filled)
    pct = int(xp * 100)
    return f"[cyan]{bar}[/cyan] [dim]{pct:>3}%[/dim]"


def show_driver_development(
    team: Team,
    drivers: Dict[str, Driver],
    gains: Dict[str, Dict[str, int]],
    xp_gains: Dict[str, Dict[str, float]],
) -> None:
    panels = []
    for did in team.driver_ids:
        driver = drivers.get(did)
        if not driver:
            continue
        driver_gains = gains.get(did, {})
        driver_xp_gains = xp_gains.get(did, {})

        table = Table(box=None, show_header=False, padding=(0, 1))
        table.add_column("Stat", min_width=12)
        table.add_column("Val", justify="right", width=4)
        table.add_column("XP Progress", min_width=18)
        table.add_column("Gained", width=6, justify="right")
        table.add_column("", width=4)

        for attr, label in _DEV_STATS:
            val = getattr(driver, attr)
            xp = driver.xp.get(attr, 0.0)
            delta = driver_gains.get(attr, 0)
            gained = driver_xp_gains.get(attr, 0.0)

            gained_str = f"[dim]+{gained * 100:.1f}%[/dim]" if gained > 0 else ""

            if delta > 0:
                badge = f"[bold green]+{delta}[/bold green]"
                val_str = f"[bold green]{val}[/bold green]"
            elif delta < 0:
                badge = f"[bold red]{delta}[/bold red]"
                val_str = f"[bold red]{val}[/bold red]"
            else:
                badge = ""
                val_str = str(val)

            table.add_row(label, val_str, _xp_bar(xp), gained_str, badge)

        panels.append(Panel(table, title=f"[bold]{driver.name}[/bold]", padding=(0, 1)))

    console.print()
    console.print(Panel(
        Columns(panels) if panels else "[dim]—[/dim]",
        title="[bold]DRIVER DEVELOPMENT[/bold]",
        border_style="cyan",
        padding=(0, 1),
    ))


# ─── Strategy UI ──────────────────────────────────────────────────────────────

def _fmt_stint(stint: TyreStint) -> str:
    """Rich-formatted compound symbol with lap count, e.g. [red]S[/red](14)."""
    info = TYRE_COMPOUNDS[stint.compound]
    return f"[{info['color']}]{info['symbol']}[/{info['color']}]({stint.laps})"


def _fmt_strategy(strategy: RaceStrategy) -> str:
    return " → ".join(_fmt_stint(s) for s in strategy.stints)


def _custom_strategy(weather: str, total_laps: int, circuit, car, driver) -> RaceStrategy:
    """Prompt the player to build a custom strategy with per-stint lap selection."""
    is_wet = weather == "wet"
    valid_map = {"I": "intermediate", "W": "wet"} if is_wet else {"H": "hard", "M": "medium", "S": "soft"}
    valid_keys = list(valid_map.keys())
    compound_hint = "/".join(valid_keys)

    while True:
        stops_str = Prompt.ask("Number of pit stops", choices=["1", "2", "3"])
        num_stints = int(stops_str) + 1
        stints: List[TyreStint] = []
        remaining = total_laps

        for i in range(num_stints):
            is_last = (i == num_stints - 1)

            # Show tyre lives for reference on dry races
            if not is_wet:
                lives = {k: adjusted_tyre_life(valid_map[k], circuit, car, driver) for k in valid_keys}
                life_hint = "  ".join(
                    f"[{TYRE_COMPOUNDS[valid_map[k]]['color']}]{k}[/{TYRE_COMPOUNDS[valid_map[k]]['color']}] ~{lives[k]}L"
                    for k in valid_keys
                )
                console.print(f"  Tyre life: {life_hint}  |  [dim]{remaining} laps remaining[/dim]")

            key = Prompt.ask(f"Stint {i + 1} compound [{compound_hint}]", choices=valid_keys).upper()
            compound = valid_map[key]
            life = adjusted_tyre_life(compound, circuit, car, driver)

            if is_last:
                laps = remaining
                overrun = laps - life
                if overrun > 0:
                    console.print(
                        f"  [yellow]⚠ Last stint runs {laps} laps on {compound} "
                        f"(life ~{life}L, overrun {overrun}L — puncture risk!)[/yellow]"
                    )
                else:
                    console.print(f"  [dim]Last stint: {laps} laps (within tyre life ✓)[/dim]")
            else:
                # Player picks laps — leave at least 1 lap per future stint
                max_laps = remaining - (num_stints - i - 1)
                while True:
                    laps_str = Prompt.ask(f"Stint {i + 1} laps [1–{max_laps}]")
                    try:
                        laps = int(laps_str)
                        if 1 <= laps <= max_laps:
                            break
                        console.print(f"[red]Enter a number between 1 and {max_laps}.[/red]")
                    except ValueError:
                        console.print("[red]Enter a valid number.[/red]")
                overrun = laps - life
                if overrun > 0:
                    console.print(
                        f"  [yellow]⚠ Stint {i + 1}: {laps} laps on {compound} "
                        f"(life ~{life}L, overrun {overrun}L — puncture risk!)[/yellow]"
                    )

            stints.append(TyreStint(compound=compound, laps=laps))
            remaining -= laps

        if not is_wet and len({s.compound for s in stints}) < 2:
            console.print("[red]You must use at least 2 different compounds in dry conditions. Try again.[/red]")
            continue

        return RaceStrategy(stints=stints, label="Custom")


def show_strategy_menu(
    circuit: Circuit,
    weather: str,
    player_team: "Team",
    drivers: Dict[str, "Driver"],
) -> Dict[str, RaceStrategy]:
    """
    Display the tyre strategy selection screen and return a dict mapping each
    player driver ID to their chosen RaceStrategy.
    """
    player_drivers = [drivers[did] for did in player_team.driver_ids if did in drivers]
    ref_driver = player_drivers[0] if player_drivers else None
    car = player_team.car
    total = race_laps(circuit)
    is_wet = weather == "wet"

    presets = suggest_strategies(circuit, weather, car, ref_driver) if ref_driver else []
    recommended_idx = 0 if is_wet else 1   # Intermediate Only / Balanced

    # ── Build panel content ──────────────────────────────────────────
    lines: List[str] = []
    weather_tag = "[blue]RAIN[/blue]" if is_wet else "[yellow]DRY[/yellow]"
    lines.append(f"[bold]TYRE STRATEGY[/bold] — {circuit.name}")
    lines.append(
        f"Weather: {weather_tag}  |  Tyre Wear: [bold]{circuit.tire_wear.upper()}[/bold]"
        f"  |  Race Distance: [bold]{total} laps[/bold]"
    )
    lines.append("")

    if ref_driver:
        lines.append("Compound life (adjusted for your car):")
        if is_wet:
            inter_life = adjusted_tyre_life("intermediate", circuit, car, ref_driver)
            wet_life   = adjusted_tyre_life("wet",          circuit, car, ref_driver)
            lines.append(f"  [green]I[/green] Intermediate — ~{inter_life} laps")
            lines.append(f"  [blue]W[/blue] Wet          — ~{wet_life} laps")
        else:
            hard_life = adjusted_tyre_life("hard",   circuit, car, ref_driver)
            med_life  = adjusted_tyre_life("medium", circuit, car, ref_driver)
            soft_life = adjusted_tyre_life("soft",   circuit, car, ref_driver)
            lines.append(f"  [white]H[/white] Hard   — ~{hard_life} laps")
            lines.append(f"  [yellow]M[/yellow] Medium — ~{med_life} laps")
            lines.append(f"  [red]S[/red] Soft   — ~{soft_life} laps")
        lines.append("")

    lines.append("Preset strategies:")
    for i, preset in enumerate(presets):
        rec = "  [bold cyan]← rec.[/bold cyan]" if i == recommended_idx else ""
        lines.append(f"  [[bold]{i + 1}[/bold]] {preset.label:<16} {_fmt_strategy(preset)}{rec}")

    custom_num = len(presets) + 1
    lines.append(f"  [[bold]{custom_num}[/bold]] Custom — choose compounds manually")

    console.print()
    console.print(Panel("\n".join(lines), border_style="cyan", padding=(0, 2)))

    valid_choices = [str(i + 1) for i in range(len(presets))] + [str(custom_num)]
    choice = Prompt.ask("Strategy", choices=valid_choices)
    choice_idx = int(choice) - 1

    if choice_idx < len(presets):
        chosen = presets[choice_idx]
    else:
        chosen = _custom_strategy(weather, total, circuit, car, ref_driver)

    return {d.id: chosen for d in player_drivers}


def show_strategy_summary(
    player_team: "Team",
    drivers: Dict[str, "Driver"],
    strategies: Dict[str, RaceStrategy],
) -> None:
    """Show the player's chosen strategy for each of their drivers."""
    lines: List[str] = []
    for did in player_team.driver_ids:
        d = drivers.get(did)
        if d and d.id in strategies:
            strategy = strategies[d.id]
            lines.append(f"  {d.name}: {_fmt_strategy(strategy)} — [italic]{strategy.label}[/italic]")
    if lines:
        console.print(Panel("\n".join(lines), title="[bold]YOUR STRATEGY[/bold]", border_style="cyan", padding=(0, 1)))


# ─── Race Simulation ──────────────────────────────────────────────────────────

def run_race_with_animation(
    entries: List[RaceEntry],
    circuit: Circuit,
    weather: str,
    grid: Optional[List[str]] = None,
    strategies: Optional[Dict[str, RaceStrategy]] = None,
) -> List[RaceResult]:
    results: Optional[List[RaceResult]] = None

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task(
            f"[yellow]Racing — {circuit.name}...[/yellow]", total=20
        )
        for _ in range(20):
            time.sleep(0.08)
            progress.advance(task, 1)
        results = simulate_race(entries, circuit, weather, grid=grid, strategies=strategies)

    return results


# ─── Finances ─────────────────────────────────────────────────────────────────

POSITION_PRIZE = {1: 8.0, 2: 7.0, 3: 6.0, 4: 5.0, 5: 4.0,
                  6: 3.2, 7: 2.5, 8: 1.8, 9: 1.2, 10: 0.8}


def _apply_race_finances(
    team: Team,
    results: List[RaceResult],
    player_team_id: str,
) -> None:
    """Compute and apply race income, ops cost, and DNF repairs. Print a summary panel."""
    player_results = [r for r in results if r.team_id == player_team_id]
    num_dnfs = sum(1 for r in player_results if r.dnf)

    base_income     = 2.0
    ops_cost        = -2.0
    dnf_repairs     = -6.0 * num_dnfs
    constructor_win = 6.0 if any(r.position == 1 and not r.dnf for r in player_results) else 0.0

    prize_lines = []
    total_prize = 0.0
    for r in player_results:
        prize = POSITION_PRIZE.get(r.position, 0.0) if not r.dnf else 0.0
        total_prize += prize
        status = "DNF" if r.dnf else f"P{r.position}"
        color = "green" if prize > 0 else "dim"
        prize_lines.append(
            f"  {r.driver.name} ({status})  [{color}]+€{prize:.1f}M[/{color}]"
        )

    net = round(base_income + total_prize + constructor_win + ops_cost + dnf_repairs, 1)
    team.budget = max(0.0, team.budget + net)

    lines = [f"  Base income      [green]+€{base_income:.1f}M[/green]"]
    lines += prize_lines
    if constructor_win:
        lines.append(f"  Constructor win  [bold green]+€{constructor_win:.1f}M[/bold green]")
    lines.append(f"  Running costs    [red]−€{abs(ops_cost):.1f}M[/red]")
    if num_dnfs:
        lines.append(
            f"  DNF repairs      [red]−€{abs(dnf_repairs):.1f}M[/red]"
            f"  ({num_dnfs} DNF{'s' if num_dnfs > 1 else ''})"
        )
    net_color = "green" if net >= 0 else "red"
    sign = "+" if net >= 0 else ""
    lines.append(f"\n  Net this race    [{net_color}]{sign}€{net:.1f}M[/{net_color}]")
    lines.append(f"  Budget now       [bold]€{team.budget:.1f}M[/bold]")

    console.print(Panel(
        "\n".join(lines),
        title="[bold]FINANCES[/bold]",
        border_style="yellow",
        padding=(0, 2),
    ))


# ─── Main Game Loop ───────────────────────────────────────────────────────────

def main() -> None:
    show_welcome()

    drivers = load_drivers()
    teams = load_teams(drivers)

    player_team_id = show_team_selection(teams, drivers)
    player_team = teams[player_team_id]

    season_year = 2026

    console.print(
        f"[bold]Season {season_year} begins — {len(load_circuits())} races ahead.[/bold]\n"
        f"[dim]Good luck![/dim]"
    )
    console.input("\n[dim]Press Enter to start…[/dim]")

    while True:
        circuits = load_circuits()
        total_races = len(circuits)

        driver_pts: Dict[str, int] = {did: 0 for did in drivers}
        team_pts: Dict[str, int] = {tid: 0 for tid in teams}

        for race_num, circuit in enumerate(circuits, 1):
            show_race_header(circuit, race_num, total_races)

            management_menu(
                player_team, drivers, teams,
                race_num, total_races,
                driver_pts, team_pts,
            )

            # Build all entries (before qualifying)
            entries: List[RaceEntry] = []
            for team in teams.values():
                for did in team.driver_ids:
                    d = drivers.get(did)
                    if d:
                        entries.append(RaceEntry(
                            driver=d, car=team.car,
                            team_id=team.id, team_name=team.short_name,
                            team_color=team.color,
                        ))
            random.shuffle(entries)

            # ── Qualifying ──────────────────────────────────────────────
            quali_weather = "wet" if random.random() * 100 < circuit.weather_chance * 0.5 else "dry"
            show_race_header(circuit, race_num, total_races, quali_weather)
            console.print(Panel("[bold cyan]QUALIFYING SESSION[/bold cyan]", border_style="cyan", padding=(0, 2)))
            quali_results = run_qualifying_with_animation(entries, circuit, quali_weather)
            show_quali_results(quali_results, player_team_id, circuit)
            grid = [qr.driver.id for qr in quali_results]
            console.input("\n[dim]Press Enter for strategy selection…[/dim]")

            # ── Race ────────────────────────────────────────────────────
            weather = "wet" if random.random() * 100 < circuit.weather_chance else "dry"
            show_race_header(circuit, race_num, total_races, weather)

            # Strategy selection — player picks, AI fills the rest
            player_strategies = show_strategy_menu(circuit, weather, player_team, drivers)
            show_strategy_summary(player_team, drivers, player_strategies)
            strategies: Dict[str, RaceStrategy] = dict(player_strategies)
            for entry in entries:
                if entry.driver.id not in strategies:
                    strategies[entry.driver.id] = ai_strategy(entry, circuit, weather)

            console.input("\n[dim]Press Enter to start the race…[/dim]")
            results = run_race_with_animation(entries, circuit, weather, grid=grid, strategies=strategies)

            # ── View 1: Race Result ──────────────────────────────────
            console.clear()
            show_race_header(circuit, race_num, total_races, weather)
            show_race_results(results, player_team_id, circuit)
            console.input("\n[dim]Press Enter for finances…[/dim]")

            # ── View 2: Finances ─────────────────────────────────────
            console.clear()
            show_race_header(circuit, race_num, total_races, weather)
            _apply_race_finances(player_team, results, player_team_id)
            console.input("\n[dim]Press Enter for driver development…[/dim]")

            # ── View 3: Driver Development ───────────────────────────
            console.clear()
            show_race_header(circuit, race_num, total_races, weather)
            gains, xp_gains = apply_development(results, drivers, grid=grid)
            show_driver_development(player_team, drivers, gains, xp_gains)
            console.input("\n[dim]Press Enter for championship standings…[/dim]")

            # ── View 4: Championship ─────────────────────────────────
            console.clear()
            for r in results:
                driver_pts[r.driver.id] = driver_pts.get(r.driver.id, 0) + r.points
                team_pts[r.team_id] = team_pts.get(r.team_id, 0) + r.points
            show_standings(driver_pts, team_pts, drivers, teams, player_team_id, season_year=season_year)

            if race_num < total_races:
                console.input("\n[dim]Press Enter for the next race…[/dim]")
            else:
                console.input("\n[dim]Press Enter to see the final standings…[/dim]")

        # ── Season summary ────────────────────────────────────────────
        console.print()
        console.print(
            Panel(
                Align.center(Text.from_markup(f"[bold yellow]SEASON {season_year} — FINAL STANDINGS[/bold yellow]")),
                border_style="yellow",
                box=box.DOUBLE_EDGE,
                padding=(1, 6),
            )
        )

        show_standings(driver_pts, team_pts, drivers, teams, player_team_id, top_n=20, season_year=season_year)

        sorted_teams_final = sorted(team_pts.items(), key=lambda x: x[1], reverse=True)
        team_pos = next(
            (i for i, (tid, _) in enumerate(sorted_teams_final, 1) if tid == player_team_id), 0
        )
        p_pts = team_pts.get(player_team_id, 0)

        sorted_drivers_final = sorted(driver_pts.items(), key=lambda x: x[1], reverse=True)
        player_driver_results = [
            (drivers[did].name, pts, pos + 1)
            for pos, (did, pts) in enumerate(sorted_drivers_final)
            if drivers.get(did) and drivers[did].team_id == player_team_id
        ]

        driver_summary = "\n".join(
            f"  {name}: P{pos} — {pts} pts" for name, pts, pos in player_driver_results
        )

        console.print()
        console.print(
            Panel(
                f"[bold {player_team.color}]{player_team.name}[/bold {player_team.color}]\n\n"
                f"Constructors: [bold]P{team_pos}[/bold]  ({p_pts} pts)\n"
                f"Budget remaining: [bold green]€{player_team.budget:.1f}M[/bold green]\n\n"
                f"[dim]Drivers:[/dim]\n{driver_summary}",
                title=f"[bold]YOUR SEASON {season_year} SUMMARY[/bold]",
                border_style=player_team.color,
                padding=(1, 2),
            )
        )
        console.print()

        play_next = _run_offseason(season_year, teams, drivers, team_pts, player_team_id)
        if not play_next:
            break
        season_year += 1

        console.print(
            f"[bold]Season {season_year} begins — {len(load_circuits())} races ahead.[/bold]\n"
            f"[dim]Good luck![/dim]"
        )
        console.input("\n[dim]Press Enter to start…[/dim]")


# ─── Off-Season ───────────────────────────────────────────────────────────────

CONSTRUCTOR_PRIZE = {1: 80, 2: 60, 3: 45, 4: 35, 5: 28, 6: 22, 7: 17, 8: 12, 9: 8, 10: 5}


def _run_offseason(
    season_year: int,
    teams: Dict[str, Team],
    drivers: Dict[str, Driver],
    team_pts: Dict[str, int],
    player_team_id: str,
) -> bool:
    """Run off-season logic. Returns True if the player wants to continue."""
    player_team = teams[player_team_id]

    # 1. Prize money payout
    sorted_teams = sorted(team_pts.items(), key=lambda x: x[1], reverse=True)
    prize_rows: List[tuple] = []
    for pos, (tid, _) in enumerate(sorted_teams, 1):
        prize = CONSTRUCTOR_PRIZE.get(pos, 0)
        teams[tid].budget += prize
        is_player = tid == player_team_id
        prize_rows.append((pos, teams[tid].name, prize, is_player))

    prize_table = Table(
        title="CONSTRUCTOR CHAMPIONSHIP PRIZE MONEY",
        box=box.SIMPLE_HEAD, show_edge=False,
    )
    prize_table.add_column("Pos", width=4, justify="center")
    prize_table.add_column("Team", min_width=22)
    prize_table.add_column("Prize", justify="right", width=10)
    for pos, name, prize, is_player in prize_rows:
        style = "bold green" if is_player else ""
        prize_table.add_row(
            str(pos),
            f"[{style}]{name}[/{style}]" if style else name,
            f"[green]+€{prize}M[/green]",
        )

    # 2. Age all drivers
    for d in drivers.values():
        d.age += 1

    # 3. Retirement roll
    retired_names: List[str] = []
    for d in list(drivers.values()):
        if d.team_id is None:
            continue
        retire = False
        if d.age >= 42 and random.random() < 0.65:
            retire = True
        elif d.age >= 40 and random.random() < 0.40:
            retire = True
        elif d.age >= 38 and random.random() < 0.18:
            retire = True
        elif d.age >= 35 and random.random() < 0.05:
            retire = True
        if retire:
            retired_names.append(d.name)
            team = teams.get(d.team_id)
            if team and d.id in team.driver_ids:
                team.driver_ids.remove(d.id)
            d.team_id = None

    # 4. Car degradation — all teams, all attributes lose 2–5 points (floor 40)
    _CAR_ATTRS = list(UPGRADE_COSTS.keys())
    _DEGRADE_FLOOR = 40
    player_degrade: Dict[str, int] = {}
    for team in teams.values():
        for attr in _CAR_ATTRS:
            current = getattr(team.car, attr)
            loss = random.randint(2, 5)
            new_val = max(_DEGRADE_FLOOR, current - loss)
            setattr(team.car, attr, new_val)
            if team.id == player_team_id:
                player_degrade[attr] = new_val - current  # negative

    degrade_table = Table(
        title=f"[bold {player_team.color}]{player_team.name}[/bold {player_team.color}]  — Car Component Wear",
        box=box.SIMPLE_HEAD, show_edge=False,
    )
    degrade_table.add_column("Component", min_width=18)
    degrade_table.add_column("Change", justify="right", width=8)
    degrade_table.add_column("New Rating", justify="right", width=10)
    attr_labels = {
        "engine": "Engine", "aerodynamics": "Aerodynamics",
        "mechanical_grip": "Mechanical Grip", "reliability": "Reliability",
        "tire_deg": "Tyre Degradation", "braking": "Braking", "pit_crew": "Pit Crew",
    }
    for attr in _CAR_ATTRS:
        delta = player_degrade.get(attr, 0)
        new_val = getattr(player_team.car, attr)
        degrade_table.add_row(
            attr_labels[attr],
            f"[red]{delta}[/red]",
            str(new_val),
        )

    # 5. Off-season summary panel
    console.print()
    console.print(
        Panel(
            Align.center(Text.from_markup(f"[bold yellow]SEASON {season_year} OFF-SEASON[/bold yellow]")),
            border_style="yellow",
            box=box.DOUBLE_EDGE,
            padding=(1, 4),
        )
    )
    console.print(prize_table)
    console.print()
    console.print(degrade_table)
    if retired_names:
        console.print()
        console.print(
            Panel(
                "\n".join(f"  [dim]•[/dim] {n}" for n in retired_names),
                title="[bold]RETIREMENTS[/bold]",
                border_style="red",
                padding=(0, 2),
            )
        )
    else:
        console.print("\n[dim]No driver retirements this off-season.[/dim]")
    console.print(
        f"\n[bold {player_team.color}]{player_team.name}[/bold {player_team.color}] "
        f"budget: [bold green]€{player_team.budget:.1f}M[/bold green]"
    )
    console.print()

    # 6. Player driver market
    existing_ids = set(drivers.keys())
    _player_offseason_market(player_team, drivers, teams, existing_ids, season_year)

    # 7. AI teams fill vacant seats
    free_agents = sorted(
        [d for d in drivers.values() if d.team_id is None],
        key=lambda d: d.overall, reverse=True,
    )
    for team in teams.values():
        if team.id == player_team_id:
            continue
        while len(team.driver_ids) < 2:
            if free_agents:
                new_d = free_agents.pop(0)
            else:
                new_d = generate_rookie(existing_ids, season_year)
                drivers[new_d.id] = new_d
            new_d.team_id = team.id
            team.driver_ids.append(new_d.id)

    # 8. AI car upgrades — prefer cheapest available attribute (lowest current value)
    for team in teams.values():
        if team.id == player_team_id:
            continue
        budget_to_spend = team.budget * 0.20
        attrs = list(UPGRADE_COSTS.keys())
        attempts = 0
        while budget_to_spend > 0 and attempts < len(attrs) * 2:
            attrs_by_value = sorted(attrs, key=lambda a: getattr(team.car, a))
            attr = attrs_by_value[0]
            current_val = getattr(team.car, attr)
            cost = upgrade_cost(attr, current_val)
            if cost <= budget_to_spend and current_val < 100:
                team.car.upgrade(attr)
                team.budget -= cost
                budget_to_spend -= cost
            else:
                attempts += 1

    # 8. Ask to continue
    return Confirm.ask(f"Start Season {season_year + 1}?")


def _player_offseason_market(
    team: Team,
    drivers: Dict[str, Driver],
    teams: Dict[str, Team],
    existing_ids: set,
    season_year: int,
) -> None:
    """Let the player manage their driver lineup in the off-season."""
    if not Confirm.ask("Manage your driver lineup?", default=False):
        return

    while True:
        console.print()
        console.print(Panel("[bold]OFF-SEASON DRIVER MARKET[/bold]", border_style="cyan", padding=(0, 2)))

        # Current roster
        console.print("[bold]Your current drivers:[/bold]")
        for slot, did in enumerate(team.driver_ids, 1):
            d = drivers.get(did)
            if d:
                console.print(f"  Seat {slot}: {d.name}  (OVR {d.overall}, Age {d.age}, €{d.salary}M/season)")
        vacant = 2 - len(team.driver_ids)
        if vacant > 0:
            for v in range(vacant):
                console.print(f"  Seat {len(team.driver_ids) + v + 1}: [red]VACANT[/red]")
        console.print()

        # Generate rookies to show alongside free agents
        free_agents = [d for d in drivers.values() if d.team_id is None]
        new_rookies: List[Driver] = []
        for _ in range(3):
            r = generate_rookie(existing_ids, season_year)
            new_rookies.append(r)

        all_candidates = free_agents + new_rookies
        fa_table = Table(title="Available Drivers (Free Agents + Rookies)", box=box.SIMPLE_HEAD, show_edge=False)
        fa_table.add_column("#", width=3)
        fa_table.add_column("Name", min_width=18)
        fa_table.add_column("OVR", justify="center", width=5)
        fa_table.add_column("Age", justify="center", width=5)
        fa_table.add_column("POT", justify="center", width=5)
        fa_table.add_column("Salary", justify="right", width=8)
        fa_table.add_column("Type", width=8)
        for i, d in enumerate(all_candidates, 1):
            kind = "[dim]Free Agent[/dim]" if d in free_agents else "[cyan]Rookie[/cyan]"
            fa_table.add_row(str(i), d.name, str(d.overall), str(d.age), str(d.potential), f"€{d.salary}M", kind)
        console.print(fa_table)

        console.print("[dim]Options: 'R<seat>' to release (e.g. R1), 'S<#>' to sign candidate (e.g. S3), or '0' to finish[/dim]")
        choice = Prompt.ask("Action", default="0").strip().upper()

        if choice == "0":
            # Ensure player team is fully staffed before leaving
            if len(team.driver_ids) < 2:
                console.print("[yellow]You must fill all seats before continuing.[/yellow]")
                continue
            break

        if choice.startswith("R") and len(choice) > 1:
            try:
                seat_idx = int(choice[1:]) - 1
                if 0 <= seat_idx < len(team.driver_ids):
                    released_id = team.driver_ids.pop(seat_idx)
                    released = drivers.get(released_id)
                    if released:
                        released.team_id = None
                        console.print(f"[yellow]{released.name} released to free agency.[/yellow]")
                else:
                    console.print("[red]Invalid seat number.[/red]")
            except ValueError:
                console.print("[red]Invalid command.[/red]")

        elif choice.startswith("S") and len(choice) > 1:
            if len(team.driver_ids) >= 2:
                console.print("[yellow]Both seats are already filled. Release a driver first.[/yellow]")
                continue
            try:
                cand_idx = int(choice[1:]) - 1
                if 0 <= cand_idx < len(all_candidates):
                    new_d = all_candidates[cand_idx]
                    # If it's a rookie not yet in drivers dict, add them
                    if new_d not in free_agents:
                        drivers[new_d.id] = new_d
                        existing_ids.add(new_d.id)
                    new_d.team_id = team.id
                    team.driver_ids.append(new_d.id)
                    console.print(f"[green]✓ {new_d.name} signed![/green]")
                else:
                    console.print("[red]Invalid candidate number.[/red]")
            except ValueError:
                console.print("[red]Invalid command.[/red]")
        else:
            console.print("[red]Unknown command. Use R<seat>, S<#>, or 0.[/red]")


if __name__ == "__main__":
    main()
