"""Build provider-neutral chat messages for the current task phase."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any


def build_context(
    *,
    system_prompt: str,
    stage_prompt: str,
    agents_content: str,
    state: str,
    history: Sequence[dict[str, Any]],
    summary: str | None = None,
    plan: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    plan_content = json.dumps(list(plan or ()), ensure_ascii=False, sort_keys=True)
    sections = [
        system_prompt.strip(),
        f"Current state: {state}\n{stage_prompt.strip()}",
        "Repository guidance:\n" + (agents_content.strip() or "(no AGENTS.md found)"),
        "Plan Todo (JSON):\n" + plan_content,
    ]
    messages: list[dict[str, Any]] = [{"role": "system", "content": "\n\n".join(sections)}]
    if summary:
        messages.append({"role": "system", "content": summary})
    messages.extend(dict(message) for message in history)
    return messages
