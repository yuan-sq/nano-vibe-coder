"""Build provider-neutral chat messages for the current task phase."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def build_context(
    *,
    system_prompt: str,
    stage_prompt: str,
    agents_content: str,
    state: str,
    history: Sequence[dict[str, Any]],
    summary: str | None = None,
) -> list[dict[str, Any]]:
    sections = [
        system_prompt.strip(),
        f"Current state: {state}\n{stage_prompt.strip()}",
        "Repository guidance:\n" + (agents_content.strip() or "(no AGENTS.md found)"),
    ]
    messages: list[dict[str, Any]] = [{"role": "system", "content": "\n\n".join(sections)}]
    if summary:
        messages.append({"role": "system", "content": summary})
    messages.extend(dict(message) for message in history)
    return messages
