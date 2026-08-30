# Nano Vibe Coder V3 GUI 设计

## 目标

V3 将本地浏览器 GUI 作为主要入口，同时保留 CLI，并继续复用 V2 的
Session、AgentLoop、Plan、State、Permission、Tool 和 Snapshot。GUI 不依赖
Chainlit 后端或 Socket.IO；只选择性移植 Chainlit 的 Message、Step、TaskList
和 Markdown 展示模式，并保留 Apache-2.0 第三方声明。

## 架构边界

浏览器运行独立 React/npm 应用，FastAPI/Uvicorn 提供 REST 与原生 WebSocket。
`nano-vibe gui` 在本机启动两个子进程：FastAPI 负责领域运行时，Node 服务负责
前端构建产物。服务只绑定 `127.0.0.1`，使用随机启动令牌兑换 HttpOnly 会话
Cookie，并验证 Host/Origin。V3 不支持远程访问、移动端、Electron/Tauri 或
Chainlit 运行时集成。

FastAPI 维护项目注册、Session GUI 元数据、配置和运行协调；V2 的 JSON
SessionSnapshot 仍是 Session 事实来源，Trace 仍写入 JSONL。应用级 SQLite
数据库位于平台用户数据目录，密钥位于权限为 `0600` 的应用 `.env`，API 只返回
脱敏状态。

## 运行模型

同一时间全局只允许一个 Agent 任务，GUI 和 CLI 共用跨进程运行锁；竞争请求返回
409，不排队。浏览器关闭不会停止后台任务。RuntimeState 与 AgentState 分离，
包含 `IDLE`、`RUNNING`、`AWAITING_APPROVAL`、`AWAITING_INPUT`、`STOPPING`、
`PAUSED` 和 `ERROR`。安全停止先拒绝新模型/工具调用，Shell 进程组发送 TERM，
等待 3 秒后 KILL，并保存 PAUSED 快照。

审批和用户问题都持久化 `PendingInteraction`（ID、类型、内容、工具调用、
恢复信息和幂等键）。断线或服务重启后原样重现，不自动授权、不重复执行。配置
保存后从同一 Session 的下一次用户输入开始生效，运行中的任务保留其不可变配置。

## 事件协议

服务端事件使用 `{version, session_id, run_id, seq, type, timestamp, payload}`
信封；每个 Session 的 `seq` 单调递增。事件类型包括模型增量、工具开始/结束、
审批、用户问题、Plan、Agent 阶段、Shell chunk、Diff、Trace、运行结束和错误。
客户端命令包括 `subscribe(last_seq)`、审批/用户问题回复和停止任务。

事件只在内存中保留，容量上限取 5,000 条或 10 MiB 先到者；落后客户端收到
`resync_required` 后重新获取 Snapshot、Diff 和 Trace。服务重启不恢复历史 token
或 Shell chunk，但完整消息、工具结果和待处理交互从 Snapshot 恢复。

## 项目、Diff 与 Shell

项目通过只读目录浏览器添加，浏览范围限定为用户主目录，且只允许现有 Git 仓库。
移除项目只移除注册项，不删除文件；Session 只能重命名或归档。

任务开始记录 HEAD、Git 状态、文件摘要和初始脏文件集合。Diff 展示 staged、
unstaged、untracked 文本文件；二进制或大文件只展示元数据，并标记任务前已有
修改与本任务期间变化。Diff 不提供编辑、回滚、暂存或提交。

Shell 改为异步进程执行，实时发送 stdout/stderr chunk，GUI 不提供 PTY 或 stdin。
Shell 结果保持有界，避免大输出撑爆 Snapshot。写工具结束后立即刷新 Diff，运行
期间按秒限流刷新。

## 前端工作台

`frontend/` 为独立 npm 项目，使用 React 18、TypeScript、Vite、TanStack Query、
Zustand、Tailwind 和 Radix/shadcn。左栏显示项目/Session，中栏显示消息与工具
步骤，右栏提供 Plan/Diff/Trace，底部为折叠 Shell 面板。只支持中文浅色桌面布局
（宽度至少 1024px）。浏览器后台等待时只更新页签标题和未读标记，不申请系统通知。

前端复制的 Chainlit 展示组件必须转换为 nano-vibe 自有类型，并在
`THIRD_PARTY_NOTICES.md` 中记录版本、来源文件和修改内容；不得引入 Chainlit
状态、数据层或客户端协议。

## 验证策略

后端覆盖 REST schema/错误、认证、路径安全、全局锁、WebSocket seq/回放、断线与
重启恢复、Shell 取消、Diff baseline、Trace 和配置生效边界。前端使用 Vitest 与
React Testing Library 测试事件归并、审批、未读和 resync，使用 Playwright 以假模型
和假工具验证完整工作流。每个逻辑单元先有失败测试，再实现最小行为并复跑全套
Python、Ruff、Pyright、npm test 和 build。

