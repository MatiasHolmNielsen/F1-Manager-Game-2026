"""Pre-race management menus: car upgrades, driver market, management hub."""
from __future__ import annotations

from typing import Dict

from rich.console import Console
from rich import box
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from models.car import UPGRADE_COSTS, UPGRADE_AMOUNT, upgrade_cost
from models.driver import Driver
from models.team import Team
from .ui import show_team_overview, show_standings, stat_bar

console = Console()

ATTR_DESC = {
    "engine":          "straight-line speed",
    "aerodynamics":    "high-speed cornering",
    "mechanical_grip": "low-speed traction",
    "reliability":     "DNF resistance",
    "tire_deg":        "tyre conservation",
    "braking":         "late-braking ability",
    "pit_crew":        "pit stop time (60–90)",
}


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
        table.add_column("Description", min_width=22)
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
            desc = f"[dim]{ATTR_DESC.get(attr, '')}[/dim]"
            table.add_row(num, label, desc, str(current), str(after), status)

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
            current_val = getattr(team.car, attr)
            after_val = min(100, current_val + UPGRADE_AMOUNT)
            confirm = Prompt.ask(
                f"Confirm: upgrade {label} from {current_val} → {after_val} for €{cost:.1f}M? (y/n)",
                choices=["y", "n"], default="n", case_sensitive=False,
            )
            if confirm != "y":
                console.print("[dim]Cancelled.[/dim]")
                continue
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
        fa_table.add_column("Pace", min_width=16)
        fa_table.add_column("Q.Pace", min_width=16)
        fa_table.add_column("Consistency", min_width=16)
        fa_table.add_column("Overtaking", min_width=16)
        fa_table.add_column("Defending", min_width=16)
        fa_table.add_column("Wet", min_width=16)
        fa_table.add_column("Tire Mgmt", min_width=16)
        fa_table.add_column("Age", justify="center", width=5)
        fa_table.add_column("POT", justify="center", width=5)
        fa_table.add_column("Hire Cost", justify="right", width=10)

        for i, d in enumerate(free_agents, 1):
            hire_cost = round(d.salary * races_remaining / total_races, 1)
            color = "green" if team.budget >= hire_cost else "red"
            fa_table.add_row(
                str(i), d.name, str(d.overall),
                stat_bar(d.pace), stat_bar(d.qualifying_pace),
                stat_bar(d.consistency), stat_bar(d.overtaking), stat_bar(d.defending),
                stat_bar(d.wet_weather), stat_bar(d.tire_management),
                str(d.age), str(d.potential),
                f"[{color}]€{hire_cost}M[/{color}]",
            )

        console.print(fa_table)

        console.print("[bold]Your current drivers:[/bold]")
        for slot, did in enumerate(team.driver_ids, 1):
            d = drivers.get(did)
            if d:
                console.print(f"  [bold]{slot}.[/bold] {d.name}  (OVR {d.overall}, €{d.salary}M/season)")

        console.print(f"\n[dim]Budget: €{team.budget:.1f}M[/dim]")
        console.print("\n[dim]0 = back  |  Enter agent number to hire[/dim]")

        agent_choices = [str(i) for i in range(len(free_agents) + 1)]
        choice = Prompt.ask("Pick a free agent (number)", choices=agent_choices, default="0")
        if choice == "0":
            break

        agent_idx = int(choice) - 1
        new_driver = free_agents[agent_idx]
        hire_cost = round(new_driver.salary * races_remaining / total_races, 1)

        if team.budget < hire_cost:
            console.print(f"[red]Not enough budget. Need €{hire_cost}M, have €{team.budget:.1f}M[/red]")
            continue

        seat_choices = [str(i) for i in range(1, len(team.driver_ids) + 1)]
        seat_str = Prompt.ask("Replace which driver? (1/2)", choices=seat_choices)
        seat_idx = int(seat_str) - 1

        old_id = team.driver_ids[seat_idx]
        old_driver = drivers.get(old_id)
        if old_driver:
            savings = old_driver.salary
            confirm = Prompt.ask(
                f"Release [bold]{old_driver.name}[/bold] (€{savings}M saved)? This cannot be undone. (y/n)",
                choices=["y", "n"], default="n", case_sensitive=False,
            )
            if confirm != "y":
                console.print("[dim]Cancelled.[/dim]")
                continue
            old_driver.team_id = None
            console.print(f"[yellow]{old_driver.name} released.[/yellow]")

        new_driver.team_id = team.id
        team.driver_ids[seat_idx] = new_driver.id
        team.budget -= hire_cost
        console.print(
            f"[green]✓ {new_driver.name} signed! Budget remaining: €{team.budget:.1f}M[/green]"
        )


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
            show_standings(driver_pts, team_pts, drivers, teams, team.id,
                           races_remaining=total_races - race_num + 1, total_races=total_races)
        elif choice == "5":
            break
