# Tavily 配置文件加载设计

## 目标

允许 Tavily Search/Extract 从根目录 `config.toml` 的 `[tavily].api_key` 读取密钥，
同时保留现有环境变量和显式 dotenv 文件方式。`config.toml` 已被根目录
`.gitignore` 忽略，因此本地密钥不会被新提交跟踪。

## 配置与优先级

`TavilyConfig` 新增可选的 `api_key` 字段，默认为空字符串并隐藏在 dataclass 的
`repr` 中。工具创建时接收该值，密钥解析顺序固定为：

1. 进程环境变量 `TAVILY_API_KEY`；
2. `config.toml` 的 `[tavily].api_key`；
3. `[tavily].env_file` 指向的 dotenv 文件。

空字符串视为未配置。现有 `WebSearchTool` 和 `WebExtractTool` 共用同一解析逻辑，
不会自动扫描其他目录。

## 数据流与安全边界

`load_config` 解析 TOML 后生成不可变 `TavilyConfig`；`Session.from_config` 将
配置中的密钥传入 Tavily 工具。工具只把密钥交给 `AsyncTavilyClient`，不写入
`ToolResult`、trace、错误详情或 GUI 配置响应。示例配置只包含占位注释。

## 错误处理

当三种来源都没有密钥时，返回 `tavily_not_configured`，错误消息只包含配置文件
路径和变量名，不包含任何密钥内容。SDK 缺失和服务请求失败保持现有错误码。

## 验证

- 配置测试覆盖 `api_key` 解析和默认值；
- 工具测试覆盖配置值、环境变量优先级、dotenv 回退和缺失配置；
- 运行后端完整 pytest、Ruff、Pyright 与 `git diff --check`。
