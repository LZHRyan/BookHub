# Tasks

> 分两批交付：**A 批**完成后读者端已可读，**B 批**补齐后台与 API。两批各自可回滚。
>
> 实际执行时用户明确「当前数据不重要，可以抹除」，因此迁移不搬运存量数据（直接把 `chapters` 清空、旧表丢弃重建），比原计划简单，A2/A3 按此调整。

## A. 数据与读者端

- [x] A1 模型：`ChapterSection` / `SectionVersion`；`Chapter` 去掉正文与版本字段、去掉 `kind`/`parent_id`；`ChapterVersion` 删除
- [x] A2 迁移 `0015_chapter_sections`：删 `chapter_versions` → 清空 `chapters` → 条件删索引 → 删 10 个旧列 → 建 `chapter_sections` + `section_versions`；downgrade 反向重建（数据不还原）
- [x] A3 迁移自检脚本：`upgrade → downgrade → upgrade` 三次通过，`chapters` 只剩 11 列、分卷行 0、新表与索引齐全
- [x] A4 `sections.py` 服务：建/改/删节、按章列节、序号（章号.节号）、slug 去重、`publish` 继承章状态
- [x] A5 `chapters.py` 瘦身：只保留目录与状态；`published_chapters` 返回「章 + 可见节」
- [x] A6 路由 `/b/{book}/{chapter}` 双形态（单节直出 / 多节索引）、`/b/{book}/{chapter}/{section}`、`/raw` 下沉
- [x] A7 模板：`book.html` 目录两级、新增 `chapter_index.html`、`chapter.html` 改为节页
- [x] A8 搜索改节粒度（`chapter_fts` 改存节 id + `book_id`/`chapter_id`/`section_id`，迁移 `0016_section_index`）；`sitemap.xml` 收录章页与节页；`visits` 改按节记录（`section_view_daily`）并按章聚合出 Book 热度
- [x] A9 测试：单节直出、多节索引、节页 404（草稿章）、序号 1.1/1.2、搜索命中节

## B. 后台与 API

- [x] B1 后台章节编辑器：章信息（标题/slug/序号/状态）+ 节列表（标题/格式/字数/版本/操作）
- [x] B2 `section_form`：单节编辑（标题、slug、格式、正文、上传替换、编码、版本备注）
- [x] B3 多文件上传：`multiple` 文件一次生成多节（标题取文件名、格式按扩展名）
- [x] B4 `book_detail`：章节表显示「N 节」，行内不再直接给正文操作；分卷相关入口全部移除（`group_form.html` 一并删除）
- [x] B5 版本页/diff/回滚改节粒度；章页显示「该章各节的版本」
- [x] B6 管理 API：章表示改为 `sections[]`；节级 CRUD（`/books/{ref}/chapters/{ref}/sections...`）；`PATCH` 章节内容改为 `PATCH` 节
- [x] B7 Webhook：新增 `section.published` / `section.updated`；`chapter.*` 只在这些字段变化时发
- [x] B8 后台测试：建章 → 加三节 → 编辑某节 → 版本回滚 → 删除节 → 发布/撤回整章

## C. 收尾

- [x] C1 文档：`docs/authoring.md`（章/节写法、批量上传）、`docs/content-model.md`（新表）、`docs/reading.md`（URL 两代对照）、`docs/ai.md`（API 契约）、`README.md`
- [x] C2 全量 `pytest`（398 passed）+ `ruff` 通过；容器重建后按「迁移自检」清单人工验收
- [x] C3 `openspec validate add-chapter-sections --strict` 通过后归档

## Workflow follow-up

- 迁移会**物理删除存量章节/分卷数据**（已获用户确认）；归档后把「章 → 节」的新结构同步进 `openspec/specs/`。
