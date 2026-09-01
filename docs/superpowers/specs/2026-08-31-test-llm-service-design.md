# LLM 服务配置连通性测试脚本设计

## 目标

在 `scripts/` 目录提供一个可直接运行的脚本，用当前项目的 `config.toml` 验证
OpenAI-compatible LLM 服务是否可访问、鉴权是否有效、模型是否能返回响应。
脚本只做一次最小请求，不执行 Agent 工具或修改目标仓库。

## 入口与参数

脚本文件为 `scripts/test_llm_service.py`，默认读取仓库根目录的 `config.toml`，并支持
`--config PATH` 指定其他配置文件。测试模型使用配置中的 `active_model`，不额外
引入模型选择逻辑，保证测试结果与默认 CLI 配置一致。

调用示例：

```bash
uv run python scripts/test_llm_service.py
uv run python scripts/test_llm_service.py --config /path/to/config.toml
```

## 实现与数据流

1. 解析命令行参数并将配置路径转换为绝对路径。
2. 调用现有 `nano_vibe.config.load_config` 加载并校验 TOML 配置。
3. 从 `AppConfig.active_model` 创建现有 `OpenAICompatibleModel`，不复制 HTTP
   协议实现。
4. 发送一条固定的短消息，要求模型返回 `OK`；请求不携带工具定义。
5. 收集模型响应并打印脱敏的服务 URL、模型名、耗时和响应摘要。

脚本以同步 CLI 入口运行，通过 `asyncio.run` 调用异步模型客户端。测试请求使用
有限超时；超时、连接错误、HTTP 鉴权错误和配置错误都输出到 stderr，并返回非零
退出码。API key 永不打印，也不出现在异常摘要中。

## 成功与失败语义

- 成功：模型请求完成且返回非空响应，打印 `PASS`，退出码为 0。
- 配置失败：文件不存在、TOML 无效或模型配置不完整，打印可操作的错误信息，
  退出码为 2。
- 服务失败：连接拒绝、超时、鉴权失败或服务返回错误，打印服务类型和安全的
  错误摘要，退出码为 1。

脚本不把“回复内容恰好等于 OK”作为成功条件；只要服务返回非空模型响应即可，
避免不同模型对指令的正常扩写被误判为失败。

## 测试策略

新增 Python 单元测试，注入假的模型客户端或 HTTP 客户端，覆盖：

- 默认配置路径与 `--config` 覆盖；
- 成功请求的退出码和脱敏输出；
- 配置不存在/无效时的退出码；
- 服务异常时的非零退出码，且输出不包含 API key。

测试默认离线运行，不访问真实网络。实现完成后运行该测试、全量 Python 测试、
Ruff、Pyright 和 `git diff --check`。

## 范围边界

本脚本不修改 `config.toml`，不保存响应，不测试工具调用、流式 token、fallback
路由或 Agent 完整流程；这些属于后续集成测试范围。
