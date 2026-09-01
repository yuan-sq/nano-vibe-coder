# Session 右键重命名设计

## 目标

将左侧 Session 列表的铅笔编辑按钮替换为右键菜单入口。用户右键点击 Session 后看到一个自定义菜单，菜单只有“重命名”一项；点击该项进入已有的内联编辑输入框。

## 交互

- Session 行保留普通左键选择行为。
- contextmenu 事件调用 preventDefault()，阻止浏览器原生菜单，也不触发 Session 选择。
- 菜单定位在右键指针附近，并限制在浏览器可视区域内，避免菜单超出窗口。
- 菜单只显示“重命名”按钮。
- 点击“重命名”后关闭菜单，输入框自动获得焦点并沿用已有保存流程：
  - Enter 或失焦保存去空格后的非空标题；
  - Escape 取消；
  - 空标题或原标题不发送请求；
  - 保存失败恢复原标题并显示错误。
- 点击菜单外、按 Escape 或页面滚动时关闭菜单。
- 同一时间最多显示一个菜单；打开另一个 Session 的菜单会替换当前菜单。
- 删除铅笔按钮和双击重命名入口，不改变后端 PATCH 接口。

## 实现边界

### SessionList

在 frontend/src/components/SessionList.tsx 中新增菜单状态：

    contextMenu = { sessionId, x, y } | null

Session 按钮增加 onContextMenu，根据 clientX/clientY 打开菜单。组件通过 document 的 mousedown、keydown 和 scroll 监听关闭菜单，并在卸载时移除监听。监听器只在菜单打开时注册，避免影响普通列表交互。

菜单使用 role="menu" 和一个 role="menuitem" 按钮；菜单按钮点击时停止冒泡、关闭菜单并进入对应 Session 的编辑状态。编辑状态仍使用现有受控 input、保存锁和错误回调。

### 样式

在 frontend/src/styles.css 中移除 .session-edit 样式，新增固定定位的 .session-context-menu 和 .session-context-menu button 样式。菜单使用白色背景、边框、阴影和当前 GUI 的紫色交互色；z-index 高于侧栏内容。

## 测试

扩展 frontend/src/components/SessionList.test.tsx：

1. Session 行不再渲染铅笔按钮。
2. 右键点击显示“重命名”，且不调用 onSelect。
3. 点击“重命名”进入输入框，Enter 仍调用 onRename。
4. Escape、点击菜单外和滚动关闭菜单。

运行前端全量测试和构建，确保现有项目选择、Session 保存、消息流和布局功能不回归。

## 非目标

- 不增加更多 Session 菜单项。
- 不修改后端 Session 数据模型或 PATCH 接口。
- 不实现系统级右键菜单。
- 不改变 Session 默认名称“新建 Session”。
