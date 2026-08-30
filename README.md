# nano-vibe-coder

一个面向本地 Git 仓库的可观察、可解释 Coding Agent。

## 开发运行

```bash
uv sync
cp config.example.toml config.toml
# 编辑 config.toml 填入 OpenAI 兼容模型与 API key
uv run nano-vibe --workspace /path/to/your/git/repository
```

自动检查：

```bash
PYTHONPATH=src python3 -m pytest
ruff check src tests
pyright
```

核心流程为 REQUIREMENTS → PLAN → IMPLEMENT → VERIFY → DONE。Agent 使用本地
Shell、unified diff、结构化用户提问和 AGENTS.md 更新工具；运行 trace 保存在
被忽略的 `runs/` 目录中。
