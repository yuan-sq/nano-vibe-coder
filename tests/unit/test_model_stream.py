from types import SimpleNamespace

from nano_vibe.models.openai_compat import assemble_stream


def delta(*, content: str | None = None, tool_calls: list[object] | None = None) -> object:
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def chunk(delta_value: object, usage: object = None) -> object:
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta_value)],
        usage=usage,
    )


def test_assemble_stream_combines_text_and_native_tool_call_deltas() -> None:
    chunks = [
        chunk(delta(content="I will inspect.")),
        chunk(
            delta(
                tool_calls=[
                    SimpleNamespace(
                        index=0,
                        id="call-1",
                        function=SimpleNamespace(name="shell", arguments='{"com'),
                    )
                ]
            )
        ),
        chunk(
            delta(
                tool_calls=[
                    SimpleNamespace(
                        index=0,
                        id=None,
                        function=SimpleNamespace(name=None, arguments='mand":"pwd"}'),
                    )
                ]
            )
        ),
        chunk(delta(content=None), usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5)),
    ]

    response = assemble_stream(chunks)

    assert response.content == "I will inspect."
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].id == "call-1"
    assert response.tool_calls[0].name == "shell"
    assert response.tool_calls[0].arguments == {"command": "pwd"}
    assert response.usage == {"prompt_tokens": 10, "completion_tokens": 5}


def test_assemble_stream_reports_malformed_tool_arguments() -> None:
    chunks = [
        chunk(
            delta(
                tool_calls=[
                    SimpleNamespace(
                        index=0,
                        id="call-1",
                        function=SimpleNamespace(name="shell", arguments="not-json"),
                    )
                ]
            )
        )
    ]

    response = assemble_stream(chunks)

    assert response.tool_calls[0].arguments == {}
    assert response.tool_calls[0].parse_error is not None
