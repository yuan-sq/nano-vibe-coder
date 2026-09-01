import { fireEvent, render, screen } from "@testing-library/react";
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

describe("RightPanel diff", () => {
  it("keeps files collapsed by default and renders unified patch line styles", () => {
    const { container } = render(<RightPanel
      tab="diff"
      onTab={vi.fn()}
      runtime={initialRuntime("session-1")}
      diff={{
        is_git: true,
        head: "abc123",
        baseline_captured_at: "2026-09-01T00:00:00Z",
        entries: [{
          path: "src/app.py",
          status: "modified",
          git_status: " M",
          staged: false,
          unstaged: true,
          deleted: false,
          task_changed: true,
          pre_existing: false,
          binary: false,
          too_large: false,
          size: 20,
          staged_patch: null,
          unstaged_patch: "@@ -1 +1 @@\n-old\n+new",
          task_patch: "@@ -1 +1 @@\n-base\n+task-new"
        }]
      }}
    />);

    const details = screen.getByText("src/app.py").closest("details");
    expect(details).not.toBeNull();
    expect(details).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("src/app.py"));
    expect(screen.getByText("+new")).toHaveClass("patch-add");
    expect(screen.getByText("-old")).toHaveClass("patch-delete");
    expect(screen.getByText("任务相对变化")).toBeInTheDocument();
    expect(screen.getByText("+task-new")).toHaveClass("patch-add");
    expect(container.querySelector(".diff-file")).not.toBeNull();
  });
});

describe("RightPanel trace", () => {
  it("shows event time and state with expandable JSON details", () => {
    render(<RightPanel
      tab="trace"
      onTab={vi.fn()}
      runtime={initialRuntime("session-1")}
      trace={{
        items: [{
          timestamp: "2026-09-01T00:00:00Z",
          event: "model_request",
          state: "PLAN",
          tool_count: 2
        }],
        next_offset: 1,
        has_more: false,
        total: 1
      }}
    />);

    expect(screen.getByText("model_request")).toBeInTheDocument();
    expect(screen.getByText("PLAN")).toBeInTheDocument();
    expect(screen.queryByText("运行状态")).not.toBeInTheDocument();
    expect(screen.getByText("2026-09-01T00:00:00Z")).toBeInTheDocument();
    const details = screen.getByText("model_request").closest("details");
    expect(details).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("model_request"));
    expect(screen.getByText(/"tool_count": 2/)).toBeInTheDocument();
  });
});
