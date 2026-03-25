"""Qualifying display and pre-race strategy selection.
# Functions: show_knockout_quali_session:23  run_knockout_qualifying_with_animation:87  _custom_strategy:123  _show_pit_panel:204  show_strategy_menu:300  show_strategy_summary:320
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

from rich import box
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt
from rich.table import Table

from engine.core.tyres import TYRE_COMPOUNDS, TyreStint, RaceStrategy, race_laps, adjusted_tyre_life, suggest_strategies, tyre_score as _tyre_score
from engine.qualifying import simulate_knockout_qualifying
from engine.core.weather import compound_pace_delta as _weather_compound_delta
from models.circuit import Circuit
from models.driver import Driver
from models.team import Team
from .helpers import console, fmt_lap_time, _fmt_stint, _fmt_strategy, _rain_bar

# Compound display order: dry compounds first, then wet
_ALL_CMP = [
    ("hard",         "H", "white"),
    ("medium",       "M", "yellow"),
    ("soft",         "S", "red"),
    ("intermediate", "I", "green"),
    ("wet",          "W", "blue"),
]


def show_knockout_quali_session(
    session: str,
    results,
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

        if cutoff is not None and r.position == cutoff and advancement_label:
            status_str = f"[dim]{advancement_label}[/dim]"

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
    entries, circuit: Circuit, weather: str, player_team_id: str,
):
    """Simulate knockout qualifying with animation and return final_grid."""
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

    console.print(Panel("[bold cyan]Q1 — QUALIFYING  (all 20 drivers)[/bold cyan]", border_style="cyan", padding=(0, 2)))
    _progress_bar(f"[cyan]Q1 — {circuit.name}...[/cyan]", 10, 0.06)
    show_knockout_quali_session("Q1", knockout.q1, player_team_id, circuit, cutoff=15, advancement_label="→ Q2")
    console.input("\n[dim]Press Enter for Q2…[/dim]")

    console.print(Panel("[bold cyan]Q2 — QUALIFYING  (top 15 advance)[/bold cyan]", border_style="cyan", padding=(0, 2)))
    _progress_bar(f"[cyan]Q2 — {circuit.name}...[/cyan]", 10, 0.06)
    show_knockout_quali_session("Q2", knockout.q2, player_team_id, circuit, cutoff=10, advancement_label="→ Q3")
    console.input("\n[dim]Press Enter for Q3…[/dim]")

    console.print(Panel("[bold yellow]Q3 — SHOOTOUT  (top 10 — final grid P1–P10)[/bold yellow]", border_style="yellow", padding=(0, 2)))
    _progress_bar(f"[yellow]Q3 — {circuit.name}...[/yellow]", 10, 0.08)
    show_knockout_quali_session("Q3", knockout.q3, player_team_id, circuit)

    return knockout.final_grid


def _custom_strategy(weather: str, total_laps: int, circuit, car, driver,
                     rain_prob: float = 0.0, allocation=None) -> RaceStrategy:
    """Custom strategy builder — 0 at any prompt restarts from stop count."""
    valid_map = {"H": "hard", "M": "medium", "S": "soft", "I": "intermediate", "W": "wet"}

    while True:  # outer: restart from stint count
        stints_str = Prompt.ask("Number of stints", choices=["1", "2", "3", "4"])
        num_stints = int(stints_str)
        stints: List[TyreStint] = []
        usage_so_far: Dict[str, int] = {}

        i = 0
        go_back_to_stops = False
        while i < num_stints:
            is_last = (i == num_stints - 1)
            remaining = total_laps - sum(s.laps for s in stints)

            # ── Tyre life hints ───────────────────────────────────────────────
            life_hint_parts = []
            for k in ["H", "M", "S", "I", "W"]:
                cmp = valid_map[k]
                col = TYRE_COMPOUNDS[cmp]["color"]
                life_v = adjusted_tyre_life(cmp, circuit, car, driver, rain_prob=rain_prob)
                sets_left = (allocation.get(cmp, 0) - usage_so_far.get(cmp, 0)) if allocation else None
                if sets_left is not None and sets_left <= 0:
                    life_hint_parts.append(f"[dim][{col}]{k}[/{col}] ~{life_v}L [red][0 sets][/red][/dim]")
                elif sets_left is not None:
                    life_hint_parts.append(f"[{col}]{k}[/{col}] ~{life_v}L [dim][{sets_left}][/dim]")
                else:
                    life_hint_parts.append(f"[{col}]{k}[/{col}] ~{life_v}L")
            life_hint = "  ".join(life_hint_parts)
            back_hint = "[dim]  0=back[/dim]" if i > 0 else "[dim]  0=restart[/dim]"
            console.print(f"  Tyre life: {life_hint}  |  [dim]{remaining} laps remaining[/dim]{back_hint}")

            # ── Compound choice ───────────────────────────────────────────────
            key = Prompt.ask(
                f"Stint {i + 1} compound [H/M/S/I/W · 0=back]",
                choices=list(valid_map.keys()) + ["0"], case_sensitive=False,
            ).upper()

            if key == "0":
                if i == 0:
                    go_back_to_stops = True
                    break
                # undo previous stint and step back
                prev_cmp = stints[-1].compound
                usage_so_far[prev_cmp] = max(0, usage_so_far.get(prev_cmp, 0) - 1)
                stints.pop()
                i -= 1
                continue

            compound = valid_map[key]
            life = adjusted_tyre_life(compound, circuit, car, driver, rain_prob=rain_prob)

            if allocation is not None:
                used = usage_so_far.get(compound, 0)
                avail = allocation.get(compound, 0)
                if used >= avail:
                    console.print(f"  [yellow]⚠ No {compound} sets remaining "
                                  f"(allocation: {avail}). Race engine may override.[/yellow]")

            # ── Lap count ─────────────────────────────────────────────────────
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
                stints.append(TyreStint(compound=compound, laps=laps))
                usage_so_far[compound] = usage_so_far.get(compound, 0) + 1
                i += 1
            else:
                max_laps = remaining - (num_stints - i - 1)
                chosen_laps = None
                while True:
                    laps_str = Prompt.ask(f"Stint {i + 1} laps [1–{max_laps} · 0=back]")
                    if laps_str.strip() == "0":
                        break  # redo compound for this stint
                    try:
                        laps = int(laps_str)
                        if 1 <= laps <= max_laps:
                            chosen_laps = laps
                            break
                        console.print(f"[red]Enter a number between 1 and {max_laps}.[/red]")
                    except ValueError:
                        console.print("[red]Enter a valid number.[/red]")

                if chosen_laps is None:
                    continue  # redo compound for this stint (don't advance i)

                overrun = chosen_laps - life
                if overrun > 0:
                    console.print(
                        f"  [yellow]⚠ Stint {i + 1}: {chosen_laps} laps on {compound} "
                        f"(life ~{life}L, overrun {overrun}L — puncture risk!)[/yellow]"
                    )
                stints.append(TyreStint(compound=compound, laps=chosen_laps))
                usage_so_far[compound] = usage_so_far.get(compound, 0) + 1
                i += 1

        if go_back_to_stops:
            continue  # restart outer while True (stop count)

        # ── Validate last stint ───────────────────────────────────────────────
        last = stints[-1]
        last_life = adjusted_tyre_life(last.compound, circuit, car, driver, rain_prob=rain_prob)
        if last.laps > last_life * 1.5:
            console.print(f"[red]✗ Strategy rejected: last stint ({last.laps}L on {last.compound}, "
                          f"life ~{last_life}L). Max {int(last_life * 1.5)}L. Try again.[/red]")
            continue

        return RaceStrategy(stints=stints, label="Custom")


def _show_pit_panel(
    circuit: Circuit, car, driver, driver_label: str,
    total_laps: int, weather: str = "dry",
    rain_prob: float = 0.0,
    forecast: Optional[List[float]] = None,
    trend: str = "stable",
    title: str = "TYRE STRATEGY",
    context_str: str = "",
    border_color: str = "cyan",
    allocation: Optional[Dict[str, int]] = None,
) -> RaceStrategy:
    """Universal pit strategy panel — all 5 compounds always shown."""
    presets = suggest_strategies(circuit, weather, car, driver, rain_prob=rain_prob)
    if weather == "wet":
        recommended_idx = 0
    else:
        scores = [_tyre_score(p, circuit, weather, car, driver) for p in presets]
        recommended_idx = scores.index(max(scores))

    is_wet_cond = rain_prob >= 50
    weather_tag = "[blue]RAIN[/blue]" if is_wet_cond else "[yellow]DRY[/yellow]"

    lines: List[str] = []
    header = f"[bold]{title}[/bold] — {circuit.name}  [dim]({driver_label})[/dim]"
    if context_str:
        header += f"  {context_str}"
    lines.append(header)
    lines.append(
        f"Weather: {weather_tag}  |  Wear: [bold]{circuit.tire_wear.upper()}[/bold]  "
        f"|  Distance: [bold]{total_laps} laps[/bold]"
    )
    lines.append("")

    # ── All compounds ────────────────────────────────────────────────────
    lines.append("Compounds (tyre life · pace at current conditions):")
    for cmp, sym, col in _ALL_CMP:
        life = adjusted_tyre_life(cmp, circuit, car, driver, rain_prob=rain_prob)
        delta = _weather_compound_delta(cmp, rain_prob)
        if delta < 0.4:
            pace_note = "  [bold green]← optimal[/bold green]"
        elif delta < 1.5:
            pace_note = f"  [dim]−{delta:.1f}s/lap[/dim]"
        elif delta < 5.0:
            pace_note = f"  [yellow]−{delta:.1f}s/lap[/yellow]"
        else:
            pace_note = f"  [red]−{delta:.1f}s/lap (wrong conditions)[/red]"
        if allocation is not None:
            sets_left = allocation.get(cmp, 0)
            sets_str = (f"  [red][0 sets][/red]" if sets_left <= 0
                        else f"  [yellow][{sets_left} set][/yellow]" if sets_left == 1
                        else f"  [dim][{sets_left} sets][/dim]")
        else:
            sets_str = ""
        lines.append(f"  [{col}]{sym}[/{col}] {cmp.capitalize():<14} ~{life:>2}L{sets_str}{pace_note}")
    lines.append("")

    # ── Weather forecast ─────────────────────────────────────────────────
    fc = forecast or []
    has_wx = rain_prob >= 20 or any(fp >= 20 for fp in fc[:15])
    if has_wx:
        trend_str = (
            {"rising": "[red]↑ rising[/red]", "falling": "[cyan]↓ falling[/cyan]", "stable": "[dim]→ stable[/dim]"}
            .get(trend, trend)
        )
        lines.append(f"  Rain: {_rain_bar(rain_prob, 10)}  ({trend_str})")
        if fc:
            lines.append("  Forecast:")
            for i, fp in enumerate(fc[:5]):
                lines.append(f"    L+{i + 1:<2} {_rain_bar(fp, 8)}")
            proj = fc[5:15]
            if proj:
                lines.append("  [dim]Projected (lower confidence):[/dim]")
                for j in range(0, len(proj), 2):
                    pair = proj[j:j + 2]
                    parts = []
                    for k, fp in enumerate(pair):
                        filled = max(0, min(6, round(fp / 100 * 6)))
                        bar = "█" * filled + "░" * (6 - filled)
                        clr = "blue" if fp >= 65 else ("cyan" if fp >= 45 else "dim")
                        parts.append(f"L+{6 + j + k:<2} [{clr}]{bar}[/{clr}] {fp:.0f}%")
                    lines.append(f"    [dim]{'   '.join(parts)}[/dim]")
        lines.append("  [dim]Reliability: high 1–5 laps · moderate 6–10 · low 11–15[/dim]")
        lines.append("")

    # ── Preset strategies ────────────────────────────────────────────────
    preset_valid = [True] * len(presets)
    if allocation is not None:
        for idx, preset in enumerate(presets):
            usage: Dict[str, int] = {}
            for stint in preset.stints:
                usage[stint.compound] = usage.get(stint.compound, 0) + 1
            if any(cnt > allocation.get(cmp, 0) for cmp, cnt in usage.items()):
                preset_valid[idx] = False

    lines.append("Preset strategies:")
    for i, preset in enumerate(presets):
        rec = "  [bold cyan]← rec.[/bold cyan]" if i == recommended_idx else ""
        if not preset_valid[i]:
            lines.append(f"  [[bold]{i + 1}[/bold]] [dim]{preset.label:<16} "
                         f"{_fmt_strategy(preset)}[/dim]  [red](exceeds allocation)[/red]")
        else:
            lines.append(f"  [[bold]{i + 1}[/bold]] {preset.label:<16} {_fmt_strategy(preset)}{rec}")
    custom_num = len(presets) + 1
    lines.append(f"  [[bold]{custom_num}[/bold]] Custom — choose any compound manually")

    console.print()
    console.print(Panel("\n".join(lines), border_style=border_color, padding=(0, 2)))

    valid_choices = [str(i + 1) for i in range(len(presets))] + [str(custom_num)]
    choice = Prompt.ask("Strategy", choices=valid_choices)
    choice_idx = int(choice) - 1
    if choice_idx < len(presets):
        return presets[choice_idx]
    return _custom_strategy(weather, total_laps, circuit, car, driver,
                            rain_prob=rain_prob, allocation=allocation)


def show_strategy_menu(
    circuit: Circuit, weather: str, player_team: Team, drivers: Dict[str, Driver],
    allocation=None,
) -> Dict[str, RaceStrategy]:
    player_drivers = [drivers[did] for did in player_team.driver_ids if did in drivers]
    car = player_team.car
    result: Dict[str, RaceStrategy] = {}
    total = race_laps(circuit)
    for driver in player_drivers:
        drv_alloc = allocation.get(driver.id) if allocation else None
        result[driver.id] = _show_pit_panel(
            circuit, car, driver, driver.name,
            total_laps=total, weather=weather,
            rain_prob=0.0 if weather != "wet" else 75.0,
            allocation=drv_alloc,
        )
        # Deduct starting set after panel returns
        if allocation and driver.id in allocation:
            start_cmp = result[driver.id].stints[0].compound
            allocation[driver.id][start_cmp] = max(0, allocation[driver.id].get(start_cmp, 0) - 1)
    return result


def show_strategy_summary(
    player_team: Team, drivers: Dict[str, Driver], strategies: Dict[str, RaceStrategy],
) -> None:
    lines: List[str] = []
    for did in player_team.driver_ids:
        d = drivers.get(did)
        if d and d.id in strategies:
            lines.append(f"  {d.name}: {_fmt_strategy(strategies[d.id])} — [italic]{strategies[d.id].label}[/italic]")
    if lines:
        console.print(Panel("\n".join(lines), title="[bold]YOUR STRATEGY[/bold]", border_style="cyan", padding=(0, 1)))
