import { useEffect, useRef, useState } from "react";
import type { Session } from "../lib/api";

interface SessionListProps {
  sessions: Session[];
  activeSessionId: string | null;
  onSelect: (session: Session) => void;
  onRename: (sessionId: string, title: string) => Promise<void>;
  onError?: (message: string) => void;
}

type ContextMenuState = { sessionId: string; x: number; y: number } | null;

export function SessionList({ sessions, activeSessionId, onSelect, onRename, onError }: SessionListProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [savingId, setSavingId] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenuState>(null);
  const savingRef = useRef(false);

  useEffect(() => {
    if (!contextMenu) return;
    const close = () => setContextMenu(null);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("scroll", close, true);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("scroll", close, true);
    };
  }, [contextMenu]);

  const cancelEdit = () => {
    setEditingId(null);
    setDraft("");
  };

  const beginEdit = (event: React.SyntheticEvent, session: Session) => {
    event.preventDefault();
    event.stopPropagation();
    if (savingRef.current) return;
    setEditingId(session.session_id);
    setDraft(session.title);
  };

  const saveEdit = async () => {
    if (!editingId || savingRef.current) return;
    const current = sessions.find((session) => session.session_id === editingId);
    if (!current) {
      cancelEdit();
      return;
    }
    const title = draft.trim();
    if (!title || title === current.title) {
      cancelEdit();
      return;
    }
    savingRef.current = true;
    setSavingId(editingId);
    try {
      await onRename(editingId, title);
      cancelEdit();
    } catch (cause) {
      cancelEdit();
      onError?.(cause instanceof Error ? cause.message : "Session 重命名失败");
    } finally {
      savingRef.current = false;
      setSavingId(null);
    }
  };

  const openContextMenu = (event: React.MouseEvent, session: Session) => {
    event.preventDefault();
    event.stopPropagation();
    const menuWidth = 120;
    const menuHeight = 40;
    setContextMenu({
      sessionId: session.session_id,
      x: Math.max(4, Math.min(event.clientX, window.innerWidth - menuWidth - 4)),
      y: Math.max(4, Math.min(event.clientY, window.innerHeight - menuHeight - 4))
    });
  };

  const menuSession = contextMenu ? sessions.find((session) => session.session_id === contextMenu.sessionId) : null;

  return <div className="session-list">
    {sessions.map((session) => {
      const editing = editingId === session.session_id;
      return <div className={`session-row ${session.session_id === activeSessionId ? "selected" : ""}`} key={session.session_id}>
        {editing
          ? <input
              className="session-edit-input"
              value={draft}
              autoFocus
              disabled={savingId === session.session_id}
              onChange={(event) => setDraft(event.target.value)}
              onClick={(event) => event.stopPropagation()}
              onBlur={() => void saveEdit()}
              onKeyDown={(event) => {
                event.stopPropagation();
                if (event.key === "Enter") {
                  event.preventDefault();
                  void saveEdit();
                } else if (event.key === "Escape") {
                  event.preventDefault();
                  cancelEdit();
                }
              }}
            />
          : <button
              className="session-item"
              onClick={() => onSelect(session)}
              onContextMenu={(event) => openContextMenu(event, session)}
            >{session.title}</button>}
      </div>;
    })}
    {contextMenu && menuSession && <div
      className="session-context-menu"
      role="menu"
      style={{ left: contextMenu.x, top: contextMenu.y }}
      onMouseDown={(event) => event.stopPropagation()}
    >
      <button
        type="button"
        role="menuitem"
        onClick={(event) => {
          event.stopPropagation();
          setContextMenu(null);
          beginEdit(event, menuSession);
        }}
      >
        重命名
      </button>
    </div>}
  </div>;
}
