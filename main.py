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
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from models.car import UPGRADE_COSTS, UPGRADE_AMOUNT
from models.car import Car
from models.circuit import Circuit
from models.driver import Driver
from models.team import Team
from engine.race import RaceEntry, RaceResult, QualiResult, simulate_race, simulate_qualifying
from engine.development import apply_development

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
        elif r.position == 1:
            pos_str = "[bold yellow]1[/bold yellow]"
            gap_str = "[green]WINNER[/green]"
        else:
            pos_str = str(r.position)
            gap_str = f"+{r.time_gap:.3f}s"

        fl_str = "[bold yellow]FL[/bold yellow]" if r.fastest_lap else ""
        pts_str = f"[bold]{r.points}[/bold]" if r.points > 0 else ""
        name_str = f"{prefix}{r.driver.name}"
        team_str = f"[{r.team_color}]{r.team_name}[/{r.team_color}]"

        table.add_row(pos_str, name_str, team_str, gap_str, pts_str, fl_str)

    console.print(table)


def show_standings(
    driver_pts: Dict[str, int],
    team_pts: Dict[str, int],
    drivers: Dict[str, Driver],
    teams: Dict[str, Team],
    player_team_id: str,
    top_n: int = 10,
) -> None:
    sorted_drivers = sorted(driver_pts.items(), key=lambda x: x[1], reverse=True)[:top_n]
    sorted_teams = sorted(team_pts.items(), key=lambda x: x[1], reverse=True)

    d_table = Table(title="DRIVERS' CHAMPIONSHIP", box=box.SIMPLE_HEAD, show_edge=False)
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

    c_table = Table(title="CONSTRUCTORS' CHAMPIONSHIP", box=box.SIMPLE_HEAD, show_edge=False)
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
            cost = UPGRADE_COSTS[attr]
            current = getattr(car, attr)
            after = min(100, current + UPGRADE_AMOUNT)
            maxed = current >= 100
            color = "green" if team.budget >= cost and not maxed else "red"
            status = "[dim]MAXED[/dim]" if maxed else f"[{color}]€{cost}M[/{color}]"
            table.add_row(num, label, str(current), str(after), status)

        table.add_row("0", "[dim]Back[/dim]", "", "", "")
        console.print(table)

        choice = Prompt.ask("Choose", choices=["0", "1", "2", "3", "4", "5", "6"])
        if choice == "0":
            break

        attr, label = attr_map[choice]
        cost = UPGRADE_COSTS[attr]

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


def show_driver_development(
    team: Team,
    drivers: Dict[str, Driver],
    gains: Dict[str, Dict[str, int]],
) -> None:
    panels = []
    for did in team.driver_ids:
        driver = drivers.get(did)
        if not driver:
            continue
        driver_gains = gains.get(did, {})
        lines: List[str] = []
        for stat, delta in driver_gains.items():
            old_val = getattr(driver, stat) - delta
            new_val = getattr(driver, stat)
            stat_label = stat.replace("_", " ").title()
            if delta > 0:
                lines.append(f"[green]+{delta}[/green] {stat_label} ({old_val} → {new_val})")
            else:
                lines.append(f"[red]{delta}[/red] {stat_label} ({old_val} → {new_val})")
        content = "\n".join(lines) if lines else "[dim]No development this race.[/dim]"
        panels.append(Panel(content, title=f"[bold]{driver.name}[/bold]", padding=(0, 1)))

    console.print()
    console.print(Panel(
        Columns(panels) if panels else "[dim]—[/dim]",
        title="[bold]DRIVER DEVELOPMENT[/bold]",
        border_style="cyan",
        padding=(0, 1),
    ))


# ─── Race Simulation ──────────────────────────────────────────────────────────

def run_race_with_animation(
    entries: List[RaceEntry], circuit: Circuit, weather: str,
    grid: Optional[List[str]] = None,
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
        results = simulate_race(entries, circuit, weather, grid=grid)

    return results


# ─── Main Game Loop ───────────────────────────────────────────────────────────

def main() -> None:
    show_welcome()

    drivers = load_drivers()
    teams = load_teams(drivers)
    circuits = load_circuits()
    total_races = len(circuits)

    player_team_id = show_team_selection(teams, drivers)
    player_team = teams[player_team_id]

    driver_pts: Dict[str, int] = {did: 0 for did in drivers}
    team_pts: Dict[str, int] = {tid: 0 for tid in teams}

    console.print(
        f"[bold]Season 2026 begins — {total_races} races ahead.[/bold]\n"
        f"[dim]Good luck![/dim]"
    )
    console.input("\n[dim]Press Enter to start…[/dim]")

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
        console.input("\n[dim]Press Enter to start the race…[/dim]")

        # ── Race ────────────────────────────────────────────────────
        weather = "wet" if random.random() * 100 < circuit.weather_chance else "dry"
        show_race_header(circuit, race_num, total_races, weather)
        results = run_race_with_animation(entries, circuit, weather, grid=grid)
        show_race_results(results, player_team_id, circuit)

        # Driver development
        gains = apply_development(results, drivers, grid=grid)
        show_driver_development(player_team, drivers, gains)

        # Update standings
        for r in results:
            driver_pts[r.driver.id] = driver_pts.get(r.driver.id, 0) + r.points
            team_pts[r.team_id] = team_pts.get(r.team_id, 0) + r.points

        # Operational cost per race
        player_team.budget = max(0.0, player_team.budget - 3.0)

        show_standings(driver_pts, team_pts, drivers, teams, player_team_id)

        if race_num < total_races:
            console.input("\n[dim]Press Enter for the next race…[/dim]")
        else:
            console.input("\n[dim]Press Enter to see the final standings…[/dim]")

    # ── Season summary ────────────────────────────────────────────
    console.print()
    console.print(
        Panel(
            Align.center(Text.from_markup("[bold yellow]SEASON 2026 — FINAL STANDINGS[/bold yellow]")),
            border_style="yellow",
            box=box.DOUBLE_EDGE,
            padding=(1, 6),
        )
    )

    show_standings(driver_pts, team_pts, drivers, teams, player_team_id, top_n=20)

    sorted_teams = sorted(team_pts.items(), key=lambda x: x[1], reverse=True)
    team_pos = next(
        (i for i, (tid, _) in enumerate(sorted_teams, 1) if tid == player_team_id), 0
    )
    p_pts = team_pts.get(player_team_id, 0)

    sorted_drivers = sorted(driver_pts.items(), key=lambda x: x[1], reverse=True)
    player_driver_results = [
        (drivers[did].name, pts, pos + 1)
        for pos, (did, pts) in enumerate(sorted_drivers)
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
            title="[bold]YOUR SEASON SUMMARY[/bold]",
            border_style=player_team.color,
            padding=(1, 2),
        )
    )
    console.print()


if __name__ == "__main__":
    main()
