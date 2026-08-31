# V3 Session 权限与 Plan/Diff/Trace 实施计划

> 设计依据：`docs/superpowers/specs/2026-09-01-v3-observability-and-session-permissions-design.md`

**目标：** 修复 GUI Session 授权与状态恢复，完整实现 Plan、Diff、Trace 观测，并删除独立 Shell 输出面板。

**原则：** 按逻辑单元执行 TDD；每个单元先补失败测试，再做最小实现和针对性验证。不得修改用户已有的 `src/nano_vibe/prompts/system.md` 与 `stages.md` 未提交改动。

## Task 1：修复 Session 恢复和本 Session 授权

**涉及文件：**

- `src/nano_vibe/permissions.py`
- `src/nano_vibe/session_store.py`
- `src/nano_vibe/session.py`
- `src/nano_vibe/gui/agent_runner.py`
- `tests/unit/test_permissions.py`
- 新增或扩展 GUI runner / SessionStore 测试

**步骤：**

1. 添加失败测试，覆盖 `once/session/deny`、同名工具免重复审批、其他工具仍审批、Snapshot 往返保存 grant、已有 GUI Session 跨消息恢复历史/Plan/grant。
2. 为审批结果增加兼容的明确决策类型；`PermissionPolicy` 按工具名维护 grant。
3. 在 `SessionSnapshot` 增加向后兼容的 `session_grants` 字段，Session 保存和恢复该字段。
4. 修复 `GuiAgentRunner`：快照存在时恢复，之后再设置 RUNNING；不存在时正常创建。
5. 运行相关 Python 测试、Ruff 和 Pyright，检查 diff 后提交：`修复 GUI Session 恢复与会话授权`。

## Task 2：实现实时 Plan

**涉及文件：**

- `src/nano_vibe/agent/loop.py`
- `frontend/src/lib/protocol.ts`
- `frontend/src/components/RightPanel.tsx`
- 对应 Python、reducer 与组件测试

**步骤：**

1. 添加失败测试，证明成功 `update_plan` 应发送 `plan_updated`，失败不发送；前端应显示 `content` 与三态状态。
2. 在工具成功结果包含合法 `metadata.plan` 时发送 `plan_updated`，payload 同时包含当前 Agent state。
3. 前端增加 `PlanItem` 类型和安全解析，使用 `id` 作为 key，按 `content/status` 渲染。
4. 验证事件更新和 Snapshot/resync 恢复的一致性。
5. 运行相关 Python/前端测试。

## Task 3：实现 Session Diff

**涉及文件：**

- `src/nano_vibe/gui/diff.py`
- `src/nano_vibe/gui/app.py`
- 必要时为 baseline 增加小型存储/注册组件
- `frontend/src/lib/api.ts`
- `frontend/src/components/RightPanel.tsx`
- `frontend/src/styles.css`
- 对应后端与前端测试

**步骤：**

1. 添加失败测试，覆盖 baseline 持久化与复用、初始脏文件、任务后变化、staged/unstaged/untracked、删除、二进制、大文件和 unified patch。
2. 修复 HEAD 内容读取；原子保存每 Session baseline，并让 API 精确复用该 baseline。
3. 扩展 Diff API 契约，返回 staged/unstaged patch 与可靠元数据；非 Git 或无 HEAD 情况返回稳定结果。
4. 写工具成功后发送轻量 `diff_updated`；前端收到后刷新 query，并保留激活页轮询。
5. 实现默认收起的文件 Diff 查看器及增删行样式。
6. 运行相关 Python/前端测试。

## Task 4：实现精确 Trace

**涉及文件：**

- `src/nano_vibe/observability/trace.py`
- `src/nano_vibe/gui/trace.py`
- `src/nano_vibe/session.py`
- `src/nano_vibe/gui/app.py`
- `frontend/src/lib/api.ts`
- `frontend/src/components/RightPanel.tsx`
- 对应后端与前端测试

**步骤：**

1. 添加失败测试，覆盖唯一 Session 路径、不同 Session 不串读、事件过滤、分页上限、损坏尾行和脱敏字段。
2. 提供共享 trace 路径函数，使 Writer 与 API 使用同一路径。
3. 改造 reader 为有界逐行读取，返回 `next_offset/has_more/total`。
4. 前端展示时间、事件、阶段和可展开 JSON 详情，并在 Trace 页激活时轮询。
5. 运行相关 Python/前端测试。

## Task 5：删除独立 Shell 输出面板

**涉及文件：**

- `frontend/src/App.tsx`
- `frontend/src/components/RightPanel.tsx`
- `frontend/src/lib/protocol.ts`
- `frontend/src/styles.css`
- `frontend/src/components/MessageList.test.tsx`
- `README.md`

**步骤：**

1. 更新测试，要求页面不存在独立 Shell 面板，同时 Shell 工具卡仍能显示命令与结果。
2. 删除 `ShellPanel` import/render/component、独立 shell 状态与 reducer 分支、相关样式。
3. 更新 README，不再宣称存在底部 Shell 面板。
4. 运行完整前端测试和构建。
5. 检查 Task 2–5 的完整 diff 后提交：`实现 Plan Diff Trace 实时观测` 与 `移除前端独立 Shell 输出面板`，不得混入用户 prompt 改动。

## Task 6：审查与完整验证

1. 规格审查：逐条对照设计与计划，确认无缺项和无范围外实现。
2. 代码质量审查：检查权限边界、路径安全、Git 边界、JSONL 大文件读取、类型安全和测试有效性。
3. 修复 Critical/Important 问题并重新审查。
4. 运行：

```bash
uv run pytest -q
uv run ruff check src tests
uv run pyright
npm test -- --run
npm run build
git diff --check
```

5. 检查完整 diff 与 `git status --short`，确认只保留用户原有 prompt 修改，任务提交均为中文且逻辑独立。
