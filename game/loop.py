"""Main game loop: welcome screen, team selection, season flow."""
import random
from typing import Dict, List, Optional

from rich.align import Align
from rich.console import Console
from rich import box
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from .loader import load_drivers, load_teams, load_circuits
from .ui import (
    show_race_header, show_race_results, show_race_events, show_pit_stats,
    show_lap_analysis, show_driver_development, show_standings,
    show_quali_results, show_strategy_menu, show_strategy_summary,
    run_knockout_qualifying_with_animation, run_race_with_animation,
)
from .management import management_menu
from .finances import _apply_race_finances
from .offseason import _run_offseason
from engine.race import RaceEntry, RaceStrategy, simulate_race, ai_strategy
from engine.development import apply_development
from models.driver import Driver
from models.team import Team

console = Console()


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
            final_grid = run_knockout_qualifying_with_animation(entries, circuit, quali_weather, player_team_id)
            grid = [qr.driver.id for qr in final_grid]
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
            report = run_race_with_animation(entries, circuit, weather, grid=grid, strategies=strategies)
            results = report.results

            # ── View 1: Race Result ──────────────────────────────────
            console.clear()
            show_race_header(circuit, race_num, total_races, weather)
            show_race_results(results, player_team_id, circuit, report.fastest_lap_time, report.driver_fastest_laps)
            console.input("\n[dim]Press Enter for pit stats…[/dim]")

            # ── View 1b: Pit Stats ────────────────────────────────────
            console.clear()
            show_race_header(circuit, race_num, total_races, weather)
            show_pit_stats(report.pit_stops, results, circuit)
            console.print()
            console.print("[dim]Enter = continue  •  [bold]L[/bold] = Lap analysis  •  [bold]Q[/bold] = Skip to standings[/dim]")
            pit_choice = Prompt.ask("", default="").strip().lower()
            if pit_choice == "l":
                console.clear()
                show_race_header(circuit, race_num, total_races, weather)
                show_lap_analysis(player_team, drivers, report, circuit)

            quick = pit_choice == "q"

            if not quick:
                # ── View 2: Finances ──────────────────────────────────
                console.clear()
                show_race_header(circuit, race_num, total_races, weather)
                _apply_race_finances(player_team, results, player_team_id)
                console.input("\n[dim]Press Enter for driver development…[/dim]")

                # ── View 3: Driver Development ────────────────────────
                console.clear()
                show_race_header(circuit, race_num, total_races, weather)
                gains, xp_gains = apply_development(results, drivers, grid=grid, report=report)
                show_driver_development(player_team, drivers, gains, xp_gains, report=report)
                console.input("\n[dim]Press Enter for championship standings…[/dim]")
            else:
                _apply_race_finances(player_team, results, player_team_id)
                gains, xp_gains = apply_development(results, drivers, grid=grid, report=report)

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
