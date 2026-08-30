import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { GuiApi, websocketUrl, type Project, type Session } from "./lib/api";
import { useGuiStore } from "./store";
import { ApprovalCard, MessageList } from "./components/MessageList";
import { RightPanel, ShellPanel } from "./components/RightPanel";
import "./styles.css";

function connectionConfig() {
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  return { apiUrl: params.get("api") || import.meta.env.VITE_API_URL || "http://127.0.0.1:8000", token: params.get("token") };
}

export default function App() {
  const config = useMemo(connectionConfig, []);
  const api = useMemo(() => new GuiApi(config.apiUrl), [config.apiUrl]);
  const queryClient = useQueryClient();
  const [projectId, setProjectId] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [tab, setTab] = useState<"plan" | "diff" | "trace">("plan");
  const { activeSessionId, setActiveSession, runtimes, unreadSessions, ingest, hydrate, setConnected, connected } = useGuiStore();
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api.projects() });
  const sessions = useQuery({ queryKey: ["sessions", projectId], queryFn: () => api.sessions(projectId!), enabled: Boolean(projectId) });
  const diff = useQuery({ queryKey: ["diff", activeSessionId], queryFn: () => api.diff(activeSessionId!), enabled: Boolean(activeSessionId) && tab === "diff", refetchInterval: tab === "diff" ? 1_000 : false });
  const trace = useQuery({ queryKey: ["trace", activeSessionId], queryFn: () => api.trace(activeSessionId!), enabled: Boolean(activeSessionId) && tab === "trace" });
  const runtime = activeSessionId ? runtimes[activeSessionId] : undefined;

  useEffect(() => {
    document.title = unreadSessions.length ? `(${unreadSessions.length}) nano-vibe GUI` : "nano-vibe GUI";
  }, [unreadSessions.length]);

  useEffect(() => {
    if (!config.token) return;
    api.exchange(config.token).then(() => { window.history.replaceState({}, "", window.location.pathname); queryClient.invalidateQueries({ queryKey: ["projects"] }); }).catch(() => undefined);
  }, [api, config.token, queryClient]);

  useEffect(() => {
    const project = projects.data?.[0];
    if (project && !projectId) setProjectId(project.id);
  }, [projects.data, projectId]);

  useEffect(() => {
    if (!activeSessionId) return;
    void api.session(activeSessionId).then((value) => hydrate(activeSessionId, value.snapshot)).catch(() => undefined);
  }, [activeSessionId, api, hydrate]);

  useEffect(() => {
    if (!activeSessionId) return;
    const socket = new WebSocket(websocketUrl(config.apiUrl, activeSessionId));
    socket.onopen = () => { setConnected(true); socket.send(JSON.stringify({ type: "subscribe", last_seq: useGuiStore.getState().runtimes[activeSessionId]?.lastSeq ?? 0 })); };
    socket.onmessage = (message) => { const value = JSON.parse(message.data) as { type: string; event?: Parameters<typeof ingest>[0] }; if (value.type === "event" && value.event) ingest(value.event); };
    socket.onclose = () => setConnected(false);
    return () => { socket.close(); setConnected(false); };
  }, [activeSessionId, config.apiUrl, ingest, setConnected]);

  const chooseSession = (session: Session) => setActiveSession(session.session_id);
  const send = async () => { if (!activeSessionId || !text.trim()) return; await api.sendMessage(activeSessionId, text.trim()); setText(""); };
  const createSession = async () => { if (!projectId) return; const session = await api.createSession(projectId); queryClient.invalidateQueries({ queryKey: ["sessions", projectId] }); chooseSession(session); };
  const addProject = async () => { const path = window.prompt("请输入 Git 仓库路径"); if (!path) return; const project = await api.addProject(path); queryClient.invalidateQueries({ queryKey: ["projects"] }); setProjectId(project.id); };

  return <main className="app-shell">
    <header className="topbar"><div className="brand">nano-vibe <span>V3</span></div><div className={`connection ${connected ? "online" : "offline"}`}>{connected ? "已连接" : "未连接"}</div></header>
    <div className="workbench">
      <aside className="left-panel"><div className="panel-heading"><h2>项目</h2><button onClick={addProject}>＋</button></div>{projects.isError && <div className="error">{(projects.error as Error).message}</div>}{projects.data?.map((project: Project) => <button className={`project-item ${project.id === projectId ? "selected" : ""}`} key={project.id} onClick={() => setProjectId(project.id)}><strong>{project.name}</strong><small>{project.path}</small></button>)}{projectId && <><div className="panel-heading sessions-heading"><h2>Sessions</h2><button onClick={createSession}>＋</button></div>{sessions.data?.map((session) => <button className={`session-item ${session.session_id === activeSessionId ? "selected" : ""}`} key={session.session_id} onClick={() => chooseSession(session)}>{session.title}</button>)}</>}</aside>
      <section className="conversation"><div className="conversation-heading"><div><h1>{activeSessionId ? "工作 Session" : "选择一个 Session"}</h1><small>{runtime?.runtimeState ?? "IDLE"}</small></div>{runtime?.runtimeState === "RUNNING" && runtime.runId && <button className="stop" onClick={() => void api.stopRun(runtime.runId!)}>停止</button>}</div><MessageList messages={runtime?.messages ?? []} />{runtime?.pendingInteraction && <ApprovalCard interaction={runtime.pendingInteraction} onResolve={(decision) => { const socket = new WebSocket(websocketUrl(config.apiUrl, activeSessionId!)); socket.onopen = () => socket.send(JSON.stringify({ type: runtime.pendingInteraction?.kind === "approval" ? "resolve_approval" : "resolve_user_request", interaction_id: runtime.pendingInteraction?.interaction_id, decision })); }} />}</section>
      <RightPanel tab={tab} onTab={setTab} runtime={runtime} diff={diff.data} trace={trace.data} />
    </div>
    <ShellPanel runtime={runtime} />
    <footer className="composer"><textarea value={text} onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void send(); } }} placeholder="描述你要完成的任务…" disabled={!activeSessionId} /><button onClick={() => void send()} disabled={!activeSessionId || !text.trim()}>发送</button></footer>
  </main>;
}
