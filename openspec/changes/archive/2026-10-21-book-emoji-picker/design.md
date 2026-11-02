# Design

## Context

Book 表单的「图标」字段现在是一个 `maxlength="8"` 的文本框（`app/templates/admin/book_form.html`），服务端只做 `strip()`，`books.icon` 是 `String(32)`。模板已有一批组件类（`.card` `.btn` `.field` `.badge`），前端只有 `theme.js` 与 `app.js` 两个小脚本，**无构建、无第三方库、CSP 禁内联脚本**（`script-src 'self'`）。

## Goals / Non-Goals

**Goals:**

- 管理员点两下就能选一个图标，不再需要知道 emoji 输入法。
- 清单离线可用、可版本化、易维护（想加就改一个 Python 列表）。
- 不改变 API 与数据模型；不引入任何外部依赖。

**Non-Goals:**

- 不做图标搜索/上传图片/自定义 SVG 图标（图片上传属于后续"附件"能力）。
- 不改前台图标渲染逻辑（空值仍回退内置矢量图标）。

## Decisions

### D1. 清单放 Python 常量，不放 JSON/数据库

`app/services/emoji.py` 定义 `EMOJI_GROUPS: list[tuple[str, list[str]]]`，附 `total_emojis()` 与 `is_known_emoji()` 辅助函数。好处：随代码走、无需额外静态文件、测试可直接断言数量。

- 备选被否：数据库表（要迁移，且这是纯前端数据）；JSON 静态文件（多一次请求，且 CSP/缓存都要重新考虑）。

### D2. 面板用原生 `<details>` + 按钮网格，事件用委托

模板里 `<details class="emoji-picker">` 包住分组网格，每个按钮 `<button type="button" data-emoji="📘" title="文档">`；`app.js` 用一次 `click` 委托处理 `[data-emoji]`，把值写进 `#icon` 并刷新预览。

- 不用 `<dialog>`/自定义弹层：`details` 键盘可达、无需焦点管理、CSP 与样式成本都最低。
- 不写内联 `onclick`（会被 CSP 拦，测试也会断言无内联脚本）。

### D3. 手工输入优先，长度放宽到 16

输入框保留，`maxlength` 提到 16：像 `🏴‍☠️`（ZWJ 序列）这类图标超过 8 个码元，原来的限制会截断成残片。服务端仍只做 `strip()` + 32 字符上限（模型约束），不做白名单校验——自定义字符（如 `◆`、`A`）也应被接受。

### D4. 预览与清空

输入框右侧一个 40×40 的预览块（`.emoji-preview`）实时显示当前值，空值显示内置矢量图标；旁边一个「清空」按钮把值置空。预览由 `app.js` 在 `input` 事件与点选时更新。

## Risks / Trade-offs

- **不同操作系统的 emoji 字形不同**（Windows Segoe UI Emoji / macOS Apple Color Emoji）→ 面板只负责"选什么字符"，具体字形交给系统；文档里说明这一点。
- **清单维护成本** → 放在一个文件里、按分组排列，新增只需往列表里加一项，测试会校验总数 ≥100 与去重。
- **组合序列被截断** → 已把 maxlength 提到 16，并在数据里避开超长 ZWJ 序列（如家庭/职业组合）。

## Migration Plan

无数据迁移；纯前端资源与模板变更，重建镜像即可。回滚 = revert 提交。

## Open Questions

无。
