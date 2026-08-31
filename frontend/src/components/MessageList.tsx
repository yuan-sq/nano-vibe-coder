import { useState } from "react";
import type { ChatMessage } from "../lib/protocol";
import type { PendingInteraction } from "../lib/protocol";

export function MessageList({ messages }: { messages: ChatMessage[] }) {
  return <div className="message-list">
    {messages.length === 0 && <div className="empty-state">发送一个任务开始工作</div>}
    {messages.map((message, index) => <article className={`message ${message.role}`} key={`${message.toolCallId ?? message.role}-${index}`}>
      <div className="message-label">{message.role === "user" ? "你" : message.role === "tool" ? `工具 · ${message.tool}` : "Agent"}</div>
      <pre>{message.content}</pre>
    </article>)}
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
