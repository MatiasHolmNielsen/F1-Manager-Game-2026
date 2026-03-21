"""Off-season logic: prize money, car degradation, retirements, driver market."""
from __future__ import annotations

import random
from typing import Dict, List, Set

from rich.align import Align
from rich.console import Console
from rich import box
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from models.car import UPGRADE_COSTS, upgrade_cost
from models.driver import Driver
from models.team import Team
from engine.generation import generate_rookie

console = Console()

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

    # 9. Ask to continue
    return Confirm.ask(f"Start Season {season_year + 1}?")


def _player_offseason_market(
    team: Team,
    drivers: Dict[str, Driver],
    teams: Dict[str, Team],
    existing_ids: Set[str],
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
