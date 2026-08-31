# V3 Session 权限与观测面板设计

## 目标

修复 GUI 中“本 Session 允许”未持久生效的问题，并把右栏的 Plan、Diff、Trace
从占位展示升级为以领域状态为事实来源的可用观测面板。同时删除独立的底部
“Shell 输出”区域，Shell 命令与结果继续通过消息流中的工具卡展示。

## Session 恢复与权限

GUI 每次处理用户消息时必须优先从既有 `SessionSnapshot` 恢复 Session；只有快照
不存在时才创建新状态。恢复完成后再把运行状态切换为 `RUNNING`，不得用空 Session
覆盖已有历史、Plan、状态、幂等记录或授权。

审批回调使用明确的 `once`、`session`、`deny` 决策。为兼容 CLI 与既有集成，布尔
`True` 解释为 `once`，`False` 解释为 `deny`。`PermissionPolicy` 按具体工具名保存
Session grant；`session` 既放行当前调用，也使同一 Session 的后续同名工具调用无需
再次审批。授权工具名写入 `SessionSnapshot`，因此可以跨消息、浏览器重连和服务重启
恢复。授权不会扩大到同一 permission scope 下的其他工具。

## Plan

`StateMachine.plan` 和 `SessionSnapshot.plan` 仍是事实来源。`update_plan` 成功执行后，
AgentLoop 额外发送 `plan_updated` 事件：

```json
{
  "plan": [
    {"id": "inspect", "content": "检查相关代码", "status": "in_progress"}
  ],
  "state": "PLAN"
}
```

失败的 `update_plan` 不发送该事件。前端使用正式 `PlanItem` 类型，按 `id` 渲染
`content` 和三态状态。WebSocket 提供实时更新，Snapshot 提供初次加载与 resync。

## Diff

每个 GUI Session 第一次运行前捕获 Git baseline，并原子持久化到：

```text
<workspace>/.nano-vibe/gui/<session_id>/diff-baseline.json
```

baseline 记录 HEAD、捕获时间、初始 porcelain 状态和工作树文件摘要。后续请求必须
复用该 baseline，不能每次 GET 临时重建。Diff API 返回 staged、unstaged、untracked、
删除、二进制和大文件元数据；文本文件附带真实 unified patch，并用 baseline 区分
`pre_existing` 与 `task_changed`。二进制和超过限制的文件不返回正文。

写工具成功结束后发送轻量 `diff_updated` 事件，前端据此重新获取 Diff；Diff 页激活时
保留低频轮询作为断线兜底。前端文件项默认收起，展开后显示 staged/unstaged patch，
新增与删除行采用不同样式。Diff 只读，不提供编辑、暂存或回滚。

## Trace

TraceWriter 和 GUI API 共同使用唯一的路径函数：

```text
<workspace>/.nano-vibe/traces/<session_id>.jsonl
```

API 精确读取指定 Session，不扫描目录猜测最新文件。读取支持 `event`、`offset`、
`limit`，限制最大页大小，逐行处理并忽略损坏的尾行。响应包含 `items`、
`next_offset`、`has_more` 和 `total`。现有敏感字段脱敏规则继续生效。

前端 Trace 页展示时间、事件名、Agent 阶段和可展开的脱敏 JSON 字段；页面激活时
轮询更新。Trace 只展示运行事件和工具元数据，不展示或推断模型隐藏思维链。

## Shell 模块删除

删除 `ShellPanel`、独立 shell 前端状态、相关 CSS 和测试。保留工具卡：

- `tool_started.arguments.command` 用于摘要和参数展示；
- `tool_finished.output` 与 Snapshot tool history 用于最终输出；
- 后端 Shell 工具与流式执行设施不因本次前端删除而移除。

## 验证边界

后端测试覆盖审批决策、跨消息/重启授权恢复、Session 恢复、Plan 事件、Diff baseline
与 patch、Trace 精确路径和分页。前端测试覆盖 Plan 字段渲染、Diff 展开内容、Trace
事件详情、Session 决策发送和 Shell 面板移除。最终运行完整 Python、Ruff、Pyright、
Vitest、前端构建与 `git diff --check`。
