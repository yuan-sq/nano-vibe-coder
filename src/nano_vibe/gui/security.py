"""Local-only GUI security and secret handling."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import subprocess
import tempfile
from pathlib import Path


class SecretStore:
    """Minimal dotenv store that never exposes secrets through status APIs."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()

    def _values(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        values: dict[str, str] = {}
        for raw_line in self.path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
        return values

    def set(self, key: str, value: str) -> None:
        if not key or "=" in key or "\n" in value:
            raise ValueError("invalid dotenv key or value")
        values = self._values()
        values[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                for name, item in sorted(values.items()):
                    stream.write(f"{name}={item}\n")
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

    def read_value(self, key: str) -> str | None:
        return self._values().get(key)

    def status(self, keys: list[str] | tuple[str, ...]) -> dict[str, bool]:
        values = self._values()
        return {key: bool(values.get(key)) for key in keys}


class StartupToken:
    def __init__(self, value: str | None = None) -> None:
        self.value = value or secrets.token_urlsafe(32)
        self._used = False

    def exchange(self, candidate: str) -> bool:
        if self._used or not hmac.compare_digest(candidate, self.value):
            return False
        self._used = True
        return True


def is_allowed_origin(origin: str | None, expected: str) -> bool:
    return origin is not None and hmac.compare_digest(origin, expected)


def validate_project_path(path: str | Path, *, home: str | Path | None = None) -> Path:
    candidate = Path(path).expanduser().resolve()
    root = Path(home).expanduser().resolve() if home is not None else Path.home().resolve()
    try:
        inside = os.path.commonpath((str(candidate), str(root))) == str(root)
    except ValueError:
        inside = False
    if not inside:
        raise ValueError("project must be inside the user home")
    if not candidate.is_dir():
        raise ValueError("project directory does not exist")
    try:
        completed = subprocess.run(
            ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("project is not a readable Git repository") from exc
    if completed.returncode != 0:
        raise ValueError("project must be an existing Git repository")
    top = Path(completed.stdout.strip()).resolve()
    if top != candidate:
        raise ValueError("project path must be the Git repository root")
    return candidate


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
