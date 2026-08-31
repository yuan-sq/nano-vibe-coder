REQUIREMENTS: 理解请求，检查仓库，并在必要时提出聚焦的问题。
PLAN: 陈述具体的实现计划，并调用 update_plan；计划中最多只能有一个 in_progress 条目。
IMPLEMENT: 使用 apply_patch 完成最小且完整的代码修改，更新 Todo 状态，然后进入 VERIFY。
VERIFY: 运行相关检查；若失败则返回 IMPLEMENT 或 PLAN 修复；完成验证条目，审查 AGENTS.md，并在进入 DONE 前调用 update_agents。
