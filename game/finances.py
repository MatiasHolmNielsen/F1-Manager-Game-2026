"""Race finances: prize money, ops costs, DNF repairs, sponsor income, milestone bonuses."""
from __future__ import annotations

from typing import Dict, List, Optional

from rich.console import Console
from rich.panel import Panel

from engine.race import RaceResult
from models.sponsor import Sponsor
from models.team import Team

console = Console()

POSITION_PRIZE: Dict[int, float] = {
    1: 4.0, 2: 3.5, 3: 3.0, 4: 2.5, 5: 2.0,
    6: 1.6, 7: 1.25, 8: 0.9, 9: 0.6, 10: 0.4,
}


def _apply_race_finances(
    team: Team,
    results: List[RaceResult],
    player_team_id: str,
    all_sponsors: Optional[Dict[str, Sponsor]] = None,
    races_remaining: Optional[int] = None,
) -> None:
    """Compute and apply race income, ops cost, DNF repairs, sponsor + milestone bonuses."""
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

    # ── Milestone bonuses ────────────────────────────────────────────────────
    pole_bonus = 0.0
    fastest_lap_bonus = 0.0
    podium_bonus = 0.0
    milestone_lines = []

    if any(r.grid_position == 1 for r in player_results):
        pole_bonus = 1.5
        milestone_lines.append(f"  Pole position    [bold cyan]+€{pole_bonus:.1f}M[/bold cyan]")

    if any(r.fastest_lap for r in player_results):
        fastest_lap_bonus = 1.0
        milestone_lines.append(f"  Fastest lap      [cyan]+€{fastest_lap_bonus:.1f}M[/cyan]")

    podium_count = sum(1 for r in player_results if r.position <= 3 and not r.dnf)
    if podium_count > 0:
        podium_bonus = 0.5 * podium_count
        milestone_lines.append(
            f"  Podium bonus     [cyan]+€{podium_bonus:.1f}M[/cyan]"
            f"  [dim]({podium_count}×€0.5M)[/dim]"
        )

    # ── Sponsor income ───────────────────────────────────────────────────────
    sponsor_base = 0.0
    sponsor_bonus = 0.0
    sponsor_lines = []
    sponsor: Optional[Sponsor] = None

    if all_sponsors and team.sponsor_id and team.sponsor_id in all_sponsors:
        sponsor = all_sponsors[team.sponsor_id]
        sponsor_base = sponsor.race_payment
        sponsor_lines.append(
            f"  [{sponsor.industry}] {sponsor.name}  [green]+€{sponsor_base:.2f}M[/green]"
        )

        bt = sponsor.bonus_type
        ba = sponsor.bonus_amount

        if bt == "fastest_lap" and any(r.fastest_lap for r in player_results):
            sponsor_bonus = ba
            sponsor_lines.append(
                f"  Sponsor bonus (fastest lap)  [bold green]+€{sponsor_bonus:.2f}M[/bold green]"
            )
        elif bt == "podium":
            pc = sum(1 for r in player_results if r.position <= 3 and not r.dnf)
            if pc > 0:
                sponsor_bonus = ba * pc
                sponsor_lines.append(
                    f"  Sponsor bonus ({pc}× podium)  [bold green]+€{sponsor_bonus:.2f}M[/bold green]"
                )
        elif bt == "win":
            wc = sum(1 for r in player_results if r.position == 1 and not r.dnf)
            if wc > 0:
                sponsor_bonus = ba * wc
                sponsor_lines.append(
                    f"  Sponsor bonus ({wc}× win)  [bold green]+€{sponsor_bonus:.2f}M[/bold green]"
                )
        elif bt == "top5_finish":
            t5 = sum(1 for r in player_results if r.position <= 5 and not r.dnf)
            if t5 > 0:
                sponsor_bonus = ba * t5
                sponsor_lines.append(
                    f"  Sponsor bonus ({t5}× top-5)  [bold green]+€{sponsor_bonus:.2f}M[/bold green]"
                )

    net = round(
        base_income + total_prize + constructor_win + ops_cost + dnf_repairs
        + pole_bonus + fastest_lap_bonus + podium_bonus
        + sponsor_base + sponsor_bonus,
        1,
    )
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
    if milestone_lines:
        lines.append("")
        lines.append("  [dim]── Milestone Bonuses ──[/dim]")
        lines += milestone_lines
    if sponsor_lines:
        lines.append("")
        lines.append("  [dim]── Sponsor Income ──[/dim]")
        lines += sponsor_lines

    net_color = "green" if net >= 0 else "red"
    sign = "+" if net >= 0 else ""
    lines.append(f"\n  Net this race    [{net_color}]{sign}€{net:.1f}M[/{net_color}]")
    lines.append(f"  Budget now       [bold]€{team.budget:.1f}M[/bold]")
    if races_remaining is not None and races_remaining > 0:
        projected = team.budget + net * races_remaining
        lines.append(f"  [dim]Est. season end: ~€{projected:.1f}M  ({races_remaining} races left)[/dim]")

    console.print(Panel(
        "\n".join(lines),
        title="[bold]FINANCES[/bold]",
        border_style="yellow",
        padding=(0, 2),
    ))
