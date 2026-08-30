import { create } from "zustand";
import { applyEvent, initialRuntime, type ChatMessage, type RuntimeView, type UIEvent } from "./lib/protocol";

interface GuiStore {
  activeSessionId: string | null;
  runtimes: Record<string, RuntimeView>;
  unreadSessions: string[];
  connected: boolean;
  setActiveSession: (sessionId: string | null) => void;
  ingest: (event: UIEvent) => void;
  hydrate: (sessionId: string, snapshot: Record<string, unknown> | null) => void;
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
  hydrate: (sessionId, snapshot) => set((state) => {
    if (!snapshot) return state;
    const history = Array.isArray(snapshot.history) ? snapshot.history : [];
    const messages = history.flatMap((item) => {
      if (!item || typeof item !== "object") return [];
      const message = item as Record<string, unknown>;
      const role = message.role;
      if (role !== "user" && role !== "assistant" && role !== "tool") return [];
      return [{ role: role as ChatMessage["role"], content: String(message.content ?? ""), tool: typeof message.name === "string" ? message.name : undefined }];
    });
    const current = initialRuntime(sessionId);
    const runtime: RuntimeView = {
      ...current,
      runtimeState: typeof snapshot.runtime_state === "string" ? snapshot.runtime_state as RuntimeView["runtimeState"] : "IDLE",
      messages,
      plan: Array.isArray(snapshot.plan) ? snapshot.plan as Array<Record<string, unknown>> : [],
      pendingInteraction: snapshot.pending_interaction && typeof snapshot.pending_interaction === "object" ? snapshot.pending_interaction as RuntimeView["pendingInteraction"] : null
    };
    return { runtimes: { ...state.runtimes, [sessionId]: runtime } };
  }),
  setConnected: (connected) => set({ connected }),
  reset: () => set({ activeSessionId: null, runtimes: {}, unreadSessions: [], connected: false })
}));
