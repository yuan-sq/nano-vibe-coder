# nano-vibe-coder

面向本地 Git 仓库的可观察、可解释 Coding Agent。核心流程是
`REQUIREMENTS → PLAN → IMPLEMENT → VERIFY → DONE`，并要求结构化 Plan Todo
在进入 DONE 前全部为 `completed`。

## 安装与运行

```bash
uv sync
cp config.example.toml config.toml
# 编辑 config.toml，填入 OpenAI-compatible 模型地址、模型名和 API key
uv run nano-vibe --workspace /path/to/your/git/repository
```

`--resume SESSION_ID` 只恢复指定的 JSON 快照；不会自动猜测或恢复会话。
`--full-access` 只切换应用层权限策略，normal 模式会对 shell、写文件和网络
工具请求审批；两种模式都继续遵守状态机、工具注册和 Plan 完成门槛。这里没有
OS 级沙箱。

交互命令：`/help`、`/state`、`/plan`、`/permissions`、`/skills`、`/sessions`、
`/quit`。Codex 兼容的 `SKILL.md` 可放在目标仓库的 `.agents/skills/` 或
`.codex/skills/`，也可在配置中增加 `[skills].roots`；技能只读加载，不执行其内容。

Tavily 使用显式配置的 `[tavily].env_file` 读取 `TAVILY_API_KEY`。Search 固定
`basic`/最多 5 条结果，Extract 最多 5 个 URL、30,000 字符。默认测试完全离线；
需要联网时显式设置 `NANO_VIBE_LIVE_TAVILY=1` 并提供 key：

```bash
NANO_VIBE_LIVE_TAVILY=1 uv run pytest tests/integration/test_tavily_live.py -q
```

## 开发检查

```bash
uv run pytest -q
uv run ruff check src tests
uv run pyright
```

trace 保存在被忽略的 `runs/`，会话快照默认保存在目标仓库的
`.nano-vibe/sessions/`。配置支持按状态静态选择模型并按顺序 fallback。

V2 明确不包含 Goal 系统、OS 级沙箱、评测框架、TUI/GUI、演示材料，以及
Tavily Crawl/Map/Research API。
