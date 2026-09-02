nano-vibe-coder
从模糊的需求到可靠的软件

Git 仓库：https://github.com/yuan-sq/nano-vibe-coder

项目简介
nano-vibe-coder 是一个面向本地 Git 仓库的 Coding Agent，不依赖 Agent 框架。项目自行实现模型调用循环、工具调度、上下文管理、错误处理、会话恢复和可观察 GUI。

核心设计
项目把软件工程智能体建模为有限状态机，任务依次经过 REQUIREMENTS（需求分析）、PLAN（计划）、IMPLEMENT（实现）、VERIFY（验证）和 DONE（完成）。与主要围绕规划和编码循环工作的 Agent 相比，本项目单独建模需求分析与验证：动手前先检查仓库、厘清目标，交付前完成测试、计划检查和项目规范审查。不同阶段只能调用对应工具，计划未全部完成时不能进入 DONE。

运行方法
环境要求：Python 3.10+、uv；使用 GUI 还需要 Node.js 20+ 和 npm。
1. 执行 uv sync。
2. 复制 config.example.toml 为 config.toml，填写支持工具调用的 OpenAI-compatible 模型地址、模型名和 API Key。
3. CLI：uv run nano-vibe --workspace /你的/Git/仓库。
4. GUI：先在 frontend 目录执行 npm ci 和 npm run build，再回到根目录执行 uv run nano-vibe gui。

功能亮点
提供结构化 Plan、文件读写、补丁、Shell、Tavily 搜索、Skill 加载和用户确认工具；GUI 实时显示对话、工具参数及结果，并提供 Plan、Diff、Trace 面板。Session 快照保存历史、计划、权限和上下文摘要，可显式恢复。Normal 模式审批写入、Shell 和网络操作；Full Access 只跳过应用层审批，仍受阶段和路径校验约束。

说明
服务仅绑定 127.0.0.1，同一时间只运行一个 Agent 任务。项目不提供操作系统沙箱，请只对可信仓库使用；包含密钥的 config.toml 不应提交到 Git。
