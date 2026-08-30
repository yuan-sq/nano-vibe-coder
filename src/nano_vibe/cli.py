"""Command-line entry point for nano-vibe-coder."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from nano_vibe.config import ConfigError, load_config
from nano_vibe.session import Session
from nano_vibe.ui.console import ConsoleUI

app = typer.Typer(add_completion=False, invoke_without_command=True)


@app.callback()
def cli(
    ctx: typer.Context,
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    config: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """Run an interactive coding-agent session."""
    if ctx.invoked_subcommand is not None:
        return
    ui = ConsoleUI()
    workspace = workspace.resolve()
    if not workspace.is_dir():
        ui.console.print(f"[red]Workspace does not exist:[/red] {workspace}")
        raise typer.Exit(1)
    config_path = config or Path(__file__).resolve().parents[2] / "config.toml"
    try:
        app_config = load_config(config_path)
    except ConfigError as exc:
        ui.console.print(f"[red]Configuration error:[/red] {exc}")
        ui.console.print("Copy config.example.toml to config.toml and fill in your model settings.")
        raise typer.Exit(1) from exc
    asyncio.run(_run_repl(Session.from_config(app_config, workspace, ui), ui))


async def _run_repl(session: Session, ui: ConsoleUI) -> None:
    ui.console.print("[bold]nano-vibe-coder[/bold] · /help for commands · /quit to exit")
    while True:
        try:
            text = await asyncio.to_thread(ui.read_input)
        except (EOFError, KeyboardInterrupt):
            ui.console.print("\nSession ended.")
            return
        if text.strip() in {"/quit", "/exit"}:
            return
        if text.strip() == "/help":
            ui.console.print("Enter a coding task. Commands: /help, /state, /quit")
            continue
        if text.strip() == "/state":
            ui.console.print(f"Current state: {session.machine.current.value}")
            continue
        result = await session.handle_input(text)
        ui.show_result(result)


def main() -> None:
    app()
