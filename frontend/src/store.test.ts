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
});
