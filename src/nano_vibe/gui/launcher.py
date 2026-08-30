"""Start and clean up the local FastAPI and React GUI processes."""

from __future__ import annotations

import secrets
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path


class GuiLaunchError(RuntimeError):
    pass


def _free_port(preferred: int | None = None) -> int:
    if preferred is not None:
        return preferred
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def launch_gui(
    *,
    frontend_port: int | None = None,
    no_open: bool = False,
    dev: bool = False,
    frontend_dir: str | Path | None = None,
) -> None:
    node = shutil.which("node")
    npm = shutil.which("npm")
    if node is None or npm is None:
        raise GuiLaunchError("V3 GUI requires Node.js and npm on PATH")
    root = (
        Path(frontend_dir).expanduser().resolve()
        if frontend_dir is not None
        else Path(__file__).resolve().parents[3] / "frontend"
    )
    if not root.is_dir() or not (root / "package.json").is_file():
        raise GuiLaunchError(f"frontend source is missing: {root}")
    if not (root / "node_modules").is_dir():
        raise GuiLaunchError(f"frontend dependencies are missing; run `npm ci` in {root}")
    if not dev and not (root / "dist").is_dir():
        raise GuiLaunchError(f"frontend build is missing; run `npm run build` in {root}")

    ui_port = _free_port(frontend_port)
    api_port = _free_port()
    origin = f"http://127.0.0.1:{ui_port}"
    token = secrets.token_urlsafe(32)
    environment = {"PYTHONPATH": str(Path(__file__).resolve().parents[2])}
    api_process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "nano_vibe.gui.server",
            "--host",
            "127.0.0.1",
            "--port",
            str(api_port),
            "--frontend-origin",
            origin,
            "--startup-token",
            token,
        ],
        cwd=root.parent,
        env={**environment, **dict(__import__("os").environ)},
    )
    command = [npm, "run", "dev" if dev else "start", "--", "--host", "127.0.0.1", "--port", str(ui_port)]
    frontend_process = subprocess.Popen(command, cwd=root, env={**dict(__import__("os").environ), "NANO_VIBE_API_URL": f"http://127.0.0.1:{api_port}"})
    url = f"{origin}/#token={token}&api=http%3A%2F%2F127.0.0.1%3A{api_port}"
    print(f"nano-vibe GUI: {url}")
    if not no_open:
        webbrowser.open(url)
    try:
        while api_process.poll() is None and frontend_process.poll() is None:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        for process in (frontend_process, api_process):
            if process.poll() is None:
                process.terminate()
        for process in (frontend_process, api_process):
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
