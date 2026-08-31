export type RuntimeState =
  | "IDLE"
  | "RUNNING"
  | "AWAITING_APPROVAL"
  | "AWAITING_INPUT"
  | "STOPPING"
  | "PAUSED"
  | "ERROR";

export type AgentState = "REQUIREMENTS" | "PLAN" | "IMPLEMENT" | "VERIFY" | "DONE";
export type ToolStatus = "running" | "completed" | "failed";

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
  arguments?: Record<string, unknown>;
  status?: ToolStatus;
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
  agentState: AgentState;
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
  agentState: "REQUIREMENTS",
  messages: [],
  pendingInteraction: null,
  plan: [],
  shell: [],
  lastSeq: 0
});

export function applyEvent(state: RuntimeView, event: UIEvent): RuntimeView {
  const next: RuntimeView = { ...state, runId: event.run_id ?? state.runId, lastSeq: Math.max(state.lastSeq, event.seq) };
  const stateFromEvent = (): AgentState => {
    const value = String(event.payload.state ?? "");
    return ["REQUIREMENTS", "PLAN", "IMPLEMENT", "VERIFY", "DONE"].includes(value)
      ? value as AgentState
      : state.agentState;
  };
  switch (event.type) {
    case "runtime_state":
      return { ...next, runtimeState: String(event.payload.state) as RuntimeState };
    case "agent_state":
    case "model_request":
    case "model_response":
      return { ...next, agentState: stateFromEvent() };
    case "user_input": {
      const content = String(event.payload.content ?? "");
      if (!content) return { ...next, agentState: stateFromEvent() };
      const messages = [...next.messages];
      const last = messages[messages.length - 1];
      if (!(last?.role === "user" && last.content === content)) messages.push({ role: "user", content });
      return { ...next, agentState: stateFromEvent(), messages };
    }
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
        agentState: stateFromEvent(),
        messages: [...next.messages, {
          role: "tool",
          content: "执行中…",
          tool: String(event.payload.tool ?? "tool"),
          toolCallId: String(event.payload.tool_call_id ?? ""),
          arguments: event.payload.arguments && typeof event.payload.arguments === "object" && !Array.isArray(event.payload.arguments)
            ? event.payload.arguments as Record<string, unknown>
            : {},
          status: "running"
        }]
      };
    case "tool_finished": {
      const id = String(event.payload.tool_call_id ?? "");
      const messages = next.messages.map((message) =>
        message.toolCallId === id ? {
          ...message,
          content: String(event.payload.output ?? ""),
          status: event.payload.ok === false ? "failed" as const : "completed" as const
        } : message
      );
      return { ...next, agentState: stateFromEvent(), messages };
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
