"""Mid-race interactive prompts for Safety Car and weather strategy decisions.
# Functions: _trim_strategy_to_remaining:20  _show_sc_strategy_panel:34  show_sc_strategy_decision:91  _show_weather_strategy_panel:178  show_weather_strategy_decision:234
"""
from __future__ import annotations

from typing import Dict, List, Optional

from rich import box
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from engine.core.tyres import TYRE_COMPOUNDS, TYRE_LIFE_BASE, TyreStint, RaceStrategy, adjusted_tyre_life
from engine.core.weather import compound_pace_delta as _weather_compound_delta
from models.circuit import Circuit
from .helpers import console, _rain_bar, _fmt_strategy
from .quali_strategy import _show_pit_panel


def _trim_strategy_to_remaining(strategy: RaceStrategy, remaining_laps: int) -> RaceStrategy:
    stints = list(strategy.stints)
    total = sum(s.laps for s in stints)
    if total <= remaining_laps:
        extra = remaining_laps - total
        stints[-1] = TyreStint(stints[-1].compound, stints[-1].laps + extra)
    else:
        while len(stints) > 1 and sum(s.laps for s in stints) > remaining_laps:
            stints.pop()
        used = sum(s.laps for s in stints[:-1])
        stints[-1] = TyreStint(stints[-1].compound, remaining_laps - used)
    return RaceStrategy(stints=stints, label=strategy.label)


def _show_sc_strategy_panel(
    circuit, weather: str, car, driver, driver_label: str,
    remaining_laps: int, rain_prob: float = 0.0,
    forecast: Optional[list] = None, trend: str = "stable",
    allocation=None,
) -> RaceStrategy:
    return _show_pit_panel(
        circuit, car, driver, driver_label,
        total_laps=remaining_laps, weather=weather,
        rain_prob=rain_prob, forecast=forecast, trend=trend,
        title="SC STRATEGY",
        context_str=f"[yellow]{remaining_laps} laps remaining[/yellow]",
        border_color="yellow",
        allocation=allocation,
    )


def show_sc_strategy_decision(lap: int, total_laps: int, driver_infos: list) -> dict:
    console.print()
    remaining = total_laps - lap
    sc_type = driver_infos[0].get("sc_type", "SC") if driver_infos else "SC"
    sc_laps_rem = driver_infos[0].get("sc_laps_remaining", 3) if driver_infos else 3
    rain_prob = driver_infos[0].get("rain_prob", 0.0) if driver_infos else 0.0
    forecast  = driver_infos[0].get("forecast", []) if driver_infos else []
    trend     = driver_infos[0].get("trend", "stable") if driver_infos else "stable"

    console.print(Panel(
        f"[bold yellow]  {sc_type} — LAP {lap} of {total_laps}  ({remaining} laps left · {sc_type} ends ~{sc_laps_rem} laps)[/bold yellow]",
        border_style="yellow", expand=False,
    ))

    if rain_prob < 20 and not any(fp >= 20 for fp in forecast[:15]):
        console.print(Panel("  [dim]Weather: Dry[/dim]", border_style="dim", padding=(0, 1), expand=False))
    else:
        trend_str = {"rising": "[red]↑ rising[/red]", "falling": "[cyan]↓ falling[/cyan]", "stable": "[dim]→ stable[/dim]"}.get(trend, trend)
        wx_lines = [
            f"  Rain: {_rain_bar(rain_prob, 10)}  ({trend_str})",
            "  Forecast (next 15 laps):",
        ]
        for i, fp in enumerate(forecast[:5]):
            wx_lines.append(f"    L{lap + i + 1:<3} {_rain_bar(fp, 8)}")
        proj = forecast[5:15]
        if proj:
            wx_lines.append("  [dim]Projected:[/dim]")
            for j in range(0, len(proj), 2):
                pair = proj[j:j + 2]
                parts = []
                for k, fp in enumerate(pair):
                    filled = max(0, min(6, round(fp / 100 * 6)))
                    bar = "█" * filled + "░" * (6 - filled)
                    clr = "blue" if fp >= 65 else ("cyan" if fp >= 45 else "dim")
                    parts.append(f"L{lap + 6 + j + k:<3} [{clr}]{bar}[/{clr}] {fp:.0f}%")
                wx_lines.append(f"    [dim]{'   '.join(parts)}[/dim]")
        wx_lines.append("  [dim]Reliability: high 1–5 laps · moderate 6–10 · low 11–15[/dim]")
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
        gap_fwd_str = ("[dim]—[/dim]" if gap_ahead is None
                       else (f"[red]{gap_ahead:.1f}s[/red]" if gap_ahead < 2.0
                             else (f"[green]{gap_ahead:.1f}s[/green]" if gap_ahead > 5.0 else f"{gap_ahead:.1f}s")))
        gap_bck_str = ("[dim]—[/dim]" if gap_behind is None
                       else (f"[red]{gap_behind:.1f}s[/red]" if gap_behind < 2.0
                             else (f"[green]{gap_behind:.1f}s[/green]" if gap_behind > 5.0 else f"{gap_behind:.1f}s")))

        table.add_row(
            info["name"], f"P{info['position']}",
            f"[{cmp_color}]{info['compound'].capitalize()}[/{cmp_color}]",
            str(info["tyre_age"]), f"~{life_left} laps",
            gap_fwd_str, gap_bck_str, rec_str,
        )
    console.print(table)

    decisions: Dict[str, Optional[RaceStrategy]] = {}
    for info in driver_infos:
        rec = recommendations[info["id"]]
        answer = Prompt.ask(
            f"  Pit [bold]{info['name']}[/bold]?",
            choices=["y", "n"],
            default="y" if rec else "n",
            case_sensitive=False,
        ).strip().lower()

        if answer == "y":
            decisions[info["id"]] = _show_sc_strategy_panel(
                info["circuit_obj"], info.get("weather", "dry"),
                info["car_obj"], info["driver_obj"], info["name"],
                remaining, rain_prob=rain_prob, forecast=forecast, trend=trend,
                allocation=info.get("allocation"),
            )
        else:
            decisions[info["id"]] = None

    console.print()
    return decisions


def _show_weather_strategy_panel(
    circuit, car, driver, driver_label: str,
    remaining_laps: int, rain_prob: float,
    forecast: Optional[list] = None, trend: str = "stable",
    allocation=None,
) -> RaceStrategy:
    weather_for_strat = "wet" if rain_prob >= 50 else "dry"
    return _show_pit_panel(
        circuit, car, driver, driver_label,
        total_laps=remaining_laps, weather=weather_for_strat,
        rain_prob=rain_prob, forecast=forecast, trend=trend,
        title="WEATHER STRATEGY",
        context_str=f"[cyan]{remaining_laps} laps remaining[/cyan]",
        border_color="cyan",
        allocation=allocation,
    )


def show_weather_strategy_decision(
    lap: int, total_laps: int, threshold: str,
    driver_infos: list, rain_prob: float, forecast: list,
    trend: str, meta: Optional[dict] = None,
) -> dict:
    console.print()
    remaining = total_laps - lap

    THRESHOLD_STYLES = {
        "warning": ("WEATHER WARNING",    "yellow",      "Conditions approaching change"),
        "damp":    ("TRACK TURNING DAMP", "bold yellow", "Intermediates now faster than slicks"),
        "wet":     ("HEAVY RAIN",         "blue",        "Wet tyres strongly advised"),
        "drying":  ("TRACK DRYING",       "cyan",        "Slick tyres becoming viable"),
    }
    title, border, subtitle = THRESHOLD_STYLES.get(threshold, ("WEATHER UPDATE", "yellow", ""))

    def _driver_options(compound: str) -> list:
        """Context-aware options based on current tyre compound and threshold."""
        penalty = _weather_compound_delta(compound, rain_prob)
        cmp_cap = compound.capitalize()
        if threshold == "warning":
            return ["Pit now", "Wait — recheck in 3 laps", "Dismiss weather warnings"]
        elif threshold == "damp":
            if compound in ("intermediate", "wet"):
                return [
                    f"Change compound (on {cmp_cap})",
                    f"Stay on {cmp_cap} (−{penalty:.1f}s/lap)",
                    "Ignore",
                ]
            return [
                "Pit for intermediates",
                f"Stay out (−{penalty:.1f}s/lap est.)",
                "Gamble on current compound",
            ]
        elif threshold == "wet":
            if compound == "wet":
                return [
                    "Already on wets — change strategy",
                    "Stay on wets (optimal)",
                    "—",
                ]
            elif compound == "intermediate":
                return [
                    f"Switch to full wets (−{penalty:.1f}s/lap on inters now)",
                    f"Stay on inters (−{penalty:.1f}s/lap)",
                    "Accept inter penalty",
                ]
            return [
                "Pit now — inters or wets (strongly advised)",
                f"Stay out on {cmp_cap} (−{penalty:.1f}s/lap penalty)",
                "Accept full wet penalty",
            ]
        elif threshold == "drying":
            if compound in ("intermediate", "wet"):
                return [
                    "Pit for dry tyres",
                    "Wait and see",
                    f"Stay on {cmp_cap}",
                ]
            return [
                "Stay on current compound (already on slicks)",
                "—",
                "—",
            ]
        return ["Pit now", "Stay out", "Ignore"]

    trend_str = {"rising": "[red]↑ rising[/red]", "falling": "[cyan]↓ falling[/cyan]", "stable": "[dim]→ stable[/dim]"}.get(trend, trend)
    header_lines = [
        f"[bold]{subtitle}[/bold]", "",
        f"  Rain probability: {_rain_bar(rain_prob, 10)}  ({trend_str})", "",
        "  Forecast — next 15 laps:",
    ]
    for i, fp in enumerate(forecast[:5]):
        header_lines.append(f"    L{lap + i + 1:<3} {_rain_bar(fp, 10)}")
    proj = forecast[5:15]
    if proj:
        header_lines.append("  [dim]Projected:[/dim]")
        for j in range(0, len(proj), 2):
            pair = proj[j:j + 2]
            parts = []
            for k, fp in enumerate(pair):
                filled = max(0, min(6, round(fp / 100 * 6)))
                bar = "█" * filled + "░" * (6 - filled)
                clr = "blue" if fp >= 65 else ("cyan" if fp >= 45 else "dim")
                parts.append(f"L{lap + 6 + j + k:<3} [{clr}]{bar}[/{clr}] {fp:.0f}%")
            header_lines.append(f"    [dim]{'   '.join(parts)}[/dim]")
    header_lines.append("")
    header_lines.append("  [dim]Reliability: high 1–5 laps · moderate 6–10 · low 11–15[/dim]")

    console.print(Panel(
        "\n".join(header_lines),
        title=f"[bold]  {title} — LAP {lap} of {total_laps}  ({remaining} laps left)  [/bold]",
        border_style=border, padding=(0, 1),
    ))

    tbl = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    tbl.add_column("Pos", width=4, justify="center")
    tbl.add_column("Driver", style="white")
    tbl.add_column("Tyre", justify="center")
    tbl.add_column("Age", justify="right")
    tbl.add_column("Penalty if rain+15%", justify="right", min_width=20)

    for info in driver_infos:
        cmp_color = {"soft": "red", "medium": "yellow", "hard": "white",
                     "intermediate": "green", "wet": "blue"}.get(info["compound"], "white")
        penalty = _weather_compound_delta(info["compound"], min(100.0, rain_prob + 15))
        penalty_color = "red" if penalty > 3.0 else ("yellow" if penalty > 1.0 else "green")
        pos = info.get("position", 0)
        tbl.add_row(
            f"P{pos}" if pos else "—",
            info["name"],
            f"[{cmp_color}]{info['compound'].capitalize()}[/{cmp_color}]",
            str(info["tyre_age"]),
            f"[{penalty_color}]-{penalty:.1f}s/lap[/{penalty_color}]",
        )
    console.print(tbl)

    fc_median = sorted(forecast[2:5])[1] if len(forecast) >= 5 else rain_prob

    decisions: Dict[str, Optional[RaceStrategy]] = {}
    for info in driver_infos:
        compound = info["compound"]
        penalty = _weather_compound_delta(compound, rain_prob)

        # Compound-aware recommendation
        if fc_median > 90 and compound == "intermediate":
            rec = "[bold red]SWITCH TO WET TYRES[/bold red] — heavy rain, inters losing significant time."
        elif fc_median > 90 and compound not in ("intermediate", "wet"):
            rec = "[bold red]PIT IMMEDIATELY[/bold red] — heavy rain, switch to inters or wets."
        elif fc_median > 75 and trend == "rising" and compound not in ("intermediate", "wet"):
            rec = "[bold yellow]PREPARE PIT[/bold yellow] — conditions worsening. Inters advised in ~3 laps."
        elif threshold == "drying" and compound in ("intermediate", "wet"):
            est_laps = max(1, int((rain_prob - 40) / 8))
            rec = f"[cyan]CONSIDER SLICKS[/cyan] — track drying, est. ~{est_laps} laps to slick window."
        elif trend == "falling" and rain_prob < 70:
            rec = "[cyan]WAIT[/cyan] — conditions may not develop. Monitor next lap."
        elif penalty < 1.0:
            rec = "[green]STAY OUT[/green] — current compound is well-suited to conditions."
        else:
            rec = "[yellow]MONITOR[/yellow] — conditions changing."

        opts = _driver_options(compound)
        cmp_color = {"soft": "red", "medium": "yellow", "hard": "white",
                     "intermediate": "green", "wet": "blue"}.get(compound, "white")
        pos = info.get("position", 0)
        pos_str = f"[bold]P{pos}[/bold]  " if pos else ""
        console.print(
            f"\n  {pos_str}[bold]{info['name']}[/bold] — "
            f"[{cmp_color}]{compound.capitalize()}[/{cmp_color}] age {info['tyre_age']}  "
            f"|  Recommendation: {rec}"
        )
        for j, label in enumerate(opts, 1):
            console.print(f"    [{j}] {label}")
        valid = [str(j) for j in range(1, len(opts) + 1)]
        choice = Prompt.ask("    Choice", choices=valid, default="2")

        if choice == "1":
            decisions[info["id"]] = _show_weather_strategy_panel(
                info["circuit_obj"], info["car_obj"], info["driver_obj"],
                info["name"], info["laps_remaining"], rain_prob,
                forecast=forecast, trend=trend,
                allocation=info.get("allocation"),
            )
        else:
            decisions[info["id"]] = None
            if threshold == "warning" and choice == "3" and meta is not None:
                meta["ignored_warning"] = True

    console.print()
    return decisions
