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

  it("renames a session on Enter and does not select the row", async () => {
    const onSelect = vi.fn();
    const onRename = vi.fn().mockResolvedValue(undefined);
    render(<SessionList sessions={[session]} activeSessionId={null} onSelect={onSelect} onRename={onRename} />);

    fireEvent.doubleClick(screen.getByText("新建 Session"));
    const input = screen.getByDisplayValue("新建 Session");
    fireEvent.change(input, { target: { value: "今天的任务" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(onRename).toHaveBeenCalledWith("session-1", "今天的任务"));
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("cancels editing with Escape and ignores an empty title", async () => {
    const onRename = vi.fn();
    render(<SessionList sessions={[session]} activeSessionId={null} onSelect={vi.fn()} onRename={onRename} />);

    fireEvent.doubleClick(screen.getByText("新建 Session"));
    const input = screen.getByDisplayValue("新建 Session");
    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onRename).not.toHaveBeenCalled();

    fireEvent.doubleClick(screen.getByText("新建 Session"));
    fireEvent.keyDown(screen.getByDisplayValue("新建 Session"), { key: "Escape" });
    expect(screen.getByText("新建 Session")).toBeInTheDocument();
  });
});
