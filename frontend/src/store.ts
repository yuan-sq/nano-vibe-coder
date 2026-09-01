import { create } from "zustand";
import { applyEvent, initialRuntime, parsePlanItems, type AgentState, type ChatMessage, type RuntimeView, type UIEvent } from "./lib/protocol";

interface GuiStore {
  activeSessionId: string | null;
  runtimes: Record<string, RuntimeView>;
  unreadSessions: string[];
  connected: boolean;
  setActiveSession: (sessionId: string | null) => void;
  ingest: (event: UIEvent) => void;
  hydrate: (sessionId: string, snapshot: Record<string, unknown> | null, source?: "initial" | "resync") => void;
  setLastSeq: (sessionId: string, seq: number) => void;
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
    if (event.seq <= current.lastSeq) return state;
    const runtimes = { ...state.runtimes, [event.session_id]: applyEvent(current, event) };
    const shouldMarkUnread = state.activeSessionId !== event.session_id;
    const unreadSessions = shouldMarkUnread && !state.unreadSessions.includes(event.session_id)
      ? [...state.unreadSessions, event.session_id]
      : state.unreadSessions;
    return { runtimes, unreadSessions };
  }),
  hydrate: (sessionId, snapshot, source = "initial") => set((state) => {
    if (!snapshot) {
      return source === "resync"
        ? { runtimes: { ...state.runtimes, [sessionId]: initialRuntime(sessionId) } }
        : state;
    }
    const history = Array.isArray(snapshot.history) ? snapshot.history : [];
    const messages: ChatMessage[] = history.flatMap((item): ChatMessage[] => {
      if (!item || typeof item !== "object") return [];
      const message = item as Record<string, unknown>;
      const role = message.role;
      if (role !== "user" && role !== "assistant" && role !== "tool") return [];
      const content = String(message.content ?? "");
      if (role === "assistant" && !content.trim()) return [];
      return [{
        role: role as ChatMessage["role"],
        content,
        tool: typeof message.name === "string" ? message.name : undefined,
        toolCallId: typeof message.tool_call_id === "string" ? message.tool_call_id : undefined,
        arguments: message.arguments && typeof message.arguments === "object" && !Array.isArray(message.arguments)
          ? message.arguments as Record<string, unknown>
          : undefined,
        status: role === "tool" ? "completed" : undefined
      }];
    });
    const current = state.runtimes[sessionId] ?? initialRuntime(sessionId);
    const hasLiveEvents = source === "initial" && current.lastSeq > 0;
    const runtime: RuntimeView = {
      ...current,
      runtimeState: hasLiveEvents
        ? current.runtimeState
        : typeof snapshot.runtime_state === "string"
          ? snapshot.runtime_state as RuntimeView["runtimeState"]
          : "IDLE",
      agentState: hasLiveEvents
        ? current.agentState
        : typeof snapshot.state === "string" && ["REQUIREMENTS", "PLAN", "IMPLEMENT", "VERIFY", "DONE"].includes(snapshot.state)
          ? snapshot.state as AgentState
          : "REQUIREMENTS",
      messages: hasLiveEvents ? current.messages : messages,
      plan: hasLiveEvents
        ? current.plan
        : Array.isArray(snapshot.plan)
          ? parsePlanItems(snapshot.plan)
          : [],
      pendingInteraction: hasLiveEvents
        ? current.pendingInteraction
        : snapshot.pending_interaction && typeof snapshot.pending_interaction === "object"
          ? snapshot.pending_interaction as RuntimeView["pendingInteraction"]
          : null
    };
    return { runtimes: { ...state.runtimes, [sessionId]: runtime } };
  }),
  setLastSeq: (sessionId, seq) => set((state) => {
    const current = state.runtimes[sessionId] ?? initialRuntime(sessionId);
    if (seq <= current.lastSeq) return state;
    return { runtimes: { ...state.runtimes, [sessionId]: { ...current, lastSeq: seq } } };
  }),
  setConnected: (connected) => set({ connected }),
  reset: () => set({ activeSessionId: null, runtimes: {}, unreadSessions: [], connected: false })
}));
