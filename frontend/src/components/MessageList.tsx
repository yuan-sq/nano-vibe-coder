import type { ChatMessage } from "../lib/protocol";

export function MessageList({ messages }: { messages: ChatMessage[] }) {
  return <div className="message-list">
    {messages.length === 0 && <div className="empty-state">发送一个任务开始工作</div>}
    {messages.map((message, index) => <article className={`message ${message.role}`} key={`${message.toolCallId ?? message.role}-${index}`}>
      <div className="message-label">{message.role === "user" ? "你" : message.role === "tool" ? `工具 · ${message.tool}` : "Agent"}</div>
      <pre>{message.content}</pre>
    </article>)}
  </div>;
}

export function ApprovalCard({ interaction, onResolve }: { interaction: { interaction_id: string; content: string; tool_name?: string; capability?: string; reason?: string }; onResolve: (decision: string) => void }) {
  return <section className="approval-card">
    <strong>需要你的确认</strong>
    <p>{interaction.content}</p>
    {interaction.tool_name && <code>{interaction.tool_name} · {interaction.capability}</code>}
    {interaction.reason && <small>{interaction.reason}</small>}
    <div className="actions"><button onClick={() => onResolve("once")}>允许一次</button><button onClick={() => onResolve("session")}>本 Session 允许</button><button className="danger" onClick={() => onResolve("deny")}>拒绝</button></div>
  </section>;
}
