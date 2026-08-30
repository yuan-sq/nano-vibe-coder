import json
from pathlib import Path

from nano_vibe.observability.trace import TraceWriter


def test_trace_writer_appends_json_events_and_redacts_secrets(tmp_path: Path) -> None:
    path = tmp_path / "runs" / "session.jsonl"
    writer = TraceWriter(path, session_id="session-1")

    writer.record(
        "tool_end",
        state="IMPLEMENT",
        api_key="top-secret",
        prompt_tokens=12,
        nested={"authorization": "Bearer secret"},
    )

    event = json.loads(path.read_text(encoding="utf-8"))
    assert event["event"] == "tool_end"
    assert event["session_id"] == "session-1"
    assert event["state"] == "IMPLEMENT"
    assert event["api_key"] == "[REDACTED]"
    assert event["prompt_tokens"] == 12
    assert event["nested"]["authorization"] == "[REDACTED]"
    assert "timestamp" in event
