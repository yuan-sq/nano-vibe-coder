import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { useGuiStore } from "./store";

vi.mock("./lib/api", () => ({
  GuiApi: class {
    async projects() { return []; }
  },
  websocketUrl: () => "ws://127.0.0.1:8000/api/v1/ws/none"
}));

vi.mock("./lib/socket", () => ({
  GuiSocketSession: class {
    start() {}
    stop() {}
    send() {}
  }
}));

describe("App shell layout", () => {
  beforeEach(() => {
    useGuiStore.getState().reset();
  });

  it("does not render a standalone Shell output panel", () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>);

    expect(screen.queryByText("Shell 输出")).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("描述你要完成的任务…")).toBeInTheDocument();
  });
});
