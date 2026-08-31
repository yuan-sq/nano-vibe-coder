# Tavily 配置加载与可用性测试实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Tavily Search/Extract 支持从 `config.toml` 加载密钥，并提供根目录 CLI 检查配置及可选真实搜索请求。

**Architecture:** `load_config` 将 `[tavily].api_key` 放入不可变 `TavilyConfig`，`Session.from_config` 把它传给现有 Tavily 工具；工具继续兼容进程环境变量和显式 dotenv 文件。新增 `test_web_search.py` 复用配置加载和 `WebSearchTool`，默认只检查配置/SDK，`--live` 才发起一次真实网络请求。

**Tech Stack:** Python 3.10+, TOML、argparse、asyncio、现有 Tavily SDK 适配、pytest/pytest-asyncio。

---

### Task 1: 扩展 Tavily 配置并保持密钥不泄露

**Files:**
- Modify: `src/nano_vibe/config.py:58-185`
- Modify: `src/nano_vibe/session.py:33-100, 250-275`
- Modify: `src/nano_vibe/tools/web_search.py:53-86`
- Modify: `src/nano_vibe/tools/web_extract.py:30-45`
- Modify: `config.example.toml:31-38`
- Test: `tests/unit/test_config.py`
- Test: `tests/unit/test_tavily_tools.py`

- [ ] **Step 1: Write failing configuration tests**

在 `tests/unit/test_config.py` 的 Tavily 配置测试中加入 `api_key = "config-key"`，
并断言 `config.tavily.api_key == "config-key"`；加入非字符串 `api_key = 1` 时抛出
包含 `tavily.api_key` 的 `ConfigError` 测试。

在 `tests/unit/test_tavily_tools.py` 加入一个环境变量优先级测试：创建带
`TAVILY_API_KEY=file-key` 的临时 dotenv，设置环境变量为 `env-key`，注入可观察的
假客户端构造器，确认工具选择环境变量而不是配置/文件值；同时确认缺失配置的错误
消息不包含任何候选密钥。

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `uv run pytest -q tests/unit/test_config.py tests/unit/test_tavily_tools.py`

Expected: the new assertions fail because `TavilyConfig` has no `api_key` field and
the configuration loader does not validate or propagate it.

- [ ] **Step 3: Implement configuration propagation**

在 `TavilyConfig` 增加 `api_key: str = field(default="", repr=False)`；在
`_tavily_from_values` 中校验 `api_key` 必须为字符串，并传入 dataclass。`Session`
构造函数增加 `tavily_api_key: str | None = None`，创建 Search/Extract 工具时传入；
`Session.from_config` 传入 `config.tavily.api_key`。`WebExtractTool` 将该参数转交
给 `_TavilyTool`。

在 `_TavilyTool._client_or_error` 中固定密钥优先级为：进程环境变量、构造参数、
dotenv 文件。缺失时继续返回 `tavily_not_configured`，错误消息只包含变量名和已解析
路径。`config.example.toml` 只增加注释形式的 `api_key` 示例，不填真实密钥。

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `uv run pytest -q tests/unit/test_config.py tests/unit/test_tavily_tools.py`

Expected: all focused tests pass and no key is present in error output or dataclass repr.

- [ ] **Step 5: Commit the configuration change**

```bash
git add src/nano_vibe/config.py src/nano_vibe/session.py src/nano_vibe/tools/web_search.py src/nano_vibe/tools/web_extract.py config.example.toml tests/unit/test_config.py tests/unit/test_tavily_tools.py
git commit -m "支持从配置文件加载 Tavily 密钥"
```

### Task 2: 新增 web_search 可用性检查 CLI

**Files:**
- Create: `test_web_search.py`
- Create: `tests/unit/test_web_search_service.py`

- [ ] **Step 1: Write failing CLI tests**

覆盖以下行为：

```python
def test_main_reports_configured_without_network(tmp_path, capsys):
    # 配置包含 tavily.api_key；默认模式只检查配置和 SDK，不调用 live 检查。
    assert main(["--config", str(config_path)]) == 0
    assert "CONFIGURED" in capsys.readouterr().out

def test_main_runs_live_check_only_when_requested(tmp_path, monkeypatch, capsys):
    # monkeypatch test_web_search.check_service，确认 --live 才进入真实检查路径。
    assert main(["--config", str(config_path), "--live"]) == 0
    assert "PASS" in capsys.readouterr().out

def test_main_returns_service_error_without_leaking_config_key(tmp_path, monkeypatch, capsys):
    # 注入失败检查并让异常文本包含 config-key；stderr 必须替换为 [REDACTED]。
    assert main(["--config", str(config_path), "--live"]) == 1
    captured = capsys.readouterr()
    assert "config-key" not in captured.err
    assert "[REDACTED]" in captured.err

def test_main_returns_config_error_for_missing_file(tmp_path, capsys):
    assert main(["--config", str(tmp_path / "missing.toml")]) == 2
```

测试使用 `FakeTavilyClient` 或 monkeypatch 的 `check_service`，不访问网络；配置内容
只使用临时的非真实 key。

- [ ] **Step 2: Run the focused CLI tests and confirm RED**

Run: `uv run pytest -q tests/unit/test_web_search_service.py`

Expected: import failure because `test_web_search.py` does not exist yet.

- [ ] **Step 3: Implement the CLI**

在根目录创建 `test_web_search.py`，定义：

- `DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.toml"`；
- 退出码 `0`（可用/配置有效）、`1`（真实请求失败）、`2`（配置错误）；
- `create_tool(config)`，把 `config.tavily.api_key`、`env_file` 传给 `WebSearchTool`；
- `async check_service(config, query, tool=None, timeout_seconds=30.0)`，通过
  `asyncio.wait_for(tool.execute({"query": query}), timeout_seconds)` 执行一次搜索，
  对失败结果抛出 `SearchCheckError`；
- `main(argv)`，支持 `--config PATH`、`--query TEXT`、`--live`。默认模式调用
  `create_tool(...)._tavily._client_or_error()` 做本地配置/SDK 检查并打印
  `CONFIGURED`，不发送网络请求；`--live` 才调用 `check_service` 并打印 `PASS`；
- 所有异常输出通过 `_redact` 替换配置中的 Tavily key，响应只打印结果数量，不打印
  完整搜索内容；模块入口使用 `raise SystemExit(main())`。

- [ ] **Step 4: Run the focused CLI tests and confirm GREEN**

Run: `uv run pytest -q tests/unit/test_web_search_service.py`

Expected: all CLI tests pass without网络访问。

- [ ] **Step 5: Verify CLI help and local configuration mode**

Run: `uv run python test_web_search.py --help` and
`uv run python test_web_search.py --config /tmp/nano-vibe-missing-tavily.toml`。

Expected: help exits 0；缺失配置退出 2，stderr 为中文配置错误且无 traceback。

- [ ] **Step 6: Commit the CLI and tests**

```bash
git add test_web_search.py tests/unit/test_web_search_service.py
git commit -m "增加 web_search 可用性测试脚本"
```

### Task 3: 完整验证与交付

**Files:**
- Verify: `src/nano_vibe/config.py`, `src/nano_vibe/session.py`, `src/nano_vibe/tools/web_search.py`, `test_web_search.py`

- [ ] **Step 1: Run the full Python test suite**

Run: `uv run pytest -q`

Expected: all tests pass；默认测试不访问网络，Tavily live 集成测试保持显式 opt-in。

- [ ] **Step 2: Run static checks**

Run: `uv run ruff check src tests test_web_search.py`、`uv run pyright` 和
`git diff --check`。

Expected: Ruff、Pyright、空白检查均通过。

- [ ] **Step 3: Inspect the final diff and repository state**

Run: `git log -3 --oneline`、`git diff HEAD~2 --stat` 和 `git status --short`。

Expected: 只有本功能的两个实现提交，`config.toml` 仍保持本地忽略，工作树干净。
