# Design

## Context

- 现状：`app/static/style.css` 316 行单文件，20 个 Jinja2 模板，**无构建链、无 CSS 框架、无 CDN**（内网部署）。已有类名如 `card` `btn` `table` `field` `badge` `alert` `empty` `pager` `reader` `admin-shell` `diff`。
- 约束一：CSP 是 `script-src 'self'`（禁内联脚本）、`style-src 'self' 'unsafe-inline'`（允许 `style=` 属性）。主题初始化脚本必须是外部文件，否则会被 CSP 拦掉。
- 约束二：模板里的上下文变量名与表单字段名**不能改**（155 个测试断言页面文本与提交字段），只能改结构、类名与展示。
- 约束三：镜像里不含 Node，静态资源必须直接进镜像，不走打包。

## Goals / Non-Goals

**Goals:**

- 一套 CSS 变量驱动的设计系统，所有页面组件从同一批组件类派生；改强调色只改一个变量。
- 亮/暗/跟随系统三态主题，首屏无闪烁，禁用 JS 时仍跟随系统。
- 访客端（首页/目录/阅读/搜索/错误）与管理端（13 个页面）视觉语言一致、信息层次清晰。
- 可访问性基线：焦点可见、对比度、`aria-current`、触控目标尺寸、`prefers-reduced-motion`。
- 零依赖、零构建、零外部网络请求。

**Non-Goals:**

- 不换前端技术栈（仍是服务端渲染 + 少量原生 JS）。
- 不引入 Tailwind/Bootstrap 等框架，不做 CSS-in-JS。
- 不改变任何 URL、状态码、权限、API 契约、数据模型（见 proposal.md 的 Capabilities 说明）。
- 不在本次实现图片上传、章节层级等功能缺口。

## Decisions

### D1. 手写 CSS 变量体系，不引框架

| 方案 | 评估 | 结论 |
| --- | --- | --- |
| 手写 + CSS 变量（选中） | 零依赖、随镜像走、CSP 友好；维护靠约定 | 采用 |
| Tailwind | 需要 Node 构建链与内容扫描，把前端构建塞回镜像；类名会污染模板 | 否 |
| Bootstrap | 默认观感重、覆盖成本高于重写；体积大 | 否 |
| 现成文档主题（如 Docsify/MkDocs 皮肤） | 与现有 Jinja 结构不兼容 | 否 |

实现上把样式拆成"令牌层 → 基础层（reset/typography）→ 组件层（.btn/.card/.table…）→ 页面层（.reader/.admin-shell）"，单文件内用注释分段，约 900 行。

### D2. 主题：`data-theme` + 变量，外部脚本首屏设置

- `:root` 定义亮色令牌；`:root[data-theme="dark"]` 覆盖为暗色令牌；`@media (prefers-color-scheme: dark)` 里的覆盖用 `:root:not([data-theme])` 包住，保证"跟随系统"且无 JS 时也生效。
- 三态存 `localStorage["bookhub-theme"]`（`auto`/`light`/`dark`），`app/static/theme.js` 在 `<head>` 中**同步**加载并写入 `data-theme`，避免闪白；切换按钮用同一份脚本处理，并把状态同步到 `<meta name="theme-color">`。
- 备选被否：纯 CSS `prefers-color-scheme`（用户无法手动切）；内联脚本（CSP 拦截）。

### D3. 语义化令牌，禁止组件写死颜色

```css
--bg, --bg-subtle, --surface, --surface-hover, --border, --border-strong,
--text, --text-muted, --text-faint, --accent, --accent-hover, --accent-soft,
--danger, --danger-soft, --success, --warning,
--radius-sm/md/lg/full, --shadow-sm/md/lg, --space-1..8,
--font-sans, --font-mono, --measure, --header-h
```

组件层只引用这些变量；暗色主题只替换变量值，不改选择器。

### D4. 排版与布局尺度

- 正文 16px / 行高 1.75，`--measure: 72ch`；标题 4 级（2rem / 1.5rem / 1.25rem / 1.0625rem）。
- 阅读页：≥1024px 为「正文 + 260px TOC 侧栏」两栏；更窄时 TOC 收进 `<details>`，正文单栏。
- 管理端：≥960px 固定 232px 侧栏 + 内容区；更窄时侧栏变为横向可滚动导航条。
- 代码块与表格统一 `overflow-x:auto`，不允许撑破容器。

### D5. 组件清单（类名保持向后兼容）

按钮（`btn` + `btn-primary/secondary/ghost/danger` + `btn-sm`）、卡片（`card` + `card-header/body/footer`）、表格（`table` 外层 `.table-wrap`）、表单（`field` `hint` `field-error`）、徽章（`badge` + 语义色）、提示条（`alert` + 语义色）、空态（`empty`）、分页（`pager-bar`）、TOC（`toc-side`）、面包屑（`breadcrumb`）、统计卡（`stat`）、差异表（`diff`）、侧栏（`admin-shell` `admin-side`）。

已存在的类名一律保留语义，只重写样式；新增类名用于结构分层（如 `.page-head` `.toolbar` `.section`）。

### D6. 图标：内联 SVG，不用 emoji 当功能图标

功能图标（搜索、主题、编辑、删除、移动、外部链接等）以内联 `<svg>` 片段（Jinja `{% include "icons/xxx.svg" %}` 或宏）使用，`stroke="currentColor"` 继承文字色；Book 的 `icon` 字段仍保留 emoji 作为内容标识。

### D7. 站点标识

新增 `app/static/favicon.svg`（圆角方块 + 字母 B，颜色取 `--accent` 的亮色值），模板加 `<link rel="icon" type="image/svg+xml">`、`<link rel="mask-icon">` 可省，`<meta name="theme-color">` 随主题切换。

### D8. 迁移方式：一次性替换 + 逐模板收敛

先落地令牌与组件层（此时旧模板仍能看），再逐个模板迁移结构；每改完一个模板跑一次 `pytest`，避免大爆炸式回归。旧类名保留，不做重命名。

## Risks / Trade-offs

- **模板改动面大（20 个文件）导致回归** → 每个模板改完即跑 `pytest`；关键页面用内置浏览器截图 + 视觉复核。
- **暗色对比度不足** → 暗色调色板按 WCAG AA（正文 ≥ 7:1、次要文字 ≥ 4.5:1）取值；新增单测断言暗色选择器与变量存在。
- **主题脚本被 CSP 拦掉或闪白** → 只用外部脚本、放在 `<head>` 且非 defer；单测断言页面含 `theme.js` 且 CSP 未放宽 `script-src`。
- **打印样式退化** → 保留并重写 `@media print`（隐藏导航/侧栏/分页，正文满宽、黑白友好）。
- **emoji 图标与 SVG 混用显得不统一** → 只把"功能入口"换成 SVG，内容型 emoji（Book icon）保留，属于刻意选择。
- **样式文件变大使维护变难** → 文件内按层分节 + 令牌注释，新增组件只允许引用令牌。

## Migration Plan

1. 纯前端资源替换，无数据库/接口变更；部署即重建镜像（静态文件在镜像内）。
2. 回滚 = `git revert` 本次提交（或回退镜像 tag），数据不受影响。
3. 浏览器缓存：静态文件未加 hash，靠 `Cache-Control` 默认；升级后用户强刷即可。

## Open Questions

- 站点 logo 图片上传（需要附件能力）——本次用 SVG favicon + 文字标识，等附件能力落地后再补。
- 是否需要"阅读密度"开关（紧凑/宽松）——观察反馈后再决定，不影响本次结构。
