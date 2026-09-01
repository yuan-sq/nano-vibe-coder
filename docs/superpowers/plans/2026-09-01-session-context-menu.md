# Session 右键重命名 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除左侧 Session 列表中的铅笔按钮和双击入口，改为通过自定义右键菜单进入现有的 Session 内联重命名流程。

**Architecture:** `SessionList` 维护唯一的 `{ sessionId, x, y } | null` 菜单状态。Session 行的左键只负责选择，右键阻止浏览器菜单并记录指针位置；菜单使用固定定位并将坐标限制在视口内。菜单打开期间按需注册 document 级 mousedown、keydown、scroll 监听，点击“重命名”后复用现有的受控输入、保存锁和错误回调，不改动后端接口或 App 的重命名请求。

**Tech Stack:** React 18 + TypeScript, Vitest, React Testing Library, CSS。

---

### Task 1: 用测试锁定右键菜单交互

**Files:**
- Modify: `frontend/src/components/SessionList.test.tsx`
- Test command: `cd frontend && pnpm vitest run src/components/SessionList.test.tsx`

- [ ] **Step 1: 将旧的双击测试改成右键菜单测试，并覆盖菜单关闭行为**

在 `SessionList.test.tsx` 中保留现有 `session` fixture，替换两个双击测试并新增行为断言：

```tsx
it("opens a rename context menu without selecting the session", () => {
  const onSelect = vi.fn();
  render(<SessionList sessions={[session]} activeSessionId={null} onSelect={onSelect} onRename={vi.fn()} />);

  fireEvent.contextMenu(screen.getByText("新建 Session"), { clientX: 40, clientY: 80 });

  expect(screen.getByRole("menu")).toBeInTheDocument();
  expect(screen.getByRole("menuitem", { name: "重命名" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /✎|重命名 新建 Session/ })).not.toBeInTheDocument();
  expect(onSelect).not.toHaveBeenCalled();
});

it("renames a session from the context menu on Enter", async () => {
  const onSelect = vi.fn();
  const onRename = vi.fn().mockResolvedValue(undefined);
  render(<SessionList sessions={[session]} activeSessionId={null} onSelect={onSelect} onRename={onRename} />);

  fireEvent.contextMenu(screen.getByText("新建 Session"));
  fireEvent.click(screen.getByRole("menuitem", { name: "重命名" }));
  const input = screen.getByDisplayValue("新建 Session");
  fireEvent.change(input, { target: { value: "今天的任务" } });
  fireEvent.keyDown(input, { key: "Enter" });

  await waitFor(() => expect(onRename).toHaveBeenCalledWith("session-1", "今天的任务"));
  expect(onSelect).not.toHaveBeenCalled();
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});

it("closes the context menu with Escape, outside click, and scroll", () => {
  render(<SessionList sessions={[session]} activeSessionId={null} onSelect={vi.fn()} onRename={vi.fn()} />);
  const item = screen.getByText("新建 Session");

  fireEvent.contextMenu(item);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();

  fireEvent.contextMenu(item);
  fireEvent.mouseDown(document.body);
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();

  fireEvent.contextMenu(item);
  fireEvent.scroll(document);
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});
```

同时新增一个普通左键即时选择的断言，确保移除双击延迟后仍可选择：

```tsx
it("selects a session on a normal left click", () => {
  const onSelect = vi.fn();
  render(<SessionList sessions={[session]} activeSessionId={null} onSelect={onSelect} onRename={vi.fn()} />);

  fireEvent.click(screen.getByText("新建 Session"));

  expect(onSelect).toHaveBeenCalledWith(session);
});
```

- [ ] **Step 2: 运行测试确认当前实现按预期失败**

运行：

```bash
cd frontend && pnpm vitest run src/components/SessionList.test.tsx
```

预期：失败，因为当前组件仍依赖双击/铅笔按钮，没有 `role="menu"`、`role="menuitem"` 或右键菜单。

### Task 2: 实现 SessionList 右键菜单

**Files:**
- Modify: `frontend/src/components/SessionList.tsx`
- Test command: `cd frontend && pnpm vitest run src/components/SessionList.test.tsx`

- [ ] **Step 1: 删除旧的双击和延迟选择逻辑**

移除 `clickTimerRef`、卸载时清理定时器、`scheduleSelect` 和 `beginEdit` 中清理点击定时器的代码；普通 Session 按钮改为直接执行 `onSelect(session)` 的 `onClick`，删除 `onDoubleClick`；删除 `session-edit` 铅笔按钮。

- [ ] **Step 2: 增加菜单状态、坐标限制和按需 document 监听**

在组件状态中加入：

```tsx
type ContextMenuState = { sessionId: string; x: number; y: number } | null;
const [contextMenu, setContextMenu] = useState<ContextMenuState>(null);
```

使用 `closeContextMenu` 将状态置空，并在 `useEffect` 中仅当菜单打开时注册以下逻辑：

```tsx
useEffect(() => {
  if (!contextMenu) return;
  const close = () => setContextMenu(null);
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "Escape") close();
  };
  document.addEventListener("mousedown", close);
  document.addEventListener("keydown", onKeyDown);
  document.addEventListener("scroll", close, true);
  return () => {
    document.removeEventListener("mousedown", close);
    document.removeEventListener("keydown", onKeyDown);
    document.removeEventListener("scroll", close, true);
  };
}, [contextMenu]);
```

右键处理器必须阻止默认菜单和冒泡，但不调用 `onSelect`。菜单坐标使用固定定位的预计尺寸（宽度 120px、高度 40px）进行视口限制：

```tsx
const openContextMenu = (event: React.MouseEvent, session: Session) => {
  event.preventDefault();
  event.stopPropagation();
  const menuWidth = 120;
  const menuHeight = 40;
  setContextMenu({
    sessionId: session.session_id,
    x: Math.max(4, Math.min(event.clientX, window.innerWidth - menuWidth - 4)),
    y: Math.max(4, Math.min(event.clientY, window.innerHeight - menuHeight - 4)),
  });
};
```

- [ ] **Step 3: 渲染唯一菜单并复用 beginEdit**

保留现有 `cancelEdit`、`beginEdit`、`saveEdit` 的保存语义。在列表渲染结束后，依据 `contextMenu` 找到目标 Session；菜单按钮使用 `role="menuitem"`，点击时停止冒泡、关闭菜单，再调用 `beginEdit`：

```tsx
{contextMenu && (() => {
  const target = sessions.find((item) => item.session_id === contextMenu.sessionId);
  if (!target) return null;
  return (
    <div
      className="session-context-menu"
      role="menu"
      style={{ left: contextMenu.x, top: contextMenu.y }}
      onMouseDown={(event) => event.stopPropagation()}
    >
      <button
        type="button"
        role="menuitem"
        onClick={(event) => {
          event.stopPropagation();
          setContextMenu(null);
          beginEdit(event, target);
        }}
      >
        重命名
      </button>
    </div>
  );
})()}
```

编辑输入框保留 Enter 保存、Escape 取消、失焦保存、空标题不请求和失败错误回调；当目标 Session 从 props 消失时，菜单通过 `target` 查找结果自动不渲染。

- [ ] **Step 4: 运行 SessionList 测试确认实现通过**

运行：

```bash
cd frontend && pnpm vitest run src/components/SessionList.test.tsx
```

预期：新增右键菜单、重命名、关闭和左键选择测试全部通过。

### Task 3: 添加菜单视觉样式并完成回归验证

**Files:**
- Modify: `frontend/src/styles.css`
- Verify: `frontend/src/components/SessionList.tsx`, `frontend/src/components/SessionList.test.tsx`

- [ ] **Step 1: 添加固定定位菜单样式并保持内联输入可用**

在 `styles.css` 中加入：

```css
.session-context-menu {
  position: fixed;
  z-index: 20;
  min-width: 120px;
  padding: 4px;
  border: 1px solid #e2e5ea;
  border-radius: 7px;
  background: #fff;
  box-shadow: 0 8px 24px rgba(32, 36, 48, 0.16);
}

.session-context-menu button {
  display: block;
  width: 100%;
  padding: 8px 10px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: #333944;
  text-align: left;
}

.session-context-menu button:hover,
.session-context-menu button:focus-visible {
  background: #f0efff;
  color: #5142d8;
  outline: none;
}
```

确认不再保留或新增 `.session-edit` 铅笔按钮样式；不改变左侧栏的布局尺寸。

- [ ] **Step 2: 运行前端完整测试和构建**

运行：

```bash
cd frontend && pnpm test -- --run
cd frontend && pnpm build
```

预期：Vitest 全部通过，Vite 构建成功。

- [ ] **Step 3: 检查工作区差异和格式问题**

运行：

```bash
git diff --check
git diff -- frontend/src/components/SessionList.tsx frontend/src/components/SessionList.test.tsx frontend/src/styles.css
```

确认 diff 只包含本功能的右键菜单、测试和样式，不修改后端或无关布局。

- [ ] **Step 4: 提交单一完整变更**

运行：

```bash
git add frontend/src/components/SessionList.tsx frontend/src/components/SessionList.test.tsx frontend/src/styles.css
git commit -m "改为通过右键菜单重命名 Session"
```

预期：创建一个中文提交，提交内容不包含设计文档之外的无关文件。
