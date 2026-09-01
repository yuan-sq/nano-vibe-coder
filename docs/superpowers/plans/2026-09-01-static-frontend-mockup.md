# V3 Static Frontend Mockup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a self-contained `frontend/mockup.html` that reproduces the complete V3 GUI with editable visual tokens and local-only interactions.

**Architecture:** Keep the artifact independent from React, Vite, FastAPI, and external assets. Use semantic HTML for the three-column workbench, CSS custom properties for visual tuning, and a small inline script that switches the inspector tabs and relies on native `<details>` disclosure controls.

**Tech Stack:** HTML5, CSS custom properties, vanilla JavaScript, native browser APIs only.

---

### Task 1: Build the static workbench markup and visual system

**Files:**
- Create: `frontend/mockup.html`

- [ ] **Step 1: Add the document shell and editable token block**

Create an HTML5 document with `lang="zh-CN"`, viewport metadata, and an inline `<style>` block. Put the editable `:root` variables at the top of the style block: `--font-body`, `--font-mono`, `--color-bg`, `--color-surface`, `--color-border`, `--color-primary`, `--color-primary-soft`, `--color-text`, `--color-muted`, `--radius-sm`, and `--radius-md`. Do not load remote fonts, icon libraries, images, or scripts.

- [ ] **Step 2: Add the complete three-column page structure**

Add semantic regions with these classes and contents:

- `.app-shell` containing `.topbar`, `.workbench`, and `.composer`.
- `.topbar` with `nano-vibe`, `V3`, and a green `已连接` status.
- `.project-sidebar` with a 项目 heading, add button, `test-repo`, its repository path, a Sessions heading, and at least five Session rows with one selected row.
- `.conversation` with the 工作 Session heading, `IDLE · Agent REQUIREMENTS`, one user message, one Markdown-style Agent response, one running tool disclosure, one completed tool disclosure, and one approval card.
- `.inspector` with a `.tabs` navigation for Plan, Diff, Trace and matching `.tab-panel` sections.
- `.composer` with a textarea placeholder `描述你要完成的任务…` and a disabled-looking 发送 button.

- [ ] **Step 3: Add representative static Plan, Diff, and Trace states**

Use fixed Chinese sample content:

- Plan: completed “检查仓库结构”, in-progress “实现静态页面”, and pending “验证页面效果”.
- Diff: `frontend/mockup.html` marked modified, with a collapsible unified patch showing added and removed lines; include a second collapsed file entry.
- Trace: runtime `IDLE`, Agent stage `REQUIREMENTS`, event sequence `98`, and at least four timestamped events.
- Tool cards: summaries must include tool name and parameters, while details contain command/output text.

- [ ] **Step 4: Add CSS for layout, typography, controls, cards, and responsive overflow**

Style the three-column grid, borders, selected project/session rows, user and Agent messages, Markdown headings/lists/code, tool disclosure summaries, approval actions, Plan status labels, Diff line colors, Trace rows, and the composer. Use only the root variables for color/font/radius decisions so later visual edits can be made without changing markup. Keep the body readable when opened at a desktop viewport and allow panels to scroll internally.

- [ ] **Step 5: Add local-only tab interaction**

Add an inline script that selects all `.tabs button` elements and `.tab-panel` elements. On click, remove `active` from all tabs/panels, add it to the clicked tab, and show only the panel whose `data-tab` matches the button’s `data-tab`. Set Plan active on initial load. Do not add network calls or form submission handlers.

- [ ] **Step 6: Verify the static artifact without a server**

Run from the repository root:

```bash
test -f frontend/mockup.html
rg -n 'nano-vibe|project-sidebar|conversation|inspector|Plan|Diff|Trace|--font-body|--color-primary' frontend/mockup.html
git diff --check
```

Expected: the file exists, every required region/token/tab appears, and `git diff --check` produces no output. Open `frontend/mockup.html` directly with a `file://` URL and verify that the initial Plan panel is visible and clicking Diff/Trace changes the visible panel without a console error.

- [ ] **Step 7: Commit the artifact**

```bash
git add frontend/mockup.html docs/superpowers/plans/2026-09-01-static-frontend-mockup.md
git diff --cached --check
git commit -m "新增前端静态视觉稿"
```
