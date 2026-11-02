# Proposal

## Why

编目录现在只能一格一格点「上移 / 下移」：把第 12 章拖到第 3 位要点 9 次，发布一批新章节要点十几次「发布」。同时，Book 首页顺序完全由访问热度算出，主编没有任何办法把「新人必读」钉在第一位——`book-ranking` 那条变更把人工排序整个去掉了，缺一个克制的替代品。

## What Changes

- **章节与分卷支持拖拽排序**：管理端 Book 页的目录可拖动同一父级内的条目（根层里分卷与散章可互相穿插，分卷内章节可重排），松手后一次性提交新的顺序。跨父级拖动不支持——改归属仍走章节表单的「归属分卷」。
- **批量操作**：目录每行加复选框，支持「批量发布 / 批量撤回 / 批量删除」，结果按条汇总提示（成功 n 条、失败 m 条及原因）。
- **Book 置顶**：`books.pinned` 开关。置顶的 Book 在首页与 `/api/v1/books` 中排在最前，置顶内部仍按热度权重排序；不做任意手工序号，避免退回到「谁最后编辑表单谁在前」。
- 新增管理 API：`POST /api/v1/admin/books/{ref}/chapters/reorder`（按父级提交有序 id）；`PATCH /api/v1/admin/books/{ref}` 接受 `pinned`。
- 排序接口 MUST 校验「提交的 id 集合与目标父级当前条目完全一致」，不一致返回 4xx 且不改动任何顺序。

## Capabilities

### New Capabilities

- `bulk-operations`: 管理端批量操作与拖拽排序的契约：作用范围（同一父级）、一次提交的原子性、逐条结果的呈现，以及失败项不影响成功项的处理方式。
- `book-pinning`: Book 置顶语义——置顶优先于自动权重、置顶内部仍按权重排序、置顶是布尔开关而非任意序号。

### Modified Capabilities

- `chapter-lifecycle`: 排序调整新增「按有序 id 列表整体重排同一父级」的入口与一致性校验。
- `management-api`: 排序与置顶 MUST 通过管理 API 可得，复用作用域、幂等与审计约定。

## Impact

- **数据**：迁移 `0010_book_pinned`（`books.pinned` BOOLEAN 默认 false）；章节无需新字段。
- **服务层**：`chapters.reorder_siblings()`（按父级重排 + 一致性校验）、`ranking._sort_key` 增加置顶位、`books.update_book` 接受 `pinned`。
- **Web**：`admin/book_detail.html` 加复选框与拖拽手柄，`app/static/app.js` 加拖拽与批量提交，`app/static/style.css` 加拖拽态样式；新增 `POST /admin/books/{id}/chapters/reorder`、`/chapters/batch`、`/pin`。
- **API**：新增 reorder 端点，Book 表示补 `pinned`。
- **测试**：新增 `tests/test_bulk.py`；`tests/test_ranking.py`、`tests/test_admin_api.py` 补置顶与重排用例。
- **非目标**：不做跨分卷拖拽、不做任意手工序号、不做「批量移动归属」、不做多选跨页。
