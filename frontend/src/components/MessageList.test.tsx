import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { InteractionCard, MessageList } from "./MessageList";
import { MarkdownContent } from "./MarkdownContent";
import { ShellPanel } from "./RightPanel";

describe("InteractionCard", () => {
  it("renders user requests as answer controls instead of permission buttons", () => {
    const onResolve = vi.fn();
    render(
      <InteractionCard
        interaction={{
          interaction_id: "q-1",
          kind: "user_request",
          content: "查哪个城市？",
          options: ["北京", "上海"]
        }}
        onResolve={onResolve}
      />
    );

    expect(screen.getByText("需要你的回答")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "允许一次" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "北京" }));
    expect(onResolve).toHaveBeenCalledWith("北京");

    fireEvent.change(screen.getByPlaceholderText("输入你的回答"), { target: { value: "广州" } });
    fireEvent.click(screen.getByRole("button", { name: "提交回答" }));
    expect(onResolve).toHaveBeenCalledWith("广州");
  });
});

describe("MessageList", () => {
  it("renders common assistant markdown as semantic elements", () => {
    render(<MessageList messages={[{ role: "assistant", content: "# 标题\n\n**重点** 和 `代码`" }]} />);

    expect(screen.getByRole("heading", { name: "标题" })).toBeInTheDocument();
    expect(screen.getByText("重点").tagName).toBe("STRONG");
    expect(screen.getByText("代码").tagName).toBe("CODE");
  });

  it("hides assistant messages with empty or whitespace-only content", () => {
    const { container } = render(<MessageList messages={[
      { role: "assistant", content: "" },
      { role: "assistant", content: "   " },
      { role: "assistant", content: "可见说明" },
      { role: "tool", tool: "shell", content: "" }
    ]} />);

    expect(container.querySelectorAll(".message.assistant .message-label")).toHaveLength(1);
    expect(screen.getByText("可见说明")).toBeInTheDocument();
    expect(screen.getByText("已运行 shell")).toBeInTheDocument();
  });

  it("supports GFM blocks without creating raw HTML or unsafe links", () => {
    const { container } = render(<MarkdownContent content={"```ts\nconst value = 1;\n```\n\n| 名称 | 值 |\n| --- | --- |\n| A | 1 |\n\n[危险](javascript:alert(1))"} />);

    expect(container.querySelector("pre code")).toHaveTextContent("const value = 1;");
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("a")).not.toHaveAttribute("href", "javascript:alert(1)");
  });

  it("shows a collapsed one-line tool summary with arguments", () => {
    const { rerender } = render(<MessageList messages={[{ role: "tool", tool: "web_search", content: "结果" }]} />);

    const details = screen.getByText("已运行 web_search").closest("details");
    expect(details).not.toBeNull();
    expect(details).not.toHaveAttribute("open");
    rerender(<MessageList messages={[{ role: "tool", tool: "web_search", content: "新结果", arguments: { query: "Python" }, status: "running" }]} />);
    expect(screen.getByText("运行中 web_search query=Python")).toBeInTheDocument();
    expect(screen.getByText("运行中 web_search query=Python").closest("details")).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("运行中 web_search query=Python"));
    expect(screen.getByText("新结果")).toBeInTheDocument();
  });

  it("puts the shell command in the tool summary", () => {
    render(<MessageList messages={[{ role: "tool", tool: "shell", arguments: { command: "node bs_test.mjs" }, content: "output", status: "running" }]} />);

    expect(screen.getByText("运行中 shell node bs_test.mjs")).toBeInTheDocument();
  });

  it("lets the user collapse the shell output panel", () => {
    render(<ShellPanel runtime={{ sessionId: "s", runId: null, runtimeState: "IDLE", agentState: "REQUIREMENTS", messages: [], pendingInteraction: null, plan: [], shell: [{ stream: "stdout", text: "ok" }], lastSeq: 0 }} />);

    const details = screen.getByText("Shell 输出").closest("details");
    expect(details).not.toBeNull();
    expect(details).toHaveAttribute("open");
    fireEvent.click(screen.getByText("Shell 输出"));
    expect(details).not.toHaveAttribute("open");
  });
});
