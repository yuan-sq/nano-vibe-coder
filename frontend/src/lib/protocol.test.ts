import { describe, expect, it } from "vitest";
import { applyEvent, initialRuntime, type UIEvent } from "./protocol";

const event = (type: string, payload: Record<string, unknown>): UIEvent => ({
  version: 1,
  session_id: "session-1",
  run_id: "run-1",
  seq: 1,
  type,
  timestamp: "2026-08-31T00:00:00Z",
  payload
});

describe("GUI event reducer", () => {
  it("updates runtime state and appends assistant deltas", () => {
    let state = initialRuntime("session-1");
    state = applyEvent(state, event("runtime_state", { state: "RUNNING" }));
    state = applyEvent(state, event("assistant_delta", { text: "你好" }));
    expect(state.runtimeState).toBe("RUNNING");
    expect(state.messages).toEqual([{ role: "assistant", content: "你好" }]);
  });

  it("renders user input, agent stage, and tool arguments from lifecycle events", () => {
    let state = initialRuntime("session-1");
    state = applyEvent(state, event("user_input", { content: "检查项目", state: "PLAN" }));
    expect(state.agentState).toBe("PLAN");
    expect(state.messages).toEqual([{ role: "user", content: "检查项目" }]);

    state = applyEvent(state, event("tool_started", {
      tool: "shell",
      arguments: { command: "git status" },
      tool_call_id: "call-1"
    }));
    expect(state.messages[1]).toMatchObject({
      role: "tool",
      tool: "shell",
      arguments: { command: "git status" },
      status: "running"
    });

    state = applyEvent(state, event("tool_finished", {
      tool: "shell",
      tool_call_id: "call-1",
      ok: true,
      output: "clean",
      state: "IMPLEMENT"
    }));
    expect(state.agentState).toBe("IMPLEMENT");
    expect(state.messages[1]).toMatchObject({ content: "clean", status: "completed" });
  });

  it("does not duplicate a user message already restored from a snapshot", () => {
    let state = initialRuntime("session-1");
    state = applyEvent(state, event("user_input", { content: "继续", state: "PLAN" }));
    state = applyEvent(state, event("user_input", { content: "继续", state: "PLAN" }));

    expect(state.messages).toHaveLength(1);
  });

  it("keeps a blocking approval visible until it is resolved", () => {
    let state = initialRuntime("session-1");
    state = applyEvent(state, event("approval_requested", { interaction_id: "a-1", content: "允许吗" }));
    expect(state.pendingInteraction?.interaction_id).toBe("a-1");
    state = applyEvent(state, event("approval_resolved", { interaction_id: "a-1" }));
    expect(state.pendingInteraction).toBeNull();
  });
});
