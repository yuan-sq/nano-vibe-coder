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

  it("keeps a blocking approval visible until it is resolved", () => {
    let state = initialRuntime("session-1");
    state = applyEvent(state, event("approval_requested", { interaction_id: "a-1", content: "允许吗" }));
    expect(state.pendingInteraction?.interaction_id).toBe("a-1");
    state = applyEvent(state, event("approval_resolved", { interaction_id: "a-1" }));
    expect(state.pendingInteraction).toBeNull();
  });
});
