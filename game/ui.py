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
from models.sponsor import Sponsor
from models.team import Team
from engine.tyres import TYRE_COMPOUNDS, TYRE_LIFE_BASE, TyreStint, RaceStrategy, race_laps, adjusted_tyre_life, suggest_strategies, _tyre_score
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

    has_weather = report.peak_rain_prob >= 55

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
    if has_weather:
        table.add_column("Rain", width=8,  justify="right")
    table.add_column("Note",     width=14)

    prev_pos = None

    for rec in records:
        if rec.dnf:
            row = [str(rec.lap), "[dim]—[/dim]", "", "", "", "", "", ""]
            if has_weather:
                row.append("")
            row.append("[red]RETIRED[/red]")
            table.add_row(*row)
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

        if has_weather:
            rp = rec.rain_prob
            if rp >= 92:
                rain_str = f"[blue]{rp:.0f}%[/blue]"
            elif rp >= 65:
                rain_str = f"[cyan]{rp:.0f}%[/cyan]"
            elif rp >= 45:
                rain_str = f"[dim cyan]{rp:.0f}%[/dim cyan]"
            else:
                rain_str = f"[dim]{rp:.0f}%[/dim]"
            table.add_row(
                str(rec.lap), pos_str, tyre_str,
                str(rec.tyre_age), wear_str,
                lap_str, delta_str, fuel_str, rain_str, note,
            )
        else:
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
        border_style="cyan",
        padding=(0, 1),
    ))
    console.print(
        "[dim]Bonus key: [/dim]"
        "[cyan]Overtake[/cyan]  [blue]Defend[/blue]  [green]Wet[/green]  [magenta]Fastest Lap[/magenta]"
    )


# ─── Championship standings ───────────────────────────────────────────────────

def show_standings(
    driver_pts: Dict[str, int],
    team_pts: Dict[str, int],
    drivers: Dict[str, Driver],
    teams: Dict[str, Team],
    player_team_id: str,
    top_n: int = 10,
    season_year: int = 2026,
    races_remaining: Optional[int] = None,
    total_races: Optional[int] = None,
) -> None:
    all_sorted_drivers = sorted(driver_pts.items(), key=lambda x: x[1], reverse=True)
    sorted_drivers = all_sorted_drivers[:top_n]
    sorted_teams = sorted(team_pts.items(), key=lambda x: x[1], reverse=True)

    driver_leader_pts = all_sorted_drivers[0][1] if all_sorted_drivers else 0
    team_leader_id, team_leader_pts = sorted_teams[0] if sorted_teams else (None, 0)

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
        name_str = f"[{t.color}][bold]{t.short_name}[/bold][/{t.color}]" if is_player else (
            f"[{t.color}]{t.short_name}[/{t.color}]" if t else tid
        )
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


# ─── Race events ──────────────────────────────────────────────────────────────

def show_race_events(events: List[str], max_events: int = 12, circuit=None) -> None:
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

    subtitle = None
    if circuit is not None:
        od = circuit.overtaking_difficulty
        if od >= 75:
            ot_label = "Very Difficult overtaking"
        elif od >= 55:
            ot_label = "Difficult overtaking"
        elif od >= 35:
            ot_label = "Moderate overtaking"
        else:
            ot_label = "Easy overtaking"
        subtitle = f"[dim]{circuit.name}  ·  {ot_label}[/dim]"

    console.print(Panel(
        "\n".join(lines),
        title="[bold]RACE EVENTS[/bold]",
        subtitle=subtitle,
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

        # Hard validation: last stint must not exceed 150% of tyre life
        last = stints[-1]
        last_life = adjusted_tyre_life(last.compound, circuit, car, driver)
        if last.laps > last_life * 1.5:
            console.print(
                f"[red]✗ Strategy rejected: last stint ({last.laps} laps on {last.compound}, "
                f"life ~{last_life}L) would destroy the tyre before the finish. "
                f"Maximum is {int(last_life * 1.5)} laps. Try again.[/red]"
            )
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
    season_poles: int = 0,
    season_fastest_laps: int = 0,
    season_podiums: int = 0,
    race_report: Optional[RaceReport] = None,
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
    if race_report and race_report.peak_rain_prob >= 65 and race_report.weather_summary:
        # Show the most significant weather event
        weather_evt = race_report.weather_summary[-1] if race_report.weather_summary else ""
        debrief_lines.append(
            f"[dim]Weather:[/dim]      [blue]{weather_evt}[/blue]  "
            f"[dim](peak {race_report.peak_rain_prob:.0f}%)[/dim]"
        )
    debrief_lines.append(
        f"[dim]Season so far: {season_poles} pole{'s' if season_poles != 1 else ''}  ·  "
        f"{season_fastest_laps} fastest lap{'s' if season_fastest_laps != 1 else ''}  ·  "
        f"{season_podiums} podium{'s' if season_podiums != 1 else ''}[/dim]"
    )

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


def _trim_strategy_to_remaining(strategy: RaceStrategy, remaining_laps: int) -> RaceStrategy:
    """Adjust a RaceStrategy to cover exactly remaining_laps."""
    stints = list(strategy.stints)
    total = sum(s.laps for s in stints)

    if total <= remaining_laps:
        # Extend last stint to fill
        extra = remaining_laps - total
        stints[-1] = TyreStint(stints[-1].compound, stints[-1].laps + extra)
    else:
        # Drop stints from the end until we fit, then trim the last
        while len(stints) > 1 and sum(s.laps for s in stints) > remaining_laps:
            stints.pop()
        used = sum(s.laps for s in stints[:-1])
        stints[-1] = TyreStint(stints[-1].compound, remaining_laps - used)

    return RaceStrategy(stints=stints, label=strategy.label)


def _show_sc_strategy_panel(
    circuit,
    weather: str,
    car,
    driver,
    driver_label: str,
    remaining_laps: int,
) -> RaceStrategy:
    """Display strategy options for remaining SC laps and return chosen strategy."""
    is_wet = weather == "wet"

    presets_full = suggest_strategies(circuit, weather, car, driver)
    presets = [_trim_strategy_to_remaining(p, remaining_laps) for p in presets_full]

    if is_wet:
        recommended_idx = 0
    else:
        scores = [_tyre_score(p, circuit, weather, car, driver) for p in presets]
        recommended_idx = scores.index(max(scores))

    lines: List[str] = []
    lines.append(
        f"[bold]SC STRATEGY[/bold] — {circuit.name}  [dim]({driver_label})[/dim]"
        f"  [yellow]{remaining_laps} laps remaining[/yellow]"
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
    console.print(Panel("\n".join(lines), border_style="yellow", padding=(0, 2)))

    valid_choices = [str(i + 1) for i in range(len(presets))] + [str(custom_num)]
    choice = Prompt.ask("Strategy", choices=valid_choices)
    choice_idx = int(choice) - 1

    if choice_idx < len(presets):
        return presets[choice_idx]
    return _custom_strategy(weather, remaining_laps, circuit, car, driver)


def show_sc_strategy_decision(lap: int, total_laps: int, driver_infos: list) -> dict:
    """Prompt the player for each driver: stay out or pit and choose full remaining strategy."""
    console.print()
    remaining = total_laps - lap
    sc_type = driver_infos[0].get("sc_type", "SC") if driver_infos else "SC"
    sc_laps_rem = driver_infos[0].get("sc_laps_remaining", 3) if driver_infos else 3
    rain_prob = driver_infos[0].get("rain_prob", 0.0) if driver_infos else 0.0
    forecast  = driver_infos[0].get("forecast", []) if driver_infos else []
    trend     = driver_infos[0].get("trend", "stable") if driver_infos else "stable"

    console.print(Panel(
        f"[bold yellow]  {sc_type} — LAP {lap} of {total_laps}  ({remaining} laps left · {sc_type} ends ~{sc_laps_rem} laps)[/bold yellow]",
        border_style="yellow",
        expand=False,
    ))

    # Weather forecast block — only shown when rain is a factor
    if rain_prob >= 45 or any(fp >= 45 for fp in forecast[:8]):
        trend_str = {"rising": "[red]↑ rising[/red]", "falling": "[cyan]↓ falling[/cyan]", "stable": "[dim]→ stable[/dim]"}.get(trend, trend)
        wx_lines = [
            f"  Rain: {_rain_bar(rain_prob, 10)}  ({trend_str})",
            "  Forecast (next 8 laps):",
        ]
        for i, fp in enumerate(forecast[:8]):
            wx_lines.append(f"    L{lap + i + 1:<3} {_rain_bar(fp, 8)}")
        wx_lines.append("  [dim]Forecast: reliable 1–3 laps, less certain beyond[/dim]")
        console.print(Panel("\n".join(wx_lines), border_style="cyan", padding=(0, 1), expand=False))

    table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    table.add_column("Driver", style="white")
    table.add_column("Pos", justify="right")
    table.add_column("Tyre", justify="center")
    table.add_column("Age", justify="right")
    table.add_column("Tyre life left", justify="right")
    table.add_column("Gap fwd", justify="right")
    table.add_column("Gap bck", justify="right")
    table.add_column("Rec", justify="center")

    recommendations: Dict[str, bool] = {}
    for info in driver_infos:
        base_life = TYRE_LIFE_BASE.get(info["circuit_wear"], TYRE_LIFE_BASE["medium"]).get(info["compound"], 25)
        life_left = max(0, base_life - info["tyre_age"])
        rec_pit = info["tyre_age"] > base_life * 0.55
        recommendations[info["id"]] = rec_pit
        rec_str = "[green]PIT[/green]" if rec_pit else "[dim]STAY[/dim]"
        cmp_color = {"soft": "red", "medium": "yellow", "hard": "white",
                     "intermediate": "green", "wet": "blue"}.get(info["compound"], "white")

        gap_ahead = info.get("gap_ahead")
        gap_behind = info.get("gap_behind")

        if gap_ahead is None:
            gap_fwd_str = "[dim]—[/dim]"
        elif gap_ahead < 2.0:
            gap_fwd_str = f"[red]{gap_ahead:.1f}s[/red]"
        elif gap_ahead > 5.0:
            gap_fwd_str = f"[green]{gap_ahead:.1f}s[/green]"
        else:
            gap_fwd_str = f"{gap_ahead:.1f}s"

        if gap_behind is None:
            gap_bck_str = "[dim]—[/dim]"
        elif gap_behind < 2.0:
            gap_bck_str = f"[red]{gap_behind:.1f}s[/red]"
        elif gap_behind > 5.0:
            gap_bck_str = f"[green]{gap_behind:.1f}s[/green]"
        else:
            gap_bck_str = f"{gap_behind:.1f}s"

        table.add_row(
            info["name"],
            f"P{info['position']}",
            f"[{cmp_color}]{info['compound'].capitalize()}[/{cmp_color}]",
            str(info["tyre_age"]),
            f"~{life_left} laps",
            gap_fwd_str,
            gap_bck_str,
            rec_str,
        )
    console.print(table)

    # Strategic notes
    for info in driver_infos:
        gap_behind = info.get("gap_behind")
        gap_ahead = info.get("gap_ahead")
        if gap_behind is not None and gap_behind < 2.0:
            console.print(
                f"[yellow]⚠ {info['name']}: car behind is {gap_behind:.1f}s back — may jump you if they pit[/yellow]"
            )
        elif gap_ahead is not None and gap_ahead > 5.0:
            console.print(
                f"[green]{info['name']}: comfortable gap ahead — pitting won't cost position[/green]"
            )

    decisions: Dict[str, Optional[RaceStrategy]] = {}
    for info in driver_infos:
        rec = recommendations[info["id"]]
        default = "y" if rec else "n"
        answer = Prompt.ask(
            f"  Pit [bold]{info['name']}[/bold]?",
            choices=["y", "n"],
            default=default,
        ).strip().lower()

        if answer == "y":
            strategy = _show_sc_strategy_panel(
                info["circuit_obj"],
                info.get("weather", "dry"),
                info["car_obj"],
                info["driver_obj"],
                info["name"],
                remaining,
            )
            decisions[info["id"]] = strategy
        else:
            decisions[info["id"]] = None

    console.print()
    return decisions


def _rain_bar(prob: float, width: int = 10) -> str:
    """Render a rain probability as a coloured bar with percentage and threshold marker."""
    filled = round(prob / 100 * width)
    filled = max(0, min(width, filled))
    color = "blue" if prob >= 65 else ("cyan" if prob >= 45 else "dim")
    bar = "█" * filled + "░" * (width - filled)
    marker = ""
    if prob >= 92:
        marker = " [dim]← wet[/dim]"
    elif prob >= 65:
        marker = " [dim]← damp[/dim]"
    return f"[{color}]{bar}[/{color}] {prob:.0f}%{marker}"


def _show_weather_strategy_panel(
    circuit,
    car,
    driver,
    driver_label: str,
    remaining_laps: int,
    rain_prob: float,
) -> RaceStrategy:
    """Show compound options for a mid-race weather pit and return chosen strategy."""
    # Show wet-weather compounds whenever rain is meaningful (warning fires at 55%).
    # Only fall back to dry compounds if rain_prob is low (drying phase).
    is_wet_cond = rain_prob >= 50
    weather_for_strat = "wet" if is_wet_cond else "dry"

    presets_full = suggest_strategies(circuit, weather_for_strat, car, driver)
    presets = [_trim_strategy_to_remaining(p, remaining_laps) for p in presets_full]

    lines: List[str] = []
    lines.append(
        f"[bold]WEATHER STRATEGY[/bold] — {circuit.name}  [dim]({driver_label})[/dim]"
        f"  [cyan]{remaining_laps} laps remaining[/cyan]"
    )
    lines.append("")
    if is_wet_cond:
        inter_life = adjusted_tyre_life("intermediate", circuit, car, driver)
        wet_life   = adjusted_tyre_life("wet", circuit, car, driver)
        if rain_prob < 65:
            lines.append(f"  [green]I[/green] Intermediate — ~{inter_life} laps  [dim]← optimal for current conditions[/dim]")
            lines.append(f"  [blue]W[/blue] Wet          — ~{wet_life} laps  [dim](rain_prob must reach 82%+)[/dim]")
        elif rain_prob < 82:
            lines.append(f"  [green]I[/green] Intermediate — ~{inter_life} laps  [dim]← optimal for current conditions[/dim]")
            lines.append(f"  [blue]W[/blue] Wet          — ~{wet_life} laps  [dim](consider if rain_prob exceeds 82%)[/dim]")
        else:
            lines.append(f"  [green]I[/green] Intermediate — ~{inter_life} laps")
            lines.append(f"  [blue]W[/blue] Wet          — ~{wet_life} laps  [dim]← optimal for current conditions[/dim]")
    else:
        for cmp, sym, col in [("hard", "H", "white"), ("medium", "M", "yellow"), ("soft", "S", "red")]:
            life = adjusted_tyre_life(cmp, circuit, car, driver)
            lines.append(f"  [{col}]{sym}[/{col}] {cmp.capitalize():<12} — ~{life} laps")
    lines.append("")
    lines.append("Preset strategies:")
    for i, preset in enumerate(presets):
        lines.append(f"  [[bold]{i + 1}[/bold]] {preset.label:<16} {_fmt_strategy(preset)}")
    custom_num = len(presets) + 1
    lines.append(f"  [[bold]{custom_num}[/bold]] Custom — choose compounds manually")

    console.print()
    console.print(Panel("\n".join(lines), border_style="cyan", padding=(0, 2)))

    valid_choices = [str(i + 1) for i in range(len(presets))] + [str(custom_num)]
    choice = Prompt.ask("Strategy", choices=valid_choices)
    choice_idx = int(choice) - 1
    if choice_idx < len(presets):
        return presets[choice_idx]
    return _custom_strategy(weather_for_strat, remaining_laps, circuit, car, driver)


def show_weather_strategy_decision(
    lap: int,
    total_laps: int,
    threshold: str,
    driver_infos: list,
    rain_prob: float,
    forecast: list,
    trend: str,
    meta: Optional[dict] = None,
) -> dict:
    """Show mid-race weather prompt and return per-driver pit decisions."""
    console.print()
    remaining = total_laps - lap

    THRESHOLD_STYLES = {
        "warning": ("WEATHER WARNING",       "yellow",      "Conditions approaching change"),
        "damp":    ("TRACK TURNING DAMP",    "bold yellow", "Intermediates now faster than slicks"),
        "wet":     ("HEAVY RAIN",            "blue",        "Wet tyres strongly advised"),
        "drying":  ("TRACK DRYING",          "cyan",        "Slick tyres becoming viable"),
    }
    title, border, subtitle = THRESHOLD_STYLES.get(threshold, ("WEATHER UPDATE", "yellow", ""))

    OPTION_LABELS = {
        "warning": ["Pit now", "Wait — recheck in 3 laps", "Dismiss weather warnings"],
        "damp":    ["Pit now for intermediates", f"Stay out (-{_weather_compound_delta_approx(rain_prob):.1f}s/lap est.)", "Gamble on current compound"],
        "wet":     ["Pit now (strongly advised)", "Stay out (~10s/lap penalty)", "Accept full wet penalty"],
        "drying":  ["Pit now for dry compound", "Wait and see", "Stay on wet/inters"],
    }
    opts = OPTION_LABELS.get(threshold, ["Pit now", "Stay out", "Ignore"])

    # Header panel
    trend_str = {"rising": "[red]↑ rising[/red]", "falling": "[cyan]↓ falling[/cyan]", "stable": "[dim]→ stable[/dim]"}.get(trend, trend)
    header_lines = [
        f"[bold]{subtitle}[/bold]",
        "",
        f"  Rain probability: {_rain_bar(rain_prob, 10)}  ({trend_str})",
        "",
        "  Forecast — next 8 laps:",
    ]
    for i, fp in enumerate(forecast[:8]):
        lap_n = lap + i + 1
        header_lines.append(f"    L{lap_n:<3} {_rain_bar(fp, 10)}")
    header_lines.append("")
    header_lines.append(
        f"  [dim]Forecast reliability: high 1–3 laps, moderate 4–6, low beyond[/dim]"
    )

    console.print(Panel(
        "\n".join(header_lines),
        title=f"[bold]  {title} — LAP {lap} of {total_laps}  ({remaining} laps left)  [/bold]",
        border_style=border,
        padding=(0, 1),
    ))

    # Driver table with compound penalty estimate
    tbl = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    tbl.add_column("Driver", style="white")
    tbl.add_column("Tyre", justify="center")
    tbl.add_column("Age", justify="right")
    tbl.add_column("Penalty if rain+15%", justify="right", min_width=20)

    from engine.race import _weather_compound_delta
    for info in driver_infos:
        cmp_color = {"soft": "red", "medium": "yellow", "hard": "white",
                     "intermediate": "green", "wet": "blue"}.get(info["compound"], "white")
        penalty_prob = min(100.0, rain_prob + 15)
        penalty = _weather_compound_delta(info["compound"], penalty_prob)
        penalty_color = "red" if penalty > 3.0 else ("yellow" if penalty > 1.0 else "green")
        tbl.add_row(
            info["name"],
            f"[{cmp_color}]{info['compound'].capitalize()}[/{cmp_color}]",
            str(info["tyre_age"]),
            f"[{penalty_color}]-{penalty:.1f}s/lap[/{penalty_color}]",
        )
    console.print(tbl)

    # Recommendation
    fc_median = sorted(forecast[2:5])[1] if len(forecast) >= 5 else rain_prob
    if fc_median > 90:
        rec = "[bold red]PIT IMMEDIATELY[/bold red] — heavy rain certain."
    elif fc_median > 75 and trend == "rising":
        rec = "[bold yellow]PREPARE PIT[/bold yellow] — damp conditions likely in ~3 laps. Inters advised."
    elif trend == "falling" and rain_prob < 70:
        rec = "[cyan]WAIT[/cyan] — conditions may not develop. Monitor next lap."
    elif threshold == "drying":
        est_laps = max(1, int((rain_prob - 40) / 8))
        rec = f"[cyan]CONSIDER SLICKS[/cyan] — track drying, est. ~{est_laps} laps to slick window."
    else:
        rec = "[yellow]MONITOR[/yellow] — conditions changing."
    console.print(f"\n  Recommendation: {rec}\n")

    # Per-driver decisions
    decisions: Dict[str, Optional[RaceStrategy]] = {}
    for info in driver_infos:
        console.print(f"  [bold]{info['name']}[/bold] — Lap {info['tyre_age']} {info['compound']}")
        for j, label in enumerate(opts, 1):
            console.print(f"    [{j}] {label}")
        valid = [str(j) for j in range(1, len(opts) + 1)]
        choice = Prompt.ask("    Choice", choices=valid, default="2")

        if choice == "1":
            strat = _show_weather_strategy_panel(
                info["circuit_obj"], info["car_obj"], info["driver_obj"],
                info["name"], info["laps_remaining"], rain_prob,
            )
            decisions[info["id"]] = strat
        else:
            decisions[info["id"]] = None
            # Meta signals for warning threshold
            if threshold == "warning" and choice == "3" and meta is not None:
                meta["ignored_warning"] = True

    console.print()
    return decisions


def _weather_compound_delta_approx(rain_prob: float) -> float:
    """Quick estimate of slick tyre penalty at current rain_prob (for UI labels)."""
    from engine.race import _weather_compound_delta
    return _weather_compound_delta("medium", rain_prob)


def run_race_with_animation(
    entries: List[RaceEntry],
    circuit: Circuit,
    weather: str,
    grid: Optional[List[str]] = None,
    strategies: Optional[Dict[str, RaceStrategy]] = None,
    player_team_id: Optional[str] = None,
) -> RaceReport:
    # Simulate first so results are ready; then animate with live event ticker
    def _sc_callback(lap, total_laps, driver_infos):
        return show_sc_strategy_decision(lap, total_laps, driver_infos)

    def _weather_callback(lap, total_laps, threshold, driver_infos, rain_prob, forecast, trend, meta=None):
        return show_weather_strategy_decision(
            lap, total_laps, threshold, driver_infos, rain_prob, forecast, trend, meta
        )

    report = simulate_race(
        entries, circuit, weather,
        grid=grid, strategies=strategies,
        player_team_id=player_team_id,
        sc_pit_callback=_sc_callback,
        weather_callback=_weather_callback,
    )
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
                if "HEAVY RAIN" in event:
                    styled = f"[bold blue]  🌧  {event}[/bold blue]"
                elif "SAFETY CAR" in event or "VIRTUAL SAFETY CAR" in event:
                    styled = f"[bold yellow]  SC  {event}[/bold yellow]"
                elif "Racing resumes" in event:
                    styled = f"[bold green]  GO  {event}[/bold green]"
                elif "TRACK TURNING DAMP" in event or "Track turning damp" in event:
                    styled = f"[blue]  ~   {event}[/blue]"
                elif "TRACK DRYING" in event or "Track drying" in event:
                    styled = f"[yellow]  ☀  {event}[/yellow]"
                elif "Rain easing" in event:
                    styled = f"[dim cyan]  ~   {event}[/dim cyan]"
                elif "Weather front" in event or "Weather:" in event:
                    styled = f"[dim blue]  ~   {event}[/dim blue]"
                elif "retires" in event or "collision" in event.lower():
                    styled = f"[red]  !!  {event}[/red]"
                elif "overtakes" in event:
                    styled = f"[cyan]  ^   {event}[/cyan]"
                elif "pits under SC" in event:
                    styled = f"[yellow]  P   {event}[/yellow]"
                elif "pits for weather" in event:
                    styled = f"[cyan]  P   {event}[/cyan]"
                elif "pits" in event:
                    styled = f"[dim]  P   {event}[/dim]"
                elif "damage" in event:
                    styled = f"[yellow]  !   {event}[/yellow]"
                else:
                    styled = f"[dim]  -   {event}[/dim]"
                console.print(styled)
    return report


# ─── Sponsor selection ────────────────────────────────────────────────────────

def show_sponsor_selection(
    available_sponsors: List[Sponsor],
    player_team: Team,
    total_races: int,
    renewing: bool = False,
) -> Sponsor:
    """Display sponsor selection UI and return the chosen Sponsor."""
    console.print()
    title = "[bold]SEASON SPONSORS — Renew your deal[/bold]" if renewing else "[bold]SEASON SPONSORS — Choose your partner[/bold]"
    console.print(Panel(title, border_style="cyan", padding=(0, 2)))

    if renewing and player_team.sponsor_id:
        current_sp = next((sp for sp in available_sponsors if sp.id == player_team.sponsor_id), None)
        current_name = current_sp.name if current_sp else player_team.sponsor_id.replace('_', ' ').title()
        console.print(f"  Current sponsor: [bold cyan]{current_name}[/bold cyan]\n")

    BONUS_LABELS = {
        "none": "—",
        "podium": "Per podium",
        "win": "Per race win",
        "fastest_lap": "Fastest lap",
        "top5_finish": "Per top-5 finish",
    }

    table = Table(box=box.ROUNDED, header_style="bold cyan", show_lines=False)
    table.add_column("#", width=3, justify="center")
    table.add_column("Sponsor", min_width=22)
    table.add_column("Industry", min_width=16)
    table.add_column("Per Race", justify="right", width=10)
    table.add_column("Bonus Condition", min_width=16)
    table.add_column("Bonus", justify="right", width=8)
    table.add_column("Est. Season", justify="right", width=12)

    for i, sp in enumerate(available_sponsors, 1):
        est = sp.race_payment * total_races
        bonus_label = BONUS_LABELS.get(sp.bonus_type, sp.bonus_type)
        bonus_str = f"€{sp.bonus_amount:.2f}M" if sp.bonus_amount > 0 else "—"
        is_current = player_team.sponsor_id == sp.id
        row_style = "bold green" if is_current else ""
        suffix = " ★" if is_current else ""
        table.add_row(
            str(i),
            f"[{row_style}]{sp.name}{suffix}[/{row_style}]" if row_style else sp.name + suffix,
            sp.industry,
            f"€{sp.race_payment:.2f}M",
            bonus_label,
            bonus_str,
            f"[dim]~€{est:.0f}M[/dim]",
        )

    console.print(table)
    console.print()
    console.print("[dim]Description:[/dim]")
    for i, sp in enumerate(available_sponsors, 1):
        console.print(f"  [dim]{i}.[/dim] {sp.description}")
    console.print()

    valid = [str(i) for i in range(1, len(available_sponsors) + 1)]
    while True:
        choice = Prompt.ask(f"Choose your sponsor [dim](1–{len(available_sponsors)})[/dim]")
        if choice in valid:
            selected = available_sponsors[int(choice) - 1]
            console.print(f"\n[bold green]✓ {selected.name} signed as your season sponsor![/bold green]\n")
            return selected
        console.print("[red]Invalid choice.[/red]")
