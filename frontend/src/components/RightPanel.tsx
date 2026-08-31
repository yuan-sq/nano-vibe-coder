import { useState } from "react";
import type { RuntimeView } from "../lib/protocol";

type Tab = "plan" | "diff" | "trace";

export function RightPanel({ tab, onTab, runtime, diff, trace }: { tab: Tab; onTab: (tab: Tab) => void; runtime: RuntimeView | undefined; diff?: Record<string, unknown>; trace?: Record<string, unknown> }) {
  return <aside className="right-panel">
    <nav className="tabs">{(["plan", "diff", "trace"] as Tab[]).map((item) => <button className={tab === item ? "active" : ""} key={item} onClick={() => onTab(item)}>{item === "plan" ? "Plan" : item === "diff" ? "Diff" : "Trace"}</button>)}</nav>
    {tab === "plan" && <div className="panel-content"><h3>执行计划</h3>{runtime?.plan.length ? runtime.plan.map((todo, i) => <div className="todo" key={i}><span>{String(todo.status ?? "pending")}</span>{String(todo.step ?? todo.title ?? "未命名步骤")}</div>) : <div className="muted">暂无计划</div>}</div>}
    {tab === "diff" && <div className="panel-content"><h3>工作树变化</h3>{Array.isArray(diff?.entries) && diff.entries.length ? diff.entries.map((entry, index) => <div className="todo" key={index}><span>{String((entry as Record<string, unknown>).status)}</span>{String((entry as Record<string, unknown>).path)}</div>) : <div className="muted">暂无变化</div>}</div>}
    {tab === "trace" && <div className="panel-content"><h3>运行观测</h3><div className="stat">阶段 <strong>{runtime?.runtimeState ?? "IDLE"}</strong></div><div className="stat">事件序号 <strong>{runtime?.lastSeq ?? 0}</strong></div>{Array.isArray(trace?.items) && trace.items.slice(-8).map((item, index) => <div className="todo" key={index}>{String((item as Record<string, unknown>).event ?? "event")}</div>)}</div>}
  </aside>;
}

export function ShellPanel({ runtime }: { runtime: RuntimeView | undefined }) {
  const [expanded, setExpanded] = useState(true);
  return <section className="shell-panel"><details open={expanded} onToggle={(event) => setExpanded(event.currentTarget.open)}><summary className="shell-title">Shell 输出 <span>只读</span></summary><pre>{runtime?.shell.map((chunk) => `[${chunk.stream}] ${chunk.text}`).join("") || "暂无输出"}</pre></details></section>;
}
