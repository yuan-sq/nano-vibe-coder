# 基础文件工具设计

## 目标

为 Agent 增加三个明确的工作区文件工具：`list` 列出目录、`read` 读取 UTF-8 文本、`write` 创建或完整覆盖 UTF-8 文本。工具必须比通用 Shell 更容易审计，并复用现有 ToolRegistry、状态机、权限审批、Session 快照和 GUI 工具卡。

## 接口

### `list`

参数为可选的相对目录路径 `path`，默认值为 `.`。只读取一层，包含隐藏项，按名称排序。每一项返回 `name`、工作区相对 `path` 和 `type`，类型为 `file`、`directory`、`symlink` 或 `other`。列表最多返回 1000 项；超出时只返回前 1000 项，并在结果 metadata 中记录 `total`、`count` 和 `truncated=true`。目录扫描不跟随符号链接。

### `read`

参数为必填的相对文件路径 `path`。只读取常规 UTF-8 文件，空文件合法，最大 100000 个字符。目录、符号链接、缺失路径、非 UTF-8 内容和超限文件均返回结构化失败结果；成功 metadata 记录规范化相对路径和字符数。

### `write`

参数为必填的相对文件路径 `path` 和字符串 `content`。允许创建文件、完整覆盖常规文件以及写入空内容；最大 100000 个字符。父目录必须已经存在，目标不能是目录或符号链接。写入在目标父目录中创建临时文件，写入后 flush、fsync，再用原子替换提交；失败时删除临时文件并保留已有目标。覆盖已有文件时保留其权限，新文件使用普通文本文件权限。成功 metadata 记录路径、字符数以及 `created`/`overwritten`。

## 路径安全

三个工具共享工作区路径校验器。只接受工作区相对路径，拒绝绝对路径和 `..` 路径段。校验器使用 `lstat` 检查每个已有路径组件，拒绝父级或目标符号链接，并确认解析后的路径仍位于工作区。应用层路径校验不是操作系统沙箱；Shell 和 apply_patch 继续保持现有职责。

## 权限与状态

`list` 和 `read` 的 permission scope 为 `read`，在 REQUIREMENTS、PLAN、IMPLEMENT、VERIFY 阶段可用。`write` 的 permission scope 为 `write`，只在 IMPLEMENT 阶段可用；normal 模式走现有一次/本 Session/拒绝审批，full-access 直接执行。Session grant 按具体工具名保存，因此放开 `write` 不会放开 `apply_patch`。写成功后沿用 AgentLoop 对写工具的 `diff_updated` 事件。

IMPLEMENT 阶段提示明确：新建或完整替换小文本文件使用 `write`，局部修改继续使用 `apply_patch`。AGENTS.md 的最终审查仍由 VERIFY 阶段的 `update_agents` 完成。

## 错误与测试

工具通过 `ToolResult.failure` 返回稳定错误，区分参数无效、路径越界、不存在、类型不符、符号链接、UTF-8 解码失败、内容超限和 I/O 失败，不向模型直接抛出未归一化异常。

测试覆盖目录排序/隐藏项/类型/截断，文本和空文件读取，各类路径与内容拒绝，文件创建/覆盖/空写入/权限保留/原子失败，状态机阶段权限，Session 默认注册和 write 的 diff 事件。实现完成后运行后端 pytest、Ruff、Pyright、前端 Vitest/Build 以及 `git diff --check`。

## 非目标

- 不实现递归或 glob 列表。
- 不实现行范围读取、追加写入或局部替换。
- 不自动创建父目录。
- 不读取二进制文件或跟随符号链接。
- 不修改前端协议或移除现有 shell/apply_patch 工具。
