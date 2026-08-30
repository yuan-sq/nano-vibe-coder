from nano_vibe.agent.context import build_context


def test_build_context_includes_stage_rules_agents_state_and_history() -> None:
    result = build_context(
        system_prompt="You are a coding agent.",
        stage_prompt="You are in PLAN.",
        agents_content="# Rules",
        state="PLAN",
        history=[{"role": "user", "content": "fix it"}],
        summary="Earlier work",
    )

    assert result[0]["role"] == "system"
    assert "You are a coding agent." in result[0]["content"]
    assert "PLAN" in result[0]["content"]
    assert "# Rules" in result[0]["content"]
    assert result[1] == {"role": "system", "content": "Earlier work"}
    assert result[-1] == {"role": "user", "content": "fix it"}
