# Tasks

## 1. 数据与权限

- [x] 1.1 `models.py` 增加 `HTML_VIEW_INLINE/HTML_VIEW_DOCUMENT/HTML_VIEWS` 与 `books.html_view`
- [x] 1.2 迁移 `0004_book_html_view`：加列（`server_default='inline'`）+ downgrade 删列
- [x] 1.3 迁移 `0005_backfill_html_view`：存量 HTML Book 回填 `document`，downgrade 回填 `inline`
- [x] 1.4 `books.resolve_html_view()` 校验取值，HTML Book 默认 `document`、Markdown Book 强制 `inline`；`create_book/update_book` 接入并写审计
- [x] 1.5 `chapters.find_chapter(allow_unpublished=...)`；`find_published_chapter` 改为委托

## 2. 原始文档通道

- [x] 2.1 `public.chapter_raw`：`GET /b/{book_slug}/{chapter_slug}/raw`，仅 HTML 章节，原样输出 `content_raw`
- [x] 2.2 `RAW_DOCUMENT_CSP`：`sandbox allow-scripts ...`（不含 `allow-same-origin`）+ 资源策略 + `form-action 'none'`
- [x] 2.3 响应头补 `Referrer-Policy: no-referrer`、`X-Robots-Tag: noindex, nofollow`、`Cache-Control: no-store`
- [x] 2.4 匿名访问计入 Book 热度（沿用去重窗口）；草稿仅登录用户可访问

## 3. 界面与 API

- [x] 3.1 管理端 Book 表单新增「HTML 阅读方式」；详情页显示模式徽章
- [x] 3.2 `book.html`：`document` 模式下章节链接指向 `/raw` 并 `target="_blank" rel="noopener"`，并加模式说明
- [x] 3.3 `chapter.html`：模式横幅 + 「原始排版」按钮；`style.css` 增加 `.doc-view-bar`
- [x] 3.4 `/api/v1` Book 表示新增 `html_view`

## 4. 测试

- [x] 4.1 `/raw` 返回未净化原文（`<style>`/`<script>`/`data:` 图片齐全）且 CSP 含 `sandbox allow-scripts`、不含 `allow-same-origin`
- [x] 4.2 草稿匿名 404、登录 200；Markdown 章节 `/raw` 404
- [x] 4.3 `/raw` 匿名访问计入热度且窗口内去重
- [x] 4.4 模式切换改变 Book 页链接与章节页提示；Markdown Book 强制 `inline`、非法值报错
- [x] 4.5 管理端表单持久化与详情徽章；API 暴露 `html_view`
- [x] 4.6 全量 `pytest`（204 条）与 `ruff` 通过

## 5. 文档与规格

- [x] 5.1 `docs/reading.md`：URL 表新增 `/raw`，新增「HTML 文档的原始排版」一节并顺延章节号
- [x] 5.2 `docs/authoring.md`：表单字段表 + 阅读方式说明（含相对路径与安全提示）
- [x] 5.3 `docs/content-model.md`：`books.html_view` 字段
- [x] 5.4 `docs/api.md`：Book 表示新增 `html_view`
- [x] 5.5 `README.md`：功能清单新增「HTML 原始排版」
- [x] 5.6 `openspec validate html-raw-document-view --strict` 通过
- [x] 5.7 重建镜像后在真实浏览器验证 `/raw` 的执行环境（`origin` 为 opaque、读不到 `document.cookie`）

## Workflow follow-up

- 归档本变更，使 `book-catalog` / `chapter-content` / `public-reading` / `content-api` 主规格包含原始文档通道。
- Safari 对顶层 CSP `sandbox` 的支持需在部署环境复测；不支持时的降级策略另起变更。
