"""game.ui package — re-exports everything callers expect from the old game.ui module."""
from game.ui.helpers import fmt_lap_time, stat_bar, _xp_bar, _rain_bar
from game.ui.race_display import (
    show_race_header, show_race_results, show_pit_stats,
    show_race_events, show_lap_analysis,
)
from game.ui.quali_strategy import (
    show_knockout_quali_session, run_knockout_qualifying_with_animation,
    show_strategy_menu, show_strategy_summary,
)
from game.ui.overview import (
    show_team_overview, show_driver_development, show_standings,
)
from game.ui.race_flow import (
    show_circuit_briefing, show_race_transition, show_sponsor_selection,
    run_race_with_animation,
)
from game.ui.weather_sc import show_sc_strategy_decision, show_weather_strategy_decision

# Dead function stub kept so existing imports don't break at load time
def show_quali_results(*args, **kwargs):  # noqa: E302
    pass
