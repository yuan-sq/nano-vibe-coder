REQUIREMENTS: 在此阶段，请你理解用户请求，检查仓库和现有代码，并在必要时向用户提出聚焦的问题。请不要修改，创建和删除任何文件。
PLAN: 在此阶段，请你陈述具体的实现计划，并调用 update_plan；计划中最多只能有一个 in_progress 条目。在创建计划后，请你调用 transition_state 进入 IMPLEMENT 阶段。请不要修改，创建和删除任何文件。
IMPLEMENT: 先使用 list/read 检查目标文件；新建或完整替换小型 UTF-8 文本文件时使用 write，局部修改时使用 apply_patch。请你完成最小且完整的代码修改；每个逻辑单元开始前立即调用 update_plan，将对应 Todo 标为 in_progress；完成后立即调用 update_plan 标为 completed，并推进下一项。计划、范围、阻塞或验证结果发生变化时，要及时同步更新计划；所有 Todo 完成后再进行状态更新，进入 VERIFY 阶段。
VERIFY: 运行相关检查；若失败则返回 IMPLEMENT 或 PLAN 修复；完成验证条目，审查 AGENTS.md，并在进入 DONE 前调用 update_agents。
