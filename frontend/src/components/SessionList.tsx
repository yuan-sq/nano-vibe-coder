import { useEffect, useRef, useState } from "react";
import type { Session } from "../lib/api";

interface SessionListProps {
  sessions: Session[];
  activeSessionId: string | null;
  onSelect: (session: Session) => void;
  onRename: (sessionId: string, title: string) => Promise<void>;
  onError?: (message: string) => void;
}

export function SessionList({ sessions, activeSessionId, onSelect, onRename, onError }: SessionListProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [savingId, setSavingId] = useState<string | null>(null);
  const savingRef = useRef(false);
  const clickTimerRef = useRef<number | null>(null);

  useEffect(() => () => {
    if (clickTimerRef.current !== null) window.clearTimeout(clickTimerRef.current);
  }, []);

  const cancelEdit = () => {
    setEditingId(null);
    setDraft("");
  };

  const beginEdit = (event: React.SyntheticEvent, session: Session) => {
    event.preventDefault();
    event.stopPropagation();
    if (savingRef.current) return;
    if (clickTimerRef.current !== null) {
      window.clearTimeout(clickTimerRef.current);
      clickTimerRef.current = null;
    }
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

  const scheduleSelect = (event: React.MouseEvent, session: Session) => {
    event.stopPropagation();
    if (event.detail > 1) {
      beginEdit(event, session);
      return;
    }
    if (clickTimerRef.current !== null) window.clearTimeout(clickTimerRef.current);
    clickTimerRef.current = window.setTimeout(() => {
      clickTimerRef.current = null;
      onSelect(session);
    }, 220);
  };

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
              onClick={(event) => scheduleSelect(event, session)}
              onDoubleClick={(event) => beginEdit(event, session)}
            >{session.title}</button>}
        {!editing && <button className="session-edit" aria-label={`重命名 ${session.title}`} onClick={(event) => beginEdit(event, session)}>✎</button>}
      </div>;
    })}
  </div>;
}
