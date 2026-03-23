"""Off-season logic: prize money, car degradation, retirements, driver market."""
from __future__ import annotations

import random
from typing import Dict, List, Optional, Set

from rich.align import Align
from rich.console import Console
from rich import box
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from models.car import UPGRADE_COSTS, upgrade_cost
from models.driver import Driver
from models.sponsor import Sponsor
from models.team import Team
from engine.generation import generate_rookie
from .ui import stat_bar

console = Console()

CONSTRUCTOR_PRIZE = {1: 80, 2: 60, 3: 45, 4: 35, 5: 28, 6: 22, 7: 17, 8: 12, 9: 8, 10: 5}


def _run_offseason(
    season_year: int,
    teams: Dict[str, Team],
    drivers: Dict[str, Driver],
    team_pts: Dict[str, int],
    player_team_id: str,
    all_sponsors: Optional[Dict[str, Sponsor]] = None,
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

    # 1b. Deduct driver salaries
    salary_rows: List[tuple] = []
    for team in teams.values():
        total_salary = sum(
            drivers[did].salary for did in team.driver_ids if did in drivers
        )
        team.budget -= total_salary
        if team.id == player_team_id:
            for did in team.driver_ids:
                d = drivers.get(did)
                if d:
                    salary_rows.append((d.name, d.salary))

    prize_table = Table(
        title="CONSTRUCTOR CHAMPIONSHIP PRIZE MONEY",
        box=box.SIMPLE_HEAD, show_edge=False,
    )
    prize_table.add_column("Pos", width=4, justify="center")
    prize_table.add_column("Team", min_width=22)
    prize_table.add_column("Prize", justify="right", width=10)
    prize_table.add_column("Driver Salaries", justify="right", width=18)
    for pos, name, prize, is_player in prize_rows:
        style = "bold green" if is_player else ""
        if is_player and salary_rows:
            sal_str = "  ".join(f"[red]−€{sal}M[/red] {n}" for n, sal in salary_rows)
        else:
            sal_str = ""
        prize_table.add_row(
            str(pos),
            f"[{style}]{name}[/{style}]" if style else name,
            f"[green]+€{prize}M[/green]",
            sal_str,
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
            retired_names.append((d.name, d.age))
            team = teams.get(d.team_id)
            if team and d.id in team.driver_ids:
                team.driver_ids.remove(d.id)
            d.team_id = None

    # 4. Car degradation — all teams, all attributes lose 2–5 points (floor 60, reliability 65)
    _CAR_ATTRS = list(UPGRADE_COSTS.keys())
    _DEGRADE_FLOOR = 60
    _RELIABILITY_FLOOR = 65
    player_degrade: Dict[str, int] = {}
    for team in teams.values():
        for attr in _CAR_ATTRS:
            current = getattr(team.car, attr)
            loss = random.randint(2, 5)
            floor = _RELIABILITY_FLOOR if attr == "reliability" else _DEGRADE_FLOOR
            new_val = max(floor, current - loss)
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
    console.input("\n[dim]Press Enter to continue...[/dim]")
    console.print()
    console.print(degrade_table)
    if retired_names:
        console.print()
        console.print(
            Panel(
                "\n".join(f"  [dim]•[/dim] {n} (age {age}) — retired" for n, age in retired_names),
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

    # 6b. Sponsor renewal
    if all_sponsors:
        _player_sponsor_renewal(player_team, all_sponsors)

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

    # Generate rookies once (outside the loop) so the list stays stable
    new_rookies: List[Driver] = []
    for _ in range(3):
        r = generate_rookie(existing_ids, season_year)
        new_rookies.append(r)

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

        free_agents = [d for d in drivers.values() if d.team_id is None]
        all_candidates = free_agents + new_rookies
        fa_table = Table(title="Available Drivers (Free Agents + Rookies)", box=box.SIMPLE_HEAD, show_edge=False)
        fa_table.add_column("#", width=3)
        fa_table.add_column("Name", min_width=18)
        fa_table.add_column("OVR", justify="center", width=5)
        fa_table.add_column("Age", justify="center", width=5)
        fa_table.add_column("POT", justify="center", width=5)
        fa_table.add_column("Pace", min_width=16)
        fa_table.add_column("Qual.", min_width=16)
        fa_table.add_column("Cons.", min_width=16)
        fa_table.add_column("Salary", justify="right", width=8)
        fa_table.add_column("Type", width=8)
        for i, d in enumerate(all_candidates, 1):
            kind = "[dim]Free Agent[/dim]" if d in free_agents else "[cyan]Rookie[/cyan]"
            fa_table.add_row(
                str(i), d.name, str(d.overall), str(d.age), str(d.potential),
                stat_bar(d.pace), stat_bar(d.qualifying_pace), stat_bar(d.consistency),
                f"€{d.salary}M", kind,
            )
        console.print(fa_table)

        console.print(
            "\n[dim]  [bold]0[/bold] Finish"
            + (f"  |  [bold]R1[/bold]–[bold]R{len(team.driver_ids)}[/bold] Release a seat" if team.driver_ids else "")
            + (f"  |  [bold]1[/bold]–[bold]{len(all_candidates)}[/bold] Sign a candidate" if len(team.driver_ids) < 2 else "")
            + "[/dim]"
        )
        action_choices = ["0"]
        for slot in range(1, len(team.driver_ids) + 1):
            action_choices.append(f"R{slot}")
        if len(team.driver_ids) < 2:
            for idx in range(1, len(all_candidates) + 1):
                action_choices.append(str(idx))

        choice = Prompt.ask("Action", default="0").strip()

        if choice == "0":
            if len(team.driver_ids) < 2:
                console.print("[yellow]You must fill all seats before continuing.[/yellow]")
                continue
            break

        # Release a seat: R1 or R2
        if choice.upper().startswith("R"):
            try:
                seat_idx = int(choice[1:]) - 1
                if 0 <= seat_idx < len(team.driver_ids):
                    released_id = team.driver_ids[seat_idx]
                    released = drivers.get(released_id)
                    if released:
                        confirm = Prompt.ask(
                            f"Release [bold]{released.name}[/bold]? Cannot be undone. (y/n)",
                            choices=["y", "n"], default="n",
                        )
                        if confirm == "y":
                            team.driver_ids.pop(seat_idx)
                            released.team_id = None
                            console.print(f"[yellow]{released.name} released to free agency.[/yellow]")
                        else:
                            console.print("[dim]Cancelled.[/dim]")
                else:
                    console.print("[red]Invalid seat number.[/red]")
            except ValueError:
                console.print("[red]Enter R1 or R2 to release a seat.[/red]")

        # Sign a candidate by number
        elif choice.isdigit():
            if len(team.driver_ids) >= 2:
                console.print("[yellow]Both seats are filled. Release a driver first (R1 or R2).[/yellow]")
                continue
            cand_idx = int(choice) - 1
            if 0 <= cand_idx < len(all_candidates):
                new_d = all_candidates[cand_idx]
                if new_d not in free_agents:
                    drivers[new_d.id] = new_d
                    existing_ids.add(new_d.id)
                new_d.team_id = team.id
                team.driver_ids.append(new_d.id)
                console.print(f"[green]✓ {new_d.name} signed! (€{new_d.salary}M/season)[/green]")
            else:
                console.print("[red]Invalid candidate number.[/red]")
        else:
            console.print("[red]Enter a candidate number to sign, R1/R2 to release, or 0 to finish.[/red]")


def _player_sponsor_renewal(
    team: Team,
    all_sponsors: Dict[str, Sponsor],
) -> None:
    """Show sponsor renewal screen. Player keeps current sponsor or picks a new one."""
    from game.ui import show_sponsor_selection  # avoid circular import at module level

    console.print()
    console.print(Panel("[bold]SPONSOR RENEWAL[/bold]", border_style="cyan", padding=(0, 2)))

    current = all_sponsors.get(team.sponsor_id) if team.sponsor_id else None
    if current:
        console.print(f"  Current sponsor: [bold cyan]{current.name}[/bold cyan] — €{current.race_payment:.2f}M/race")
        console.print()

    keep = Confirm.ask("Keep your current sponsor?", default=True) if current else False

    if not keep:
        available = random.sample(list(all_sponsors.values()), min(4, len(all_sponsors)))
        # Ensure the current sponsor is always included as an option when renewing
        if current and current not in available:
            available[0] = current
        # Use a placeholder total_races (22) for estimation — exact count loaded per season
        selected = show_sponsor_selection(available, team, total_races=22, renewing=True)
        team.sponsor_id = selected.id
    else:
        console.print(f"  [green]✓ {current.name} contract renewed![/green]\n")
