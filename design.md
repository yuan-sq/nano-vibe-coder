## 项目亮点
- 把 需求分析 - 计划 - 实现 - 测试 的软件工程流程融入 coding agent
- 不同模块可以采用不同的 llm 配置，如强模型规划，弱模型执行，进而平衡性能和成本
	- 同时采用不同的权限系统
```
REQUIREMENTS
    ↓
PLAN
    ↓
IMPLEMENT
    ↓
VERIFY
    ↓
DONE
```

不同状态下，背后的模型调用参数（如模型型号不同），提示词不同
状态需要 Agent 手动更新
## 工具设计
- shell
- apply_patch
- user_request（给用户发送结构化信息，进行提问）	
- web_search
- goal tools
## Agent loop / 状态机

这是核心中的核心。你需要明确：

```text
用户提示词
   ↓
build context
   ↓
model
   ↓
tool call?
 ├─ no → final
 └─ yes
      ↓
    execute tool
      ↓
    append result
      ↓
    model again

结束对话后：
    更新项目级别记忆 MEMORY.md
```

## Context management

- system_prompt 
- AGENTS.md
- goal_information（如有）
- tool信息
- skill信息
- 和用户的对话+以及 agent 执行结果（history）

## AGENTS.md 生成
```
生成一个名为 `AGENTS.md` 的文件，作为该代码仓库的贡献者指南。

在写入之前，先检查当前工作目录中是否已经存在 `AGENTS.md`。如果已经存在，则不要覆盖或修改它。

你的目标是生成一份清晰、简洁、结构良好的文档。文档应使用描述性标题，并在每个章节中提供可操作的说明。

请参考下面的结构，但可以根据实际情况进行调整——如果某些章节与该项目相关，可以添加；如果某些章节不适用，则可以省略。

## 文档要求

- 文档标题设为 **“AGENTS.md”**。
- 使用 Markdown 标题（`#`、`##` 等）组织文档结构。
- 保持文档简洁，建议控制在 **200–400 个单词**。
- 说明应简短、直接，并针对当前代码仓库的实际情况。
- 在有帮助的地方提供示例，例如命令、目录路径、命名模式等。
- 保持专业、指导性的语气。
    

## 推荐章节

### Project Structure 

- 概述项目结构，包括源代码、测试代码以及资源文件所在的位置。
    

### Build, Test, and Development Commands

- 列出构建、测试以及本地运行项目时使用的关键命令，例如 `npm test`、`make build`。
    
- 简要说明每条命令的作用。
    

### Coding Style & User Preference

- 说明缩进规则、特定编程语言的代码风格偏好以及命名规范。
    
- 包括项目使用的格式化工具或 lint 工具。
    

### Testing Guidelines

- 指出项目使用的测试框架以及测试覆盖率要求。
    
- 说明测试文件或测试用例的命名规范，以及如何运行测试。
    

### Commit & Pull Request Guidelines

- 根据项目的 Git 历史，总结其 commit message 的惯例。
    
- 概述 Pull Request 的要求，例如描述、关联 issue、截图等。
    
### 其他你需要的章节
```

## Verification loop

这是非常关键的一块。

Coding agent 不能满足于：

> “代码已经修改。”

而应该默认：

```text
edit
↓
lint / test / typecheck / build
↓
fail?
├─ yes → inspect → patch again
└─ no  → finish
```

甚至可以把它写进 harness policy，而不是完全依赖模型自觉。

## 权限系统
- 提供一组可插拔的权限，如
	- web
	- rm -rf
	- read-only

## Prompt layering

我们聊过 Codex prompt，但你自己的实现最好也拆层：

```text
prompts/
  system.md
  compact.md
```

## Model abstraction

如果方便，别把 harness 跟某一个 API 焊死。
可以抽象成：

```python
class Model:
    async def complete(messages, tools): ...
```

然后：

```text
OpenAIModel
AnthropicModel
OpenRouterModel
```

## Tool registry

同理：

```python
registry.register(ReadTool())
registry.register(ApplyPatchTool())
registry.register(ShellTool())
```

## Tool 返回值
让模型在工具调用的时候，输出简单解释，给用户看

## Observability / trace

比如 CLI 输出：

```text
- 工具调用描述
- 正在掉用什么工具
- 工具执行结果
```

而内部记录：

```text
turn
tokens
tool
latency
exit_code
model
```

对 debugging agent 非常有帮助。

## Compaction

提示词：

```text
你正在执行上下文压缩**。请为另一个将继续执行该任务的 LLM 创建一份交接摘要。

请包含：

- 当前进展以及已经做出的关键决策
- 重要的上下文、约束条件或用户偏好
- 尚未完成的工作（明确的下一步）
- 其他任务所需的任何关键数据、示例或参考信息

请保持简洁、结构清晰，并重点确保下一个 LLM 能够无缝接手并继续完成工作。
```

## Evals

我们选取 SWE-Pro 中，中等通过率的一组题。
- 测试 Harness
  - Claude Code
  - mini-SWE-agent
  - nano-vibe-coder
- 测试模型
  - Qwen-35B-A3B
  - Deepseek-v4-flash
- 测试指标
  - task-level 通过率
  - test-level 通过率
  - token 消耗

|#|Repo|项目简介|
|--:|---|---|
|1|NodeBB|基于 Node.js 的现代论坛 / 社区平台，支持实时交互、WebSocket、插件和多种数据库。 ([GitHub](https://github.com/NodeBB/NodeBB?utm_source=chatgpt.com "GitHub - NodeBB/NodeBB: Node.js based forum software built for the modern web · GitHub"))|
|2|Ansible|无 Agent 的 IT 自动化平台，用于配置管理、应用部署、云资源管理和多节点编排。 ([GitHub](https://github.com/ansible/ansible?utm_source=chatgpt.com "GitHub - ansible/ansible: Ansible is a radically simple IT automation platform that makes your applications and systems easier to deploy and maintain. Automate everything from code deployment to network configuration to cloud management, in a language that approaches plain English, using SSH, with no agents to install on remote systems. https://docs.ansible.com. · GitHub"))|
|3|ProtonMail WebClients|Proton Web 应用的 Monorepo，包含 Proton Mail、Calendar、Drive、VPN、Pass 等客户端及共享模块。 ([GitHub](https://github.com/ProtonMail/WebClients?utm_source=chatgpt.com "GitHub - ProtonMail/WebClients: Monorepo hosting the proton web clients · GitHub"))|
|4|Element Web|基于 Matrix 协议的 Web / Desktop 即时通信与协作客户端，主要使用 TypeScript。 ([GitHub](https://github.com/element-hq/element-web?utm_source=chatgpt.com "GitHub - element-hq/element-web: A glossy Matrix collaboration client for the web. · GitHub"))|
|5|OpenLibrary|Internet Archive 维护的开放式图书目录，目标是为每一本出版过的书建立网页。 ([GitHub](https://github.com/internetarchive/openlibrary?utm_source=chatgpt.com "GitHub - internetarchive/openlibrary: One webpage for every book ever published! · GitHub"))|
|6|Flipt|Git-native 的 Feature Flag / Feature Management 平台，用于功能开关、灰度发布和 GitOps 工作流。 ([GitHub](https://github.com/flipt-io/flipt?utm_source=chatgpt.com "GitHub - flipt-io/flipt: Enterprise-ready, Git native feature management solution · GitHub"))|
|7|Navidrome|开源、自托管的音乐服务器与流媒体服务，可理解为个人版 Spotify。 ([GitHub](https://github.com/Navidrome/Navidrome?utm_source=chatgpt.com "GitHub - navidrome/navidrome: 🎧 Your Personal Streaming Service · GitHub"))|
|8|Teleport|面向 SSH、Kubernetes、数据库、云服务等基础设施的身份认证与安全访问平台。 ([GitHub](https://github.com/gravitational/teleport?utm_source=chatgpt.com "GitHub - gravitational/teleport: The easiest, and most secure way to access and protect all of your infrastructure. · GitHub"))|
|9|Vuls|Go 编写的无 Agent 漏洞扫描器，用于 Linux、FreeBSD、容器及软件依赖等安全漏洞检测。 ([GitHub](https://github.com/future-architect/vuls?utm_source=chatgpt.com "GitHub - future-architect/vuls: Agent-less vulnerability scanner for Linux, FreeBSD, Container, WordPress, Programming language libraries, Network devices · GitHub"))|
|10|qutebrowser|Python + Qt 编写的键盘驱动、Vim 风格轻量浏览器。 ([GitHub](https://github.com/qutebrowser/qutebrowser?utm_source=chatgpt.com "GitHub - qutebrowser/qutebrowser: A keyboard-driven, vim-like browser based on Python and Qt. · GitHub"))|
```json
{
  "name": "swe-pro-10-v1",
  "instances": [
    "instance_NodeBB__NodeBB-087e6020e490b4a1759f38c1ad03869511928263-vf2cf3cbd463b7ad942381f1c6d077626485a1e9e",
    "instance_ansible__ansible-709484969c8a4ffd74b839a673431a8c5caa6457-vba6da65a0f3baefda7a058ebbd0a8dcafb8512f5",
    "instance_protonmail__webclients-c5a2089ca2bfe9aa1d85a664b8ad87ef843a1c9c",
    "instance_element-hq__element-web-ad26925bb6628260cfe0fcf90ec0a8cba381f4a4-vnan",
    "instance_internetarchive__openlibrary-322d7a46cdc965bfabbf9500e98fde098c9d95b2-v13642507b4fc1f8d234172bf8129942da2c2ca26",
    "instance_flipt-io__flipt-72d06db14d58692bfb4d07b1aa745a37b35956f3",
    "instance_navidrome__navidrome-6c6223f2f9db2c8c253e0d40a192e3519c9037d1",
    "instance_gravitational__teleport-baeb2697c4e4870c9850ff0cd5c7a2d08e1401c9-vee9b09fb20c43af7e520f57e9239bbcf46b7113d",
    "instance_future-architect__vuls-e6c0da61324a0c04026ffd1c031436ee2be9503a",
    "instance_qutebrowser__qutebrowser-305e7c96d5e2fdb3b248b27dfb21042fb2b7e0b8-v2ef375ac784985212b1805e1d0431dc8f1b3c171"
  ]
}

## 推荐开发顺序

- 阶段1 核心功能
- 阶段2 附加功能，如权限系统
- 阶段3 tui gui
