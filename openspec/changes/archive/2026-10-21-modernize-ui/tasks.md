# Tasks

## 1. 设计系统与静态资源

- [x] 1.1 重写 `app/static/style.css` 为令牌层 + 基础层 + 组件层 + 页面层结构（含 `--bg/--surface/--text/--accent/--radius/--shadow/--space/--measure` 等令牌），验证 `:root` 之外没有硬编码色值（脚本扫描十六进制色值应为 0）
- [x] 1.2 为暗色主题补齐 `:root[data-theme="dark"]` 与 `@media (prefers-color-scheme: dark) :root:not([data-theme])` 两套变量，验证两套变量的键集合一致（脚本比对）
- [x] 1.3 新增 `app/static/theme.js`（读取/写入 `localStorage['bookhub-theme']`、设置 `data-theme`、更新 `theme-color`、绑定切换按钮），验证禁用脚本时页面仍跟随系统
- [x] 1.4 新增 `app/static/favicon.svg`，验证 `GET /static/favicon.svg` 返回 200 且 `content-type` 为 `image/svg+xml`
- [x] 1.5 重新生成 `app/static/pygments.css`，使高亮跟随 `data-theme`（亮/暗两套选择器都存在），验证暗色下代码块配色生效

## 2. 访客端页面

- [x] 2.1 重做 `base.html`：`<head>` 同步加载 `theme.js`、加入 favicon 与 `theme-color`、重排顶栏（品牌/搜索/主题切换/导航）、补 `aria-current`，验证既有测试全绿
- [x] 2.2 重做首页 `index.html`：Book 卡片网格、首页说明区、空态，验证 1440px 与 390px 下无整页横向滚动
- [x] 2.3 重做 Book 目录页 `book.html`：Book 头部信息 + 章节列表（序号/标题/字数/格式徽章）+ 空态，验证点击可进入章节
- [x] 2.4 重做章节阅读页 `chapter.html`：正文排版、TOC 侧栏（窄屏折叠为 details）、上下篇、底部元信息与 API 入口、打印样式，验证 `@media print` 规则存在并生效
- [x] 2.5 重做搜索结果页 `search.html` 与分页片段 `_pager.html`：结果卡片、命中高亮、空结果提示、分页控件，验证关键词仍被高亮
- [x] 2.6 重做统一错误页 `error.html`（404/403/500）并提供返回入口，验证访问不存在章节返回 404 且含状态码与返回链接

## 3. 管理端页面

- [x] 3.1 重做 `admin/base.html`：品牌区、分组导航、当前项高亮（`aria-current`）、底部返回站点与退出、窄屏横向导航，验证各管理页仍能打开
- [x] 3.2 重做 `admin/login.html`：居中卡片、错误提示、字段标签关联，验证错误密码返回 401 且提示可见
- [x] 3.3 重做 `admin/dashboard.html`：统计卡 + Book 表格（可见性徽章、章节数、更新时间、操作区），验证危险操作有独立视觉与二次确认
- [x] 3.4 重做 `admin/book_form.html` 与 `admin/book_detail.html`：表单分区 + 字段级错误、章节表格（状态徽章、排序按钮、危险操作独立区块），验证空标题提交返回 400 且错误就近显示
- [x] 3.5 重做 `admin/chapter_form.html`：正文编辑区 + 右侧元信息栏（格式/状态/上传/编码/版本备注）+ 预览与版本入口，验证 GB18030 上传仍能入库
- [x] 3.6 重做 `admin/versions.html`、`admin/version_detail.html`、`admin/diff.html`：版本表格、版本详情、差异对比（增删行配色与行号），验证 diff 页仍渲染差异行
- [x] 3.7 重做 `admin/trash.html`、`admin/users.html`、`admin/settings.html`、`admin/audit.html`：空态、表格、表单与筛选区，验证恢复与账号操作仍可用

## 4. 可访问性与响应式细节

- [x] 4.1 补齐控件标签关联与 `aria-label`（图标按钮、TOC、分页、状态徽章），验证页面中不存在无名称的交互元素
- [x] 4.2 实现统一 `:focus-visible` 焦点环与 `prefers-reduced-motion` 关闭动效，验证键盘 Tab 可见焦点
- [x] 4.3 校验亮/暗两套主题下正文与次要文字对比度 ≥4.5:1，脚本计算并输出结果
- [x] 4.4 验证 390px / 768px / 1440px 三档宽度下首页、阅读页、管理端列表均无整页横向滚动

## 5. 验证与文档

- [x] 5.1 新增 `tests/test_presentation.py`：断言页面含 `theme.js`、`favicon.svg`、`aria-current`，CSP 未放宽（`script-src 'self'`），`style.css` 同时含亮暗令牌，并保持 `pytest` 全绿
- [x] 5.2 用内置浏览器逐页截图复核（首页、目录、阅读、搜索、仪表盘、章节编辑、差异对比），确认无样式缺失、无乱码、无重叠
- [x] 5.3 运行 `scripts/e2e_admin_flow.py`，确认改版后 14 步业务流仍全部通过
- [x] 5.4 更新 `README.md`：新增「界面与主题」一节（三态切换、改强调色、favicon 位置、暗色说明）
- [x] 5.5 `openspec validate modernize-ui --strict` 通过，`tasks.md` 全部勾选

## Workflow follow-up

- 归档本变更，使 `web-presentation` 进入 `openspec/specs/`。
