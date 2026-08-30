"""Streaming, cancellable shell execution for GUI read-only output."""

from __future__ import annotations

import asyncio
import inspect
import os
import signal
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from nano_vibe.tools.base import ToolResult

ChunkSink = Callable[[str, str], Any]


class StreamingShellRunner:
    def __init__(self, workspace: str | Path, *, timeout_seconds: float = 300) -> None:
        self.workspace = Path(workspace).resolve()
        self.timeout_seconds = timeout_seconds

    async def run(
        self,
        command: str,
        emit: ChunkSink,
        *,
        cancel_event: asyncio.Event | None = None,
        chunk_size: int = 4096,
    ) -> ToolResult:
        if not command.strip():
            return ToolResult.failure("shell command must be a non-empty string", code="invalid_shell_command")
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=self.workspace,
                executable="/bin/sh",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            return ToolResult.failure(str(exc), code="shell_error", retryable=True)

        output: list[str] = []

        async def read_stream(stream: asyncio.StreamReader | None, name: str) -> None:
            if stream is None:
                return
            while chunk := await stream.read(chunk_size):
                text = chunk.decode("utf-8", errors="replace")
                output.append(text)
                result = emit(name, text)
                if inspect.isawaitable(result):
                    await result

        readers = [
            asyncio.create_task(read_stream(process.stdout, "stdout")),
            asyncio.create_task(read_stream(process.stderr, "stderr")),
        ]
        wait_task = asyncio.create_task(process.wait())
        pump_task = asyncio.ensure_future(asyncio.gather(*readers))
        cancel_task = asyncio.create_task(cancel_event.wait()) if cancel_event is not None else None
        timed_out = False
        cancelled = False
        try:
            waiters: list[asyncio.Future[Any]] = [pump_task]
            if cancel_task is not None:
                waiters.append(cast(asyncio.Future[Any], cancel_task))
            done, _ = await asyncio.wait(
                waiters,
                timeout=self.timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if pump_task not in done:
                if cancel_task is not None and cancel_task in done and cancel_task.result():
                    cancelled = True
                else:
                    timed_out = True
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.wait(), timeout=3)
                except asyncio.TimeoutError:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    await process.wait()
            else:
                await wait_task
        finally:
            if cancel_task is not None:
                cancel_task.cancel()
            if not wait_task.done():
                wait_task.cancel()
            if not pump_task.done():
                pump_task.cancel()
            await asyncio.gather(pump_task, return_exceptions=True)

        exit_code = process.returncode
        metadata = {
            "exit_code": exit_code,
            "timed_out": timed_out,
            "cancelled": cancelled,
        }
        if cancelled:
            return ToolResult.failure("shell command cancelled", code="shell_cancelled", **metadata)
        if timed_out:
            return ToolResult.failure("shell command timed out", code="shell_timeout", retryable=True, **metadata)
        if exit_code != 0:
            return ToolResult.failure(
                "".join(output), code="shell_exit", details={"exit_code": exit_code}, **metadata
            )
        return ToolResult(ok=True, output="".join(output), metadata=metadata)
