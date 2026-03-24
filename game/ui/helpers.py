"""Shared formatting helpers and the console singleton.
# Functions: fmt_lap_time:10  stat_bar:17  _xp_bar:29  _rain_bar:36  _delta_str:49  _fmt_stint:62  _fmt_strategy:68
"""
from __future__ import annotations

from rich.console import Console
from engine.tyres import TYRE_COMPOUNDS

console = Console()


def fmt_lap_time(seconds: float) -> str:
    """Format seconds as M:SS.mmm."""
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


def _rain_bar(prob: float, width: int = 10) -> str:
    """Render a rain probability as a coloured bar with percentage."""
    filled = max(0, min(width, round(prob / 100 * width)))
    color = "blue" if prob >= 65 else ("cyan" if prob >= 45 else "dim")
    bar = "█" * filled + "░" * (width - filled)
    marker = ""
    if prob >= 92:
        marker = " [dim]← wet[/dim]"
    elif prob >= 65:
        marker = " [dim]← damp[/dim]"
    return f"[{color}]{bar}[/{color}] {prob:.0f}%{marker}"


def _delta_str(grid_position: int, race_position: int) -> str:
    """Format grid-to-race position delta for race results table."""
    if grid_position <= 0:
        return ""
    delta = grid_position - race_position
    if delta > 0:
        return f"[green]+{delta}[/green]"
    elif delta == 0:
        return "[dim]—[/dim]"
    else:
        return f"[red]{delta}[/red]"


def _fmt_stint(stint) -> str:
    """Rich-formatted compound symbol with lap count, e.g. [red]S[/red](14)."""
    info = TYRE_COMPOUNDS[stint.compound]
    return f"[{info['color']}]{info['symbol']}[/{info['color']}]({stint.laps})"


def _fmt_strategy(strategy) -> str:
    return " → ".join(_fmt_stint(s) for s in strategy.stints)
