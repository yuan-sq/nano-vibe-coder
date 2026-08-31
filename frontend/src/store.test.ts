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
      state: "PLAN",
      history: [
        { role: "user", content: "继续" },
        { role: "tool", name: "shell", tool_call_id: "call-1", arguments: { command: "git status" }, content: "clean" }
      ],
      plan: [{ id: "one", status: "pending" }],
      pending_interaction: { interaction_id: "q-1", kind: "user_request", content: "选择" }
    });
    const runtime = useGuiStore.getState().runtimes["session-1"];
    expect(runtime.runtimeState).toBe("AWAITING_INPUT");
    expect(runtime.agentState).toBe("PLAN");
    expect(runtime.messages[0].content).toBe("继续");
    expect(runtime.messages[1]).toMatchObject({ tool: "shell", arguments: { command: "git status" }, status: "completed" });
    expect(runtime.pendingInteraction?.interaction_id).toBe("q-1");
  });

  it("records the latest sequence after a resync", () => {
    useGuiStore.getState().reset();
    useGuiStore.getState().hydrate("session-1", { runtime_state: "IDLE", history: [] });
    useGuiStore.getState().setLastSeq("session-1", 9);

    expect(useGuiStore.getState().runtimes["session-1"].lastSeq).toBe(9);
  });

  it("ignores duplicate events delivered by replay and live subscriptions", () => {
    useGuiStore.getState().reset();
    useGuiStore.getState().ingest({
      version: 1,
      session_id: "session-1",
      run_id: "run-1",
      seq: 1,
      type: "assistant_delta",
      timestamp: "2026-08-31T00:00:00Z",
      payload: { text: "你好" }
    });
    useGuiStore.getState().ingest({
      version: 1,
      session_id: "session-1",
      run_id: "run-1",
      seq: 1,
      type: "assistant_delta",
      timestamp: "2026-08-31T00:00:00Z",
      payload: { text: "你好" }
    });

    expect(useGuiStore.getState().runtimes["session-1"].messages).toHaveLength(1);
    expect(useGuiStore.getState().runtimes["session-1"].messages[0].content).toBe("你好");
  });

  it("does not let a late snapshot replace live events", () => {
    useGuiStore.getState().reset();
    useGuiStore.getState().ingest({
      version: 1,
      session_id: "session-1",
      run_id: "run-1",
      seq: 1,
      type: "runtime_state",
      timestamp: "2026-08-31T00:00:00Z",
      payload: { state: "RUNNING" }
    });
    useGuiStore.getState().ingest({
      version: 1,
      session_id: "session-1",
      run_id: "run-1",
      seq: 2,
      type: "assistant_delta",
      timestamp: "2026-08-31T00:00:00Z",
      payload: { text: "实时回复" }
    });
    useGuiStore.getState().hydrate("session-1", {
      runtime_state: "IDLE",
      history: [{ role: "assistant", content: "旧快照" }]
    });

    const runtime = useGuiStore.getState().runtimes["session-1"];
    expect(runtime.runtimeState).toBe("RUNNING");
    expect(runtime.messages[0].content).toBe("实时回复");
    expect(runtime.lastSeq).toBe(2);
  });

  it("uses the snapshot as the recovery base after an event gap", () => {
    useGuiStore.getState().reset();
    useGuiStore.getState().ingest({
      version: 1,
      session_id: "session-1",
      run_id: "run-1",
      seq: 1,
      type: "assistant_delta",
      timestamp: "2026-08-31T00:00:00Z",
      payload: { text: "旧客户端状态" }
    });
    useGuiStore.getState().hydrate("session-1", {
      runtime_state: "AWAITING_INPUT",
      history: [{ role: "assistant", content: "持久化恢复状态" }],
      pending_interaction: { interaction_id: "q-1", kind: "user_request", content: "选择城市" }
    }, "resync");

    const runtime = useGuiStore.getState().runtimes["session-1"];
    expect(runtime.runtimeState).toBe("AWAITING_INPUT");
    expect(runtime.messages[0].content).toBe("持久化恢复状态");
    expect(runtime.pendingInteraction?.interaction_id).toBe("q-1");
  });
});
