# nano-vibe-coder V2 实施计划

> **For agentic workers:** 按任务逐项执行；每个逻辑单元遵循 RED → GREEN → REFACTOR，完成后运行针对性测试并检查 diff。V2 不引入 Goal 系统、OS 级沙箱、评测框架、TUI/GUI、演示，也不实现 Tavily Crawl/Map/Research。

**目标：** 在现有 REQUIREMENTS → PLAN → IMPLEMENT → VERIFY → DONE Coding Agent 闭环上，加入策略审批权限、多模型静态路由与 fallback、可恢复 JSON 会话、幂等工具、结构化 Plan Todo、Codex `SKILL.md` 技能生命周期、Tavily Search/Extract 和可脚本化 CLI 管理命令。

**架构：** 保留现有轻量 Python AgentLoop/ToolRegistry；把权限判定、模型路由、计划 Todo、会话快照和 Skill 管理实现为可单测的领域模块。normal/full-access 只改变策略审批结果，不尝试创建 OS 沙箱；状态与工具定义在每轮请求前静态计算，模型调用失败按配置的 fallback 链切换。会话快照使用 JSON 文件保存，并通过显式 `--resume SESSION_ID` 恢复，工具调用携带幂等 key 后由 Session/Registry 去重。

**技术栈：** Python 3.10+、Typer、Rich、OpenAI-compatible SDK、TOML、JSON、pytest/pytest-asyncio、可选 `tavily-python`；live Tavily 测试仅在显式环境变量开启时运行。

---

## Task 1：V2 计划与配置模型

**Files:**
- Modify: `src/nano_vibe/config.py`
- Modify: `config.example.toml`
- Modify: `pyproject.toml`
- Test: `tests/unit/test_config.py`

- [x] 为 `RuntimeConfig` 增加 `permission_mode`（`normal`/`full-access`）、会话目录、fallback/快照配置；为模型配置增加静态状态路由字段和 fallback 名称，并保持旧配置可加载。
- [x] 先写配置解析、非法权限模式、未知路由模型和密钥不泄露的失败测试，确认失败后实现最小解析。
- [x] 增加 Tavily 依赖为可选/运行时友好配置，示例配置展示 `models`、`state_models`、`fallback_models`、`[tavily] env_file` 等无密钥字段。
- [x] 运行 `PYTHONPATH=src python3 -m pytest tests/unit/test_config.py -q`、Ruff/Pyright 并检查 diff。

## Task 2：统一结构化 ToolError 与权限策略

**Files:**
- Modify: `src/nano_vibe/tools/base.py`
- Create: `src/nano_vibe/permissions.py`
- Modify: `src/nano_vibe/tools/registry.py`
- Modify: `src/nano_vibe/tools/shell.py`
- Test: `tests/unit/test_permissions.py`, `tests/unit/test_tool_registry.py`, `tests/unit/test_shell_tool.py`

- [x] 定义可序列化 `ToolError(code, message, details, retryable)` 和 `ToolResult(ok, output, error, metadata)`，保留现有 `success/failure` 调用兼容性；所有工具失败统一填充 `ToolError`，不把 Python 异常字符串当唯一协议。
- [x] 实现 `PermissionMode` 与策略审批器：normal 对写文件、shell、网络等策略项逐次调用审批回调，full-access 自动放行；审批是应用策略，不使用 OS 沙箱。测试拒绝、允许、未知策略和结构化错误。
- [x] Registry 在执行前校验工具权限与幂等 key；重复 key 返回首个结果且不再次执行，工具异常转为结构化错误。
- [x] 运行针对性工具测试并确保全部旧工具测试通过。

## Task 3：按状态静态模型路由与 fallback

**Files:**
- Create: `src/nano_vibe/models/router.py`
- Modify: `src/nano_vibe/models/base.py`
- Modify: `src/nano_vibe/session.py`
- Modify: `src/nano_vibe/agent/loop.py`
- Test: `tests/unit/test_model_router.py`, `tests/unit/test_agent_loop.py`

- [x] 先写测试：REQUIREMENTS/PLAN/IMPLEMENT/VERIFY/DONE 各自从静态映射选模型；未配置状态回退到 active；模型请求异常按 fallback 链尝试并报告最终结构化错误；同一轮不动态按模型输出切换状态路由。
- [x] 实现 `ModelRouter`，按 `AgentState` 解析主模型与去重 fallback 链；为每个 `Model` 保留名称/描述，路由接口可被 AgentLoop 注入。
- [x] AgentLoop 每轮请求取当前状态对应模型；上下文压缩沿用当前路由；trace 记录尝试的模型和 fallback 原因。
- [x] Session.from_config 构造所有配置模型，旧 `Session(model, ...)` API 继续可用。

## Task 4：结构化 Plan Todo 与 DONE 门槛

**Files:**
- Create: `src/nano_vibe/agent/plan.py`
- Modify: `src/nano_vibe/agent/state.py`
- Create: `src/nano_vibe/tools/update_plan.py`
- Modify: `src/nano_vibe/session.py`
- Modify: `src/nano_vibe/agent/loop.py`
- Test: `tests/unit/test_plan.py`, `tests/unit/test_state.py`, `tests/integration/test_agent_loop.py`

- [x] 定义 Todo 项 `{id, content, status}`，状态严格为 `pending/in_progress/completed`；`update_plan` 支持完整替换/增量更新，拒绝重复 id、空内容、非法状态和多个 `in_progress`。
- [x] 状态机持有 PlanTodoList；PLAN 阶段允许 `update_plan`，VERIFY → DONE 前要求计划非空且所有项 completed，工具错误不得绕过门槛。
- [x] 加入测试覆盖计划更新、最多一个进行中、回退后恢复、DONE 拒绝未完成计划；更新后的计划进入上下文和 trace。
- [x] 将 `update_plan` 纳入 PLAN/IMPLEMENT/VERIFY 合适权限，检查旧闭环测试需补齐计划后仍能通过。

## Task 5：JSON 会话快照与显式恢复

**Files:**
- Create: `src/nano_vibe/session_store.py`
- Modify: `src/nano_vibe/session.py`
- Modify: `src/nano_vibe/agent/loop.py`
- Modify: `src/nano_vibe/cli.py`
- Test: `tests/unit/test_session_store.py`, `tests/unit/test_session.py`, `tests/integration/test_session_resume.py`

- [x] 定义 JSON 快照 schema：version、session_id、workspace、permission_mode、state、plan、history、summary、turn/error counters、updated_at；快照写入临时文件后原子替换并避免 API key。
- [x] 每个用户输入、工具结果、状态/计划变化后保存快照；`Session.resume` 显式读取指定 session id，校验 workspace 和 schema，禁止自动猜测或静默恢复。
- [x] CLI 增加 `--resume SESSION_ID`，`/sessions` 列出快照元数据；恢复后的 AgentLoop 能继续执行且幂等缓存一并恢复。
- [x] 覆盖损坏 JSON、未知版本、跨 workspace、权限模式不一致和正常恢复测试。

## Task 6：工具幂等与状态持久化

**Files:**
- Modify: `src/nano_vibe/tools/base.py`
- Modify: `src/nano_vibe/tools/registry.py`
- Modify: `src/nano_vibe/agent/loop.py`
- Modify: `src/nano_vibe/session_store.py`
- Test: `tests/unit/test_tool_idempotency.py`, `tests/unit/test_agent_loop.py`

- [x] 工具调用协议支持 `idempotency_key`（模型参数或调用 id fallback），Registry 缓存成功和失败结果的 JSON 表示；同 key/同工具/同参数重放不执行副作用，冲突参数返回结构化错误。
- [x] 快照保存幂等记录并在恢复时重建，确保 apply_patch/shell 等副作用工具在模型重试时最多执行一次。
- [x] 测试同一 Session 重复调用、恢复后重复调用、参数冲突和无 key 的兼容行为。

## Task 7：Codex SKILL.md load/read/unload

**Files:**
- Create: `src/nano_vibe/skills.py`
- Create: `src/nano_vibe/tools/skills.py`
- Modify: `src/nano_vibe/agent/context.py`
- Modify: `src/nano_vibe/session.py`
- Test: `tests/unit/test_skills.py`, `tests/unit/test_skill_tools.py`, `tests/unit/test_context.py`

- [x] 实现从 workspace 及配置 skill roots 发现兼容 Codex `SKILL.md` 的目录；解析 front matter/name/description，限制路径在允许根目录内。
- [x] 实现 `load_skill(name)`, `read_skill(name, path)`, `unload_skill(name)` 的生命周期和缓存；read 只读技能包内文件，不执行 skill 内容；工具返回结构化结果和路径。
- [x] 将已加载技能说明/正文摘要注入 context，快照保存已加载技能；实现名称不存在、越界读取、重复加载/卸载测试。

## Task 8：Tavily Search + Extract

**Files:**
- Modify: `src/nano_vibe/tools/web_search.py`
- Create: `src/nano_vibe/tools/web_extract.py`
- Modify: `src/nano_vibe/session.py`
- Modify: `src/nano_vibe/config.py`
- Test: `tests/unit/test_tavily_tools.py`, `tests/integration/test_tavily_live.py`

- [x] 运行时显式读取配置指定 `env_file`（默认 `.env` 可配置），仅从该文件/环境中读取 `TAVILY_API_KEY`，不自动扫描任意 dotenv；无 key 时返回结构化配置错误。
- [x] 使用 `AsyncTavilyClient` 实现 `web_search(query, search_depth="basic", max_results=5)`；Extract 最多 5 个 URL、总输出最多 30,000 字符，保留来源和截断元数据。
- [x] 单测使用可注入 fake client 覆盖参数、错误、数量/字符限制；live 测试默认 skip，只有显式 `NANO_VIBE_LIVE_TAVILY=1` 且存在 key 时运行，严禁在默认离线测试中联网。
- [x] 移除 v1 placeholder 测试并更新状态工具权限说明。

## Task 9：CLI 管理命令与权限交互

**Files:**
- Modify: `src/nano_vibe/cli.py`
- Modify: `src/nano_vibe/ui/console.py`
- Modify: `src/nano_vibe/session.py`
- Modify: `src/nano_vibe/__main__.py`
- Test: `tests/unit/test_cli.py`, `tests/unit/test_module_entrypoint.py`

- [x] 增加 `/plan` 展示结构化 Todo、`/permissions` 展示当前模式/策略、`/skills` 展示已加载技能、`/sessions` 列出快照；保持 `/help`、`/state`、`/quit`。
- [x] 增加启动参数 `--resume SESSION_ID` 与 `--full-access`；full-access 仅设置策略模式并在 UI 明确显示，不绕过工具合法性、状态机或 DONE 门槛。
- [x] Typer 命令测试使用 CliRunner/注入 UI，覆盖 flags 组合、未知 session、命令输出和正常离线启动。

## Task 10：提示词、文档与最终验证

**Files:**
- Modify: `src/nano_vibe/prompts/system.md`
- Modify: `src/nano_vibe/prompts/stages.md`
- Modify: `README.md`
- Modify: `config.example.toml`
- Modify: `AGENTS.md`
- Test: `tests/integration/test_agent_loop.py`, `tests/integration/test_offline_v2.py`

- [x] 更新提示词明确权限策略、静态模型路由、Todo 完成门槛、Skill 只读边界和 Tavily 限制；移除 v1 “web search 未实现”描述。
- [x] README/config/AGENTS 记录安装、离线测试、opt-in live 测试、`--resume`/`--full-access` 和四个 REPL 命令；明确不支持 Goal、OS 沙箱、评测、TUI/GUI、Tavily Crawl/Map/Research。
- [x] 增加 FakeModel 驱动的全闭环离线集成测试：计划 → 实现 → 验证 → 完成；包含权限拒绝、fallback、快照恢复和幂等重放。
- [x] 运行 `PYTHONPATH=src python3 -m pytest -q`、`uv run ruff check src tests`、`uv run pyright`；检查 `git diff --check`、完整 diff、密钥扫描，然后用中文 commit 信息提交。

## 验收清单

- [x] 双权限模式仅由应用策略审批实现，无 OS 级沙箱。
- [x] 状态静态路由和 fallback 可配置、可测试、可追踪。
- [x] JSON 快照需显式 `--resume`，工具副作用具备幂等保障。
- [x] Plan Todo 严格三态且最多一个进行中，VERIFY → DONE 前全部完成。
- [x] `SKILL.md` load/read/unload 可用且路径安全。
- [x] Tavily 通过 `AsyncTavilyClient`，Search basic/5，Extract ≤5 URL/30k 字符；live 测试 opt-in。
- [x] 所有工具错误均为结构化 `ToolError`。
- [x] CLI 命令和 flags、文档、离线/opt-in live 测试齐全。
