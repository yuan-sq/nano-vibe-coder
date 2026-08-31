# LLM 服务测试脚本 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在仓库根目录提供一个读取 `config.toml` 并发起一次最小 OpenAI-compatible 请求的 CLI，用退出码明确报告 LLM 服务是否有效。

**Architecture:** 复用 `nano_vibe.config.load_config` 解析配置和 `OpenAICompatibleModel` 发起请求；根目录脚本只负责参数、超时、输出脱敏和退出码。模型调用通过可注入的 `Model` 参数测试，默认请求不携带工具。

**Tech Stack:** Python 3.10+, argparse, asyncio, 现有 `nano_vibe` 配置与 OpenAI-compatible 客户端，pytest/pytest-asyncio。

---

### Task 1: 离线失败测试

**Files:**
- Create: `tests/unit/test_llm_service.py`
- Reference: `src/nano_vibe/config.py`, `src/nano_vibe/models/base.py`

- [ ] **Step 1: Write the failing tests** for a successful injected model, missing configuration, and service exception with key redaction.

```python
from pathlib import Path

import pytest

from nano_vibe.models.base import ModelResponse
from test_llm_service import main


def write_config(path: Path, api_key: str = "secret-key") -> None:
    path.write_text(
        """
active_model = "default"

[models.default]
name = "default"
url = "https://llm.example.test/v1"
model_name = "demo"
api_key = "__API_KEY__"
""".replace("__API_KEY__", api_key),
        encoding="utf-8",
    )


def test_main_reports_pass_for_a_non_empty_model_response(tmp_path: Path, capsys, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    class FakeModel:
        async def complete(self, messages, tools):
            assert messages[-1]["content"]
            assert tools == []
            return ModelResponse(content="OK")

    monkeypatch.setattr("test_llm_service.create_model", lambda config: FakeModel())

    assert main(["--config", str(config_path)]) == 0
    assert "PASS" in capsys.readouterr().out


def test_main_returns_config_error_for_missing_file(tmp_path: Path, capsys) -> None:
    result = main(["--config", str(tmp_path / "missing.toml")])

    captured = capsys.readouterr()
    assert result == 2
    assert "配置" in captured.err


def test_main_redacts_api_key_when_service_fails(tmp_path: Path, capsys, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    class FailingModel:
        async def complete(self, messages, tools):
            raise RuntimeError("request failed with secret-key")

    monkeypatch.setattr("test_llm_service.create_model", lambda config: FailingModel())

    assert main(["--config", str(config_path)]) == 1
    captured = capsys.readouterr()
    assert "服务" in captured.err
    assert "secret-key" not in captured.err
    assert "[REDACTED]" in captured.err
```

- [ ] **Step 2: Run the focused tests and confirm the expected RED state**

Run: `uv run pytest -q tests/unit/test_llm_service.py`

Expected: collection/import failure because `test_llm_service.py` and `create_model` do not exist yet.

### Task 2: 根目录 CLI 实现

**Files:**
- Create: `test_llm_service.py`

- [ ] **Step 1: Implement the minimal public seams used by the tests**

In `test_llm_service.py`, define `DEFAULT_CONFIG_PATH` as the repository-root `config.toml`,
`EXIT_OK = 0`, `EXIT_SERVICE_ERROR = 1`, and `EXIT_CONFIG_ERROR = 2`. Define
`create_model(config: AppConfig) -> OpenAICompatibleModel`,
`async check_service(config: AppConfig, model: Model, timeout_seconds: float = 30.0) -> ModelResponse`,
and `main(argv: Sequence[str] | None = None) -> int`; finish the module with
`if __name__ == "__main__": raise SystemExit(main())`.

`create_model` 必须使用 `config.active_model` 和 `retries=1`；`check_service` 必须调用
`asyncio.wait_for(model.complete([{"role": "user", "content": "请连接模型服务并只回复 OK。"}], []), timeout_seconds)`，
并在响应内容为空时抛出服务错误。`main` 默认读取 `DEFAULT_CONFIG_PATH`，`--config` 覆盖路径；
`ConfigError` 或配置文件错误返回 2，超时/连接/模型异常返回 1，成功打印 `PASS` 和非敏感响应摘要并返回 0。
错误摘要必须把配置中出现的 API key 替换为 `[REDACTED]`，服务 URL 只输出 scheme、host 和 path，不能输出 query、fragment 或 key。

- [ ] **Step 2: Run the focused tests and confirm GREEN**

Run: `uv run pytest -q tests/unit/test_llm_service.py`

Expected: 3 passed.

- [ ] **Step 3: Verify the CLI help and offline configuration error**

Run: `uv run python test_llm_service.py --help` and `uv run python test_llm_service.py --config /tmp/nano-vibe-missing-config.toml`.

Expected: help exits 0; missing config exits 2 and prints a Chinese configuration error to stderr without a traceback.

- [ ] **Step 4: Commit the self-contained script and tests**

```bash
git add test_llm_service.py tests/unit/test_llm_service.py
git commit -m "增加 LLM 服务配置测试脚本"
```

### Task 3: 完整验证与交付

**Files:**
- Verify: `test_llm_service.py`, `tests/unit/test_llm_service.py`

- [ ] **Step 1: Run the full Python test suite**

Run: `uv run pytest -q`

Expected: all existing tests pass; no network request is made by the new tests.

- [ ] **Step 2: Run static checks for the changed Python files**

Run: `uv run ruff check test_llm_service.py tests/unit/test_llm_service.py` and `uv run pyright`.

Expected: Ruff reports no violations and Pyright reports 0 errors.

- [ ] **Step 3: Inspect the final diff and repository state**

Run: `git diff HEAD^ --check`, `git show --stat --oneline HEAD`, and `git status --short`.

Expected: no whitespace errors, only the script and its tests in the implementation commit, and a clean worktree.
