"""Season and team overview screens: team stats, driver development, standings.
# Functions: show_team_overview:28  show_driver_development:78  show_standings:183
"""
from __future__ import annotations

from typing import Dict, List, Optional

from rich.align import Align
from rich.columns import Columns
from rich import box
from rich.panel import Panel
from rich.table import Table

from models.circuit import Circuit
from models.driver import Driver
from models.team import Team
from .helpers import console, stat_bar, _xp_bar


_DEV_STATS = [
    ("pace",            "Pace"),
    ("qualifying_pace", "Qualifying"),
    ("consistency",     "Consistency"),
    ("overtaking",      "Overtaking"),
    ("defending",       "Defending"),
    ("aggression",      "Aggression"),
    ("car_control",     "Car Control"),
    ("wet_weather",     "Wet Weather"),
    ("tire_management", "Tyre Mgmt"),
    ("mental",          "Mental"),
    ("experience",      "Experience"),
]


def show_team_overview(team: Team, drivers: Dict[str, Driver]) -> None:
    console.print()
    console.print(Panel(
        f"[bold {team.color}]{team.name}[/bold {team.color}]",
        subtitle=f"Budget: [bold green]€{team.budget:.1f}M[/bold green]",
        border_style=team.color,
    ))

    d_table = Table(title="Drivers — Performance", box=box.SIMPLE_HEAD, show_edge=False)
    d_table.add_column("Name", min_width=18)
    d_table.add_column("OVR", justify="center", width=5)
    d_table.add_column("Pace", min_width=16)
    d_table.add_column("Q.Pace", min_width=16)
    d_table.add_column("Consistency", min_width=16)
    d_table.add_column("Overtaking", min_width=16)
    d_table.add_column("Defending", min_width=16)
    d_table.add_column("Car Control", min_width=16)
    d_table.add_column("Aggression", min_width=16)

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
                f"[{age_color}]{d.age}[/{age_color}] [dim]{d.age_group.capitalize()}[/dim]  "
                f"[dim]POT [/dim][bold]{d.potential}[/bold]"
            )
            d_table.add_row(
                d.name, str(d.overall),
                stat_bar(d.pace), stat_bar(d.qualifying_pace),
                stat_bar(d.consistency), stat_bar(d.overtaking),
                stat_bar(d.defending), stat_bar(d.car_control), stat_bar(d.aggression),
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


def show_driver_development(
    team: Team, drivers: Dict[str, Driver],
    gains: Dict[str, Dict[str, int]],
    xp_gains: Dict[str, Dict[str, float]],
    report=None,
) -> None:
    panels = []
    for did in team.driver_ids:
        driver = drivers.get(did)
        if not driver:
            continue
        driver_gains = gains.get(did, {})
        driver_xp_gains = xp_gains.get(did, {})

        overtakes = defenses = 0
        wet_fraction = 0.0
        has_fl = False
        if report is not None:
            overtakes   = report.overtakes_made.get(did, 0)
            defenses    = report.defenses_made.get(did, 0)
            driver_laps = report.lap_data.get(did, [])
            total_laps  = len(driver_laps)
            if total_laps > 0:
                rain_laps    = sum(1 for r in driver_laps if r.compound in ("intermediate", "wet"))
                wet_fraction = rain_laps / total_laps
            result  = next((r for r in report.results if r.driver.id == did), None)
            has_fl  = bool(result and result.fastest_lap)

        _bonus_color: Dict[str, str] = {}
        if overtakes > 0:
            _bonus_color["overtaking"] = "cyan"
            _bonus_color["aggression"] = "cyan"
        if defenses > 0:
            _bonus_color["defending"] = "blue"
        if wet_fraction > 0:
            _bonus_color["wet_weather"] = "green"
        if has_fl:
            _bonus_color["pace"] = "magenta"
            _bonus_color["qualifying_pace"] = "magenta"

        ordered_stats = sorted(_DEV_STATS, key=lambda x: (0 if x[0] in _bonus_color else 1))

        table = Table(box=None, show_header=False, padding=(0, 1))
        table.add_column("Stat", min_width=12)
        table.add_column("Val", justify="right", width=4)
        table.add_column("XP Pool", min_width=18)
        table.add_column("Race XP", width=7, justify="right")
        table.add_column("", width=4)

        perf_parts: List[str] = []
        if overtakes > 0:
            perf_parts.append(f"[cyan]{overtakes} overtake{'s' if overtakes > 1 else ''}[/cyan]")
        if defenses > 0:
            perf_parts.append(f"[blue]{defenses} defense{'s' if defenses > 1 else ''}[/blue]")
        if wet_fraction > 0:
            perf_parts.append(f"[green]{int(wet_fraction * 100)}% wet laps[/green]")
        if has_fl:
            perf_parts.append("[magenta]Fastest Lap[/magenta]")
        if perf_parts:
            table.add_row("[dim]Bonuses:[/dim]", "", "  ".join(perf_parts), "", "", end_section=True)

        for attr, label in ordered_stats:
            val   = getattr(driver, attr)
            xp    = driver.xp.get(attr, 0.0)
            delta = driver_gains.get(attr, 0)
            gained = driver_xp_gains.get(attr, 0.0)

            bonus_col = _bonus_color.get(attr, "")
            if bonus_col:
                gained_str = f"[bold {bonus_col}]+{gained * 100:.1f}%[/bold {bonus_col}]"
            elif gained > 0:
                gained_str = f"[dim]+{gained * 100:.1f}%[/dim]"
            else:
                gained_str = ""

            if delta > 0:
                badge   = f"[bold green]+{delta}[/bold green]"
                val_str = f"[bold green]{val}[/bold green]"
            elif delta < 0:
                badge   = f"[bold red]{delta}[/bold red]"
                val_str = f"[bold red]{val}[/bold red]"
            else:
                badge   = ""
                val_str = str(val)

            if val >= driver.potential:
                val_str += " [dim](capped)[/dim]"
            elif val == driver.potential - 1:
                val_str += " [yellow](near cap)[/yellow]"

            table.add_row(label, val_str, _xp_bar(xp), gained_str, badge)

        panels.append(Panel(table, title=f"[bold]{driver.name}[/bold]", padding=(0, 1)))

    console.print()
    console.print(Panel(
        Columns(panels, expand=True) if panels else "[dim]—[/dim]",
        title="[bold]DRIVER DEVELOPMENT[/bold]",
        border_style="cyan", padding=(0, 1),
    ))
    console.print(
        "[dim]Bonus key: [/dim]"
        "[cyan]Overtake[/cyan]  [blue]Defend[/blue]  [green]Wet[/green]  [magenta]Fastest Lap[/magenta]"
    )


def show_standings(
    driver_pts: Dict[str, int], team_pts: Dict[str, int],
    drivers: Dict[str, Driver], teams: Dict[str, Team],
    player_team_id: str, top_n: int = 10,
    season_year: int = 2026,
    races_remaining: Optional[int] = None,
    total_races: Optional[int] = None,
) -> None:
    all_sorted_drivers = sorted(driver_pts.items(), key=lambda x: x[1], reverse=True)
    sorted_drivers = all_sorted_drivers[:top_n]
    sorted_teams = sorted(team_pts.items(), key=lambda x: x[1], reverse=True)

    driver_leader_pts = all_sorted_drivers[0][1] if all_sorted_drivers else 0
    team_leader_id, team_leader_pts = sorted_teams[0] if sorted_teams else (None, 0)

    player_team = teams.get(player_team_id)
    player_driver_ids = set(player_team.driver_ids) if player_team else set()
    shown_ids = {did for did, _ in sorted_drivers}
    extra_player_rows = [
        (pos, did, pts)
        for pos, (did, pts) in enumerate(all_sorted_drivers, 1)
        if did in player_driver_ids and did not in shown_ids
    ]

    d_table = Table(title=f"DRIVERS' CHAMPIONSHIP — Season {season_year}", box=box.SIMPLE_HEAD, show_edge=False)
    d_table.add_column("Pos", width=4, justify="center")
    d_table.add_column("Driver", min_width=18)
    d_table.add_column("Team", min_width=16)
    d_table.add_column("Pts", justify="right", width=6)
    d_table.add_column("Gap", justify="right", width=10)

    for i, (did, pts) in enumerate(sorted_drivers, 1):
        d = drivers.get(did)
        t = teams.get(d.team_id) if d and d.team_id else None
        is_player = t and t.id == player_team_id
        team_str = f"[{t.color}]{t.short_name}[/{t.color}]" if t else "—"
        name_str = f"[bold]{d.name}[/bold]" if is_player else (d.name if d else did)
        gap_str = "[dim]— LEADER —[/dim]" if i == 1 else f"[dim]−{driver_leader_pts - pts}[/dim]"
        d_table.add_row(str(i), name_str, team_str, str(pts), gap_str)

    if extra_player_rows:
        d_table.add_row("[dim]…[/dim]", "", "", "", "")
        for pos, did, pts in extra_player_rows:
            d = drivers.get(did)
            t = teams.get(d.team_id) if d and d.team_id else None
            team_str = f"[{t.color}]{t.short_name}[/{t.color}]" if t else "—"
            gap_str = "[dim]— LEADER —[/dim]" if pos == 1 else f"[dim]−{driver_leader_pts - pts}[/dim]"
            d_table.add_row(f"[bold]{pos}[/bold]", f"[bold]{d.name}[/bold]" if d else did, team_str, str(pts), gap_str)

    c_table = Table(title=f"CONSTRUCTORS' CHAMPIONSHIP — Season {season_year}", box=box.SIMPLE_HEAD, show_edge=False)
    c_table.add_column("Pos", width=4, justify="center")
    c_table.add_column("Team", min_width=18)
    c_table.add_column("Pts", justify="right", width=6)
    c_table.add_column("Gap", justify="right", width=10)

    for i, (tid, pts) in enumerate(sorted_teams, 1):
        t = teams.get(tid)
        is_player = tid == player_team_id
        name_str = (f"[{t.color}][bold]{t.short_name}[/bold][/{t.color}]" if is_player
                    else (f"[{t.color}]{t.short_name}[/{t.color}]" if t else tid))
        gap_str = "[dim]— LEADER —[/dim]" if i == 1 else f"[dim]−{team_leader_pts - pts}[/dim]"
        c_table.add_row(str(i), name_str, str(pts), gap_str)

    console.print()
    console.print(Columns([d_table, c_table]))

    if races_remaining is not None and total_races is not None and sorted_teams:
        leader_team = teams.get(team_leader_id)
        leader_name = leader_team.short_name if leader_team else team_leader_id
        console.print(
            f"[dim]{races_remaining} race{'s' if races_remaining != 1 else ''} remaining  ·  "
            f"Leader: {leader_name} ({team_leader_pts} pts)[/dim]"
        )
