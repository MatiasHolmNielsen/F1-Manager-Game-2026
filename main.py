#!/usr/bin/env python3
import game.loop as game_loop
from game.loop import show_welcome
from game.save_load import save_exists, load_game

if __name__ == "__main__":
    show_welcome()

    if save_exists():
        from rich.prompt import Prompt
        choice = Prompt.ask(
            "  [bold]N[/bold] New Game  ·  [bold]L[/bold] Load saved game",
            choices=["N", "L", "n", "l"],
            default="N",
        ).upper()
        data = load_game() if choice == "L" else None
    else:
        data = None

    game_loop.main(save_data=data)
