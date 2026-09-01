import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { useGuiStore } from "./store";

const testState = vi.hoisted(() => ({
  sessionCalls: 0,
  sockets: [] as Array<{ failInteraction: () => void }>,
  returnCleanSnapshot: false
}));

vi.mock("./lib/api", () => ({
  GuiApi: class {
    async projects() { return []; }
    async session() {
      testState.sessionCalls += 1;
      return {
        metadata: {},
        snapshot: !testState.returnCleanSnapshot
          ? {
              runtime_state: "AWAITING_APPROVAL",
              pending_interaction: { interaction_id: "stale-1", kind: "approval", content: "确认" }
            }
          : { runtime_state: "PAUSED", pending_interaction: null }
      };
    }
  },
  websocketUrl: () => "ws://127.0.0.1:8000/api/v1/ws/none"
}));

vi.mock("./lib/socket", () => ({
  GuiSocketSession: class {
    private readonly onCommandResult: (result: Record<string, unknown>) => void;
    constructor(options: { onCommandResult?: (result: Record<string, unknown>) => void }) {
      this.onCommandResult = options.onCommandResult ?? (() => undefined);
      testState.sockets.push({
        failInteraction: () => {
          testState.returnCleanSnapshot = true;
          this.onCommandResult({ type: "interaction_result", ok: false });
        }
      });
    }
    start() {}
    stop() {}
    send() {}
  }
}));

describe("App shell layout", () => {
  afterEach(() => cleanup());

  beforeEach(() => {
    useGuiStore.getState().reset();
    testState.sessionCalls = 0;
    testState.sockets.length = 0;
    testState.returnCleanSnapshot = false;
  });

  it("does not render a standalone Shell output panel", () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>);

    expect(screen.queryByText("Shell 输出")).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("描述你要完成的任务…")).toBeInTheDocument();
  });

  it("resyncs the snapshot when an interaction result is stale", async () => {
    useGuiStore.getState().setActiveSession("session-1");
    useGuiStore.getState().hydrate("session-1", {
      runtime_state: "AWAITING_APPROVAL",
      pending_interaction: { interaction_id: "stale-1", kind: "approval", content: "确认" }
    });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>);

    expect(await screen.findByText("需要你的确认")).toBeInTheDocument();
    await waitFor(() => expect(testState.sockets).toHaveLength(1));
    testState.sockets[0].failInteraction();

    await waitFor(() => expect(screen.queryByText("需要你的确认")).not.toBeInTheDocument());
    expect(testState.sessionCalls).toBeGreaterThanOrEqual(2);
  });
});
