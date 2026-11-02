# Design

## Context

`chapters` 现在一表身兼三职：目录行（`slug`/`title`/`sort_order`/`status`）、正文载体（`content_raw`/`content_safe`/`word_count`/`checksum`）、版本主体（`current_version_no` + `chapter_versions`）。分卷用 `kind='group'` + `parent_id` 复用同一张表。读者的三级结构（Book → 分卷 → 章节）与编辑的心智（一章一篇）都对不上「一章多文件」。动机与三个已确认的产品决定见 `proposal.md`。

## Goals / Non-Goals

**Goals:**

- 章的职责收敛为「目录行 + 发布开关」，节承担正文/格式/版本。
- 存量零丢失：每章 → 一章一节，版本历史原样搬过去，旧 URL 仍可用。
- 分卷彻底消失，目录回到两级。
- 多文件一次上传即多节。

**Non-Goals:**

- 章内节的拖拽排序、跨章移动节、节级权限/可见性。
- 把 PDF / 图片当作节（继续走媒体库）。
- 保留分卷的兼容读接口（分卷数据直接删）。

## Decisions

### D1. 新表 `chapter_sections` + `section_versions`，`chapters` 瘦身

```text
chapters          id, book_id, slug, title, sort_order, status, created_at, updated_at, created_by, updated_at_by, deleted_at
chapter_sections  id, chapter_id, slug, title, format, content_raw, content_safe, word_count, checksum,
                  current_version_no, sort_order, created_at, updated_at, created_by, deleted_at
section_versions  id, section_id, version_no, title, format, content_raw, note, created_by, created_at
```

- `chapters` 只留目录与状态；`content_*`、`format`、`current_version_no`、`kind`、`parent_id` 全部移除。
- 节的唯一性约束是 `(chapter_id, slug)` 部分唯一索引（`deleted_at IS NULL`），与现有章的唯一性同款做法。
- **理由**：版本挂在节上才能"只回滚某一节"；章无正文后，章表只负责排序与发布。

### D2. 迁移 `0015_chapter_sections`：先建后搬再删

> **实际执行时的简化**：实施前用户确认「当前数据不重要，可以抹除」，所以迁移没有搬运存量数据——直接清空 `chapters`、删掉 `chapter_versions` 与旧的正文列，再建新表。下面 1–6 步保留为「需要保数据时」的做法（downgrade 也只恢复结构，不恢复数据）。

1. 建 `chapter_sections` / `section_versions`；
2. 遍历 `chapters`：
   - `kind='doc'` → 建一条节：`slug='main'`、`title=章.title`、`format=章.format`、正文/校验/字数照搬，`sort_order=10`；
   - `kind='group'` → 不建节，记下它的 `(book_id, sort_order)` 供第 3 步排序；
3. 章节提升到章层：把分卷下所有章节的 `book_id` 保持不变、`parent_id` 清空，按「原分卷序号 + 章内序号」重排全书的 `sort_order`；
4. 删除分卷行；
5. `chapter_versions` → `section_versions`：按 `chapter_id` 找到对应节，逐行搬 `version_no/title/format/content_raw/note/created_*`；
6. 删除 `chapters` 的正文相关列。

- **节 slug 在章内唯一**：留空时按节标题生成（中文标题回退成 `section-xxxxxx`），所以单节章第一节的地址是 `/b/ops/deploy/<节 slug>`；章页 `/b/ops/deploy` 在单节时直出同一篇。
- **旧链接兼容**：`/b/<book>/<chapter>` 在单节章上直接渲染唯一节，所以迁移后所有旧链接照旧可用（D4）。
- 回滚：downgrade 反向搬回（单节章的节内容写回 `chapters`，多节章只保留第一节），并重建分卷表结构；文档里明确「回滚会丢多节」。

### D3. 版本、diff、回滚全部下沉到节

`versions` 服务改为按节读写；章的「历史版本」页面变成「该章所有节的版本列表」（按节分组）。回滚只作用于一个节，章状态不变。

### D4. 路由：章页双形态，节页永远独立

| 路由 | 行为 |
| --- | --- |
| `/b/<book>` | 目录：章（可展开节） |
| `/b/<book>/<chapter>` | 该章**只有一节**→ 直出这一节正文；**多节**→ 该章的节索引 |
| `/b/<book>/<chapter>/<section>` | 节正文（唯一正文出口） |
| `/b/<book>/<chapter>/<section>/raw` | HTML 节的原始文档通道（原 `/raw` 下沉） |

- **理由**：保住存量链接（分享出去的地址不会 404），同时给多节章一个合理的落地页。
- 备选：章页永远做索引 + 单节章 302 到节页——会让老链接多一跳，且锚点/统计都变，放弃。

### D5. 发布状态留在章级

节没有独立 `status`：章 `published` → 所有节可见；章 `draft` → 所有节 404。**理由**：避免「同一章一半可见」的目录表达问题（侧栏要么整章出现，要么不出现）。

### D6. `Book.format` 降级为默认格式

Book 的 `format` 保留（新建节时预选、媒体上传时提示），但不再限制节的格式：同一章可以既有 `.md` 也有 `.html`。`html_view` 仍是 Book 级（HTML 节按它决定原始/站内渲染）。

### D7. 多文件上传

- 后台章节编辑器提供 `upload` 多选（`multiple`）；`_resolve_payload` 改为对每个文件产出 `(title, format, raw)`，逐个建节。
- 顺序 = 选择顺序（`UploadFile` 列表顺序），每节 `sort_order` 步长 10。
- 单个 `.md`/`.html` 仍支持（生成一节），不破坏既有习惯。

### D8. 搜索 / 站点地图 / Webhook 改到节粒度

- 搜索：索引 `sections`（正文），结果为节，链接指向节页；`chapter_slug` 保留在结果里用于拼 URL。
- sitemap：收录章页（多节章是索引页，值得收录）与所有节页。
- Webhook：新增 `section.published` / `section.updated`；`chapter.*` 只在章标题/序号/发布状态变化时发，避免一次改正文触发两条。

## Risks / Trade-offs

- [迁移把每章都变成一个 `main` 节，URL 变成 `/b/x/y/main`] → 旧 URL 仍直出正文（D4），新分享才用节页；文档里给出两代地址的对照。
- [章的版本历史消失（全部归到节）] → 界面上「章 → 历史版本」列出该章各节的版本，语义更准。
- [分卷数据物理删除] → 迁移前自动快照（`scripts/backup.py`），且 downgrade 能恢复"单节 → 章"的部分。
- [章状态仍是大颗粒：一个节写坏要整章撤回] → 与现状一致，不是新增限制；节级草稿留作后续需求。
- [搜索/统计口径从章变成节，热度会重新分布] → `visits` 表按节记录后，Book 热度改按章聚合（一章的访问 = 其各节之和），文档说明。

## Migration Plan

1. 部署前自动快照数据库（entrypoint 已有）。
2. `0015_chapter_sections`：建表 → 搬数据 → 提升章节 → 删分卷 → 搬版本 → 删旧列。
3. 迁移后自检：`chapters` 里 `kind='group'` 为 0；每章至少 0 节、至多 N 节；`section_versions` 行数 = 原 `chapter_versions` 行数；抽样 3 个旧章节地址仍 200。
4. 回滚：`alembic downgrade -1`（多节章只保留第一节内容，文档已注明）。
