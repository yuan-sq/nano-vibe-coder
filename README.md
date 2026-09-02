# nano-vibe-coder

> 从模糊的需求到可靠的软件。

nano-vibe-coder 是一个面向本地 Git 仓库的 Coding Agent。它不依赖 Agent 框架，模型调用循环、工具调度、上下文管理、会话恢复、权限审批和 GUI 事件协议都由项目自行实现。

公开仓库：[github.com/yuan-sq/nano-vibe-coder](https://github.com/yuan-sq/nano-vibe-coder)

## 为什么要做这个项目

代码生成并不是软件开发的全部。很多失败发生在写代码之前和之后：Agent 没有理解用户真正想要什么，或者代码看起来已经完成，却没有经过可靠的验证。

nano-vibe-coder 把一次编码任务建模为有限状态机：

```text
REQUIREMENTS → PLAN → IMPLEMENT → VERIFY → DONE
     需求分析      计划       实现        验证      完成
```

REQUIREMENTS 和 VERIFY 是两个独立阶段。前者要求 Agent 先阅读仓库、识别约束并澄清需求；后者要求它运行检查，失败时返回 PLAN 或 IMPLEMENT 修正。这个设计把“先想清楚”和“确认真的可用”写进运行流程，而不是只靠模型临场记住。

## 核心设计

### 五阶段状态机

| 阶段 | Agent 要做什么 | 主要约束 |
| --- | --- | --- |
| `REQUIREMENTS` | 检查仓库，理解请求，必要时向用户提问 | 不创建、修改或删除文件 |
| `PLAN` | 给出可执行计划，并用 `update_plan` 建立结构化 Todo | 不修改文件；先建立计划，再进入实现 |
| `IMPLEMENT` | 按 Todo 修改代码，并及时同步计划状态 | 文件写入工具只在此阶段开放 |
| `VERIFY` | 运行检查，处理失败，审查 `AGENTS.md` | 验证失败时返回计划或实现阶段 |
| `DONE` | 结束当前任务 | Plan 必须全部完成，且 `AGENTS.md` 已审查 |

状态转换不是一条只能向前的直线。IMPLEMENT 可以退回 PLAN；VERIFY 可以回到 PLAN 或 IMPLEMENT。只有 VERIFY 能进入 DONE。

Plan Todo 只接受 `pending`、`in_progress`、`completed` 三种状态，同时最多有一个条目处于 `in_progress`。空计划或存在未完成条目时，状态机拒绝进入 DONE。

### 与常见 Coding Agent 的设计差异

| 常见的规划与编码循环 | nano-vibe-coder |
| --- | --- |
| 需求理解通常混在首次模型回复中 | REQUIREMENTS 是独立阶段，先检查仓库再决定怎么做 |
| 测试常作为编码后的一个可选动作 | VERIFY 是独立阶段，失败后必须回到前序阶段处理 |
| 工具主要由模型自行选择 | 状态机为每个阶段提供不同的工具白名单 |
| 过程信息散落在对话里 | Plan、Diff、Trace 和 SessionSnapshot 分别记录计划、变更、事件和恢复状态 |

这张表描述的是运行结构，而不是对所有 Agent 产品的优劣判断。

## 已实现的功能

- 自行实现的 Agent Loop：支持流式模型输出、原生工具调用、连续工具执行、错误计数和最大轮次限制。
- 结构化计划：状态更新会立即推送到 GUI，未完成计划无法通过 DONE 门槛。
- 工作区工具：`list`、`read`、`write`、`apply_patch` 和 `shell`；文件工具带有路径、符号链接、UTF-8 和容量校验。
- 网络工具：通过 Tavily 提供 `web_search` 和 `web_extract`，只有显式配置后才会联网。
- Skill：发现并只读加载兼容 Codex `SKILL.md` 的本地技能。
- SessionSnapshot：保存历史、计划、阶段、权限、幂等记录、已加载技能和上下文摘要。
- 模型路由：可以按阶段静态选择模型，并在请求失败时依次尝试 fallback。
- 本地 GUI：支持多项目和多 Session、流式消息、工具卡、阻塞式审批、用户提问、Session 重命名以及可拖动分栏。
- 可观察性：右侧面板显示 Plan、Git Diff 和 Trace；写入或 Shell 执行后刷新 Diff。

## 快速开始

### 环境要求

- Python 3.10 或更高版本
- [uv](https://docs.astral.sh/uv/)
- 一个支持原生工具调用的 OpenAI-compatible 模型服务
- GUI 额外需要 Node.js 20+ 和 npm

### 安装与配置

```bash
git clone https://github.com/yuan-sq/nano-vibe-coder.git
cd nano-vibe-coder
uv sync
cp config.example.toml config.toml
```

编辑 `config.toml`，至少填写一个模型：

```toml
active_model = "default"

[models.default]
name = "default"
url = "https://api.example.com/v1"
api_key = "replace-me"
model_name = "your-tool-calling-model"
reasoning_level = "medium"
context_window = 128000

[runtime]
permission_mode = "normal"
```

`config.toml` 已被 Git 忽略，不要把真实 API Key 写进其他受版本控制的文件。

### 运行 CLI

```bash
uv run nano-vibe --workspace /path/to/your/git/repository
```

常用选项：

```bash
# 使用指定配置文件
uv run nano-vibe --workspace /path/to/repo --config /path/to/config.toml

# 显式恢复一个 Session 快照
uv run nano-vibe --workspace /path/to/repo --resume SESSION_ID

# 本次启动使用 Full Access 应用层权限策略
uv run nano-vibe --workspace /path/to/repo --full-access
```

CLI 内置 `/help`、`/state`、`/plan`、`/permissions`、`/skills`、`/sessions` 和 `/quit` 命令。

### 运行 GUI

首次使用先安装并构建前端：

```bash
cd frontend
npm ci
npm run build
cd ..
uv run nano-vibe gui
```

启动器会为前端和 FastAPI 后端分配本地端口，生成本次启动的访问令牌，并自动打开浏览器。两个服务都只绑定 `127.0.0.1`。

```bash
uv run nano-vibe gui --no-open    # 不自动打开浏览器
uv run nano-vibe gui --port 5173  # 指定前端端口
uv run nano-vibe gui --dev        # 使用 Vite 开发服务器
```

浏览器关闭不会终止正在运行的 Agent。重新连接后，GUI 会回放内存事件，必要时从 SessionSnapshot 恢复显示。全局运行锁保证同一时间最多执行一个 Agent 任务。

## GUI 中能看到什么

- **Plan**：显示结构化 Todo 及其 `pending`、`in_progress`、`completed` 状态。
- **Diff**：显示当前 Session 相对于其基线的 Git 变更。
- **Trace**：显示模型请求、模型选择、工具执行、上下文压缩和状态变化等事件。
- **工具卡**：默认只显示一行工具名和参数摘要，展开后可查看完整参数、输出和错误。
- **审批卡片**：Normal 模式下，写文件、Shell 和网络工具会暂停等待用户允许一次、允许本 Session 或拒绝。

项目通过 macOS 原生目录选择器添加仓库。Session 可在左侧列表的右键菜单中重命名；权限模式只能在 Session 处于 `IDLE` 时切换，新设置从下一次输入开始生效。

## 工具与阶段权限

下表列出每个阶段可供模型调用的工具。阶段白名单与权限模式是两套机制：前者决定工具是否存在，后者决定受限工具执行前是否审批。

| 阶段 | 可用工具 |
| --- | --- |
| `REQUIREMENTS` | `list`、`read`、`shell`、`user_request`、`transition_state`、`web_search`、`web_extract`、`load_skill`、`read_skill`、`unload_skill` |
| `PLAN` | REQUIREMENTS 的工具，加上 `update_plan` |
| `IMPLEMENT` | PLAN 的工具，加上 `write`、`apply_patch` |
| `VERIFY` | PLAN 的工具，加上 `update_agents` |
| `DONE` | 无 |

REQUIREMENTS 和 PLAN 的提示词明确禁止修改文件；VERIFY 使用 Shell 运行检查，并通过 `update_agents` 完成项目前台规范审查。`write` 和 `apply_patch` 只在 IMPLEMENT 开放。

### Normal 与 Full Access

`normal` 是默认模式。以下 permission scope 需要审批：

- `write`：`write`、`apply_patch`、`update_agents`
- `shell`：Shell 命令
- `network`：Tavily Search 与 Extract

`list`、`read`、计划更新、状态转换和 Skill 读取不需要审批。选择“本 Session 允许”时，授权按工具名写入快照；允许 `write` 不会顺带允许 `apply_patch`。

`full-access` 跳过上述应用层审批，但不会改变阶段工具白名单，也不会绕过工具参数、文件路径、Plan 或 DONE 门槛。它不是操作系统沙箱。

## 文件工具的安全边界

`list`、`read` 和 `write` 只接受工作区相对路径，拒绝绝对路径、`..` 和符号链接路径组件。`read` 与 `write` 只处理 UTF-8 文本，单次最多 100,000 个字符；`write` 使用同目录临时文件和原子替换，覆盖时保留原文件权限。

这些规则只约束结构化文件工具。Shell 仍然是通用进程执行能力，Normal 模式下必须经过审批；开启 Full Access 前应确认目标仓库和模型服务可信。

## 上下文与恢复

每次模型请求都会重新组合以下信息：

1. 系统提示与当前阶段提示；
2. 目标仓库根目录的 `AGENTS.md`；
3. 当前 Plan 和已加载 Skill 的元数据；
4. Session 历史，以及较早历史的压缩摘要。

当估算上下文达到模型窗口的 `compact_ratio` 时，Agent 使用模型总结较早消息，把近期消息保留到 `compact_target_ratio` 附近。压缩摘要、历史和运行计数都会写入 SessionSnapshot。

CLI 只通过明确的 `--resume SESSION_ID` 恢复快照，不会自动猜测要恢复哪个会话。默认数据位置为：

```text
<目标仓库>/.nano-vibe/sessions/<session_id>.json
<目标仓库>/.nano-vibe/traces/<session_id>.jsonl
```

工具调用结果使用 call id 做幂等记录，恢复后重复的同一调用不会再次执行副作用。

## Tavily 搜索与网页提取

默认配置从目标工作区的 `.env` 读取 `TAVILY_API_KEY`：

```dotenv
TAVILY_API_KEY=tvly-your-key
```

也可以在根目录 `config.toml` 的 `[tavily]` 中设置 `api_key`，或者把 `env_file` 改为相对目标工作区的路径或绝对路径。程序不会扫描其他目录寻找 `.env`。

Search 使用 `basic` 深度并最多返回 5 条结果；Extract 一次最多处理 5 个 URL、30,000 个字符。诊断脚本默认只检查配置和 SDK，添加 `--live` 才会真正联网：

```bash
uv run python scripts/test_web_search.py
uv run python scripts/test_web_search.py --live --query "Python 3.13"
```

测试套件默认离线。运行仓库中的 Tavily live 集成测试需要同时显式提供开关和密钥：

```bash
NANO_VIBE_LIVE_TAVILY=1 uv run pytest tests/integration/test_tavily_live.py -q
```

## Skill

项目读取兼容 Codex 格式的 `SKILL.md`。默认搜索目标仓库中的：

```text
.agents/skills/
.codex/skills/
```

也可以通过 `config.toml` 的 `[skills].roots` 增加目录。Skill 只读加载；Agent 能读取说明和被引用的资源，但不会把 `SKILL.md` 当脚本执行。

## 运行架构

```text
CLI / React GUI
       │
     Session ───── SessionStore / TraceWriter
       │
    AgentLoop ──── ContextCompactor
       │
   ModelRouter ─── OpenAI-compatible API
       │
  ToolRegistry ─── StateMachine + PermissionPolicy
       │
 本地文件 / Git / Shell / Tavily / Skill
```

主要目录：

```text
src/nano_vibe/
├── agent/          # Agent Loop、状态机、Plan 和上下文压缩
├── gui/            # FastAPI、本地运行协调、Diff、Trace 和 Session 服务
├── models/         # OpenAI-compatible 模型与按阶段路由
├── observability/  # JSONL Trace
├── prompts/        # 系统、阶段和压缩提示词
├── tools/          # 文件、Shell、计划、状态、网络和 Skill 工具
├── ui/             # CLI 交互
├── config.py       # TOML 配置加载
├── permissions.py  # Normal / Full Access 应用层策略
└── session.py      # Session 组装、保存与恢复

frontend/           # React、TypeScript、Vite GUI
tests/              # 后端单元与集成测试
scripts/            # LLM 和 Tavily 诊断脚本
docs/               # 设计、计划和项目文档
```

## 开发检查

后端：

```bash
uv run pytest -q
uv run ruff check src tests
uv run pyright
git diff --check
```

前端：

```bash
cd frontend
npm test -- --run
npm run build
```

## 当前边界

- 本项目没有操作系统级沙箱，只在应用层控制已注册工具的审批与阶段权限。
- GUI 是本地工作台，不提供远程访问、移动端或多用户服务。
- 同一时间全局只运行一个 Agent 任务，不实现多 Agent 队列。
- 当前不包含 Goal 系统、评测框架、GUI 代码编辑/回滚、交互式终端和 Session 永久删除。
- Tavily 只接入 Search 和 Extract，不包含 Crawl、Map 或 Research API。

第三方依赖和 Apache-2.0 代码来源说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
