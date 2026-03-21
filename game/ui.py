"""All display / rendering functions for the F1 Manager game."""
from __future__ import annotations

import time
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

from models.circuit import Circuit
from models.driver import Driver
from models.team import Team
from engine.tyres import TYRE_COMPOUNDS, TyreStint, RaceStrategy, race_laps, adjusted_tyre_life, suggest_strategies, _tyre_score
from engine.qualifying import QualiResult, KnockoutQualiResult, simulate_qualifying, simulate_knockout_qualifying
from engine.race import (
    RaceEntry, RaceResult, RaceReport, PitStop, DriverLapRecord,
    simulate_race,
)

console = Console()


# ─── Formatting helpers ───────────────────────────────────────────────────────

def fmt_lap_time(seconds: float) -> str:
    """Format a lap time in seconds as M:SS.mmm (e.g. 1:27.341)."""
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


# ─── Team / Driver display ────────────────────────────────────────────────────

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
    d_table.add_column("Overtaking", min_width=16)
    d_table.add_column("Defending", min_width=16)
    d_table.add_column("Car Control", min_width=16)
    d_table.add_column("Aggression", min_width=16)

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


# ─── Race display ─────────────────────────────────────────────────────────────

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
            f"[bold white]{circuit.name}[/bold white]\n"
            f"[dim]{circuit.country}  •  {circuit.length_km}km  "
            f"•  {circuit.corners} corners  "
            f"•  Tire wear {tire_icon} {circuit.tire_wear}"
            f"{weather_str}[/dim]",
            border_style="yellow",
            box=box.HEAVY_HEAD,
        )
    )


def show_race_results(
    results: List[RaceResult], player_team_id: str, circuit: Circuit,
    fastest_lap_time: float = 0.0,
    driver_fastest_laps: Optional[Dict[str, float]] = None,
) -> None:
    console.print()
    table = Table(
        title=f"RACE RESULT — {circuit.name}",
        box=box.ROUNDED,
        header_style="bold white",
        show_lines=False,
    )
    table.add_column("Pos", width=4, justify="center")
    table.add_column("Grid±", width=6, justify="right")
    table.add_column("Driver", min_width=20)
    table.add_column("Team", min_width=18)
    table.add_column("Gap / Status", min_width=22)
    table.add_column("Pts", width=5, justify="center")
    table.add_column("Best Lap", width=12, justify="right")

    fl_laps = driver_fastest_laps or {}

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
        elif r.position == 2:
            pos_str = "[bold white]2[/bold white]"
            gap_str = f"+{r.time_gap:.3f}s"
            if r.grid_position > 0:
                delta = r.grid_position - r.position
                delta_str = f"[green]+{delta}[/green]" if delta > 0 else ("[dim]—[/dim]" if delta == 0 else f"[red]{delta}[/red]")
            else:
                delta_str = ""
        elif r.position == 3:
            pos_str = "[bold orange3]3[/bold orange3]"
            gap_str = f"+{r.time_gap:.3f}s"
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

        best = fl_laps.get(r.driver.id)
        if best:
            lap_str = fmt_lap_time(best)
            fl_str = f"[bold magenta]{lap_str}[/bold magenta]" if r.fastest_lap else f"[dim]{lap_str}[/dim]"
        else:
            fl_str = "[dim]—[/dim]"

        pts_str = f"[bold]{r.points}[/bold]" if r.points > 0 else ""
        name_str = f"{prefix}{r.driver.name}"
        team_str = f"[{r.team_color}]{r.team_name}[/{r.team_color}]"

        table.add_row(pos_str, delta_str, name_str, team_str, gap_str, pts_str, fl_str)

    console.print(table)


def show_pit_stats(
    pit_stops: List[PitStop],
    results: List[RaceResult],
    circuit: Circuit,
) -> None:
    """Display a compact pit stop summary per driver."""
    from collections import defaultdict

    console.print()

    driver_stops: dict = defaultdict(list)
    for stop in sorted(pit_stops, key=lambda s: s.lap):
        driver_stops[stop.driver_name].append(stop)

    table = Table(
        title=f"PIT STOPS  [dim](lane loss: {circuit.pit_lane_loss}s)[/dim]",
        box=box.SIMPLE_HEAD, show_edge=False, header_style="bold white",
    )
    table.add_column("Pos", width=4, justify="center")
    table.add_column("Driver", min_width=20)
    table.add_column("Stops", width=6, justify="center")
    table.add_column("Strategy", min_width=28)
    table.add_column("Stop laps (time lost)", min_width=30)
    table.add_column("Best Stop", width=10, justify="right")

    for r in results:
        name = r.driver.name
        stops = driver_stops.get(name, [])

        if stops:
            compounds = [stops[0].old_compound] + [s.new_compound for s in stops]
        else:
            compounds = []
        strategy_str = " → ".join(
            f"[{TYRE_COMPOUNDS[c]['color']}]{TYRE_COMPOUNDS[c]['symbol']}[/{TYRE_COMPOUNDS[c]['color']}]"
            for c in compounds
        ) if compounds else "[dim]—[/dim]"

        stop_detail = "  ".join(
            f"L{s.lap} [dim]({s.total_time:.1f}s)[/dim]" for s in stops
        ) if stops else "[dim]no stops[/dim]"

        if stops:
            best_stop = min(stops, key=lambda s: s.stationary_time)
            best_str = f"[bold]{best_stop.stationary_time:.2f}s[/bold]"
        else:
            best_str = "[dim]—[/dim]"

        pos_str = "[dim]—[/dim]" if r.dnf else str(r.position)
        name_str = f"[dim]{name}[/dim]" if r.dnf else name

        table.add_row(pos_str, name_str, str(len(stops)), strategy_str, stop_detail, best_str)

    console.print(table)
    parts = "  ".join(
        f"[{info['color']}]{info['symbol']}[/{info['color']}][dim]={name.capitalize()}[/dim]"
        for name, info in TYRE_COMPOUNDS.items()
    )
    console.print(f"[dim]  Compounds:[/dim]  {parts}")


# ─── Lap analysis ─────────────────────────────────────────────────────────────

def show_lap_analysis(
    team: Team,
    drivers: Dict[str, Driver],
    report: RaceReport,
    circuit: Circuit,
) -> None:
    """Interactive lap-by-lap data browser for the player's drivers."""
    player_drivers = [drivers[did] for did in team.driver_ids if did in drivers]
    if not player_drivers:
        return

    while True:
        console.print()
        console.print(Panel("[bold]LAP ANALYSIS[/bold]", border_style="cyan", padding=(0, 2)))
        for i, d in enumerate(player_drivers, 1):
            result = next((r for r in report.results if r.driver.id == d.id), None)
            result_str = f"DNF — {result.dnf_reason}" if result and result.dnf else (f"P{result.position}" if result else "—")
            laps_done = len(report.lap_data.get(d.id, []))
            best = report.driver_fastest_laps.get(d.id)
            best_str = fmt_lap_time(best) if best else "—"
            console.print(f"  [{i}] {d.name}  [dim]{result_str}  •  {laps_done} laps  •  best {best_str}[/dim]")
        console.print("  [0] Back")
        console.print()

        choices = [str(i) for i in range(len(player_drivers) + 1)]
        choice = Prompt.ask("Driver", choices=choices, default="0")
        if choice == "0":
            break

        driver = player_drivers[int(choice) - 1]
        records = report.lap_data.get(driver.id, [])
        if not records:
            console.print("[dim]No lap data available.[/dim]")
            continue

        _show_driver_laps(driver, records, report, circuit)


def _show_driver_laps(
    driver: Driver,
    records: List[DriverLapRecord],
    report: RaceReport,
    circuit: Circuit,
) -> None:
    """Render the per-lap table for one driver."""
    result = next((r for r in report.results if r.driver.id == driver.id), None)
    best_time = report.driver_fastest_laps.get(driver.id, 0.0)

    if result:
        if result.dnf:
            result_str = f"[red]DNF — {result.dnf_reason}[/red]  (lap {len(records)})"
        else:
            result_str = f"[bold]P{result.position}[/bold]  +{result.time_gap:.3f}s  (grid P{result.grid_position})"
    else:
        result_str = "—"

    console.print()
    console.print(Panel(
        f"[bold]{driver.name}[/bold]  •  {circuit.name}\n"
        f"{result_str}  •  best lap [bold magenta]{fmt_lap_time(best_time)}[/bold magenta]",
        border_style="cyan", padding=(0, 2),
    ))

    table = Table(
        box=box.SIMPLE_HEAD, show_edge=False, header_style="bold white",
        padding=(0, 1),
    )
    table.add_column("Lap",      width=4,  justify="right")
    table.add_column("Pos",      width=4,  justify="center")
    table.add_column("Tyre",     width=5,  justify="center")
    table.add_column("Age",      width=4,  justify="right")
    table.add_column("Wear",     width=7,  justify="right")
    table.add_column("Lap Time", width=12, justify="right")
    table.add_column("Δ Best",   width=9,  justify="right")
    table.add_column("Fuel",     width=7,  justify="right")
    table.add_column("Note",     width=14)

    prev_pos = None

    for rec in records:
        if rec.dnf:
            table.add_row(
                str(rec.lap), "[dim]—[/dim]", "", "", "", "",
                "", "", "[red]RETIRED[/red]",
            )
            break

        info    = TYRE_COMPOUNDS[rec.compound]
        c_color = info["color"]
        c_sym   = info["symbol"]
        tyre_str = f"[{c_color}]{c_sym}[/{c_color}]"

        if rec.wear_pct >= 75:
            wear_str = f"[red]{rec.wear_pct:.0f}%[/red]"
        elif rec.wear_pct >= 50:
            wear_str = f"[yellow]{rec.wear_pct:.0f}%[/yellow]"
        else:
            wear_str = f"[green]{rec.wear_pct:.0f}%[/green]"

        is_best = best_time > 0 and abs(rec.lap_time - best_time) < 0.001
        if is_best:
            lap_str = f"[bold magenta]{fmt_lap_time(rec.lap_time)}[/bold magenta]"
        else:
            lap_str = f"[{c_color}]{fmt_lap_time(rec.lap_time)}[/{c_color}]"

        delta = rec.lap_time - best_time if best_time > 0 else 0.0
        if is_best:
            delta_str = "[magenta]fastest[/magenta]"
        elif delta <= 0.5:
            delta_str = f"[dim]+{delta:.3f}[/dim]"
        elif delta <= 2.0:
            delta_str = f"+{delta:.3f}"
        else:
            delta_str = f"[red]+{delta:.3f}[/red]"

        if prev_pos is None or rec.position == prev_pos:
            pos_str = str(rec.position)
        elif rec.position < prev_pos:
            pos_str = f"[green]{rec.position}▲[/green]"
        else:
            pos_str = f"[red]{rec.position}▼[/red]"
        prev_pos = rec.position

        fuel_str = f"[dim]{rec.fuel_load:.1f}kg[/dim]"

        if rec.pitted:
            pit_stop = next(
                (s for s in report.pit_stops
                 if s.driver_name == driver.name and s.lap == rec.lap),
                None,
            )
            if pit_stop:
                ni = TYRE_COMPOUNDS[pit_stop.new_compound]
                note = (
                    f"PIT [{ni['color']}]{ni['symbol']}[/{ni['color']}]"
                    f" [dim]{pit_stop.total_time:.1f}s[/dim]"
                )
            else:
                note = "PIT"
        else:
            note = ""

        table.add_row(
            str(rec.lap), pos_str, tyre_str,
            str(rec.tyre_age), wear_str,
            lap_str, delta_str, fuel_str, note,
        )

    console.print(table)
    console.input("\n[dim]Press Enter to go back…[/dim]")


# ─── Driver development display ───────────────────────────────────────────────

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


def show_driver_development(
    team: Team,
    drivers: Dict[str, Driver],
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

        # Extract performance context
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

        # Map each stat to its bonus colour (empty string = no performance bonus this race)
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

        # Sort: stats with a performance bonus this race float to the top
        ordered_stats = sorted(
            _DEV_STATS,
            key=lambda x: (0 if x[0] in _bonus_color else 1),
        )

        table = Table(box=None, show_header=False, padding=(0, 1))
        table.add_column("Stat", min_width=12)
        table.add_column("Val", justify="right", width=4)
        table.add_column("XP Pool", min_width=18)
        table.add_column("Race XP", width=7, justify="right")
        table.add_column("", width=4)

        # Performance summary row at the top of the table
        perf_parts: List[str] = []
        if overtakes > 0:
            perf_parts.append(f"[cyan]{overtakes} overtake{'s' if overtakes > 1 else ''}[/cyan]")
        if defenses > 0:
            perf_parts.append(f"[blue]{defenses} defense{'s' if defenses > 1 else ''}[/blue]")
        if wet_fraction > 0:
            pct = int(wet_fraction * 100)
            perf_parts.append(f"[green]{pct}% wet laps[/green]")
        if has_fl:
            perf_parts.append("[magenta]Fastest Lap[/magenta]")
        if perf_parts:
            table.add_row(
                "[dim]Bonuses:[/dim]",
                "",
                "  ".join(perf_parts),
                "", "",
                end_section=True,
            )

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

            table.add_row(label, val_str, _xp_bar(xp), gained_str, badge)

        panels.append(Panel(table, title=f"[bold]{driver.name}[/bold]", padding=(0, 1)))

    console.print()
    console.print(Panel(
        Columns(panels, expand=True) if panels else "[dim]—[/dim]",
        title="[bold]DRIVER DEVELOPMENT[/bold]",
        border_style="cyan",
        padding=(0, 1),
    ))


# ─── Championship standings ───────────────────────────────────────────────────

def show_standings(
    driver_pts: Dict[str, int],
    team_pts: Dict[str, int],
    drivers: Dict[str, Driver],
    teams: Dict[str, Team],
    player_team_id: str,
    top_n: int = 10,
    season_year: int = 2026,
) -> None:
    all_sorted_drivers = sorted(driver_pts.items(), key=lambda x: x[1], reverse=True)
    sorted_drivers = all_sorted_drivers[:top_n]
    sorted_teams = sorted(team_pts.items(), key=lambda x: x[1], reverse=True)

    # Find player driver IDs not already in top_n
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

    for i, (did, pts) in enumerate(sorted_drivers, 1):
        d = drivers.get(did)
        t = teams.get(d.team_id) if d and d.team_id else None
        is_player = t and t.id == player_team_id
        team_str = f"[{t.color}]{t.short_name}[/{t.color}]" if t else "—"
        name_str = f"[bold]{d.name}[/bold]" if is_player else (d.name if d else did)
        d_table.add_row(str(i), name_str, team_str, str(pts))

    if extra_player_rows:
        d_table.add_row("[dim]…[/dim]", "", "", "")
        for pos, did, pts in extra_player_rows:
            d = drivers.get(did)
            t = teams.get(d.team_id) if d and d.team_id else None
            team_str = f"[{t.color}]{t.short_name}[/{t.color}]" if t else "—"
            d_table.add_row(f"[bold]{pos}[/bold]", f"[bold]{d.name}[/bold]" if d else did, team_str, str(pts))

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


# ─── Race events ──────────────────────────────────────────────────────────────

def show_race_events(events: List[str], max_events: int = 12) -> None:
    """Display notable race events (pit stops, overtakes, DNFs) in a panel."""
    if not events:
        return

    total_events = len(events)
    priority = [e for e in events if "retires" in e or "overtakes" in e]
    pits = [e for e in events if "pits" in e]

    shown = priority[:max_events]
    remaining = max_events - len(shown)
    if remaining > 0:
        shown += pits[:remaining]

    shown.sort(key=lambda e: int(e.split(":")[0].replace("Lap ", "")) if e.startswith("Lap ") else 0)

    lines = []
    for e in shown:
        if "retires" in e:
            lines.append(f"[red]{e}[/red]")
        elif "overtakes" in e:
            lines.append(f"[cyan]{e}[/cyan]")
        else:
            lines.append(f"[dim]{e}[/dim]")

    if total_events > max_events:
        lines.append(f"\n[dim]Showing {len(shown)} of {total_events} events[/dim]")

    console.print(Panel(
        "\n".join(lines),
        title="[bold]RACE EVENTS[/bold]",
        border_style="yellow",
        padding=(0, 2),
    ))


# ─── Qualifying display ───────────────────────────────────────────────────────

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


def show_knockout_quali_session(
    session: str,
    results: List[QualiResult],
    player_team_id: str,
    circuit: Circuit,
    cutoff: Optional[int] = None,
    advancement_label: Optional[str] = None,
) -> None:
    console.print()
    table = Table(
        title=f"{session} — {circuit.name}",
        box=box.ROUNDED,
        header_style="bold white",
        show_lines=False,
    )
    table.add_column("Pos", width=5, justify="center")
    table.add_column("Driver", min_width=20)
    table.add_column("Team", min_width=18)
    table.add_column("Gap to Fastest", min_width=14, justify="right")
    table.add_column("Status", width=12, justify="center")

    for r in results:
        is_player = r.team_id == player_team_id
        eliminated = cutoff is not None and r.position > cutoff
        prefix = "[bold]▶ [/bold]" if is_player else "  "

        if eliminated:
            name_str = f"[dim]{prefix}{r.driver.name}[/dim]"
            team_str = f"[dim][{r.team_color}]{r.team_name}[/{r.team_color}][/dim]"
            gap_str = f"[dim]+{r.lap_time_delta:.3f}s[/dim]"
            status_str = "[bold red]OUT[/bold red]"
        elif r.position == 1:
            name_str = f"{prefix}{r.driver.name}"
            team_str = f"[{r.team_color}]{r.team_name}[/{r.team_color}]"
            gap_str = "[bold cyan]POLE[/bold cyan]"
            status_str = ""
        elif r.position <= 3:
            name_str = f"{prefix}{r.driver.name}"
            team_str = f"[{r.team_color}]{r.team_name}[/{r.team_color}]"
            gap_str = f"[bold green]+{r.lap_time_delta:.3f}s[/bold green]"
            status_str = ""
        else:
            name_str = f"{prefix}{r.driver.name}"
            team_str = f"[{r.team_color}]{r.team_name}[/{r.team_color}]"
            gap_str = f"+{r.lap_time_delta:.3f}s"
            status_str = ""

        # Show advancement label at the cutoff boundary
        if cutoff is not None and r.position == cutoff and advancement_label:
            status_str = f"[dim]{advancement_label}[/dim]"

        pos_str: str
        if eliminated:
            pos_str = f"[dim]P{r.position}[/dim]"
        elif r.position == 1:
            pos_str = "[bold yellow]P1[/bold yellow]"
        elif r.position <= 3:
            pos_str = f"[bold green]P{r.position}[/bold green]"
        else:
            pos_str = f"P{r.position}"

        table.add_row(pos_str, name_str, team_str, gap_str, status_str)

    console.print(table)


def run_knockout_qualifying_with_animation(
    entries: List[RaceEntry],
    circuit: Circuit,
    weather: str,
    player_team_id: str,
) -> List[QualiResult]:
    """Simulate knockout qualifying, animate each session, return final_grid."""
    knockout = simulate_knockout_qualifying(entries, circuit, weather)

    def _progress_bar(description: str, steps: int, step_time: float) -> None:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
        ) as progress:
            task = progress.add_task(description, total=steps)
            for _ in range(steps):
                time.sleep(step_time)
                progress.advance(task, 1)

    # Q1
    console.print(Panel("[bold cyan]Q1 — QUALIFYING  (all 20 drivers)[/bold cyan]", border_style="cyan", padding=(0, 2)))
    _progress_bar(f"[cyan]Q1 — {circuit.name}...[/cyan]", 10, 0.06)
    show_knockout_quali_session("Q1", knockout.q1, player_team_id, circuit, cutoff=15, advancement_label="→ Q2")
    console.input("\n[dim]Press Enter for Q2…[/dim]")

    # Q2
    console.print(Panel("[bold cyan]Q2 — QUALIFYING  (top 15 advance)[/bold cyan]", border_style="cyan", padding=(0, 2)))
    _progress_bar(f"[cyan]Q2 — {circuit.name}...[/cyan]", 10, 0.06)
    show_knockout_quali_session("Q2", knockout.q2, player_team_id, circuit, cutoff=10, advancement_label="→ Q3")
    console.input("\n[dim]Press Enter for Q3…[/dim]")

    # Q3
    console.print(Panel("[bold yellow]Q3 — SHOOTOUT  (top 10 — final grid P1–P10)[/bold yellow]", border_style="yellow", padding=(0, 2)))
    _progress_bar(f"[yellow]Q3 — {circuit.name}...[/yellow]", 10, 0.08)
    show_knockout_quali_session("Q3", knockout.q3, player_team_id, circuit, cutoff=None)

    return knockout.final_grid


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


def _show_strategy_panel(
    circuit: Circuit,
    weather: str,
    car,
    driver,
    driver_label: str,
) -> RaceStrategy:
    """Display strategy options for a single driver and return their chosen strategy."""
    total = race_laps(circuit)
    is_wet = weather == "wet"

    presets = suggest_strategies(circuit, weather, car, driver)

    # Compute recommended index using tyre score
    if is_wet:
        recommended_idx = 0
    else:
        scores = [_tyre_score(p, circuit, weather, car, driver) for p in presets]
        recommended_idx = scores.index(max(scores))

    lines: List[str] = []
    weather_tag = "[blue]RAIN[/blue]" if is_wet else "[yellow]DRY[/yellow]"
    lines.append(f"[bold]TYRE STRATEGY[/bold] — {circuit.name}  [dim]({driver_label})[/dim]")
    lines.append(
        f"Weather: {weather_tag}  |  Tyre Wear: [bold]{circuit.tire_wear.upper()}[/bold]"
        f"  |  Race Distance: [bold]{total} laps[/bold]"
    )
    lines.append("")

    lines.append("Compound life (adjusted for this driver):")
    if is_wet:
        inter_life = adjusted_tyre_life("intermediate", circuit, car, driver)
        wet_life   = adjusted_tyre_life("wet",          circuit, car, driver)
        lines.append(f"  [green]I[/green] Intermediate — ~{inter_life} laps")
        lines.append(f"  [blue]W[/blue] Wet          — ~{wet_life} laps")
    else:
        hard_life = adjusted_tyre_life("hard",   circuit, car, driver)
        med_life  = adjusted_tyre_life("medium", circuit, car, driver)
        soft_life = adjusted_tyre_life("soft",   circuit, car, driver)
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
        return presets[choice_idx]
    return _custom_strategy(weather, total, circuit, car, driver)


def show_strategy_menu(
    circuit: Circuit,
    weather: str,
    player_team: Team,
    drivers: Dict[str, Driver],
) -> Dict[str, RaceStrategy]:
    """
    Display the tyre strategy selection screen and return a dict mapping each
    player driver ID to their chosen RaceStrategy.
    """
    player_drivers = [drivers[did] for did in player_team.driver_ids if did in drivers]
    car = player_team.car
    result: Dict[str, RaceStrategy] = {}

    for driver in player_drivers:
        strategy = _show_strategy_panel(circuit, weather, car, driver, driver.name)
        result[driver.id] = strategy

    return result


def show_strategy_summary(
    player_team: Team,
    drivers: Dict[str, Driver],
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


# ─── Animation wrappers ───────────────────────────────────────────────────────

def show_circuit_briefing(circuit: Circuit, player_team: Team) -> None:
    """Pre-race circuit briefing shown once per race weekend before the management hub."""
    total_laps = race_laps(circuit)

    # Tyre wear
    wear_color = {"low": "green", "medium": "yellow", "high": "red"}[circuit.tire_wear]
    wear_label = circuit.tire_wear.upper()

    # Overtaking difficulty
    od = circuit.overtaking_difficulty
    if od < 30:
        ot_label = "[green]EASY[/green]"
    elif od < 55:
        ot_label = "[yellow]MODERATE[/yellow]"
    elif od < 75:
        ot_label = "[red]DIFFICULT[/red]"
    else:
        ot_label = "[bold red]VERY DIFFICULT[/bold red]"

    # Weather forecast
    wc = circuit.weather_chance
    if wc < 20:
        wx_label = "[yellow]DRY[/yellow]"
    elif wc < 50:
        wx_label = "[blue]WET RISK[/blue]"
    else:
        wx_label = "[bold blue]LIKELY WET[/bold blue]"

    # Car spotlight: which attribute matters most here
    car = player_team.car
    if circuit.aero_weight >= circuit.engine_weight:
        spot_attr = "Aerodynamics"
        spot_val  = car.aerodynamics
        spot_note = f"Aero-dominant circuit ({circuit.aero_weight:.0%} aero weight)"
    else:
        spot_attr = "Engine"
        spot_val  = car.engine
        spot_note = f"Engine-dominant circuit ({circuit.engine_weight:.0%} engine weight)"
    spot_color = "green" if spot_val >= 75 else ("yellow" if spot_val >= 60 else "red")

    # Strategic hint
    hints: List[str] = []
    if circuit.tire_wear == "high":
        hints.append("High tyre wear — 2-stop viable. Pit crew speed matters.")
    elif circuit.tire_wear == "low":
        hints.append("Low tyre wear — 1-stop likely optimal.")
    if circuit.overtaking_difficulty >= 70:
        hints.append("Very hard to overtake — qualifying position is crucial.")
    elif circuit.overtaking_difficulty <= 30:
        hints.append("Plenty of overtaking chances — aggressive strategy viable.")
    if circuit.weather_chance >= 40:
        hints.append("Rain likely — have Intermediates ready.")
    hint_str = "  ".join(hints) if hints else "Standard conditions expected."

    stats_lines = [
        f"[dim]Laps:[/dim]        [bold]{total_laps}[/bold]  [dim]×[/dim]  [bold]{circuit.length_km}km[/bold]",
        f"[dim]Corners:[/dim]     [bold]{circuit.corners}[/bold]",
        f"[dim]Tyre wear:[/dim]   [bold {wear_color}]{wear_label}[/bold {wear_color}]",
        f"[dim]Overtaking:[/dim]  {ot_label}",
        f"[dim]Weather:[/dim]     {wx_label}  [dim]({circuit.weather_chance}% rain)[/dim]",
        f"[dim]Pit loss:[/dim]    [bold]{circuit.pit_lane_loss}s[/bold]",
    ]

    hint_lines = [
        f"[dim]Strategy hint:[/dim]",
        f"[italic]{hint_str}[/italic]",
        "",
        f"[dim]Car spotlight[/dim] [bold]{spot_attr}[/bold]",
        f"  [{spot_color}]{spot_note}[/{spot_color}]",
        f"  Your rating: [{spot_color}]{spot_val}[/{spot_color}]",
    ]

    stats_panel = Panel("\n".join(stats_lines), title="[dim]Circuit[/dim]", border_style="dim", padding=(0, 1))
    hint_panel  = Panel("\n".join(hint_lines),  title="[dim]Strategy Notes[/dim]", border_style="dim", padding=(0, 1))

    console.print()
    console.print(Panel(
        Columns([stats_panel, hint_panel]),
        title=f"[bold]{circuit.flag}  {circuit.name.upper()}  —  RACE WEEKEND BRIEFING[/bold]",
        subtitle=f"[dim]{circuit.country}[/dim]",
        border_style="yellow",
        padding=(0, 1),
    ))
    console.input("\n[dim]Press Enter to open team management…[/dim]")


def show_race_transition(
    prev_circuit: Circuit,
    next_circuit: Optional[Circuit],
    player_team: Team,
    drivers: Dict[str, Driver],
    teams: Dict[str, Team],
    player_team_id: str,
    driver_pts: Dict[str, int],
    team_pts: Dict[str, int],
    prev_team_pts: Dict[str, int],
    prev_driver_pts: Dict[str, int],
    race_results: List[RaceResult],
    race_num: int,
    total_races: int,
) -> None:
    """Debrief panel after standings; previews the next race."""
    # ── Section A: Race debrief ──────────────────────────────────────────────
    player_results = [r for r in race_results if r.team_id == player_team_id]
    team_pts_gained = team_pts.get(player_team_id, 0) - prev_team_pts.get(player_team_id, 0)
    pos_strs = " + ".join(
        f"P{r.position}" if not r.dnf else "DNF"
        for r in sorted(player_results, key=lambda x: x.position if not x.dnf else 99)
    )

    # Championship position & delta
    sorted_teams_now  = sorted(team_pts.items(), key=lambda x: x[1], reverse=True)
    sorted_teams_prev = sorted(prev_team_pts.items(), key=lambda x: x[1], reverse=True)
    pos_now  = next((i for i, (t, _) in enumerate(sorted_teams_now,  1) if t == player_team_id), 0)
    pos_prev = next((i for i, (t, _) in enumerate(sorted_teams_prev, 1) if t == player_team_id), 0)
    pos_delta = pos_prev - pos_now   # positive = moved up

    leader_team_id, leader_pts = sorted_teams_now[0]
    player_pts_now = team_pts.get(player_team_id, 0)

    if leader_team_id == player_team_id:
        champ_line = f"[bold green]You lead the championship by {player_pts_now - sorted_teams_now[1][1]} points![/bold green]"
    else:
        leader_team = teams.get(leader_team_id)
        gap_to_leader = leader_pts - player_pts_now
        delta_str = (f" [green](+{pos_delta} pos{'s' if pos_delta != 1 else ''})[/green]" if pos_delta > 0
                     else f" [red](-{-pos_delta} pos{'s' if -pos_delta != 1 else ''})[/red]" if pos_delta < 0
                     else "")
        leader_name = leader_team.short_name if leader_team else leader_team_id
        champ_line = f"P{pos_now} — [bold]{gap_to_leader}pts[/bold] behind {leader_name}{delta_str}"

    # Notable event from the race
    notable = ""
    dnf_results = [r for r in race_results if r.dnf]
    leader_result = next((r for r in race_results if r.position == 1 and not r.dnf), None)
    if dnf_results:
        # Pick a DNF that affected the player (if leader DNF'd it's notable)
        top_dnf = min(dnf_results, key=lambda r: r.grid_position if r.grid_position > 0 else 99)
        pts_gained_from_dnf = team_pts_gained - (prev_team_pts.get(player_team_id, 0) - team_pts.get(player_team_id, 0))
        notable = f"{top_dnf.driver.name} DNF ({top_dnf.dnf_reason})"
    if leader_result:
        fl_result = next((r for r in race_results if r.fastest_lap), None)
        if fl_result and fl_result.team_id != player_team_id and any(r.team_id == player_team_id and r.position <= 10 for r in race_results):
            notable = notable or f"{fl_result.driver.name} took fastest lap"

    debrief_lines = [
        f"[bold]Your result:[/bold]  {pos_strs}  >>  [bold cyan]+{team_pts_gained} pts[/bold cyan]",
        f"[bold]Championship:[/bold] {champ_line}",
    ]
    if notable:
        debrief_lines.append(f"[dim]Notable:[/dim]      {notable}")

    # ── Section B: Next race preview ────────────────────────────────────────
    if next_circuit:
        nod = next_circuit.overtaking_difficulty
        if nod >= 70:
            ot_hint = "low overtaking, qualifying crucial"
        elif nod <= 30:
            ot_hint = "high overtaking, strategy battles likely"
        else:
            ot_hint = "moderate overtaking opportunities"
        wear_hint = {"low": "easy on tyres", "medium": "medium tyre wear", "high": "heavy tyre wear"}[next_circuit.tire_wear]
        next_laps = race_laps(next_circuit)
        preview_lines = [
            f"[bold]Round {race_num + 1} of {total_races}[/bold]",
            f"[bold white]{next_circuit.flag}  {next_circuit.name}[/bold white]  [dim]{next_circuit.country}[/dim]",
            f"[dim]{next_laps} laps  •  {ot_hint}  •  {wear_hint}[/dim]",
            "",
            f"[dim]Budget:[/dim]  [bold green]€{player_team.budget:.1f}M[/bold green]",
        ]
    else:
        preview_lines = ["[dim]Season complete.[/dim]"]

    debrief_panel = Panel("\n".join(debrief_lines), title="[bold]Race Debrief[/bold]", border_style="cyan",  padding=(0, 1))
    preview_panel = Panel("\n".join(preview_lines), title="[bold]Next Race[/bold]",   border_style="yellow", padding=(0, 1))

    console.print()
    console.print(Panel(
        Columns([debrief_panel, preview_panel]),
        title=f"[bold]AFTER {prev_circuit.name.upper()}[/bold]",
        border_style="dim",
        padding=(0, 1),
    ))
    console.input("\n[dim]Press Enter to continue…[/dim]")


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


def run_race_with_animation(
    entries: List[RaceEntry],
    circuit: Circuit,
    weather: str,
    grid: Optional[List[str]] = None,
    strategies: Optional[Dict[str, RaceStrategy]] = None,
) -> RaceReport:
    # Simulate first so results are ready; then animate with live event ticker
    report = simulate_race(entries, circuit, weather, grid=grid, strategies=strategies)
    total_steps = 20
    total_laps = race_laps(circuit)

    # Bucket events by animation step: "Lap N: ..." → step proportional to N
    bucketed: Dict[int, List[str]] = {}
    for event in report.events:
        lap_num = 0
        if event.startswith("Lap "):
            try:
                lap_num = int(event.split(":")[0].replace("Lap ", "").strip())
            except (ValueError, IndexError):
                lap_num = 0
        step = min(total_steps - 1, int((lap_num / max(1, total_laps)) * total_steps))
        bucketed.setdefault(step, []).append(event)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task(
            f"[yellow]Racing — {circuit.name}...[/yellow]", total=total_steps
        )
        for step in range(total_steps):
            time.sleep(0.08)
            progress.advance(task, 1)
            for event in bucketed.get(step, []):
                if "SAFETY CAR" in event or "VIRTUAL SAFETY CAR" in event:
                    styled = f"[bold yellow]  SC  {event}[/bold yellow]"
                elif "Racing resumes" in event:
                    styled = f"[bold green]  GO  {event}[/bold green]"
                elif "retires" in event or "collision" in event.lower():
                    styled = f"[red]  !!  {event}[/red]"
                elif "overtakes" in event:
                    styled = f"[cyan]  ^   {event}[/cyan]"
                elif "pits under SC" in event:
                    styled = f"[yellow]  P   {event}[/yellow]"
                elif "pits" in event:
                    styled = f"[dim]  P   {event}[/dim]"
                elif "damage" in event:
                    styled = f"[yellow]  !   {event}[/yellow]"
                else:
                    styled = f"[dim]  -   {event}[/dim]"
                console.print(styled)
    return report
