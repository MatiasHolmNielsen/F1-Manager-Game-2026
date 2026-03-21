"""Race finances: prize money, ops costs, DNF repairs."""
from __future__ import annotations

from typing import Dict, List

from rich.console import Console
from rich.panel import Panel

from engine.race import RaceResult
from models.team import Team

console = Console()

POSITION_PRIZE: Dict[int, float] = {
    1: 8.0, 2: 7.0, 3: 6.0, 4: 5.0, 5: 4.0,
    6: 3.2, 7: 2.5, 8: 1.8, 9: 1.2, 10: 0.8,
}


def _apply_race_finances(
    team: Team,
    results: List[RaceResult],
    player_team_id: str,
) -> None:
    """Compute and apply race income, ops cost, and DNF repairs. Print a summary panel."""
    player_results = [r for r in results if r.team_id == player_team_id]
    num_dnfs = sum(1 for r in player_results if r.dnf)

    base_income     = 2.0
    ops_cost        = -2.0
    dnf_repairs     = -6.0 * num_dnfs
    constructor_win = 6.0 if any(r.position == 1 and not r.dnf for r in player_results) else 0.0

    prize_lines = []
    total_prize = 0.0
    for r in player_results:
        prize = POSITION_PRIZE.get(r.position, 0.0) if not r.dnf else 0.0
        total_prize += prize
        status = "DNF" if r.dnf else f"P{r.position}"
        color = "green" if prize > 0 else "dim"
        prize_lines.append(
            f"  {r.driver.name} ({status})  [{color}]+€{prize:.1f}M[/{color}]"
        )

    net = round(base_income + total_prize + constructor_win + ops_cost + dnf_repairs, 1)
    team.budget = max(0.0, team.budget + net)

    lines = [f"  Base income      [green]+€{base_income:.1f}M[/green]"]
    lines += prize_lines
    if constructor_win:
        lines.append(f"  Constructor win  [bold green]+€{constructor_win:.1f}M[/bold green]")
    lines.append(f"  Running costs    [red]−€{abs(ops_cost):.1f}M[/red]")
    if num_dnfs:
        lines.append(
            f"  DNF repairs      [red]−€{abs(dnf_repairs):.1f}M[/red]"
            f"  ({num_dnfs} DNF{'s' if num_dnfs > 1 else ''})"
        )
    net_color = "green" if net >= 0 else "red"
    sign = "+" if net >= 0 else ""
    lines.append(f"\n  Net this race    [{net_color}]{sign}€{net:.1f}M[/{net_color}]")
    lines.append(f"  Budget now       [bold]€{team.budget:.1f}M[/bold]")

    console.print(Panel(
        "\n".join(lines),
        title="[bold]FINANCES[/bold]",
        border_style="yellow",
        padding=(0, 2),
    ))
