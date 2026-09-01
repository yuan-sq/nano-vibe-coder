# nano-vibe-coder 首版开发与提交计划

## 1. 目标与验收

在 2026 年 9 月 2 日 24:00 前完成一个面向个人使用的通用交互式 Coding Agent：

- 在任意 Git 仓库中接收自然语言任务。
- 自主完成需求澄清、计划、代码修改和验证。
- 使用本地 Shell 与补丁工具，不依赖 Agent 框架或服务端代码执行。
- 验证成功后审阅并更新目标仓库的 `AGENTS.md`，随后进入 DONE。
- 产生可复盘的 JSONL trace。
- 完成公开 GitHub 仓库、README.md、1000 汉字内 README.txt、2 分钟内 MP4 演示和面试材料。

首版不实现 SWE-Pro 评测、多模型分阶段调度、Skills、Goal 系统、命令级权限审批、沙箱和真实 Web 搜索。

## 2. 核心架构与接口

### 工程和 CLI

- 使用 Python 3.10+、uv、Typer、Rich、OpenAI Python SDK。
- 提供命令：
  - `nano-vibe`
  - `nano-vibe --workspace PATH`
  - `nano-vibe --config PATH`
- 默认工作区是当前目录，默认配置位于 Agent 项目根目录。
- CLI 为持续交互式会话；每项任务完成后保留压缩摘要与近期消息，再接受下一项任务。
- 支持 `/help`、`/state`、`/quit` 等最小会话命令。

### 配置与模型

- 提供多个命名 `ModelConfig`，通过 `active_model` 选择唯一运行模型。
- `ModelConfig` 至少包含：
  - `name`
  - `url`
  - `api_key`
  - `model_name`
  - `reasoning_level`
  - `description`
  - `context_window`
- 实际 `config.toml` 不入库；提交无密钥的 `config.example.toml`。
- 模型层只实现 OpenAI 兼容接口和原生 `tool_calls`。
- 文本内容流式显示；工具参数增量累积完整后串行执行。
- 定义可替换 Tokenizer 接口；默认提供字符估算回退，后续替换为用户提供的 tokenizer。

### Agent loop 与状态机

状态：

```text
REQUIREMENTS → PLAN → IMPLEMENT → VERIFY → DONE
                       ↑          │
                       └──────────┘
PLAN ← IMPLEMENT
PLAN ← VERIFY
```

- Agent 通过 `transition_state(target_state)` 显式迁移，运行时校验迁移是否合法。
- DONE 后接收新任务时重置到 REQUIREMENTS。
- 通用系统提示放在 `system.md`。
- 所有阶段的简短特定提示集中在一个阶段提示文件。
- 压缩摘要使用独立 `compact.md`。
- 上下文构成为：系统提示、当前阶段提示、AGENTS.md、状态、工具定义、摘要、近期对话和工具结果。

### 工具注册与权限

统一工具注册表包含：

- `shell(command)`：在目标仓库根目录启动独立子进程。
- `apply_patch(diff)`：接收 unified diff，先执行 `git apply --check`，再正式应用。
- `user_request(question, options)`：显示单选项并允许自由输入。
- `transition_state(target_state)`：推进或回退状态。
- `update_agents(content)`：只能创建或整体重写仓库根目录的 AGENTS.md。
- `web_search(query)`：首版占位，明确返回“尚未实现”。

权限矩阵：

| 状态 | 可用工具 |
|---|---|
| REQUIREMENTS | Shell、UserRequest、Transition、WebSearch |
| PLAN | Shell、UserRequest、Transition、WebSearch |
| IMPLEMENT | Shell、ApplyPatch、UserRequest、Transition、WebSearch |
| VERIFY | Shell、UserRequest、Transition、UpdateAgents、WebSearch |
| DONE | 不再执行工具，输出任务总结并返回交互提示符 |

首版不分析 Shell 命令危险性；需求和计划阶段的只读要求依赖提示词约束。完整权限系统进入第二版。

### 验证与 AGENTS.md

- VERIFY 失败时只能回到 IMPLEMENT 或 PLAN。
- 验证通过后，Agent 必须在前台调用 `update_agents`。
- 更新内容保留已有规则的含义，并整合经验证的项目结构、命令、规范、关键决策和当前限制，不写聊天流水账。
- 若没有新知识，也必须调用工具完成审阅；内容允许保持不变。
- 只有 `update_agents` 成功后，状态机才接受 VERIFY → DONE。
- 不创建 MEMORY.md；上下文摘要只保存在当前进程内。

### 限制与可观测性

默认限制：

- 单任务最多 100 个模型轮次。
- 连续工具错误最多 5 次。
- API 请求最多重试 5 次，使用指数退避。
- Shell 默认超时 300 秒。
- Shell 输出最多 50,000 字符，超限保留头尾并标注截断。
- 上下文达到 `context_window` 的 75% 时自动压缩；压缩后降至约 50%。
- 每个任务 DONE 后再压缩一次，供下一任务继承。

JSONL trace 保存于 Agent 项目下被忽略的 `runs/`，按目标仓库哈希和 session ID 分组。记录 session、turn、state、model、tool、latency、token、exit code、迁移、压缩和错误事件，并对 API key 等敏感字段脱敏。

## 3. 测试与完成标准

使用 pytest、Ruff、Pyright。

自动测试覆盖：

- TOML 配置解析、缺失字段、活动模型选择和密钥脱敏。
- 合法与非法状态迁移、回退路径、DONE 前置条件。
- 各状态的工具可见性。
- Shell 成功、失败、超时和输出截断。
- unified diff 检查、成功应用和失败回滚。
- UserRequest 选项及自由输入。
- UpdateAgents 创建、重写、不变审阅和路径限制。
- 原生 tool call 增量组装及串行执行。
- API 重试、循环上限和连续工具错误中止。
- 75% 自动压缩、压缩后上下文构建及 DONE 后任务继承。
- JSONL trace 字段完整性和敏感信息脱敏。

端到端测试使用脚本化 FakeModel 和临时 Git 仓库，完整走通：

```text
用户任务
→ REQUIREMENTS
→ PLAN
→ IMPLEMENT
→ ApplyPatch
→ VERIFY
→ 测试失败
→ IMPLEMENT
→ 再次修复
→ VERIFY
→ UpdateAgents
→ DONE
```

提交前使用实际配置的 OpenAI 兼容模型完成一次真实冒烟。完成标准是 Agent 能修改独立仓库、运行测试、更新 AGENTS.md、进入 DONE，且 `pytest`、Ruff、Pyright 全部通过。

## 4. 四天实施与 Commit 节奏

### 8 月 30 日：基础设施

- 新建公开 GitHub 仓库并立即开始保留提交历史。
- 初始化 uv、包结构、Typer 入口和质量工具。
- 实现配置、ModelConfig、模型协议、OpenAI 兼容适配器和 FakeModel。
- 建立 prompt 分层与 JSONL trace 骨架。

建议 Commit：

- `初始化 Python CLI 工程与配置`
- `实现模型适配与流式响应`
- `增加运行追踪基础设施`

### 8 月 31 日：核心闭环

- 实现状态机、合法回退和阶段工具权限。
- 实现 Shell、ApplyPatch、UserRequest、Transition 和 WebSearch 占位。
- 实现完整 Agent loop、交互式 CLI、错误恢复和循环限制。
- 当天结束前锁定视频任务；若没有另选，默认使用带失败测试的小型 Python Bug 仓库。

建议 Commit：

- `实现阶段状态机与工具注册`
- `实现本地工具与补丁应用`
- `实现交互式 Agent 循环`

### 9 月 1 日：上下文、AGENTS 与稳定性

- 接入 tokenizer 接口和自动 compaction。
- 实现 `update_agents` 及 DONE 前置条件。
- 补齐全部单元与端到端测试。
- 使用真实模型完成冒烟。
- 对默认视频任务至少彩排两次。
- 起草 README.md、README.txt 和面试讲解提纲。

建议 Commit：

- `实现上下文压缩与多任务继承`
- `实现 AGENTS 指南更新流程`
- `完善端到端测试与错误处理`

### 9 月 2 日：交付日

- 上午执行完整 `pytest`、Ruff、Pyright 和真实任务回归。
- 检查完整 Git diff、提交历史、安装步骤和全新环境运行流程。
- 扫描 API key、token、个人路径和运行日志，确保均未提交。
- 下午录制并剪辑视频，确保小于 2 分钟、MP4、小于 200 MB。
- 完成详细 README.md 和 1000 汉字内 README.txt。
- 准备面试问答：状态机、工具调用、上下文压缩、验证闭环、失败处理、权限边界。
- 将 README.txt 与视频压缩为姓名命名的 ZIP，目标在 22:00 前上传。
- 截止后不再向公开仓库推送 Commit。

最终文档 Commit：

- `完善项目文档与提交材料`

## 5. 明确假设与第二版路线

- 首版要求目标工作区是 Git 仓库，因为 ApplyPatch 依赖 `git apply`。
- 实际演示模型和密钥稍后写入本地 `config.toml`。
- 首版所有阶段使用同一个 active model；多模型配置仅保留结构能力。
- 视频默认使用独立的小型 Python Bug 仓库，不使用 SWE-Pro。
- 第二版再实现阶段多模型、命令审批与沙箱、真实 WebSearch、Skills、Goal/Todo、会话恢复和 SWE-Pro 评测。

## 6 目录结构

nano-vibe-coder/
├── .gitignore
├── AGENTS.md
├── README.md
├── README.txt
├── pyproject.toml
├── uv.lock
├── config.example.toml
├── config.toml                  # 本地配置，不入库
│
├── src/
│   └── nano_vibe/
│       ├── __init__.py
│       ├── cli.py               # Typer 入口、交互式 REPL
│       ├── config.py            # TOML 加载、ModelConfig、运行限制
│       ├── session.py           # 多任务会话生命周期
│       │
│       ├── agent/
│       │   ├── __init__.py
│       │   ├── loop.py          # model → tool → model 主循环
│       │   ├── state.py         # 状态枚举、迁移图、权限矩阵
│       │   ├── context.py       # 构建模型上下文
│       │   └── compaction.py    # token 计算与上下文压缩
│       │
│       ├── models/
│       │   ├── __init__.py
│       │   ├── base.py          # Model 抽象、响应与 tool-call 类型
│       │   └── openai_compat.py # OpenAI 兼容接口、流式响应与重试
│       │
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── base.py          # Tool、ToolResult 抽象
│       │   ├── registry.py      # 注册、权限过滤、参数分发
│       │   ├── shell.py
│       │   ├── apply_patch.py
│       │   ├── user_request.py
│       │   ├── transition.py
│       │   ├── update_agents.py
│       │   └── web_search.py    # 首版占位实现
│       │
│       ├── prompts/
│       │   ├── system.md
│       │   ├── stages.md        # 所有阶段的简短提示词
│       │   └── compact.md
│       │
│       ├── observability/
│       │   ├── __init__.py
│       │   └── trace.py         # JSONL 事件与敏感字段脱敏
│       │
│       └── ui/
│           ├── __init__.py
│           └── console.py       # Rich 输出、流式文本、用户选择
│
├── tests/
│   ├── conftest.py
│   ├── fakes.py                 # 脚本化 FakeModel
│   ├── unit/
│   │   ├── test_config.py
│   │   ├── test_state.py
│   │   ├── test_context.py
│   │   ├── test_compaction.py
│   │   ├── test_tools.py
│   │   └── test_trace.py
│   └── integration/
│       └── test_agent_loop.py   # 临时 Git 仓库端到端测试
│
├── docs/
│   ├── architecture.md
│   └── interview-notes.md
│
└── runs/                        # JSONL trace，不入库
