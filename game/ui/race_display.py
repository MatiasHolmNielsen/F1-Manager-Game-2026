"""Race weekend rendering: results, pit stats, events, lap analysis.
# Functions: show_race_header:21  show_race_results:47  show_pit_stats:112  show_race_events:161  show_lap_analysis:210  _show_driver_laps:242
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

from rich import box
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from engine.tyres import TYRE_COMPOUNDS
from models.circuit import Circuit
from models.driver import Driver
from models.team import Team
from .helpers import console, fmt_lap_time, stat_bar, _delta_str


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
    results, player_team_id: str, circuit: Circuit,
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
            delta_s = ""
        elif r.position == 1:
            pos_str = "[bold yellow]1[/bold yellow]"
            gap_str = "[green]WINNER[/green]"
            delta_s = _delta_str(r.grid_position, r.position)
        elif r.position == 2:
            pos_str = "[bold white]2[/bold white]"
            gap_str = f"+{r.time_gap:.3f}s"
            delta_s = _delta_str(r.grid_position, r.position)
        elif r.position == 3:
            pos_str = "[bold orange3]3[/bold orange3]"
            gap_str = f"+{r.time_gap:.3f}s"
            delta_s = _delta_str(r.grid_position, r.position)
        else:
            pos_str = str(r.position)
            gap_str = f"+{r.time_gap:.3f}s"
            delta_s = _delta_str(r.grid_position, r.position)

        best = fl_laps.get(r.driver.id)
        if best:
            lap_str = fmt_lap_time(best)
            fl_str = f"[bold magenta]{lap_str}[/bold magenta]" if r.fastest_lap else f"[dim]{lap_str}[/dim]"
        else:
            fl_str = "[dim]—[/dim]"

        pts_str = f"[bold]{r.points}[/bold]" if r.points > 0 else ""
        table.add_row(
            pos_str, delta_s,
            f"{prefix}{r.driver.name}",
            f"[{r.team_color}]{r.team_name}[/{r.team_color}]",
            gap_str, pts_str, fl_str,
        )

    console.print(table)


def show_pit_stats(pit_stops, results, circuit: Circuit) -> None:
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
            strategy_str = " → ".join(
                f"[{TYRE_COMPOUNDS[c]['color']}]{TYRE_COMPOUNDS[c]['symbol']}[/{TYRE_COMPOUNDS[c]['color']}]"
                for c in compounds
            )
        else:
            strategy_str = "[dim]—[/dim]"

        stop_detail = "  ".join(
            f"L{s.lap} [dim]({s.total_time:.1f}s)[/dim]" for s in stops
        ) if stops else "[dim]no stops[/dim]"

        best_str = f"[bold]{min(stops, key=lambda s: s.stationary_time).stationary_time:.2f}s[/bold]" if stops else "[dim]—[/dim]"
        pos_str = "[dim]—[/dim]" if r.dnf else str(r.position)
        name_str = f"[dim]{name}[/dim]" if r.dnf else name

        table.add_row(pos_str, name_str, str(len(stops)), strategy_str, stop_detail, best_str)

    console.print(table)
    parts = "  ".join(
        f"[{info['color']}]{info['symbol']}[/{info['color']}][dim]={name.capitalize()}[/dim]"
        for name, info in TYRE_COMPOUNDS.items()
    )
    console.print(f"[dim]  Compounds:[/dim]  {parts}")


def show_race_events(events: List[str], max_events: int = 12, circuit=None) -> None:
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


def show_lap_analysis(
    team: Team, drivers: Dict[str, Driver], report, circuit: Circuit,
    player_team_id: str = "",
) -> None:
    # Build ordered list: player team first, then rest by finishing position
    all_results = sorted(
        [r for r in report.results if report.lap_data.get(r.driver.id)],
        key=lambda r: (r.position if not r.dnf else 99),
    )
    player_results = [r for r in all_results if r.team_id == (player_team_id or team.id)]
    other_results  = [r for r in all_results if r.team_id != (player_team_id or team.id)]
    ordered = player_results + other_results

    if not ordered:
        return

    while True:
        console.print()
        lines: List[str] = [f"[bold]LAP ANALYSIS — {circuit.name}[/bold]", ""]

        # Player team section
        if player_results:
            lines.append("  [bold cyan]Your Team[/bold cyan]")
            for i, r in enumerate(player_results, 1):
                result_str = (f"DNF — {r.dnf_reason}" if r.dnf else f"P{r.position}")
                laps_done = len(report.lap_data.get(r.driver.id, []))
                best = report.driver_fastest_laps.get(r.driver.id)
                best_str = fmt_lap_time(best) if best else "—"
                lines.append(
                    f"  [[bold]{i}[/bold]] [bold]{r.driver.name}[/bold]"
                    f"  [dim]{result_str}  •  {laps_done} laps  •  best {best_str}[/dim]"
                )
            lines.append("")

        # All other drivers
        lines.append("  [dim]All Drivers[/dim]")
        offset = len(player_results)
        for j, r in enumerate(other_results, offset + 1):
            result_str = (f"DNF — {r.dnf_reason}" if r.dnf else f"P{r.position}")
            laps_done = len(report.lap_data.get(r.driver.id, []))
            best = report.driver_fastest_laps.get(r.driver.id)
            best_str = fmt_lap_time(best) if best else "—"
            lines.append(
                f"  [[bold]{j}[/bold]] [{r.team_color}]{r.driver.name}[/{r.team_color}]"
                f"  [dim]{result_str}  •  {r.team_name}  •  {laps_done} laps  •  best {best_str}[/dim]"
            )

        lines.append("")
        lines.append("  [dim][0] Back[/dim]")
        console.print(Panel("\n".join(lines), border_style="cyan", padding=(0, 2)))

        choices = [str(i) for i in range(len(ordered) + 1)]
        choice = Prompt.ask("Select driver", choices=choices, default="0")
        if choice == "0":
            break

        selected_result = ordered[int(choice) - 1]
        records = report.lap_data.get(selected_result.driver.id, [])
        if not records:
            console.print("[dim]No lap data available.[/dim]")
            continue
        _show_driver_laps(selected_result.driver, records, report, circuit)


def _show_driver_laps(driver: Driver, records, report, circuit: Circuit) -> None:
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

    table = Table(box=box.SIMPLE_HEAD, show_edge=False, header_style="bold white", padding=(0, 1))
    table.add_column("Lap",      width=4,  justify="right")
    table.add_column("Pos",      width=4,  justify="center")
    table.add_column("Tyre",     width=5,  justify="center")
    table.add_column("Age",      width=4,  justify="right")
    table.add_column("Wear",     width=7,  justify="right")
    table.add_column("Lap Time", width=12, justify="right")
    table.add_column("Δ Best",   width=9,  justify="right")
    table.add_column("Fuel",     width=7,  justify="right")
    if has_weather:
        table.add_column("Rain", width=8, justify="right")
    table.add_column("Flag", width=5, justify="center")
    table.add_column("Note", width=14)

    # Build SC/VSC pit lookup from events
    sc_pit_laps: set = set()
    vsc_pit_laps: set = set()
    for e in report.events:
        if driver.name in e and " pits under " in e:
            try:
                lap_num = int(e.split(":")[0].replace("Lap ", "").strip())
                if "under SC" in e:
                    sc_pit_laps.add(lap_num)
                elif "under VSC" in e:
                    vsc_pit_laps.add(lap_num)
            except ValueError:
                pass

    prev_pos = None

    for rec in records:
        if rec.dnf:
            row = [str(rec.lap), "[dim]—[/dim]", "", "", "", "", "", ""]
            if has_weather:
                row.append("")
            row.append("")  # Flag column
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

        if rec.sc_active:
            lap_str = f"[dim]{fmt_lap_time(rec.lap_time)}[/dim]"
            delta_str = "[dim]SC[/dim]" if rec.sc_active == "SC" else "[dim]VSC[/dim]"
            flag_str = "[bold yellow]SC[/bold yellow]" if rec.sc_active == "SC" else "[yellow]VSC[/yellow]"
        else:
            flag_str = ""
            is_best = best_time > 0 and abs(rec.lap_time - best_time) < 0.001
            lap_str = (f"[bold magenta]{fmt_lap_time(rec.lap_time)}[/bold magenta]" if is_best
                       else f"[{c_color}]{fmt_lap_time(rec.lap_time)}[/{c_color}]")

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
                (s for s in report.pit_stops if s.driver_name == driver.name and s.lap == rec.lap),
                None,
            )
            if pit_stop:
                ni = TYRE_COMPOUNDS[pit_stop.new_compound]
                if rec.lap in sc_pit_laps:
                    suffix = " [bold yellow](SC)[/bold yellow]"
                elif rec.lap in vsc_pit_laps:
                    suffix = " [yellow](VSC)[/yellow]"
                else:
                    suffix = ""
                note = (f"PIT [{ni['color']}]{ni['symbol']}[/{ni['color']}]"
                        f" [dim]{pit_stop.total_time:.1f}s[/dim]{suffix}")
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
            table.add_row(str(rec.lap), pos_str, tyre_str, str(rec.tyre_age), wear_str,
                          lap_str, delta_str, fuel_str, rain_str, flag_str, note)
        else:
            table.add_row(str(rec.lap), pos_str, tyre_str, str(rec.tyre_age), wear_str,
                          lap_str, delta_str, fuel_str, flag_str, note)

    console.print(table)
    console.input("\n[dim]Press Enter to go back…[/dim]")
