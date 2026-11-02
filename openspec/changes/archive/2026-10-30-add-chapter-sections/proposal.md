# Proposal

## Why

现在的模型是 `Book →（可选分卷）→ 章节`，而「章节」既是目录里的一行，又是一段正文、一个版本、一个页面。三件事叠在一起带来两个问题：

1. **分卷不好理解**：它和「分组」并列，却只能装章节，读者和编辑都要先分清「分组是 Book 的上层、分卷是 Book 的内部」；而且分卷还让目录多了一层编号（1 / 1.1）。
2. **一章装不下多个文件**：真实的文档经常是「第 1 章」下面有「1.1 概述.md」「1.2 架构.md」「1.3 示例.html」三个文件。现在只能拆成三个并列章节，或者把内容硬塞进一篇里；同一章里想混排 Markdown 与 HTML 文件根本做不到（格式是 Book 级的）。

## What Changes

- **删掉分卷**：章节直接排在 Book 下，编号回到 `1.`、`2.`、`3.`。存量分卷里的章节提升到章层并按原顺序重排，旧地址不变。
- **章变成容器，节是内容单元**：一章可包含多个文件，每个文件就是一节（自带标题、格式、正文、版本）。新建/编辑章节时可以一次上传多个 `.md` / `.html`，一个文件生成一节。
- **节是独立页面**：`/b/<book>/<chapter>/<section>`；章页 `/b/<book>/<chapter>` 在**只有一节时直接显示正文**（兼容存量链接），多节时列出该章的节。
- **版本按节记**：每节有自己的 v1/v2 与历史、diff、回滚；章本身不再有版本（只是容器）。
- **格式下放到节**：节自己决定 Markdown 还是 HTML，Book 的「文档类型」降级为**默认格式**（新建节时预选），不再锁死整本。
- **发布状态留在章级**：章发布 → 其下所有节同时对外可见；节不单独设草稿（避免"半章可见"）。
- 搜索、站点地图、Webhook、只读 API 全部改到**节粒度**（正文、URL、版本号都属于节）。

## Capabilities

### New Capabilities

- `chapter-sections`: 章与节的所有权关系、节级版本与回滚、节级 URL 与序号（1.1 / 1.2）、多文件上传生成多节、以及「章页在单节时直出正文」的兼容语义。

### Modified Capabilities

- `chapter-lifecycle`: 内容、格式、版本、slug 从章移到节；章只保留标题、序号与发布状态。
- `public-reading`: 目录变两级（章 → 节），新增节页；章页在多节时作为该章的节索引。
- `management-api`: 章/节契约拆分（章不再返回正文与版本号，改为返回 `sections[]`）。
- `web-presentation`: 后台章节编辑器改为「章信息 + 节列表 + 单节编辑器」；支持一次上传多个文件。
- `book-catalog`: Book 的 `format` 由「整本锁定」降级为「默认格式」。
- `search-and-index`: 全文索引按节建立；搜索结果显示到节，链接指向节页。
- `service-deployment`: 迁移 `0015_chapter_sections` 必须保证存量数据零丢失、旧链接可用。

## Impact

- **数据**：新建 `chapter_sections` 与 `section_versions`；`chapters` 去掉 `content_*` / `format` / `current_version_no` / `kind` / `parent_id`；`chapter_versions` 数据迁到 `section_versions`；分卷行删除、其子章节提升。
- **服务层**：`chapters.py` 拆成「章」与「节」两组函数；`versions`/`diff`/`rollback` 改为节级；`search.py` 索引节；`media` 引用扫描适配节。
- **Web**：`/b/{book}` 目录两级；新增 `/b/{book}/{chapter}/{section}`；后台 `chapter_form` 拆分 + `section_form`；`book_detail` 章节表加「节数」列。
- **API**：`GET /books/{ref}/chapters/{ref}` 返回 `sections[]`；新增节级端点；`/search`、`/sitemap.xml` 输出节。
- **测试**：`tests/test_sections.py` 新增；现有约 60 条依赖「章节有正文」的用例需迁移到节。
- **非目标**：不做章内节的拖拽排序（沿用序号）、不做跨章移动节、不做节级权限、不做 PDF/图片作为节（仍走媒体库）。
