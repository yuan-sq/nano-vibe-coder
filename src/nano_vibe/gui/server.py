"""Command-line runner for the FastAPI GUI service."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from nano_vibe.config import ConfigError, load_config

from .app import create_app
from .security import StartupToken


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the nano-vibe GUI API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--frontend-origin", required=True)
    parser.add_argument("--startup-token", required=True)
    args = parser.parse_args()
    config = None
    config_path = Path.cwd() / "config.toml"
    if config_path.is_file():
        try:
            config = load_config(config_path)
        except ConfigError:
            config = None
    app = create_app(
        require_auth=True,
        startup_token=StartupToken(args.startup_token),
        frontend_origin=args.frontend_origin,
        agent_config=config,
    )
    uvicorn.run(app, host=args.host, port=args.port, workers=1, log_level="info")


if __name__ == "__main__":
    main()
