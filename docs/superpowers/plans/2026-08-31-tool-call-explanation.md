# Tool-call Explanation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require a concise user-facing explanation before tool calls, retry tool-only model responses up to three additional times, then execute the final tool call without blocking if no explanation is produced.

**Architecture:** Add the explanation contract to the system prompt and every generated tool definition. Validate `ModelResponse` inside `AgentLoop` before appending it to history or executing tools; rejected responses remain ephemeral, and the fourth tool-only response is accepted after three corrective retries. Preserve protocol-valid assistant tool-call history while filtering empty assistant content from GUI hydration and rendering.

**Tech Stack:** Python 3.10+, pytest/pytest-asyncio, OpenAI-compatible streamed chat completions, React 18, TypeScript, Zustand, Vitest/Testing Library.

---

### Task 1: Advertise the explanation contract to the model

**Files:**
- Modify: `src/nano_vibe/tools/base.py:125-142`
- Modify: `src/nano_vibe/prompts/system.md`
- Test: `tests/unit/test_tool_registry.py`

- [ ] **Step 1: Write the failing tool-definition test**

Add these assertions immediately after the existing tool-name assertion in `test_registry_filters_tools_and_executes_structured_result` in `tests/unit/test_tool_registry.py`:

```python
definition = registry.definitions({"echo"})[0]
description = definition["function"]["description"]
assert "user-facing explanation" in description
assert "assistant content" in description
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
uv run pytest -q tests/unit/test_tool_registry.py::test_registry_filters_tools_and_executes_structured_result
```

Expected: FAIL because the current description is only `Echo a value.`.

- [ ] **Step 3: Add one shared instruction to every tool definition**

In `src/nano_vibe/tools/base.py`, define one module-level constant and append it when building `Tool.definition`:

```python
TOOL_EXPLANATION_INSTRUCTION = (
    "Before calling this tool, include a brief user-facing explanation "
    "in the assistant content."
)
```

Set the generated description to:

```python
"description": f"{self.description} {TOOL_EXPLANATION_INSTRUCTION}",
```

This keeps individual tool classes focused on tool-specific behavior while applying the contract uniformly.

- [ ] **Step 4: Reinforce the same rule in the system prompt**

Add this sentence to `src/nano_vibe/prompts/system.md`:

```text
Whenever a response contains tool calls, first include one brief user-facing action explanation in the assistant content; do not reveal hidden chain-of-thought.
```

The explanation describes the next action, not private reasoning.

- [ ] **Step 5: Run the focused test and verify GREEN**

Run:

```bash
uv run pytest -q tests/unit/test_tool_registry.py
```

Expected: all tests in the file pass.

- [ ] **Step 6: Commit the model-contract change**

```bash
git add src/nano_vibe/tools/base.py src/nano_vibe/prompts/system.md tests/unit/test_tool_registry.py
git commit -m "要求工具调用提供操作说明"
```

### Task 2: Retry tool-only responses before tool execution

**Files:**
- Modify: `src/nano_vibe/agent/loop.py:37-218`
- Test: `tests/unit/test_agent_loop.py`
- Test: `tests/unit/test_gui_runtime.py`
- Test: `tests/integration/test_agent_loop.py`
- Test: `tests/integration/test_offline_v2.py`

- [ ] **Step 1: Write a failing test for a successful corrective retry**

Add this test to `tests/unit/test_agent_loop.py`:

```python
@pytest.mark.asyncio
async def test_agent_loop_retries_tool_call_without_explanation(tmp_path: Path) -> None:
    model = ScriptedModel(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall("call-1", "transition_state", {"target_state": "PLAN"})
                ]
            ),
            ModelResponse(
                content="I will move into planning before drafting the implementation steps.",
                tool_calls=[
                    ToolCall("call-2", "transition_state", {"target_state": "PLAN"})
                ],
            ),
            ModelResponse(content="The planning phase is ready."),
        ]
    )
    machine = StateMachine()
    events: list[tuple[str, dict[str, Any]]] = []
    loop = AgentLoop(
        model,
        ToolRegistry([TransitionTool(machine)]),
        machine,
        tmp_path,
        on_event=lambda name, payload: events.append((name, payload)),
    )

    result = await loop.handle_input("Plan the change")

    assert result.message == "The planning phase is ready."
    assert machine.current is AgentState.PLAN
    assert len(model.requests) == 3
    assert [message["role"] for message in loop.history].count("tool") == 1
    assert loop.history[1]["content"].startswith("I will move into planning")
    retries = [payload for name, payload in events if name == "model_explanation_retry"]
    assert retries == [
        {
            "attempt": 1,
            "max_retries": 3,
            "tool_names": ["transition_state"],
        }
    ]
    retry_prompt = str(model.requests[1][0][-1]["content"])
    assert "brief user-facing explanation" in retry_prompt
```

- [ ] **Step 2: Run the successful-retry test and verify RED**

Run:

```bash
uv run pytest -q tests/unit/test_agent_loop.py::test_agent_loop_retries_tool_call_without_explanation
```

Expected: FAIL because the first tool call currently executes immediately and no `model_explanation_retry` event exists.

- [ ] **Step 3: Write a failing test for the three-retry fallback**

Add this test to `tests/unit/test_agent_loop.py`:

```python
@pytest.mark.asyncio
async def test_agent_loop_executes_tool_after_three_empty_explanation_retries(
    tmp_path: Path,
) -> None:
    tool_responses = [
        ModelResponse(
            content="   " if index == 3 else "",
            tool_calls=[
                ToolCall(
                    f"call-{index}",
                    "transition_state",
                    {"target_state": "PLAN"},
                )
            ],
        )
        for index in range(4)
    ]
    model = ScriptedModel([*tool_responses, ModelResponse(content="Fallback completed.")])
    machine = StateMachine()
    events: list[tuple[str, dict[str, Any]]] = []
    loop = AgentLoop(
        model,
        ToolRegistry([TransitionTool(machine)]),
        machine,
        tmp_path,
        on_event=lambda name, payload: events.append((name, payload)),
    )

    result = await loop.handle_input("Plan the change")

    assert result.message == "Fallback completed."
    assert machine.current is AgentState.PLAN
    assert len(model.requests) == 5
    assert [name for name, _payload in events].count("model_explanation_retry") == 3
    fallback = [payload for name, payload in events if name == "model_explanation_fallback"]
    assert fallback == [{"attempts": 4, "tool_names": ["transition_state"]}]
    assert [message["role"] for message in loop.history].count("tool") == 1
```

- [ ] **Step 4: Run the fallback test and verify RED**

Run:

```bash
uv run pytest -q tests/unit/test_agent_loop.py::test_agent_loop_executes_tool_after_three_empty_explanation_retries
```

Expected: FAIL because the loop executes the initial tool response instead of making three corrective retries.

- [ ] **Step 5: Implement the bounded response guard**

In `src/nano_vibe/agent/loop.py`, add:

```python
_MAX_TOOL_EXPLANATION_RETRIES = 3
_TOOL_EXPLANATION_RETRY_PROMPT = (
    "Your previous response contained tool calls but no explanation. "
    "Return the intended tool calls again, and include one brief user-facing "
    "explanation in the assistant content before those calls. Do not reveal "
    "hidden chain-of-thought."
)
```

Add this helper to `AgentLoop`:

```python
async def _complete_with_tool_explanation(
    self,
    messages: Sequence[Mapping[str, Any]],
    tools: Sequence[Mapping[str, Any]],
) -> ModelResponse:
    response = await self._complete(messages, tools)
    for attempt in range(1, _MAX_TOOL_EXPLANATION_RETRIES + 1):
        if not response.tool_calls or response.content.strip():
            return response
        payload = {
            "attempt": attempt,
            "max_retries": _MAX_TOOL_EXPLANATION_RETRIES,
            "tool_names": [call.name for call in response.tool_calls],
        }
        self._trace("model_explanation_retry", **payload)
        await self._emit_event("model_explanation_retry", payload)
        retry_messages = [
            *messages,
            {"role": "system", "content": _TOOL_EXPLANATION_RETRY_PROMPT},
        ]
        response = await self._complete(retry_messages, tools)
    if response.tool_calls and not response.content.strip():
        payload = {
            "attempts": _MAX_TOOL_EXPLANATION_RETRIES + 1,
            "tool_names": [call.name for call in response.tool_calls],
        }
        self._trace("model_explanation_fallback", **payload)
        await self._emit_event("model_explanation_fallback", payload)
    return response
```

Replace the direct `_complete(messages, self.registry.definitions(allowed))` call in `_run_until_pause` with `_complete_with_tool_explanation`. Rejected responses must not be appended to `history`, and tools must not execute until the helper returns. Keep the final empty assistant tool-call entry in backend history because OpenAI-compatible tool-result messages require their preceding assistant tool-call message.

- [ ] **Step 6: Run both new tests and verify GREEN**

Run:

```bash
uv run pytest -q \
  tests/unit/test_agent_loop.py::test_agent_loop_retries_tool_call_without_explanation \
  tests/unit/test_agent_loop.py::test_agent_loop_executes_tool_after_three_empty_explanation_retries
```

Expected: both tests pass.

- [ ] **Step 7: Update existing scripted tool responses to satisfy the new contract**

The existing tests below exercise state transitions, compaction, idempotency, GUI lifecycle events, and end-to-end flows rather than explanation retries. Give their scripted tool-call responses non-empty action text so each test retains its original scope:

- In `tests/unit/test_agent_loop.py`, add a short non-empty `content` value to the tool-call responses in:
  - `test_agent_loop_executes_tool_and_pauses_on_plain_response`
  - `test_agent_loop_notifies_before_executing_tool`
  - `test_agent_loop_compacts_history_before_next_model_turn`
  - `test_agent_loop_resets_turn_limit_for_a_new_task_after_done`
  - `test_agent_loop_replays_same_tool_call_id_without_second_side_effect`
- In `tests/unit/test_gui_runtime.py`, set the `_Model` tool-call response content to `"I will move into planning."`.
- In `tests/integration/test_agent_loop.py`, replace the `call` helper body with:

  ```python
  return ModelResponse(
      content=f"I will run {name}.",
      tool_calls=[ToolCall(f"call-{name}-{next(_call_ids)}", name, arguments)],
  )
  ```

- In `tests/integration/test_offline_v2.py`, replace the `call` helper body with:

  ```python
  return ModelResponse(
      content=f"I will run {name}.",
      tool_calls=[ToolCall(f"offline-{next(_ids)}", name, arguments)],
  )
  ```

- [ ] **Step 8: Run the complete backend regression set for this behavior**

Run:

```bash
uv run pytest -q \
  tests/unit/test_agent_loop.py \
  tests/unit/test_gui_runtime.py \
  tests/integration/test_agent_loop.py \
  tests/integration/test_offline_v2.py
```

Expected: all tests pass.

- [ ] **Step 9: Commit the retry guard**

```bash
git add \
  src/nano_vibe/agent/loop.py \
  tests/unit/test_agent_loop.py \
  tests/unit/test_gui_runtime.py \
  tests/integration/test_agent_loop.py \
  tests/integration/test_offline_v2.py
git commit -m "为空工具调用增加说明重试"
```

### Task 3: Suppress empty Agent cards in live and restored GUI state

**Files:**
- Modify: `frontend/src/store.ts:36-54`
- Modify: `frontend/src/components/MessageList.tsx:39-52`
- Test: `frontend/src/store.test.ts`
- Test: `frontend/src/components/MessageList.test.tsx`

- [ ] **Step 1: Write the failing snapshot-hydration test**

Add this test to `frontend/src/store.test.ts`:

```typescript
it("omits empty assistant tool-call placeholders from restored snapshots", () => {
  useGuiStore.getState().reset();
  useGuiStore.getState().hydrate("session-1", {
    runtime_state: "IDLE",
    history: [
      { role: "user", content: "继续" },
      {
        role: "assistant",
        content: null,
        tool_calls: [{ id: "call-1", function: { name: "shell", arguments: "{}" } }]
      },
      { role: "tool", name: "shell", tool_call_id: "call-1", content: "clean" },
      { role: "assistant", content: "检查完成。" }
    ]
  });

  const messages = useGuiStore.getState().runtimes["session-1"].messages;
  expect(messages.map((message) => [message.role, message.content])).toEqual([
    ["user", "继续"],
    ["tool", "clean"],
    ["assistant", "检查完成。"]
  ]);
});
```

- [ ] **Step 2: Write the failing defensive-rendering test**

Add this test to `frontend/src/components/MessageList.test.tsx`:

```typescript
it("does not render empty or whitespace-only assistant cards", () => {
  render(<MessageList messages={[
    { role: "assistant", content: "" },
    { role: "assistant", content: "   " },
    { role: "assistant", content: "可见说明" }
  ]} />);

  expect(screen.getAllByText("Agent")).toHaveLength(1);
  expect(screen.getByText("可见说明")).toBeInTheDocument();
});
```

- [ ] **Step 3: Run both frontend tests and verify RED**

Run:

```bash
cd frontend
npm test -- --run src/store.test.ts src/components/MessageList.test.tsx
```

Expected: FAIL because snapshot hydration and `MessageList` currently retain empty assistant messages.

- [ ] **Step 4: Filter empty assistant content at both boundaries**

In `frontend/src/store.ts`, after reading `role` and before returning the mapped message, calculate:

```typescript
const content = String(message.content ?? "");
if (role === "assistant" && !content.trim()) return [];
```

Use `content` in the resulting `ChatMessage` instead of converting it again.

In `frontend/src/components/MessageList.tsx`, create the defensive visible list before rendering:

```typescript
const visibleMessages = messages.filter(
  (message) => message.role !== "assistant" || Boolean(message.content.trim())
);
```

Use `visibleMessages` for the empty-state check and message mapping. Do not filter tool messages, even when their output is empty; their summary and arguments remain useful.

- [ ] **Step 5: Run focused frontend tests and verify GREEN**

Run:

```bash
cd frontend
npm test -- --run src/store.test.ts src/components/MessageList.test.tsx
```

Expected: both test files pass.

- [ ] **Step 6: Run complete verification**

Run from the repository root unless a command specifies another directory:

```bash
uv run pytest -q
uv run ruff check src tests
uv run pyright
git diff --check
```

Run from `frontend/`:

```bash
npm test -- --run
npm run build
```

Expected: all commands exit successfully; the Python suite may retain its existing explicitly skipped offline test.

- [ ] **Step 7: Review the complete diff and commit the GUI guard**

```bash
git diff --check
git status --short
git diff
git add frontend/src/store.ts frontend/src/store.test.ts frontend/src/components/MessageList.tsx frontend/src/components/MessageList.test.tsx
git commit -m "隐藏无内容的 Agent 消息"
```

After the commit, `git status --short` must be empty.
