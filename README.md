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

### 本地 GUI（V3）

GUI 需要 Node.js 20+ 和 npm。首次使用时在仓库根目录执行：

```bash
cd frontend
npm ci
npm run build
cd ..
uv run nano-vibe gui
```

`nano-vibe gui` 仅绑定 `127.0.0.1`，自动启动 FastAPI 与前端 Node 服务并打开
浏览器。`--no-open` 可关闭自动打开，`--port PORT` 指定前端端口，`--dev` 使用
Vite 开发服务器。浏览器关闭不会停止后台 Agent；重连后会回放内存事件或从
SessionSnapshot 恢复。GUI 使用多项目/Session 工作台、Plan、Diff、Trace、只读
Shell 输出和阻塞审批卡片；同一时间全局只允许一个 Agent 任务。

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

如果 GUI 中提示 Tavily 未配置，请把 `TAVILY_API_KEY=...` 写入所选项目根目录下
的 env 文件（默认是 `<项目路径>/.env`），或在启动 GUI 的进程环境中设置同名变量，
然后重启 GUI。`[tavily].env_file` 可以在根目录 `config.toml` 中改为相对所选项目
的路径或绝对路径；程序不会自动搜索其他目录中的 `.env`。

## 开发检查

```bash
uv run pytest -q
uv run ruff check src tests
uv run pyright
```

trace 保存在被忽略的 `runs/`，会话快照默认保存在目标仓库的
`.nano-vibe/sessions/`。配置支持按状态静态选择模型并按顺序 fallback。

V3 仍不包含 Goal 系统、OS 级沙箱、评测框架、远程访问、移动端、GUI 编辑器、
交互式终端、Session 永久删除，以及 Tavily Crawl/Map/Research API。Chainlit
只作为 Apache-2.0 的前端交互参考，不作为运行时依赖。
