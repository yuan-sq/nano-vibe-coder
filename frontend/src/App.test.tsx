import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { useGuiStore } from "./store";

const testState = vi.hoisted(() => ({
  sessionCalls: 0,
  sockets: [] as Array<{ failInteraction: () => void; failCleanup: () => void }>,
  returnCleanSnapshot: false,
  returnMissingSnapshot: false,
  returnIdleSnapshot: false,
  permissionMode: "normal" as "normal" | "full-access",
  updatePermissionModeCalls: 0,
  sendCalls: 0,
  releaseSend: null as (() => void) | null
}));

vi.mock("./lib/api", () => ({
  GuiApi: class {
    async projects() { return []; }
    async session() {
      testState.sessionCalls += 1;
      return {
        metadata: {},
        snapshot: testState.returnMissingSnapshot
          ? null
          : !testState.returnCleanSnapshot
          ? {
              runtime_state: "AWAITING_APPROVAL",
              pending_interaction: { interaction_id: "stale-1", kind: "approval", content: "确认" }
            }
          : { runtime_state: testState.returnIdleSnapshot ? "IDLE" : "PAUSED", pending_interaction: null, permission_mode: testState.permissionMode }
      };
    }
    async updatePermissionMode(_sessionId: string, mode: "normal" | "full-access") {
      testState.updatePermissionModeCalls += 1;
      testState.permissionMode = mode;
      return { session_id: "session-1", permission_mode: mode };
    }
    async sendMessage() {
      testState.sendCalls += 1;
      await new Promise<void>((resolve) => {
        testState.releaseSend = () => {
          testState.releaseSend = null;
          resolve();
        };
      });
      return { run_id: "run-1", status: "RUNNING" };
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
        },
        failCleanup: () => {
          this.onCommandResult({
            type: "error",
            code: "stale_pending_cleanup_failed",
            message: "无法写入 Session 快照：磁盘不可写"
          });
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
    testState.returnMissingSnapshot = false;
    testState.returnIdleSnapshot = false;
    testState.permissionMode = "normal";
    testState.updatePermissionModeCalls = 0;
    testState.sendCalls = 0;
    testState.releaseSend = null;
  });

  it("does not render a standalone Shell output panel", () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>);

    expect(screen.queryByText("Shell 输出")).not.toBeInTheDocument();
    expect(screen.queryByText("V3")).not.toBeInTheDocument();
    expect(screen.queryByText("已连接")).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("描述你要完成的任务…")).toBeInTheDocument();
  });

  it("renders the current agent stage as a stage label", async () => {
    useGuiStore.getState().setActiveSession("session-1");
    testState.returnCleanSnapshot = true;
    testState.returnIdleSnapshot = true;
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>);

    expect(await screen.findByText("REQUIREMENTS 阶段")).toBeInTheDocument();
    expect(screen.queryByText("IDLE · Agent REQUIREMENTS")).not.toBeInTheDocument();
  });

  it("resyncs the snapshot when an interaction result is stale", async () => {
    useGuiStore.getState().setActiveSession("session-1");
    useGuiStore.getState().hydrate("session-1", {
      runtime_state: "AWAITING_APPROVAL",
      pending_interaction: { interaction_id: "stale-1", kind: "approval", content: "确认" }
    });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>);

    expect(await screen.findByText("确认")).toBeInTheDocument();
    expect(screen.queryByText("需要你的确认")).not.toBeInTheDocument();
    await waitFor(() => expect(testState.sockets).toHaveLength(1));
    testState.sockets[0].failInteraction();

    await waitFor(() => expect(screen.queryByText("确认")).not.toBeInTheDocument());
    expect(testState.sessionCalls).toBeGreaterThanOrEqual(2);
  });

  it("clears a stale approval when resync returns no snapshot", async () => {
    useGuiStore.getState().setActiveSession("session-1");
    useGuiStore.getState().hydrate("session-1", {
      runtime_state: "AWAITING_APPROVAL",
      pending_interaction: { interaction_id: "stale-1", kind: "approval", content: "确认" }
    });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>);

    expect(await screen.findByText("确认")).toBeInTheDocument();
    await waitFor(() => expect(testState.sockets).toHaveLength(1));
    testState.returnMissingSnapshot = true;
    testState.sockets[0].failInteraction();

    await waitFor(() => expect(screen.queryByText("确认")).not.toBeInTheDocument());
  });

  it("shows stale cleanup persistence errors from the server", async () => {
    useGuiStore.getState().setActiveSession("session-1");
    useGuiStore.getState().hydrate("session-1", {
      runtime_state: "AWAITING_APPROVAL",
      pending_interaction: { interaction_id: "stale-1", kind: "approval", content: "确认" }
    });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>);

    expect(await screen.findByText("确认")).toBeInTheDocument();
    await waitFor(() => expect(testState.sockets).toHaveLength(1));
    testState.sockets[0].failCleanup();

    expect(await screen.findByText("无法写入 Session 快照：磁盘不可写")).toBeInTheDocument();
    expect(screen.getByText("确认")).toBeInTheDocument();
  });

  it("does not POST duplicate messages while the first send is pending", async () => {
    useGuiStore.getState().setActiveSession("session-1");
    testState.returnCleanSnapshot = true;
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>);

    const input = await screen.findByPlaceholderText("描述你要完成的任务…");
    fireEvent.change(input, { target: { value: "执行一次任务" } });
    const sendButton = screen.getByRole("button", { name: "发送" });
    fireEvent.click(sendButton);
    fireEvent.click(sendButton);

    expect(testState.sendCalls).toBe(1);
    expect(sendButton).toBeDisabled();
    testState.releaseSend?.();
    await waitFor(() => expect(testState.releaseSend).toBeNull());
  });

  it("switches the active Session permission mode from the heading", async () => {
    useGuiStore.getState().setActiveSession("session-1");
    testState.returnCleanSnapshot = true;
    testState.returnIdleSnapshot = true;
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>);

    const selector = await screen.findByRole("button", { name: "权限模式：Normal" });
    fireEvent.click(selector);
    fireEvent.click(screen.getByRole("menuitem", { name: /Full Access/ }));

    await waitFor(() => expect(testState.updatePermissionModeCalls).toBe(1));
    expect(useGuiStore.getState().runtimes["session-1"]?.permissionMode).toBe("full-access");
  });
});
