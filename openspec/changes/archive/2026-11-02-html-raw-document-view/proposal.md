# Proposal

## Why

BookHub 的 HTML 章节一律走白名单净化：`<script>`、内联事件、`<style>`、inline `style`、`data:` 图片全部被移除。对"自己写的一页 Markdown/HTML 笔记"够用，但把一份**完整的、带自己样式与脚本的 HTML 文档**（导出的报告、单文件 wiki、交互 demo）上传进来后，样式没了、图片裂了、脚本不执行、文档自带的导航也失效——读者只能看到一份被剥干净的骨架。

同时，这类文档通常自带目录/导航（锚点列表、折叠侧栏、Tab），站点再塞一套「本页目录」反而重复。管理员需要能选择"这本书按上传时的原样提供"。

## What Changes

- Book 新增 `html_view` 字段（`inline` | `document`）：HTML Book **默认 `document`**（列默认值保留 `inline` 作安全兜底，由服务层按格式落值）；Markdown Book 恒为 `inline`。
- 存量 HTML Book 由一次性迁移 `0005_backfill_html_view` 统一回填为 `document`。
- 新增端点 `GET /b/{book_slug}/{chapter_slug}/raw`：把 `content_raw` **原样**输出为 `text/html`，不做任何净化。
- 该端点用 CSP `sandbox`（**不含 `allow-same-origin`**）把文档降级成唯一源：文档自己的 CSS / JS / 导航 / base64 图片全部生效，但读不到本站 Cookie、localStorage 与同源接口响应；另配 `Referrer-Policy: no-referrer`、`X-Robots-Tag: noindex`、`Cache-Control: no-store`。
- `html_view=document` 时，Book 目录里的章节链接直接指向 `/raw` 并 `target="_blank"`；章节页仍保留（站内净化版兜底），顶部横幅说明当前模式，并给「原始排版」按钮。
- `html_view=inline` 时行为不变；HTML 章节页只是多一条模式提示与「原始排版」入口。
- 管理端表单新增「HTML 阅读方式」下拉；Book 详情页显示当前模式徽章。`/api/v1` 的 Book 表示新增 `html_view`。
- `/raw` 命中计入 Book 热度（匿名访问，沿用同一去重窗口）。
- 明确**不支持**：文档里相对路径引用的 CSS/JS/图片（没有附件上传能力），需要 base64 或绝对 https URL。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `book-catalog`: Book 增加"HTML 阅读方式"元数据（创建/更新/校验/展示），Markdown Book 强制站内渲染。
- `chapter-content`: 新增"原始文档通道"——不净化、原样输出，安全边界由 CSP 沙箱承担，仅 HTML 章节可用。
- `public-reading`: 章节页增加模式提示与「原始排版」入口；阅读页原有 CSP 约束不变（沙箱只作用于 `/raw` 响应）。
- `content-api`: Book 表示新增 `html_view` 字段。

## Impact

- **数据**：迁移 `0004_book_html_view` 加列（`server_default='inline'`），`0005_backfill_html_view` 把存量 HTML Book 回填成 `document`；两条都有 downgrade。
- **服务层**：`books.resolve_html_view()` 统一校验；`create_book/update_book` 增加 `html_view`；`chapters.find_chapter(allow_unpublished=...)` 供 `/raw` 复用草稿预览规则。
- **Web**：`public.chapter_raw` 新路由 + `RAW_DOCUMENT_CSP`；`chapter.html` / `book.html` 增加入口与模式提示；`style.css` 增加 `.doc-view-bar`。
- **安全**：`/raw` 的响应不再受站点 CSP 约束，改为自有沙箱策略——这是本变更的核心风险点，写进 spec 与文档。
- **测试**：新增 `tests/test_html_view.py`（11 条），覆盖原文输出、CSP 头、草稿/格式 404、计热、模式切换与表单/API 字段。
- **文档**：`docs/reading.md`、`docs/authoring.md`、`docs/content-model.md`、`docs/api.md`、`README.md`。
