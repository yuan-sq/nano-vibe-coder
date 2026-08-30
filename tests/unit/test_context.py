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


def test_build_context_includes_structured_plan_when_present() -> None:
    result = build_context(
        system_prompt="system",
        stage_prompt="plan",
        agents_content="rules",
        state="PLAN",
        history=[],
        plan=[{"id": "one", "content": "Inspect", "status": "in_progress"}],
    )

    assert "Plan Todo" in result[0]["content"]
    assert '"status": "in_progress"' in result[0]["content"]


def test_build_context_includes_loaded_skill_context() -> None:
    result = build_context(
        system_prompt="system",
        stage_prompt="plan",
        agents_content="rules",
        state="PLAN",
        history=[],
        skills=[{"name": "demo", "description": "A demo", "content": "Use it."}],
    )

    assert "Loaded skills" in result[0]["content"]
    assert "Use it." in result[0]["content"]
