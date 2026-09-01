import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PermissionModeSelector } from "./PermissionModeSelector";

describe("PermissionModeSelector", () => {
  afterEach(() => cleanup());

  it("opens both modes and switches without a confirmation dialog", () => {
    const onChange = vi.fn();
    render(<PermissionModeSelector mode="normal" runtimeState="IDLE" onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: "权限模式：Normal" }));
    expect(screen.getByText("写文件、Shell 和网络工具按策略请求审批")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("menuitem", { name: /Full Access/ }));

    expect(onChange).toHaveBeenCalledWith("full-access");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("is disabled outside IDLE and explains why", () => {
    render(<PermissionModeSelector mode="full-access" runtimeState="RUNNING" onChange={vi.fn()} />);

    const button = screen.getByRole("button", { name: "权限模式：Full Access" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "仅可在 IDLE 状态切换");
  });

  it("closes the menu with Escape and an outside click", () => {
    render(<PermissionModeSelector mode="normal" runtimeState="IDLE" onChange={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "权限模式：Normal" }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "权限模式：Normal" }));
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("closes an open menu when the Session stops being idle", () => {
    const view = render(<PermissionModeSelector mode="normal" runtimeState="IDLE" onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "权限模式：Normal" }));
    expect(screen.getByRole("menu")).toBeInTheDocument();

    view.rerender(<PermissionModeSelector mode="normal" runtimeState="RUNNING" onChange={vi.fn()} />);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});
