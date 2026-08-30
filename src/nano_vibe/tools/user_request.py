"""A blocking tool for structured user clarification."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from .base import Tool, ToolResult

AnswerCallback = Callable[[str, list[str]], Awaitable[str] | str]


class UserRequestTool(Tool):
    name = "user_request"
    description = "Ask the user one question with 2 to 4 options and free-text input."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "options": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["question", "options"],
        "additionalProperties": False,
    }

    def __init__(self, callback: AnswerCallback | None = None) -> None:
        self.callback = callback

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        question = arguments.get("question")
        options = arguments.get("options")
        if not isinstance(question, str) or not question.strip():
            return ToolResult.failure("question must be a non-empty string")
        if not isinstance(options, list) or not 2 <= len(options) <= 4:
            return ToolResult.failure("options must contain between 2 and 4 choices")
        if not all(isinstance(option, str) and option.strip() for option in options):
            return ToolResult.failure("each option must be a non-empty string")

        if self.callback is None:
            answer = await asyncio.to_thread(input, f"{question} ")
        else:
            answer = self.callback(question, options)
            if inspect.isawaitable(answer):
                answer = await answer
        if not isinstance(answer, str):
            return ToolResult.failure("user answer must be text")
        return ToolResult.success(answer, question=question, options=options)
