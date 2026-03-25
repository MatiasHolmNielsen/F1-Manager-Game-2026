#!/usr/bin/env python3
import game.loop as game_loop
from game.loop import show_welcome, show_main_menu
from game.save_load import save_exists


def _run() -> None:
    show_welcome()

    from rich.console import Console
    from rich.panel import Panel
    from rich.align import Align
    from rich.text import Text
    from rich import box

    _console = Console()

    choice = show_main_menu(has_save=save_exists())

    if choice == "L":
        from game.save_load import list_saves, load_game
        from game.ui import show_slot_picker
        slots = list_saves()
        slot = show_slot_picker(slots, mode="load")
        if slot == 0:
            return
        data = load_game(slot)
        game_loop.main(save_data=data, slot=slot)
    elif choice == "1":
        game_loop.main()
    elif choice == "2":
        game_loop.main(create_team=True)
    elif choice == "3":
        _console.print()
        _console.print(
            Panel(
                Align.center(
                    Text.from_markup(
                        "[bold yellow]Driver Career mode is coming in a future update.[/bold yellow]\n\n"
                        "[dim]Stay tuned — for now, pick a team and get racing.[/dim]"
                    )
                ),
                title="[bold]COMING SOON[/bold]",
                border_style="red",
                box=box.DOUBLE_EDGE,
                padding=(1, 4),
            )
        )


if __name__ == "__main__":
    _run()
