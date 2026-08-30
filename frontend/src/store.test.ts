import { describe, expect, it } from "vitest";
import { useGuiStore } from "./store";

describe("GUI store", () => {
  it("marks a background session as unread", () => {
    useGuiStore.getState().reset();
    useGuiStore.getState().setActiveSession("session-1");
    useGuiStore.getState().setActiveSession("session-2");
    useGuiStore.getState().ingest({
      version: 1,
      session_id: "session-1",
      run_id: "run-1",
      seq: 1,
      type: "runtime_state",
      timestamp: "2026-08-31T00:00:00Z",
      payload: { state: "AWAITING_INPUT" }
    });
    expect(useGuiStore.getState().unreadSessions).toContain("session-1");
  });

  it("hydrates a persisted snapshot after reconnect", () => {
    useGuiStore.getState().reset();
    useGuiStore.getState().hydrate("session-1", {
      runtime_state: "AWAITING_INPUT",
      history: [{ role: "user", content: "继续" }],
      plan: [{ id: "one", status: "pending" }],
      pending_interaction: { interaction_id: "q-1", kind: "user_request", content: "选择" }
    });
    const runtime = useGuiStore.getState().runtimes["session-1"];
    expect(runtime.runtimeState).toBe("AWAITING_INPUT");
    expect(runtime.messages[0].content).toBe("继续");
    expect(runtime.pendingInteraction?.interaction_id).toBe("q-1");
  });
});
