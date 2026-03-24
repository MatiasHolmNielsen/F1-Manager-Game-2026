"""Race weekend flow: circuit briefing, race animation, transition, sponsor selection.
# Functions: show_circuit_briefing:16  show_race_transition:69  show_sponsor_selection:130  run_race_with_animation:191
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

from rich.align import Align
from rich.columns import Columns
from rich import box
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt
from rich.table import Table

from engine.race import simulate_race
from engine.tyres import RaceStrategy, race_laps
from models.circuit import Circuit
from models.driver import Driver
from models.sponsor import Sponsor
from models.team import Team
from .helpers import console
from .weather_sc import show_sc_strategy_decision, show_weather_strategy_decision


def show_circuit_briefing(circuit: Circuit, player_team: Team) -> None:
    total_laps = race_laps(circuit)

    wear_color = {"low": "green", "medium": "yellow", "high": "red"}[circuit.tire_wear]
    od = circuit.overtaking_difficulty
    if od < 30:
        ot_label = "[green]EASY[/green]"
    elif od < 55:
        ot_label = "[yellow]MODERATE[/yellow]"
    elif od < 75:
        ot_label = "[red]DIFFICULT[/red]"
    else:
        ot_label = "[bold red]VERY DIFFICULT[/bold red]"

    wc = circuit.weather_chance
    if wc < 20:
        wx_label = "[yellow]DRY[/yellow]"
    elif wc < 50:
        wx_label = "[blue]WET RISK[/blue]"
    else:
        wx_label = "[bold blue]LIKELY WET[/bold blue]"

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
        f"[dim]Tyre wear:[/dim]   [bold {wear_color}]{circuit.tire_wear.upper()}[/bold {wear_color}]",
        f"[dim]Overtaking:[/dim]  {ot_label}",
        f"[dim]Weather:[/dim]     {wx_label}  [dim]({circuit.weather_chance}% rain)[/dim]",
        f"[dim]Pit loss:[/dim]    [bold]{circuit.pit_lane_loss}s[/bold]",
    ]
    hint_lines = [
        "[dim]Strategy hint:[/dim]",
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
        border_style="yellow", padding=(0, 1),
    ))
    console.input("\n[dim]Press Enter to open team management…[/dim]")


def show_race_transition(
    prev_circuit: Circuit, next_circuit: Optional[Circuit],
    player_team: Team, drivers: Dict[str, Driver],
    teams: Dict[str, Team], player_team_id: str,
    driver_pts: Dict[str, int], team_pts: Dict[str, int],
    prev_team_pts: Dict[str, int], prev_driver_pts: Dict[str, int],
    race_results, race_num: int, total_races: int,
    season_poles: int = 0, season_fastest_laps: int = 0,
    season_podiums: int = 0, race_report=None,
) -> None:
    player_results = [r for r in race_results if r.team_id == player_team_id]
    team_pts_gained = team_pts.get(player_team_id, 0) - prev_team_pts.get(player_team_id, 0)
    pos_strs = " + ".join(
        f"P{r.position}" if not r.dnf else "DNF"
        for r in sorted(player_results, key=lambda x: x.position if not x.dnf else 99)
    )

    sorted_teams_now  = sorted(team_pts.items(), key=lambda x: x[1], reverse=True)
    sorted_teams_prev = sorted(prev_team_pts.items(), key=lambda x: x[1], reverse=True)
    pos_now  = next((i for i, (t, _) in enumerate(sorted_teams_now,  1) if t == player_team_id), 0)
    pos_prev = next((i for i, (t, _) in enumerate(sorted_teams_prev, 1) if t == player_team_id), 0)
    pos_delta = pos_prev - pos_now

    leader_team_id, leader_pts = sorted_teams_now[0]
    player_pts_now = team_pts.get(player_team_id, 0)

    if leader_team_id == player_team_id:
        champ_line = f"[bold green]You lead the championship by {player_pts_now - sorted_teams_now[1][1]} points![/bold green]"
    else:
        leader_team = teams.get(leader_team_id)
        gap_to_leader = leader_pts - player_pts_now
        delta_s = (f" [green](+{pos_delta} pos{'s' if pos_delta != 1 else ''})[/green]" if pos_delta > 0
                   else f" [red](-{-pos_delta} pos{'s' if -pos_delta != 1 else ''})[/red]" if pos_delta < 0
                   else "")
        leader_name = leader_team.short_name if leader_team else leader_team_id
        champ_line = f"P{pos_now} — [bold]{gap_to_leader}pts[/bold] behind {leader_name}{delta_s}"

    notable = ""
    dnf_results = [r for r in race_results if r.dnf]
    if dnf_results:
        top_dnf = min(dnf_results, key=lambda r: r.grid_position if r.grid_position > 0 else 99)
        notable = f"{top_dnf.driver.name} DNF ({top_dnf.dnf_reason})"
    leader_result = next((r for r in race_results if r.position == 1 and not r.dnf), None)
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
        weather_evt = race_report.weather_summary[-1]
        debrief_lines.append(
            f"[dim]Weather:[/dim]      [blue]{weather_evt}[/blue]  "
            f"[dim](peak {race_report.peak_rain_prob:.0f}%)[/dim]"
        )
    debrief_lines.append(
        f"[dim]Season so far: {season_poles} pole{'s' if season_poles != 1 else ''}  ·  "
        f"{season_fastest_laps} fastest lap{'s' if season_fastest_laps != 1 else ''}  ·  "
        f"{season_podiums} podium{'s' if season_podiums != 1 else ''}[/dim]"
    )

    if next_circuit:
        nod = next_circuit.overtaking_difficulty
        ot_hint = ("low overtaking, qualifying crucial" if nod >= 70
                   else ("high overtaking, strategy battles likely" if nod <= 30
                         else "moderate overtaking opportunities"))
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

    console.print()
    console.print(Panel(
        Columns([
            Panel("\n".join(debrief_lines), title="[bold]Race Debrief[/bold]", border_style="cyan",  padding=(0, 1)),
            Panel("\n".join(preview_lines), title="[bold]Next Race[/bold]",   border_style="yellow", padding=(0, 1)),
        ]),
        title=f"[bold]AFTER {prev_circuit.name.upper()}[/bold]",
        border_style="dim", padding=(0, 1),
    ))
    console.input("\n[dim]Press Enter to continue…[/dim]")


def show_sponsor_selection(
    available_sponsors: List[Sponsor],
    player_team: Team,
    total_races: int,
    renewing: bool = False,
) -> Sponsor:
    console.print()
    title = "[bold]SEASON SPONSORS — Renew your deal[/bold]" if renewing else "[bold]SEASON SPONSORS — Choose your partner[/bold]"
    console.print(Panel(title, border_style="cyan", padding=(0, 2)))

    if renewing and player_team.sponsor_id:
        current_sp = next((sp for sp in available_sponsors if sp.id == player_team.sponsor_id), None)
        current_name = current_sp.name if current_sp else player_team.sponsor_id.replace('_', ' ').title()
        console.print(f"  Current sponsor: [bold cyan]{current_name}[/bold cyan]\n")

    BONUS_LABELS = {
        "none": "—", "podium": "Per podium", "win": "Per race win",
        "fastest_lap": "Fastest lap", "top5_finish": "Per top-5 finish",
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
        bonus_str = f"€{sp.bonus_amount:.2f}M" if sp.bonus_amount > 0 else "—"
        is_current = player_team.sponsor_id == sp.id
        row_style = "bold green" if is_current else ""
        suffix = " ★" if is_current else ""
        table.add_row(
            str(i),
            f"[{row_style}]{sp.name}{suffix}[/{row_style}]" if row_style else sp.name + suffix,
            sp.industry,
            f"€{sp.race_payment:.2f}M",
            BONUS_LABELS.get(sp.bonus_type, sp.bonus_type),
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


def run_race_with_animation(
    entries, circuit: Circuit, weather: str,
    grid=None, strategies=None, player_team_id=None,
    player_allocation=None,
):
    def _sc_callback(lap, total_laps, driver_infos):
        return show_sc_strategy_decision(lap, total_laps, driver_infos)

    def _weather_callback(lap, total_laps, threshold, driver_infos, rain_prob, forecast, trend, meta=None):
        return show_weather_strategy_decision(lap, total_laps, threshold, driver_infos, rain_prob, forecast, trend, meta)

    report = simulate_race(
        entries, circuit, weather,
        grid=grid, strategies=strategies,
        player_team_id=player_team_id,
        sc_pit_callback=_sc_callback,
        weather_callback=_weather_callback,
        player_allocation=player_allocation,
    )
    total_steps = 20
    total_laps = race_laps(circuit)

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
        task = progress.add_task(f"[yellow]Racing — {circuit.name}...[/yellow]", total=total_steps)
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
