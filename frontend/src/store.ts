import { create } from "zustand";
import { applyEvent, initialRuntime, type RuntimeView, type UIEvent } from "./lib/protocol";

interface GuiStore {
  activeSessionId: string | null;
  runtimes: Record<string, RuntimeView>;
  unreadSessions: string[];
  connected: boolean;
  setActiveSession: (sessionId: string | null) => void;
  ingest: (event: UIEvent) => void;
  setConnected: (connected: boolean) => void;
  reset: () => void;
}

export const useGuiStore = create<GuiStore>((set) => ({
  activeSessionId: null,
  runtimes: {},
  unreadSessions: [],
  connected: false,
  setActiveSession: (sessionId) => set((state) => ({
    activeSessionId: sessionId,
    unreadSessions: sessionId ? state.unreadSessions.filter((id) => id !== sessionId) : state.unreadSessions
  })),
  ingest: (event) => set((state) => {
    const current = state.runtimes[event.session_id] ?? initialRuntime(event.session_id);
    const runtimes = { ...state.runtimes, [event.session_id]: applyEvent(current, event) };
    const shouldMarkUnread = state.activeSessionId !== event.session_id;
    const unreadSessions = shouldMarkUnread && !state.unreadSessions.includes(event.session_id)
      ? [...state.unreadSessions, event.session_id]
      : state.unreadSessions;
    return { runtimes, unreadSessions };
  }),
  setConnected: (connected) => set({ connected }),
  reset: () => set({ activeSessionId: null, runtimes: {}, unreadSessions: [], connected: false })
}));
