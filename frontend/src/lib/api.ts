import type { PendingInteraction, UIEvent } from "./protocol";

export interface Project { id: string; path: string; name: string; created_at: string; last_opened_at: string }
export interface Session { session_id: string; project_id: string; title: string; archived: boolean; created_at: string; updated_at: string }
export interface DiffEntry {
  path: string;
  status: string;
  git_status: string;
  staged: boolean;
  unstaged: boolean;
  deleted: boolean;
  task_changed: boolean;
  pre_existing: boolean;
  binary: boolean;
  too_large: boolean;
  size: number;
  staged_patch: string | null;
  unstaged_patch: string | null;
  task_patch?: string | null;
  content?: string | null;
}
export interface DiffSnapshot {
  is_git: boolean;
  head: string | null;
  baseline_captured_at: string;
  entries: DiffEntry[];
}
export interface TracePage {
  items: Array<Record<string, unknown>>;
  next_offset: number;
  has_more: boolean;
  total: number;
}

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) { super(message); this.status = status; }
}

export class GuiApi {
  constructor(readonly baseUrl: string, private readonly fetcher: typeof fetch = fetch) {}

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await this.fetcher.call(globalThis, `${this.baseUrl}${path}`, {
      ...init,
      credentials: "include",
      headers: { "Content-Type": "application/json", ...(init.headers ?? {}) }
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({})) as { detail?: { message?: string; code?: string } };
      throw new ApiError(response.status, detail.detail?.message ?? detail.detail?.code ?? `请求失败（${response.status}）`);
    }
    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
  }

  async exchange(token: string): Promise<void> { await this.request("/api/v1/auth/exchange", { method: "POST", body: JSON.stringify({ token }) }); }
  async bootstrap(): Promise<Record<string, unknown>> { return this.request("/api/v1/bootstrap"); }
  async config(scope = "global"): Promise<Record<string, unknown>> { return this.request(`/api/v1/config?scope=${encodeURIComponent(scope)}`); }
  async updateConfig(scope: string, values: Record<string, unknown>, secrets: Record<string, string> = {}): Promise<Record<string, unknown>> { return this.request("/api/v1/config", { method: "PUT", body: JSON.stringify({ scope, values, secrets }) }); }
  async projects(): Promise<Project[]> { return this.request("/api/v1/projects"); }
  async selectProject(): Promise<Project> { return this.request("/api/v1/projects/select", { method: "POST", body: JSON.stringify({}) }); }
  async addProject(path: string, name?: string): Promise<Project> { return this.request("/api/v1/projects", { method: "POST", body: JSON.stringify({ path, name }) }); }
  async sessions(projectId: string): Promise<Session[]> { return this.request(`/api/v1/projects/${projectId}/sessions`); }
  async createSession(projectId: string, title?: string): Promise<Session> { return this.request(`/api/v1/projects/${projectId}/sessions`, { method: "POST", body: JSON.stringify({ title }) }); }
  async updateSession(sessionId: string, update: { title?: string; archived?: boolean }): Promise<Session> { return this.request(`/api/v1/sessions/${sessionId}`, { method: "PATCH", body: JSON.stringify(update) }); }
  async session(sessionId: string): Promise<{ metadata: Session; snapshot: Record<string, unknown> | null }> { return this.request(`/api/v1/sessions/${sessionId}`); }
  async sendMessage(sessionId: string, text: string): Promise<{ run_id: string; status: string }> { return this.request(`/api/v1/sessions/${sessionId}/messages`, { method: "POST", body: JSON.stringify({ text }) }); }
  async stopRun(runId: string): Promise<{ run_id: string; status: string }> { return this.request(`/api/v1/runs/${runId}/stop`, { method: "POST" }); }
  async diff(sessionId: string): Promise<DiffSnapshot> { return this.request(`/api/v1/sessions/${sessionId}/diff`); }
  async trace(sessionId: string, options: { event?: string; offset?: number; limit?: number; tail?: boolean } = {}): Promise<TracePage> {
    const query = new URLSearchParams();
    if (options.event) query.set("event", options.event);
    if (options.offset !== undefined) query.set("offset", String(options.offset));
    if (options.limit !== undefined) query.set("limit", String(options.limit));
    if (options.tail !== undefined) query.set("tail", String(options.tail));
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return this.request(`/api/v1/sessions/${sessionId}/trace${suffix}`);
  }
}

export function websocketUrl(baseUrl: string, sessionId: string): string {
  const url = new URL(`/api/v1/ws/${encodeURIComponent(sessionId)}`, baseUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export interface EventMessage { type: "event"; event: UIEvent }
export interface InteractionMessage { type: "approval_requested" | "user_request"; interaction: PendingInteraction }
