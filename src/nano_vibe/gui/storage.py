"""Persistent GUI metadata kept separate from V2 session snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "nano-vibe"


@dataclass(frozen=True)
class ProjectRecord:
    id: str
    path: str
    name: str
    created_at: str
    last_opened_at: str


@dataclass(frozen=True)
class SessionMetadata:
    session_id: str
    project_id: str
    title: str
    archived: bool
    created_at: str
    updated_at: str


class AppStorage:
    """Small SQLite repository for non-domain GUI metadata."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root).expanduser().resolve() if root is not None else default_data_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "app.db"
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    path TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_opened_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS config_values (
                    scope TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def add_project(self, path: str | Path, *, name: str | None = None) -> ProjectRecord:
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_dir():
            raise ValueError(f"project directory does not exist: {resolved}")
        project_id = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:16]
        now = _now()
        display_name = name or resolved.name or str(resolved)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO projects(id, path, name, created_at, last_opened_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET last_opened_at=excluded.last_opened_at
                """,
                (project_id, str(resolved), display_name, now, now),
            )
        return self.get_project(project_id)

    def get_project(self, project_id: str) -> ProjectRecord:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown project: {project_id}")
        return ProjectRecord(
            id=row["id"],
            path=row["path"],
            name=row["name"],
            created_at=row["created_at"],
            last_opened_at=row["last_opened_at"],
        )

    def list_projects(self) -> list[ProjectRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM projects ORDER BY last_opened_at DESC"
            ).fetchall()
        return [
            ProjectRecord(row["id"], row["path"], row["name"], row["created_at"], row["last_opened_at"])
            for row in rows
        ]

    def remove_project(self, project_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM projects WHERE id=?", (project_id,))

    def create_session(self, project_id: str, *, title: str = "新建 Session") -> SessionMetadata:
        self.get_project(project_id)
        session_id = uuid.uuid4().hex[:12]
        now = _now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, 0, ?, ?)",
                (session_id, project_id, title, now, now),
            )
        return self.get_session(session_id)

    def get_session(self, session_id: str) -> SessionMetadata:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown session: {session_id}")
        return SessionMetadata(
            row["session_id"], row["project_id"], row["title"], bool(row["archived"]),
            row["created_at"], row["updated_at"],
        )

    def list_sessions(self, project_id: str, *, include_archived: bool = False) -> list[SessionMetadata]:
        query = "SELECT * FROM sessions WHERE project_id=?"
        args: list[Any] = [project_id]
        if not include_archived:
            query += " AND archived=0"
        query += " ORDER BY updated_at DESC"
        with self._connect() as connection:
            rows = connection.execute(query, args).fetchall()
        return [
            SessionMetadata(
                row["session_id"], row["project_id"], row["title"], bool(row["archived"]),
                row["created_at"], row["updated_at"],
            )
            for row in rows
        ]

    def update_session(
        self, session_id: str, *, title: str | None = None, archived: bool | None = None
    ) -> SessionMetadata:
        current = self.get_session(session_id)
        updated_title = current.title if title is None else title.strip() or current.title
        updated_archived = current.archived if archived is None else archived
        with self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET title=?, archived=?, updated_at=? WHERE session_id=?",
                (updated_title, int(updated_archived), _now(), session_id),
            )
        return self.get_session(session_id)

    def get_config(self, scope: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM config_values WHERE scope=?", (scope,)
            ).fetchone()
        return dict(json.loads(row["value"])) if row is not None else {}

    def set_config(self, scope: str, value: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO config_values(scope, value) VALUES (?, ?) "
                "ON CONFLICT(scope) DO UPDATE SET value=excluded.value",
                (scope, encoded),
            )
        return dict(value)
