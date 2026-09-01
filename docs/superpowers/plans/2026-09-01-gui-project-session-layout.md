# GUI 项目选择、Session 管理与可调整布局 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 将已确认的 GUI 设计实现为 macOS 原生项目选择、Session 内联重命名、独立滚动中间区和可拖拽三栏布局。

**Architecture:** 后端新增独立的 macOS osascript 目录选择器模块，FastAPI 接口负责选择、校验并注册项目；前端保留现有 React Query/Zustand 数据流，将 Session 列表和分隔线拖拽拆成小组件。中间区改为自己的 flex 容器，消息列表负责自动滚动，左右栏各自拥有滚动容器。

**Tech Stack:** Python 3.10+、FastAPI、pytest、React 18、TypeScript、Vitest、Testing Library、CSS Grid、Pointer Events。

---

### Task 1: 实现 macOS 原生项目目录选择器与接口

**Files:**
- Create: src/nano_vibe/gui/project_picker.py
- Modify: src/nano_vibe/gui/app.py:1-30, 381-405
- Test: tests/unit/test_project_picker.py
- Test: tests/unit/test_gui_api.py:16-47

- [ ] Step 1: Write failing picker unit tests

    def test_choose_directory_returns_selected_path(monkeypatch):
        monkeypatch.setattr(project_picker.sys, "platform", "darwin")
        monkeypatch.setattr(
            project_picker.subprocess,
            "run",
            lambda *args, **kwargs: CompletedProcess(args[0], 0, "/Users/me/repo\n", ""),
        )
        assert project_picker.choose_directory() == Path("/Users/me/repo")

    def test_choose_directory_reports_cancel(monkeypatch):
        monkeypatch.setattr(project_picker.sys, "platform", "darwin")
        monkeypatch.setattr(
            project_picker.subprocess,
            "run",
            lambda *args, **kwargs: CompletedProcess(args[0], 1, "", "User canceled."),
        )
        with pytest.raises(project_picker.ProjectPickerCancelled):
            project_picker.choose_directory()

    def test_choose_directory_is_macos_only(monkeypatch):
        monkeypatch.setattr(project_picker.sys, "platform", "linux")
        with pytest.raises(project_picker.ProjectPickerUnavailable):
            project_picker.choose_directory()

    Use a small CompletedProcess import in the test and assert the subprocess receives osascript and an AppleScript choose folder expression. The tests must not launch a real dialog.

- [ ] Step 2: Run picker tests to verify the expected RED failure

Run: uv run pytest -q tests/unit/test_project_picker.py

Expected: FAIL because project_picker.py and its exceptions do not exist yet.

- [ ] Step 3: Implement the picker module

Create ProjectPickerCancelled and ProjectPickerUnavailable exceptions and this behavior:

    def choose_directory() -> Path:
        if sys.platform != "darwin":
            raise ProjectPickerUnavailable("macOS folder picker is unavailable")
        try:
            completed = subprocess.run(
                ["osascript", "-e", 'POSIX path of (choose folder with prompt "选择项目目录")'],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise ProjectPickerUnavailable("osascript is unavailable") from exc
        if completed.returncode != 0:
            if "cancel" in completed.stderr.lower():
                raise ProjectPickerCancelled("project selection cancelled")
            raise ProjectPickerUnavailable("macOS folder picker failed")
        selected = completed.stdout.strip()
        if not selected:
            raise ProjectPickerUnavailable("macOS folder picker returned no directory")
        return Path(selected).expanduser().resolve()

- [ ] Step 4: Add the authenticated FastAPI endpoint and API tests

Import the picker exceptions and add POST /api/v1/projects/select next to the existing project routes. Run only the blocking dialog in asyncio.to_thread; then pass the returned path through validate_project_path and state.storage.add_project. Map errors to 409 {"detail": {"code": "project_selection_cancelled"}}, 503 {"detail": {"code": "project_picker_unavailable", "message": ...}}, and the existing 400 invalid_project shape.

Add TestClient cases that monkeypatch nano_vibe.gui.app.choose_directory to return a temporary Git repository, raise ProjectPickerCancelled, and raise ProjectPickerUnavailable; assert status codes and that the successful project appears in GET /api/v1/projects.

- [ ] Step 5: Run the focused backend tests

Run: uv run pytest -q tests/unit/test_project_picker.py tests/unit/test_gui_api.py -k 'project or picker'

Expected: all selected tests PASS without opening a system dialog.

- [ ] Step 6: Commit the backend unit

    git add src/nano_vibe/gui/project_picker.py src/nano_vibe/gui/app.py tests/unit/test_project_picker.py tests/unit/test_gui_api.py
    git commit -m "增加 macOS 原生项目目录选择接口"

### Task 2: 接入项目选择并抽离 Session 列表重命名

**Files:**
- Modify: frontend/src/lib/api.ts:54-66
- Modify: frontend/src/lib/api.test.ts
- Create: frontend/src/components/SessionList.tsx
- Create: frontend/src/components/SessionList.test.tsx
- Modify: frontend/src/App.tsx:1-180
- Modify: frontend/src/App.test.tsx

- [ ] Step 1: Write failing API and SessionList tests

Add an API test that calls selectProject() and verifies POST /api/v1/projects/select, then add component tests for these behaviors:

    it("renames a session on Enter and does not select the row", async () => {
      const onSelect = vi.fn();
      const onRename = vi.fn().mockResolvedValue(undefined);
      render(<SessionList sessions={[session]} activeSessionId={null} onSelect={onSelect} onRename={onRename} />);
      fireEvent.doubleClick(screen.getByText("新建 Session"));
      const input = screen.getByDisplayValue("新建 Session");
      fireEvent.change(input, { target: { value: "今天的任务" } });
      fireEvent.keyDown(input, { key: "Enter" });
      await waitFor(() => expect(onRename).toHaveBeenCalledWith("session-1", "今天的任务"));
      expect(onSelect).not.toHaveBeenCalled();
    });

    it("cancels editing with Escape and ignores an empty title", async () => {
      const onRename = vi.fn();
      render(<SessionList sessions={[session]} activeSessionId={null} onSelect={vi.fn()} onRename={onRename} />);
      fireEvent.doubleClick(screen.getByText("新建 Session"));
      const input = screen.getByDisplayValue("新建 Session");
      fireEvent.change(input, { target: { value: "   " } });
      fireEvent.keyDown(input, { key: "Enter" });
      expect(onRename).not.toHaveBeenCalled();
      fireEvent.doubleClick(screen.getByText("新建 Session"));
      fireEvent.keyDown(screen.getByDisplayValue("新建 Session"), { key: "Escape" });
      expect(screen.getByText("新建 Session")).toBeInTheDocument();
    });

- [ ] Step 2: Run the new frontend tests and verify RED

Run: npm test -- --run src/components/SessionList.test.tsx src/lib/api.test.ts

Expected: FAIL because selectProject and SessionList do not exist.

- [ ] Step 3: Implement the API method and SessionList component

Add GuiApi.selectProject(): Promise<Project> using POST /api/v1/projects/select with an empty JSON object. Implement SessionList with a session row, a double-clickable title, an edit button, and an editing input. The component owns editingId, draft text, and savingId; Enter/blur trims and calls onRename, Escape restores the original title, and an empty/unchanged title exits without calling the API. Call stopPropagation() from edit controls and the input.

- [ ] Step 4: Replace the path prompt and wire SessionList into App

Replace window.prompt("请输入 Git 仓库路径") with api.selectProject(). Treat ApiError.status === 409 and message/code project_selection_cancelled as a silent cancellation; show other errors in the existing error area and invalidate projects on success. Add renameSession that calls api.updateSession(sessionId, { title }), updates queryClient.setQueryData(["sessions", projectId], ...), and rethrows failures so SessionList can display them through onError.

- [ ] Step 5: Run focused frontend tests and verify GREEN

Run: npm test -- --run src/components/SessionList.test.tsx src/lib/api.test.ts src/App.test.tsx

Expected: all selected tests PASS, including the existing duplicate-send and stale-interaction cases.

- [ ] Step 6: Commit the project/session unit

    git add frontend/src/lib/api.ts frontend/src/lib/api.test.ts frontend/src/components/SessionList.tsx frontend/src/components/SessionList.test.tsx frontend/src/App.tsx frontend/src/App.test.tsx
    git commit -m "支持原生项目选择与 Session 内联重命名"

### Task 3: 增加消息自动滚动并重排中间区

**Files:**
- Modify: frontend/src/components/MessageList.tsx:1-48
- Modify: frontend/src/components/MessageList.test.tsx
- Modify: frontend/src/App.tsx:160-180
- Modify: frontend/src/styles.css:4-20

- [ ] Step 1: Write the failing auto-scroll test

Render MessageList, define a writable scrollHeight on .message-list, rerender with an appended assistant message, and assert scrollTop equals the new scrollHeight after waitFor. This must fail before the ref/effect exists because scrollTop remains unchanged.

- [ ] Step 2: Run the test and verify RED

Run: npm test -- --run src/components/MessageList.test.tsx

Expected: the new auto-scroll assertion FAILS while existing markdown/tool tests pass.

- [ ] Step 3: Implement the scroll effect and move Composer into the center column

In MessageList, attach useRef<HTMLDivElement> to the list and run:

    useEffect(() => {
      const element = listRef.current;
      if (element) element.scrollTop = element.scrollHeight;
    }, [messages]);

In App, render a .center-panel inside the workbench. Put the existing .conversation and its footer .composer inside this center panel; remove the old footer outside the workbench. Keep the existing send/stop/interaction behavior unchanged.

- [ ] Step 4: Apply fixed/independent scrolling CSS

Change the root/workbench rules to height: 100vh; min-height: 0; overflow: hidden, make .workbench the only grid viewport, add .center-panel { display:flex; flex-direction:column; min-width:0; min-height:0; }, set .conversation { flex:1; min-height:0; overflow:hidden; }, keep .message-list { overflow-y:auto; min-height:0; }, set .left-panel, .right-panel { min-width:0; min-height:0; overflow-y:auto; }, and remove the old .composer left padding (padding: 12px 24px 18px 264px).

- [ ] Step 5: Run the focused layout tests and verify GREEN

Run: npm test -- --run src/components/MessageList.test.tsx src/App.test.tsx

Expected: auto-scroll, existing App behavior, and all prior message tests PASS.

- [ ] Step 6: Commit the scrolling/layout unit

    git add frontend/src/components/MessageList.tsx frontend/src/components/MessageList.test.tsx frontend/src/App.tsx frontend/src/styles.css
    git commit -m "调整 GUI 三栏滚动与消息自动跟随"

### Task 4: 实现可拖拽分隔线与三栏宽度状态

**Files:**
- Create: frontend/src/components/ResizeDivider.tsx
- Create: frontend/src/components/ResizeDivider.test.tsx
- Modify: frontend/src/App.tsx:1-190
- Modify: frontend/src/styles.css:8-20

- [ ] Step 1: Write failing divider interaction tests

Test a left divider with value={240}, min={220}, max={420}: fire pointer down at x=100, move to x=180, and assert onChange(320); then move far left/right and assert callbacks never exceed the bounds. Also assert role="separator", aria-orientation="horizontal", and aria-valuenow.

- [ ] Step 2: Run divider tests and verify RED

Run: npm test -- --run src/components/ResizeDivider.test.tsx

Expected: FAIL because the component does not exist.

- [ ] Step 3: Implement the Pointer Events divider

Create a controlled component with pointerdown, pointermove, pointerup, and pointercancel. Store the initial pointer coordinate/value in a ref, call onChange with the clamped value on movement, set pointer capture while dragging, and release it when finished. Render the required separator ARIA attributes and a data-side attribute for styling.

- [ ] Step 4: Add width state and grid columns to App

Initialize leftWidth to 240 and rightWidth to 300. Render the workbench as five children: left panel, left divider, center panel, right divider, right panel. Use this style value:

    style={{ gridTemplateColumns: leftWidth + "px 8px minmax(420px, 1fr) 8px " + rightWidth + "px" }}

The left drag callback clamps to 220–420 and to window.innerWidth - rightWidth - 436; the right callback clamps to 240–480 and to window.innerWidth - leftWidth - 436, preserving at least 420px for the center plus two 8px dividers. Pass the current width to each divider for aria-valuenow.

- [ ] Step 5: Style the dividers and run focused tests

Add .resize-divider { cursor: col-resize; background: transparent; }, a visible hover/drag pseudo-element, and touch-action: none. Run npm test -- --run src/components/ResizeDivider.test.tsx src/App.test.tsx; expect all tests PASS.

- [ ] Step 6: Commit the resize unit

    git add frontend/src/components/ResizeDivider.tsx frontend/src/components/ResizeDivider.test.tsx frontend/src/App.tsx frontend/src/styles.css
    git commit -m "支持 GUI 三栏分隔线拖拽调整"

### Task 5: 全量验证与最终检查

**Files:**
- Modify: none unless a failing regression requires a focused correction.

- [ ] Step 1: Run the complete frontend verification

Run from frontend:

    npm test -- --run
    npm run build

Expected: every Vitest test passes and Vite produces a production build.

- [ ] Step 2: Run the complete repository verification

Run from the repository root:

    uv run pytest -q
    uv run ruff check src tests
    uv run pyright
    git diff --check

Expected: Python tests pass with only the repository’s existing skips, static checks pass, and git diff --check prints nothing.

- [ ] Step 3: Review the final diff and status

Run: git diff HEAD~5..HEAD --stat && git status --short

Confirm only the picker, Session rename, scroll/layout, divider, and their tests/docs changed; confirm the working tree is clean.

- [ ] Step 4: Commit any focused verification correction

If a test exposes a defect, add a regression test first, make the smallest correction, rerun the affected test, and commit it with a Chinese message describing that correction. If all checks pass, no extra commit is needed.
