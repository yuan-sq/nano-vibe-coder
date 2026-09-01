import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, GuiApi, websocketUrl, type Project, type Session } from "./lib/api";
import { GuiSocketSession, type SocketCommand } from "./lib/socket";
import { useGuiStore } from "./store";
import { InteractionCard, MessageList } from "./components/MessageList";
import { RightPanel } from "./components/RightPanel";
import { SessionList } from "./components/SessionList";
import "./styles.css";

export function connectionConfig() {
  const hashParams = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const queryParams = new URLSearchParams(window.location.search);
  return {
    apiUrl: hashParams.get("api") || queryParams.get("api") || import.meta.env.VITE_API_URL || "http://127.0.0.1:8000",
    token: hashParams.get("token")
  };
}

function persistConnectionConfig(apiUrl: string) {
  const url = new URL(window.location.href);
  url.hash = "";
  url.searchParams.set("api", apiUrl);
  window.history.replaceState({}, "", `${url.pathname}${url.search}`);
}

export default function App() {
  const config = useMemo(connectionConfig, []);
  const api = useMemo(() => new GuiApi(config.apiUrl), [config.apiUrl]);
  const queryClient = useQueryClient();
  const [projectId, setProjectId] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"plan" | "diff" | "trace">("plan");
  const [sending, setSending] = useState(false);
  const sendingRef = useRef(false);
  const socketRef = useRef<GuiSocketSession | null>(null);
  const { activeSessionId, setActiveSession, runtimes, unreadSessions, ingest, hydrate, setLastSeq, setConnected } = useGuiStore();
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api.projects() });
  const sessions = useQuery({ queryKey: ["sessions", projectId], queryFn: () => api.sessions(projectId!), enabled: Boolean(projectId) });
  const diff = useQuery({ queryKey: ["diff", activeSessionId], queryFn: () => api.diff(activeSessionId!), enabled: Boolean(activeSessionId) && tab === "diff", refetchInterval: tab === "diff" ? 1_000 : false });
  const trace = useQuery({ queryKey: ["trace", activeSessionId], queryFn: () => api.trace(activeSessionId!, { tail: true }), enabled: Boolean(activeSessionId) && tab === "trace", refetchInterval: tab === "trace" ? 2_000 : false });
  const runtime = activeSessionId ? runtimes[activeSessionId] : undefined;

  useEffect(() => {
    document.title = unreadSessions.length ? `(${unreadSessions.length}) nano-vibe-coder` : "nano-vibe-coder";
  }, [unreadSessions.length]);

  useEffect(() => {
    if (!config.token) return;
    api.exchange(config.token).then(() => { persistConnectionConfig(config.apiUrl); queryClient.invalidateQueries({ queryKey: ["projects"] }); }).catch(() => undefined);
  }, [api, config.token, queryClient]);

  useEffect(() => {
    const project = projects.data?.[0];
    if (project && !projectId) setProjectId(project.id);
  }, [projects.data, projectId]);

  useEffect(() => {
    if (!activeSessionId) return;
    let disposed = false;
    let resyncing = false;
    const resyncSession = () => {
      void api.session(activeSessionId).then((value) => {
        if (disposed) return;
        hydrate(activeSessionId, value.snapshot, "resync");
        setError(null);
      }).catch(() => {
        if (!disposed) setError("同步 Session 状态失败，请稍后重试");
      });
    };
    const socket = new GuiSocketSession({
      url: websocketUrl(config.apiUrl, activeSessionId),
      getLastSeq: () => useGuiStore.getState().runtimes[activeSessionId]?.lastSeq ?? 0,
      onEvent: (event) => {
        ingest(event);
        if (event.type === "diff_updated") {
          void queryClient.invalidateQueries({ queryKey: ["diff", activeSessionId] });
        }
      },
      onResync: (latestSeq) => {
        if (disposed || resyncing) return;
        resyncing = true;
        socket.stop();
        void api.session(activeSessionId).then((value) => {
          if (disposed) return;
          hydrate(activeSessionId, value.snapshot, "resync");
          setLastSeq(activeSessionId, latestSeq);
          setError(null);
        }).catch(() => {
          if (!disposed) setError("同步 Session 状态失败，请稍后重试");
        }).finally(() => {
          resyncing = false;
          if (!disposed) socket.start();
        });
      },
      onCommandResult: (result) => {
        if (result.type === "interaction_result" && result.ok === false) {
          resyncSession();
        } else if (result.type === "error") {
          setError(String(result.message ?? result.code ?? "实时命令失败"));
        }
      },
      onStatus: setConnected
    });
    socketRef.current = socket;
    void api.session(activeSessionId).then((value) => {
      if (!disposed) {
        hydrate(activeSessionId, value.snapshot);
        socket.start();
      }
    }).catch(() => {
      if (!disposed) {
        setError("加载 Session 状态失败，实时连接仍将继续尝试");
        socket.start();
      }
    });
    return () => {
      disposed = true;
      socket.stop();
      if (socketRef.current === socket) socketRef.current = null;
    };
  }, [activeSessionId, api, config.apiUrl, hydrate, ingest, queryClient, setConnected, setLastSeq]);

  const chooseSession = (session: Session) => setActiveSession(session.session_id);
  const sendSocketCommand = (command: SocketCommand) => socketRef.current?.send(command);
  const resolveInteraction = (decision: string) => {
    const interaction = runtime?.pendingInteraction;
    if (!interaction) return;
    setError(null);
    sendSocketCommand({
      type: interaction.kind === "approval" ? "resolve_approval" : "resolve_user_request",
      interaction_id: interaction.interaction_id,
      decision
    });
  };
  const send = async () => {
    const trimmed = text.trim();
    if (!activeSessionId || !trimmed || sendingRef.current) return;
    setError(null);
    if (runtime?.pendingInteraction?.kind === "user_request") {
      resolveInteraction(trimmed);
      setText("");
      return;
    }
    if (runtime?.pendingInteraction) return;
    if (runtime?.runtimeState === "RUNNING" || runtime?.runtimeState === "STOPPING") return;
    sendingRef.current = true;
    setSending(true);
    try {
      await api.sendMessage(activeSessionId, trimmed);
      setText("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "发送失败");
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
  };
  const createSession = async () => { if (!projectId) return; const session = await api.createSession(projectId); queryClient.invalidateQueries({ queryKey: ["sessions", projectId] }); chooseSession(session); };
  const addProject = async () => {
    try {
      const project = await api.selectProject();
      await queryClient.invalidateQueries({ queryKey: ["projects"] });
      setProjectId(project.id);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409 && cause.message === "project_selection_cancelled") return;
      setError(cause instanceof Error ? cause.message : "添加项目失败");
    }
  };
  const renameSession = async (sessionId: string, title: string) => {
    if (!projectId) return;
    const updated = await api.updateSession(sessionId, { title });
    queryClient.setQueryData<Session[]>(["sessions", projectId], (current) =>
      current?.map((session) => session.session_id === updated.session_id ? updated : session)
    );
  };

  return <main className="app-shell">
    <header className="topbar"><div className="brand">nano-vibe-coder</div></header>
    <div className="workbench">
      <aside className="left-panel"><div className="panel-heading"><h2>项目</h2><button onClick={() => void addProject()}>＋</button></div>{projects.isError && <div className="error">{(projects.error as Error).message}</div>}{projects.data?.map((project: Project) => <button className={`project-item ${project.id === projectId ? "selected" : ""}`} key={project.id} onClick={() => setProjectId(project.id)}><strong>{project.name}</strong><small>{project.path}</small></button>)}{projectId && <><div className="panel-heading sessions-heading"><h2>Sessions</h2><button onClick={() => void createSession()}>＋</button></div><SessionList sessions={sessions.data ?? []} activeSessionId={activeSessionId} onSelect={chooseSession} onRename={renameSession} onError={setError} /></>}</aside>
      <section className="center-panel"><section className="conversation"><div className="conversation-heading"><div><h1>{activeSessionId ? "工作 Session" : "选择一个 Session"}</h1><small>{runtime?.runtimeState ?? "IDLE"} · Agent {runtime?.agentState ?? "REQUIREMENTS"}</small></div>{runtime?.runtimeState === "RUNNING" && runtime.runId && <button className="stop" onClick={() => void api.stopRun(runtime.runId!)}>停止</button>}</div>{error && <div className="error">{error}</div>}<MessageList messages={runtime?.messages ?? []} />{runtime?.pendingInteraction && <InteractionCard interaction={runtime.pendingInteraction} onResolve={resolveInteraction} />}</section><footer className="composer"><textarea value={text} onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void send(); } }} placeholder="描述你要完成的任务…" disabled={!activeSessionId} /><button onClick={() => void send()} disabled={!activeSessionId || !text.trim() || sending || runtime?.runtimeState === "RUNNING" || runtime?.runtimeState === "STOPPING"}>发送</button></footer></section>
      <RightPanel tab={tab} onTab={setTab} runtime={runtime} diff={diff.data} trace={trace.data} />
    </div>
  </main>;
}
