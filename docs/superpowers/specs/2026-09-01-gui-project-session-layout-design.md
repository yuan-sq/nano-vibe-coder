# GUI 项目选择、Session 管理与可调整布局设计

## 背景与目标

当前 V3 GUI 已经具备项目列表、Session 列表、消息流和 Plan/Diff/Trace 面板，但项目新增仍依赖浏览器 `prompt` 输入路径，Session 只能使用后端生成的默认标题，三栏宽度固定且左右栏会参与整体滚动。此次改动的目标是让本地 macOS 使用流程更自然，同时不改变现有 Session/Agent API 和实时事件协议：

1. 用 macOS 原生文件夹选择器选择项目目录。
2. 保持新建 Session 的默认名称为“新建 Session”，并支持在前端内联重命名。
3. 让左栏、右栏固定在各自滚动容器中，只有中间消息列表滚动；消息或流式内容变化后自动跟随最新内容。
4. 允许拖动两条分隔线调整三栏宽度，并对宽度设置安全边界。

## 方案与边界

### 项目选择

浏览器不能安全地向后端提供用户选择目录的绝对路径，因此不使用 `<input type="file">` 或 `showDirectoryPicker()`。后端新增 macOS 专用选择接口，在运行 GUI 服务的本机进程中执行：

```text
osascript -e 'POSIX path of (choose folder with prompt "选择项目目录")'
```

接口在后台线程中运行该进程，避免阻塞 FastAPI 事件循环。用户取消时返回明确的 `project_selection_cancelled` 错误，前端不显示错误红条；命令失败或返回无效目录时显示可读错误。选择成功后由同一接口完成现有项目注册逻辑并返回项目元数据，避免前端先拿路径再发第二个请求造成竞态。保留现有 `POST /api/v1/projects` 作为内部/测试 API，但 GUI 的“＋”按钮不再调用路径输入弹窗。

### Session 重命名

后端已有 `PATCH /api/v1/sessions/{session_id}` 和 `SessionStorage.update_session`，不新增数据模型。Session 创建接口继续使用“新建 Session”作为默认标题。

前端 Session 列表项提供编辑按钮，并支持双击标题进入编辑状态。编辑态使用受控输入框：

- Enter 或失焦：去除首尾空白后保存；空字符串恢复原标题，不发送无效请求。
- Escape：放弃编辑并恢复原标题。
- 保存期间禁用输入，避免重复 PATCH；失败时恢复原标题并显示错误。
- 保存成功后更新 React Query 的 Session 列表缓存，当前 Session 的标题立即可见，无需刷新页面。

编辑按钮和输入框阻止点击事件冒泡，不能意外切换 Session。默认“新建 Session”不需要前端特殊分支。

### 三栏布局与滚动

应用根布局采用 `height: 100vh` 和 `overflow: hidden`。顶部栏保持固定高度；工作区使用 CSS Grid，列定义由 React 状态提供：

```text
minmax(220px, leftWidth) minmax(420px, 1fr) minmax(240px, rightWidth)
```

工作区中间列改成垂直 flex 容器，包含会话标题、消息列表、审批卡和发送框；发送框不再位于工作区外，也不使用左侧补偿 padding。左栏和右栏使用 `overflow-y: auto`，中间列设置 `min-height: 0`，只有 `.message-list` 设置 `overflow-y: auto`。这样侧栏滚动位置独立，发送框始终位于中间列底部。

消息列表使用 `ref` 指向滚动容器，在消息数组或消息内容更新后把 `scrollTop` 设为 `scrollHeight`，覆盖模型 token 流式追加和工具输出更新。该产品当前要求始终跟随最新消息，因此不实现“用户向上浏览时暂停自动滚动”的分支。

### 可拖拽分隔线

工作区在左栏/中间列和中间列/右栏之间各渲染一个语义化分隔线元素。分隔线使用 Pointer Events：`pointerdown` 记录起始指针位置和起始宽度，捕获指针；`pointermove` 根据水平位移更新对应栏宽度；`pointerup`/`pointercancel` 释放捕获。宽度限制如下：

- 左栏：220–420px。
- 右栏：240–480px。
- 中间列至少保留 420px；当窗口过窄时以中间列最小宽度优先，分隔线不允许把内容挤出可视区域。

拖拽时仅更新内存中的本次页面布局，不写入后端或 SessionSnapshot。分隔线提供 `role="separator"`、水平 `aria-orientation` 和 `aria-valuenow`；键盘调整不是本次范围，鼠标拖拽是主要交互。指针悬停和拖拽时使用水平调整光标。

## 组件与数据流

### 后端

- `src/nano_vibe/gui/app.py`：新增 `POST /api/v1/projects/select`，认证方式与现有项目接口一致；调用选择器并注册项目。
- `src/nano_vibe/gui/project_picker.py`：封装 macOS `osascript` 调用、取消/进程失败/无效目录错误，便于单元测试和未来替换实现。
- `tests/unit/test_gui_api.py`：覆盖成功选择、用户取消和选择器失败；通过依赖注入或 monkeypatch 禁止测试弹出真实系统窗口。

### 前端

- `frontend/src/lib/api.ts`：增加 `selectProject()` 和已有 `updateSession()` 的调用测试。
- `frontend/src/App.tsx`：调用项目选择接口；维护编辑 Session 状态、布局宽度状态和分隔线拖拽事件；把 Composer 移入中间列。
- `frontend/src/components/SessionList.tsx`：承载 Session 列表、选择和内联重命名，避免继续把列表逻辑堆在 `App.tsx`。
- `frontend/src/components/ResizeDivider.tsx`：提供受边界限制的 Pointer Events 分隔线。
- `frontend/src/components/MessageList.tsx`：增加消息滚动容器 ref 和更新后滚动逻辑。
- `frontend/src/styles.css`：实现固定工作区、独立滚动、可拖拽分隔线和编辑态样式；移除旧的全局 Composer 补偿布局。
- 对应组件测试覆盖 API 调用、重命名键盘/失焦行为、拖拽边界、消息自动滚动和分隔线语义属性。

## 错误处理与兼容性

- 项目选择取消是正常用户操作，不在页面显示错误；其他选择器错误显示在项目栏并允许再次点击“＋”。
- Session 重命名失败不改变缓存中的旧标题，并显示现有错误区域的错误信息。
- 分隔线拖拽仅影响前端本地状态；窗口尺寸变化不会触发后端请求。
- WebSocket 断开、Agent 运行和审批交互沿用现有逻辑，不因布局重排而改变生命周期。
- 本次仅实现 macOS 原生选择器；在非 macOS 环境调用接口时返回明确的 `project_picker_unavailable`，不伪装成浏览器目录选择。

## 测试策略

1. 后端：使用 FastAPI TestClient 测试项目选择接口，注入成功路径、取消和失败三种选择器结果；验证成功项目写入存储。
2. 前端 API：验证 `selectProject()` 的请求方法/路径以及 `updateSession()` 的 PATCH 请求体。
3. 前端交互：验证默认 Session 标题、双击/编辑按钮、Enter/失焦保存、Escape 取消、空标题处理和失败恢复。
4. 布局交互：验证消息列表滚动到最新消息、左右栏滚动容器样式存在、分隔线 Pointer Events 更新宽度并遵守最小/最大边界。
5. 回归：运行前端全量测试与构建，再运行仓库约定的 Python 测试、ruff、pyright 和 `git diff --check`。

## 非目标

- 不实现跨平台系统文件夹选择器。
- 不把布局宽度写入配置文件或跨设备同步。
- 不修改 Agent、SessionSnapshot、WebSocket 事件协议或权限语义。
- 不实现用户滚动上翻时暂停自动跟随、虚拟列表或复杂响应式移动端布局。
