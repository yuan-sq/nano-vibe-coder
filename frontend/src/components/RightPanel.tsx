import type { RuntimeView } from "../lib/protocol";
import type { DiffSnapshot, TracePage } from "../lib/api";

type Tab = "plan" | "diff" | "trace";
type RecordValue = Record<string, unknown>;

function asRecord(value: unknown): RecordValue | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as RecordValue
    : null;
}

function Patch({ value }: { value: unknown }) {
  if (typeof value !== "string" || !value) return null;
  return <pre className="diff-patch">{value.split("\n").map((line, index) => {
    const className = line.startsWith("+") && !line.startsWith("+++")
      ? "patch-add"
      : line.startsWith("-") && !line.startsWith("---")
        ? "patch-delete"
        : undefined;
    return <span className={className} key={`${index}-${line}`}>{line || " "}{index < value.split("\n").length - 1 ? "\n" : ""}</span>;
  })}</pre>;
}

function DiffFile({ entry }: { entry: RecordValue }) {
  const path = String(entry.path ?? "unknown");
  const status = String(entry.status ?? "modified");
  const stagedPatch = entry.staged_patch;
  const unstagedPatch = entry.unstaged_patch;
  return <details className="diff-file">
    <summary className="diff-file-summary"><span>{path}</span><small>{status}{entry.pre_existing ? " · 已存在" : ""}{entry.task_changed ? " · 任务变更" : ""}</small></summary>
    <div className="diff-file-details">
      <div className="diff-meta">
        <span>{entry.git_status ? `Git ${String(entry.git_status)}` : "基线变化"}</span>
        <span>{entry.binary ? "二进制" : entry.too_large ? "文件过大" : `${String(entry.size ?? 0)} B`}</span>
      </div>
      {entry.binary || entry.too_large
        ? <div className="muted">正文已隐藏，仅显示元数据</div>
        : <><Patch value={stagedPatch} /><Patch value={unstagedPatch} /></>}
    </div>
  </details>;
}

function TraceEvent({ item }: { item: RecordValue }) {
  const event = String(item.event ?? "event");
  const timestamp = String(item.timestamp ?? "");
  const state = String(item.state ?? "");
  let details = "{}";
  try {
    details = JSON.stringify(item, null, 2);
  } catch {
    details = "无法显示事件详情";
  }
  return <details className="trace-event">
    <summary><time dateTime={timestamp}>{timestamp}</time><strong>{event}</strong>{state && <span>{state}</span>}</summary>
    <pre>{details}</pre>
  </details>;
}

export function RightPanel({ tab, onTab, runtime, diff, trace }: { tab: Tab; onTab: (tab: Tab) => void; runtime: RuntimeView | undefined; diff?: DiffSnapshot; trace?: TracePage }) {
  const entries = Array.isArray(diff?.entries)
    ? diff.entries.map(asRecord).filter((entry): entry is RecordValue => entry !== null)
    : [];
  const traceItems = Array.isArray(trace?.items)
    ? trace.items.map(asRecord).filter((item): item is RecordValue => item !== null)
    : [];
  return <aside className="right-panel">
    <nav className="tabs">{(["plan", "diff", "trace"] as Tab[]).map((item) => <button className={tab === item ? "active" : ""} key={item} onClick={() => onTab(item)}>{item === "plan" ? "Plan" : item === "diff" ? "Diff" : "Trace"}</button>)}</nav>
    {tab === "plan" && <div className="panel-content"><h3>执行计划</h3>{runtime?.plan.length ? runtime.plan.map((todo) => <div className="todo" key={todo.id}><span>{todo.status}</span>{todo.content}</div>) : <div className="muted">暂无计划</div>}</div>}
    {tab === "diff" && <div className="panel-content"><h3>工作树变化</h3>{entries.length ? entries.map((entry) => <DiffFile entry={entry} key={String(entry.path)} />) : <div className="muted">暂无变化</div>}</div>}
    {tab === "trace" && <div className="panel-content"><h3>运行观测</h3><div className="stat">运行状态 <strong>{runtime?.runtimeState ?? "IDLE"}</strong></div><div className="stat">Agent 阶段 <strong>{runtime?.agentState ?? "REQUIREMENTS"}</strong></div><div className="stat">事件序号 <strong>{runtime?.lastSeq ?? 0}</strong></div>{traceItems.length ? <div className="trace-list">{traceItems.map((item, index) => <TraceEvent item={item} key={`${String(item.timestamp ?? "")}-${String(item.event ?? "event")}-${index}`} />)}</div> : <div className="muted">暂无事件</div>}</div>}
  </aside>;
}
