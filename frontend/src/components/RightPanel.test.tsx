import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { initialRuntime } from "../lib/protocol";
import { RightPanel } from "./RightPanel";

describe("RightPanel plan", () => {
  it("renders plan content and all three statuses", () => {
    const runtime = {
      ...initialRuntime("session-1"),
      plan: [
        { id: "inspect", content: "检查代码", status: "completed" as const },
        { id: "edit", content: "修改实现", status: "in_progress" as const },
        { id: "verify", content: "运行测试", status: "pending" as const }
      ]
    };

    render(<RightPanel tab="plan" onTab={vi.fn()} runtime={runtime} />);

    expect(screen.getByText("检查代码")).toBeInTheDocument();
    expect(screen.getByText("修改实现")).toBeInTheDocument();
    expect(screen.getByText("运行测试")).toBeInTheDocument();
    expect(screen.getByText("completed")).toBeInTheDocument();
    expect(screen.getByText("in_progress")).toBeInTheDocument();
    expect(screen.getByText("pending")).toBeInTheDocument();
  });
});
