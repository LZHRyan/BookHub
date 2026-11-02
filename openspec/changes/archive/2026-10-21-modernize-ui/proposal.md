# Proposal

## Why

BookHub 的功能面已经够用（Book/章节/版本/检索/只读 API），但**界面是"能用"而不是"想用"**：一套 316 行的样式表、emoji 当图标、卡片和表格几乎没有层次、没有站点标识（浏览器标签页连 favicon 都没有，`/favicon.ico` 直接 404）、只能跟随系统的亮/暗模式、空态和错误页是最小实现。内部知识库的成败往往取决于"同事愿不愿意打开它"，所以值得做一次系统性的视觉与交互重做，而不是继续在旧样式上打补丁。

## What Changes

**视觉体系（新增能力 `web-presentation`）**

- 重写 `app/static/style.css` 为一套自建设计系统：颜色/字号/行高/间距/圆角/阴影全部走 CSS 变量（`:root` + `[data-theme]`），页面组件只从统一组件类派生（`.card` `.btn` `.table` `.field` `.badge` `.alert` `.empty` `.toc` 等）。
- 字体阶梯与排版规则：正文 measure 控制在 68–76ch，标题按 4 级递减，代码/表格超宽横向滚动而不撑破布局。
- 现代文档站风格（Stripe Docs / Tailwind Docs 取向）：大标题、充足留白、细边框 + 轻阴影卡片、单一靛蓝强调色、克制的状态色。

**主题（亮/暗三态）**

- 顶部导航加三态切换：跟随系统 / 亮色 / 暗色，写入 `localStorage`，首屏由 `/static/theme.js` 在 `<head>` 同步执行设置 `data-theme`，避免闪白。
- 暗色调色板单独设计（不是简单反色），代码高亮同步切换（`pygments.css` 已按 `prefers-color-scheme` 提供两套，改为跟随 `data-theme`）。

**站点标识**

- 新增 SVG favicon（`app/static/favicon.svg`）+ `theme-color`，浏览器标签页有图标、移动端地址栏有品牌色。
- 站点名与页面标题格式统一为 `页面 · 站点名`；`<html lang="zh-CN">` 保持。

**全部页面重绘（不改变任何既有行为）**

- 访客端：首页（Book 卡片网格）、Book 目录页、章节阅读页（TOC 侧栏 + 上下篇 + 打印样式）、搜索结果页、404/403/500 错误页。
- 管理端：登录页、仪表盘（统计卡）、Book 表单、Book 详情（章节表）、章节编辑（双栏：正文 + 右侧元信息）、版本列表、版本对比、回收站、账号管理、站点设置、审计日志。
- 统一的空态、错误提示（`.alert`）、危险操作视觉隔离（放到独立区块，用 danger 描边而非实心红）。

**可访问性与响应式（小修）**

- 所有表单控件 `label`/`for` 关联、`aria-current` 标记当前导航、`aria-label` 补全图标按钮、`focus-visible` 明确焦点环。
- 移动端：顶栏搜索框折叠、管理端侧栏变横向滚动的导航条、表格横向滚动、触控目标 ≥ 40px。
- `prefers-reduced-motion` 下关闭过渡动画。

**不在本次范围（仅记录，供后续排期）**

功能缺口清单见下节；本次不实现图片/附件上传、章节层级、批量操作、拖拽排序、SSO、Book 级授权等。

## 现状与功能缺口（本次仅分析，不实现）

已实现（有测试与端到端证据）：Book/章节 CRUD 与排序、文件上传与编码识别、整体替换、草稿/发布、软删除与恢复、版本历史/对比/回滚、Markdown(GFM+高亮+锚点+TOC) 与 HTML 白名单净化、中文二元组全文检索、访客只读浏览与搜索、管理员会话/角色/CSRF/登录限流/账号管理/站点设置/审计日志、`/api/v1` 只读 API（ETag/304/导出/增量/限流/API Key/OpenAPI）、Docker 部署与备份恢复。

缺口（按影响排序，后续变更处理）：

1. **图片/附件上传**：正文只能引用外链图片，内网无图床时文档"有图不能看"。
2. **章节层级（分卷/父子）**：目录扁平，几十章后导航困难。
3. **站点品牌**：无 logo/封面图（本次只补 favicon 与配色）。
4. **批量操作与拖拽排序**：目前只能逐章上移/下移一格。
5. **搜索命中定位**：只给片段，点进正文不跳到命中位置。
6. **整站导出 / 审计导出**：目前只能按 Book 导出。
7. **API Key 管理界面**：只能改环境变量并重启。
8. **协作与集成**：SSO/OIDC、Book 级授权、评论纠错、Webhook 通知、阅读统计、定时发布、i18n。

## Capabilities

### New Capabilities

- `web-presentation`: 面向人与机器的界面表现契约——设计令牌与组件一致性、明暗主题与首屏无闪烁、站点标识与浏览器元信息、阅读页排版、导航与响应式、管理端信息密度、可访问性基线、空态与错误页、动效克制。

### Modified Capabilities

（无。现有 8 个能力规格描述的都是行为契约，本次不改变任何可见行为：URL、状态码、权限、API 契约、数据模型全部不动。）

## Impact

- **样式**：`app/static/style.css` 整体重写（约 316 → 900 行），`app/static/pygments.css` 改为跟随 `data-theme`，新增 `app/static/theme.js`、`app/static/favicon.svg`。
- **模板**：`base.html`、`index.html`、`book.html`、`chapter.html`、`search.html`、`error.html`、`_pager.html` 与 13 个 `admin/*.html` 全部调整结构与类名（不改变变量名与表单字段名，避免影响路由与测试）。
- **路由**：不新增业务路由；仅通过 `/static` 提供 `theme.js`、`favicon.svg`。
- **CSP**：主题脚本必须走外部文件（`script-src 'self'` 禁止内联），首屏由 `<head>` 中的同步 `<script src>` 设置主题，避免闪白。
- **测试**：现有 155 个测试必须继续通过（它们断言的是页面文本与行为，不是样式）；新增主题切换、favicon、`data-theme`、CSP 不被放宽的测试。
- **文档**：README 增加"界面与主题"一节，说明三态主题、如何改强调色（CSS 变量）与 favicon。
