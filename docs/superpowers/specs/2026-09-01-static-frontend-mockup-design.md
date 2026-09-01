# V3 前端静态视觉稿设计

## 目标

创建一个可以直接双击打开的单文件 HTML，用于调整 nano-vibe V3 GUI 的字体、颜色、间距和组件视觉效果。该文件只展示固定示例数据，不连接 FastAPI、不读取 Session，也不改变正式 React 前端。

## 方案

使用 `frontend/mockup.html`，将 HTML、CSS 和少量交互 JavaScript 放在同一个文件中。

选择单文件的原因：

- 不依赖 npm、Vite 或后端服务，双击即可查看。
- 所有视觉变量集中在 `:root`，便于直接修改。
- 不会把视觉试验代码混入正式 React 组件。

## 页面结构

页面固定为三栏工作台：

1. 顶部栏：品牌 `nano-vibe V3` 和连接状态。
2. 左侧栏：项目名称、仓库路径、Session 列表和新增按钮。
3. 中间区：当前 Session 标题/状态、用户消息、Agent Markdown 回复、工具调用折叠卡片、审批卡片和底部输入区。
4. 右侧栏：Plan、Diff、Trace 三个标签页。

示例数据同时覆盖以下状态：空计划、已完成计划、运行中的工具、已完成工具、Diff 文件、Trace 事件和待审批请求。数据写在 HTML 中，修改文字不会影响正式 GUI。

## 可编辑视觉边界

文件顶部的 `:root` 定义主要视觉变量：

- `--font-body`：界面字体。
- `--font-mono`：工具参数、输出和 Trace 字体。
- `--color-bg`、`--color-surface`、`--color-border`：背景、卡片和边框。
- `--color-primary`、`--color-primary-soft`：按钮、选中状态和用户消息。
- `--color-text`、`--color-muted`：主文本和辅助文本。
- `--radius-sm`、`--radius-md`：控件和卡片圆角。

其余 CSS 使用语义化 class，方便在浏览器开发者工具或文件中定位。页面不引入外部字体、图标库或 CDN，避免离线打开时出现差异。

## 交互范围

内嵌 JavaScript 只实现视觉稿所需的本地交互：

- 切换 Plan、Diff、Trace 标签页。
- 展开/收起工具调用和 Diff 文件详情。
- 展示静态连接状态。

按钮不会发送真实消息、执行工具或修改文件。正式 GUI 的数据流、WebSocket 和权限逻辑保持不变。

## 验证方式

- 使用浏览器直接打开 `frontend/mockup.html`，确认页面无需服务端即可加载。
- 检查三栏布局、标签页切换、折叠详情和中文示例内容。
- 运行 `git diff --check`。

## 后续迁移

用户修改 `mockup.html` 后，比较 CSS 变量和语义化 class 的变更，将确认后的视觉规则迁移到 `frontend/src/styles.css` 及对应 React 组件；不直接复制静态稿中的示例数据或交互逻辑。
