import { useState } from "react";
import type { ChatMessage } from "../lib/protocol";
import type { PendingInteraction } from "../lib/protocol";
import { MarkdownContent } from "./MarkdownContent";

function formatToolArguments(argumentsValue: Record<string, unknown> | undefined): string {
  if (!argumentsValue || Object.keys(argumentsValue).length === 0) return "";
  const entries = Object.entries(argumentsValue).map(([key, value]) => {
    if (key === "command" && typeof value === "string") return value;
    if (typeof value === "string") return `${key}=${value}`;
    try {
      return `${key}=${JSON.stringify(value)}`;
    } catch {
      return `${key}=${String(value)}`;
    }
  });
  const text = entries.join(" ").replace(/\s+/g, " ").trim();
  return text.length > 180 ? `${text.slice(0, 177)}…` : text;
}

function toolSummary(message: ChatMessage): string {
  const status = message.status === "running" ? "运行中" : message.status === "failed" ? "运行失败" : "已运行";
  const tool = message.tool ?? "tool";
  const argumentsText = formatToolArguments(message.arguments);
  return `${status} ${tool}${argumentsText ? ` ${argumentsText}` : ""}`;
}

function ToolMessage({ message }: { message: ChatMessage }) {
  const [expanded, setExpanded] = useState(false);
  return <details className="message tool" open={expanded} onToggle={(event) => setExpanded(event.currentTarget.open)}>
    <summary className="message-label">{toolSummary(message)}</summary>
    <div className="tool-details">
      {message.arguments && Object.keys(message.arguments).length > 0 && <pre className="tool-arguments">参数：{JSON.stringify(message.arguments, null, 2)}</pre>}
      <pre className="tool-output">{message.content}</pre>
    </div>
  </details>;
}

export function MessageList({ messages }: { messages: ChatMessage[] }) {
  const visibleMessages = messages.filter((message) => message.role !== "assistant" || message.content.trim());
  return <div className="message-list">
    {visibleMessages.length === 0 && <div className="empty-state">发送一个任务开始工作</div>}
    {visibleMessages.map((message, index) => {
      const key = `${message.toolCallId ?? message.role}-${index}`;
      if (message.role === "tool") {
        return <ToolMessage key={key} message={message} />;
      }
      return <article className={`message ${message.role}`} key={key}>
        <div className="message-label">{message.role === "user" ? "你" : "Agent"}</div>
        <MarkdownContent content={message.content} />
      </article>;
    })}
  </div>;
}

export function InteractionCard({ interaction, onResolve }: { interaction: PendingInteraction; onResolve: (decision: string) => void }) {
  const [answer, setAnswer] = useState("");
  if (interaction.kind === "user_request") {
    const submit = () => {
      const value = answer.trim();
      if (value) {
        onResolve(value);
        setAnswer("");
      }
    };
    return <section className="approval-card user-request-card">
      <strong>需要你的回答</strong>
      <p>{interaction.content}</p>
      {interaction.options && interaction.options.length > 0 && <div className="actions">{interaction.options.map((option) => <button key={option} onClick={() => onResolve(option)}>{option}</button>)}</div>}
      <div className="answer-row"><input value={answer} onChange={(event) => setAnswer(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") submit(); }} placeholder="输入你的回答" /><button onClick={submit} disabled={!answer.trim()}>提交回答</button></div>
    </section>;
  }
  return <section className="approval-card">
    <strong>需要你的确认</strong>
    <p>{interaction.content}</p>
    {interaction.tool_name && <code>{interaction.tool_name} · {interaction.capability}</code>}
    {interaction.reason && <small>{interaction.reason}</small>}
    <div className="actions"><button onClick={() => onResolve("once")}>允许一次</button><button onClick={() => onResolve("session")}>本 Session 允许</button><button className="danger" onClick={() => onResolve("deny")}>拒绝</button></div>
  </section>;
}
