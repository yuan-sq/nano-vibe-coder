import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Session } from "../lib/api";
import { SessionList } from "./SessionList";

const session: Session = {
  session_id: "session-1",
  project_id: "project-1",
  title: "新建 Session",
  archived: false,
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z"
};

describe("SessionList", () => {
  afterEach(() => cleanup());

  it("opens a rename context menu without selecting the session", () => {
    const onSelect = vi.fn();
    render(<SessionList sessions={[session]} activeSessionId={null} onSelect={onSelect} onRename={vi.fn()} />);

    fireEvent.contextMenu(screen.getByText("新建 Session"), { clientX: 40, clientY: 80 });

    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "重命名" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /✎|重命名 新建 Session/ })).not.toBeInTheDocument();
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("renames a session from the context menu on Enter", async () => {
    const onSelect = vi.fn();
    const onRename = vi.fn().mockResolvedValue(undefined);
    render(<SessionList sessions={[session]} activeSessionId={null} onSelect={onSelect} onRename={onRename} />);

    fireEvent.contextMenu(screen.getByText("新建 Session"));
    fireEvent.click(screen.getByRole("menuitem", { name: "重命名" }));
    const input = screen.getByDisplayValue("新建 Session");
    fireEvent.change(input, { target: { value: "今天的任务" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(onRename).toHaveBeenCalledWith("session-1", "今天的任务"));
    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("cancels editing with Escape and ignores an empty title", () => {
    const onRename = vi.fn();
    render(<SessionList sessions={[session]} activeSessionId={null} onSelect={vi.fn()} onRename={onRename} />);

    fireEvent.contextMenu(screen.getByText("新建 Session"));
    fireEvent.click(screen.getByRole("menuitem", { name: "重命名" }));
    const input = screen.getByDisplayValue("新建 Session");
    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onRename).not.toHaveBeenCalled();

    fireEvent.contextMenu(screen.getByText("新建 Session"));
    fireEvent.click(screen.getByRole("menuitem", { name: "重命名" }));
    fireEvent.keyDown(screen.getByDisplayValue("新建 Session"), { key: "Escape" });
    expect(screen.getByText("新建 Session")).toBeInTheDocument();
  });

  it("closes the context menu with Escape, outside click, and scroll", () => {
    render(<SessionList sessions={[session]} activeSessionId={null} onSelect={vi.fn()} onRename={vi.fn()} />);
    const item = screen.getByText("新建 Session");

    fireEvent.contextMenu(item);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    fireEvent.contextMenu(item);
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    fireEvent.contextMenu(item);
    fireEvent.scroll(document);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("selects a session on a normal left click", () => {
    const onSelect = vi.fn();
    render(<SessionList sessions={[session]} activeSessionId={null} onSelect={onSelect} onRename={vi.fn()} />);

    fireEvent.click(screen.getByText("新建 Session"));

    expect(onSelect).toHaveBeenCalledWith(session);
  });
});
