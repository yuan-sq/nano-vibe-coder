"""Rich terminal UI used by the interactive CLI."""

from __future__ import annotations

from rich.console import Console
from rich.prompt import Prompt

from nano_vibe.agent.loop import LoopResult, LoopStatus


class ConsoleUI:
    def __init__(self) -> None:
        self.console = Console()

    def read_input(self) -> str:
        return Prompt.ask("[bold cyan]You[/bold cyan]")

    def ask(self, question: str, options: list[str]) -> str:
        self.console.print(f"[bold yellow]Agent question:[/bold yellow] {question}")
        for index, option in enumerate(options, start=1):
            self.console.print(f"  {index}. {option}")
        answer = Prompt.ask("Choose a number or enter your own answer")
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1]
        return answer

    def approve(self, tool_name: str, arguments: dict[str, object]) -> bool:
        """Ask for application-level approval of a restricted tool call."""

        details = ", ".join(f"{key}={value!r}" for key, value in arguments.items())
        answer = Prompt.ask(
            f"Allow restricted tool {tool_name}({details})? [y/N]",
            default="N",
        )
        return answer.strip().lower() in {"y", "yes"}

    def write_stream(self, text: str) -> None:
        self.console.print(text, end="")

    def tool_start(self, name: str, arguments: dict[str, object]) -> None:
        details = ", ".join(f"{key}={value!r}" for key, value in arguments.items())
        self.console.print(f"\n[bold magenta]Tool[/bold magenta] {name}({details})")

    def show_result(self, result: LoopResult) -> None:
        if result.message:
            self.console.print()
            self.console.print(result.message)
        label = {
            LoopStatus.COMPLETED: "[green]DONE[/green]",
            LoopStatus.WAITING: "[yellow]WAITING[/yellow]",
            LoopStatus.ABORTED: "[red]ABORTED[/red]",
            LoopStatus.ERROR: "[red]ERROR[/red]",
        }[result.status]
        self.console.print(f"{label} · state turns: {result.turns}")
