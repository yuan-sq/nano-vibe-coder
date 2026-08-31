import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { InteractionCard } from "./MessageList";

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
