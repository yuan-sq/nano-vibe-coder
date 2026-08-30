"""Command-line entry point for nano-vibe-coder."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from nano_vibe.config import ConfigError, load_config
from nano_vibe.gui.runtime import GlobalRunLock, LockAcquisitionError
from nano_vibe.gui.storage import default_data_dir
from nano_vibe.permissions import PermissionMode
from nano_vibe.session import Session
from nano_vibe.session_store import SessionStoreError
from nano_vibe.ui.console import ConsoleUI

app = typer.Typer(add_completion=False, invoke_without_command=True)


@app.command("gui")
def gui(
    port: int | None = typer.Option(None, "--port", help="Frontend port."),
    no_open: bool = typer.Option(False, "--no-open", help="Do not open a browser window."),
    dev: bool = typer.Option(False, "--dev", help="Start the Vite development server."),
) -> None:
    """Start the local browser GUI and its FastAPI service."""
    from nano_vibe.gui.launcher import GuiLaunchError, launch_gui

    try:
        launch_gui(frontend_port=port, no_open=no_open, dev=dev)
    except GuiLaunchError as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.callback()
def cli(
    ctx: typer.Context,
    workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),  # noqa: B008
    config: Path | None = typer.Option(None, "--config", "-c"),  # noqa: B008
    resume: str | None = typer.Option(None, "--resume", help="Resume an explicit session snapshot."),
    full_access: bool = typer.Option(
        False,
        "--full-access",
        help="Allow restricted registered tools through the application policy.",
    ),
) -> None:
    """Run an interactive coding-agent session.

    REPL commands: /help, /state, /plan, /permissions, /skills, /sessions,
    /quit. Use --resume SESSION_ID for explicit snapshot recovery.
    """
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
    mode = "full-access" if full_access else app_config.runtime.permission_mode
    session = Session.from_config(
        app_config,
        workspace,
        ui,
        session_id=resume,
        permission_mode=mode,
    )
    if resume is not None:
        try:
            snapshot = session.session_store.load(resume)
            if not full_access:
                session.permission_mode = PermissionMode.parse(snapshot.permission_mode)
                if session.registry.permission_policy is not None:
                    session.registry.permission_policy.mode = session.permission_mode
            session.restore_snapshot(snapshot)
        except SessionStoreError as exc:
            ui.console.print(f"[red]Session resume error:[/red] {exc}")
            raise typer.Exit(1) from exc
    asyncio.run(_run_repl(session, ui))


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
            ui.console.print(
                "Enter a coding task. Commands: /help, /state, /plan, "
                "/permissions, /skills, /sessions, /quit"
            )
            continue
        if text.strip() == "/state":
            ui.console.print(f"Current state: {session.machine.current.value}")
            continue
        if handle_repl_command(text, session, ui):
            continue
        lock = GlobalRunLock(default_data_dir() / "run.lock")
        try:
            lock.acquire()
        except LockAcquisitionError:
            ui.console.print("[yellow]Another Agent task is already running.[/yellow]")
            continue
        try:
            result = await session.handle_input(text)
        finally:
            lock.release()
        ui.show_result(result)


def handle_repl_command(text: str, session: Session, ui: ConsoleUI) -> bool:
    """Handle a read-only session management command; return whether handled."""

    command = text.strip().lower()
    if command == "/plan":
        ui.console.print(json.dumps(session.machine.plan.to_list(), ensure_ascii=False, indent=2))
        return True
    if command == "/permissions":
        policy = session.registry.permission_policy
        mode = policy.mode.value if policy is not None else session.permission_mode.value
        ui.console.print(f"Permission mode: {mode}")
        ui.console.print("Restricted scopes: write, shell, network")
        return True
    if command == "/skills":
        discovered = session.skill_manager.discover()
        loaded = set(session.skill_manager.loaded_names)
        if not discovered:
            ui.console.print("No skills found.")
        else:
            for name, metadata in discovered.items():
                marker = " [loaded]" if name in loaded else ""
                ui.console.print(f"{name}{marker} — {metadata.description}")
        return True
    if command == "/sessions":
        sessions = session.session_store.list_sessions()
        if not sessions:
            ui.console.print("No saved sessions.")
        else:
            for item in sessions:
                ui.console.print(
                    f"{item['session_id']} · {item['state']} · "
                    f"{item['permission_mode']} · {item['updated_at']}"
                )
        return True
    return False


def main() -> None:
    app()
