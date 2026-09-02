# nano-vibe-coder：从模糊的需求到可靠的软件

Git 仓库：https://github.com/yuan-sq/nano-vibe-coder

## 项目简介
nano-vibe-coder 是一个面向本地 Git 仓库的 Coding Agent。项目自行实现模型调用循环、工具调度、上下文管理、错误处理、会话恢复和可观察 GUI，可自主读写文件、执行命令并完成真实编程任务。项目希望模拟更接近真实软件工程的 Agent 工作方式：不仅关注“如何写代码”，也关注“何时开始写、何时可以交付”。

## 核心设计
针对用户需求模糊，以及现有 Coding Agent 在需求理解和交付验证环节约束不足的问题，本项目把 Coding Agent 建模为有限状态机。任务依次经过 REQUIREMENTS（需求分析）、PLAN（计划）、IMPLEMENT（实现）、VERIFY（验证）和 DONE（完成）。其中 REQUIREMENTS 与 VERIFY 被单独建模为一等阶段：动手前检查仓库、理解现有实现并厘清用户目标；交付前执行测试、检查计划完成度和项目规范。不同阶段只能调用对应工具，计划未完成、验证未通过时不能进入 DONE，实现“先理解，再编码；先验证，再交付”。

## 运行方法
环境要求：Python 3.10+、uv；GUI 还需 Node.js 20+ 和 npm。
1. 执行 uv sync。
2. 复制 config.example.toml 为 config.toml，填写模型地址、模型名和 API Key。
3. CLI：uv run nano-vibe --workspace /你的/Git/仓库。
4. GUI：在 frontend 执行 npm ci 和 npm run build，再回到根目录执行 uv run nano-vibe gui。

## 功能亮点
提供结构化 Plan、文件读写与补丁、Shell、web_search、Skill 加载和用户确认工具；GUI 实时展示对话、工具参数及结果，并提供 Plan、Diff、Trace 面板，便于观察 Agent 的决策和执行过程。Session 快照保存历史、计划、权限和上下文摘要，可显式恢复长任务。