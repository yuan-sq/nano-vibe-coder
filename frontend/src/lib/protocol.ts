export type RuntimeState =
  | "IDLE"
  | "RUNNING"
  | "AWAITING_APPROVAL"
  | "AWAITING_INPUT"
  | "STOPPING"
  | "PAUSED"
  | "ERROR";

export interface UIEvent {
  version: 1;
  session_id: string;
  run_id: string | null;
  seq: number;
  type: string;
  timestamp: string;
  payload: Record<string, unknown>;
}

export interface ChatMessage {
  role: "user" | "assistant" | "tool";
  content: string;
  tool?: string;
  toolCallId?: string;
}

export interface PendingInteraction {
  interaction_id: string;
  kind: "approval" | "user_request";
  content: string;
  tool_name?: string;
  arguments?: Record<string, unknown>;
  capability?: string;
  reason?: string;
  options?: string[];
}

export interface RuntimeView {
  sessionId: string;
  runId: string | null;
  runtimeState: RuntimeState;
  messages: ChatMessage[];
  pendingInteraction: PendingInteraction | null;
  plan: Array<Record<string, unknown>>;
  shell: Array<{ stream: string; text: string }>;
  lastSeq: number;
}

export const initialRuntime = (sessionId: string): RuntimeView => ({
  sessionId,
  runId: null,
  runtimeState: "IDLE",
  messages: [],
  pendingInteraction: null,
  plan: [],
  shell: [],
  lastSeq: 0
});

export function applyEvent(state: RuntimeView, event: UIEvent): RuntimeView {
  const next: RuntimeView = { ...state, runId: event.run_id ?? state.runId, lastSeq: Math.max(state.lastSeq, event.seq) };
  switch (event.type) {
    case "runtime_state":
      return { ...next, runtimeState: String(event.payload.state) as RuntimeState };
    case "assistant_delta": {
      const text = String(event.payload.text ?? "");
      const messages = [...next.messages];
      const last = messages[messages.length - 1];
      if (last?.role === "assistant") messages[messages.length - 1] = { ...last, content: last.content + text };
      else messages.push({ role: "assistant", content: text });
      return { ...next, messages };
    }
    case "message_completed": {
      const content = String(event.payload.content ?? "");
      if (!content) return next;
      const messages = [...next.messages];
      const last = messages[messages.length - 1];
      if (last?.role === "assistant") messages[messages.length - 1] = { ...last, content };
      else messages.push({ role: "assistant", content });
      return { ...next, messages };
    }
    case "tool_started":
      return {
        ...next,
        messages: [...next.messages, {
          role: "tool",
          content: "执行中…",
          tool: String(event.payload.tool ?? "tool"),
          toolCallId: String(event.payload.tool_call_id ?? "")
        }]
      };
    case "tool_finished": {
      const id = String(event.payload.tool_call_id ?? "");
      const messages = next.messages.map((message) =>
        message.toolCallId === id ? { ...message, content: String(event.payload.output ?? "") } : message
      );
      return { ...next, messages };
    }
    case "approval_requested":
    case "user_request":
      return { ...next, runtimeState: event.type === "approval_requested" ? "AWAITING_APPROVAL" : "AWAITING_INPUT", pendingInteraction: event.payload as unknown as PendingInteraction };
    case "approval_resolved":
    case "user_request_resolved":
      return { ...next, pendingInteraction: null, runtimeState: "RUNNING" };
    case "plan_updated":
      return { ...next, plan: Array.isArray(event.payload.plan) ? event.payload.plan as Array<Record<string, unknown>> : next.plan };
    case "shell_chunk":
      return { ...next, shell: [...next.shell, { stream: String(event.payload.stream ?? "stdout"), text: String(event.payload.text ?? "") }] };
    case "error":
      return { ...next, runtimeState: "ERROR" };
    case "run_completed":
      return { ...next, runtimeState: String(event.payload.status ?? "completed") === "paused" ? "PAUSED" : "IDLE" };
    default:
      return next;
  }
}
