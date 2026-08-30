import type { PendingInteraction, UIEvent } from "./protocol";

export interface Project { id: string; path: string; name: string; created_at: string; last_opened_at: string }
export interface Session { session_id: string; project_id: string; title: string; archived: boolean; created_at: string; updated_at: string }

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) { super(message); this.status = status; }
}

export class GuiApi {
  constructor(readonly baseUrl: string, private readonly fetcher: typeof fetch = fetch) {}

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await this.fetcher(`${this.baseUrl}${path}`, {
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
  async addProject(path: string, name?: string): Promise<Project> { return this.request("/api/v1/projects", { method: "POST", body: JSON.stringify({ path, name }) }); }
  async sessions(projectId: string): Promise<Session[]> { return this.request(`/api/v1/projects/${projectId}/sessions`); }
  async createSession(projectId: string, title?: string): Promise<Session> { return this.request(`/api/v1/projects/${projectId}/sessions`, { method: "POST", body: JSON.stringify({ title }) }); }
  async updateSession(sessionId: string, update: { title?: string; archived?: boolean }): Promise<Session> { return this.request(`/api/v1/sessions/${sessionId}`, { method: "PATCH", body: JSON.stringify(update) }); }
  async session(sessionId: string): Promise<{ metadata: Session; snapshot: Record<string, unknown> | null }> { return this.request(`/api/v1/sessions/${sessionId}`); }
  async sendMessage(sessionId: string, text: string): Promise<{ run_id: string; status: string }> { return this.request(`/api/v1/sessions/${sessionId}/messages`, { method: "POST", body: JSON.stringify({ text }) }); }
  async stopRun(runId: string): Promise<{ run_id: string; status: string }> { return this.request(`/api/v1/runs/${runId}/stop`, { method: "POST" }); }
  async diff(sessionId: string): Promise<Record<string, unknown>> { return this.request(`/api/v1/sessions/${sessionId}/diff`); }
  async trace(sessionId: string): Promise<Record<string, unknown>> { return this.request(`/api/v1/sessions/${sessionId}/trace`); }
}

export function websocketUrl(baseUrl: string, sessionId: string): string {
  const url = new URL(`/api/v1/ws/${encodeURIComponent(sessionId)}`, baseUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export interface EventMessage { type: "event"; event: UIEvent }
export interface InteractionMessage { type: "approval_requested" | "user_request"; interaction: PendingInteraction }
