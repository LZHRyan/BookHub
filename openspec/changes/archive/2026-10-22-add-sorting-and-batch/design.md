# Design

## Context

目录排序目前只有单步上移/下移（`chapters.move_chapter`，按父级交换后整体重写 10/20/30）；管理 API 已有 `/chapters/batch`，但网页端没有对应入口；Book 顺序由 `ranking.rank_books` 按访问热度实时计算，`book-auto-ranking` 那条变更明确删掉了人工序号。动机见 `proposal.md`。

## Goals / Non-Goals

**Goals:**

- 一次拖动/一次提交完成多步排序，且失败时目录不动。
- 批量操作在网页端可用，结果逐条可见。
- 给主编一个「把这本书钉在前面」的最小手段，不重引入任意序号。

**Non-Goals:**

- 跨分卷拖拽（改归属仍走表单，避免一次拖动同时改结构与顺序）。
- 任意手工序号、置顶排序权重、置顶有效期。
- 多页多选（当前目录不分页）。

## Decisions

### D1. 重排用「完整有序 id 列表 + 父级」一次提交，而不是「从 A 移到 B 的增量」

前端松手时把该父级的 DOM 顺序整体提交给 `POST /chapters/reorder`（JSON：`{parent, chapter_ids}`）。

- **理由**：增量语义在并发下容易错位（两个人同时拖动），完整列表可以直接比对集合，不一致就拒绝——这正是 `reorder_chapters` 已有的思路，只是把它按父级收窄。
- 校验在服务层做：`set(ids) == set(该父级未删除条目)`，否则 400，且不改动。
- 重写复用 `_rewrite_order`（10/20/30）。

### D2. 拖拽用原生 HTML5 drag & drop，不引入前端库

目录行加 `draggable="true"` 与 `data-chapter-id`/`data-parent`，`app.js` 只做三件事：记录拖动源、在目标位置移动 DOM、松手后提交。

- **理由**：目录是单页短列表，`dragstart/dragover/drop` 足够；引入 sortable 库需要构建步骤或额外静态依赖，与「无构建、无依赖」的既有约束冲突。
- 只允许同 `data-parent` 之间交换：拖动源与目标父级不同时直接忽略并提示。
- 松手后如果服务端拒绝，重新加载页面回到真实顺序（比在前端猜更可靠）。

### D3. 批量操作用表单提交，不用前端拼多次请求

目录每行一个 `name="chapter_id"` 复选框 + 三个提交按钮（`action=publish|unpublish|delete`），提交到 `POST /admin/books/{id}/chapters/batch`。

- **理由**：服务端一次拿全量 id，逐条执行并汇总，天然原子到「每条一个事务边界内的尽力而为」；不依赖 JS，禁用脚本也能用。
- 结果通过 `?batch=publish:4,1` 之类的查询参数回显成提示条（成功/失败条数），避免引入 flash 框架。
- 删除按钮带 `data-confirm`（复用既有确认逻辑）。

### D4. 置顶是布尔字段，排序键最前面加一位

`books.pinned` BOOLEAN 默认 false；`ranking._sort_key` 改为 `(0 if pinned else 1, -weight, -created_ts, -id)`。

- **理由**：布尔开关不需要任何维护成本，也不会像手工序号那样被「最后一次编辑」绑架；置顶内部仍由热度决定，保留自动排序的优点。
- **备选**：`pinned_until` 到期自动失效——增加一个时间语义与清理任务，收益不明显，先不做。
- 迁移 `0010_book_pinned`：加列（`server_default=sa.false()`），downgrade 删列。

### D5. 置顶入口放两处：Book 列表行内与详情页顶部

详情页顶部一个「置顶 / 取消置顶」按钮（`POST /admin/books/{id}/pin`，CSRF）；列表页显示 `置顶` 徽章，点徽章同样可切换。

## Risks / Trade-offs

- [两个管理员同时拖动同一分卷] → 后提交的一方因集合一致但顺序不同会覆盖前者；这是"最后提交者胜出"的预期语义，审计里能看到两次顺序。
- [拖拽在触屏设备上不工作] → HTML5 DnD 在移动端支持差；保留上移/下移按钮作为兜底，不做额外触摸实现。
- [批量删除误操作] → 必须显式确认，且删除是软删除可恢复；结果逐条返回，失败项单独列出。
- [置顶被滥用导致首页固定几本] → 置顶是布尔值、需要 admin 权限、有审计；不做数量限制，靠团队规范。
- [重排提交的 id 集合包含分卷] → 校验按父级做，分卷属于根层父级，和散章一起提交是合法的（它们共用根层顺序空间）。

## Migration Plan

1. `0010_book_pinned`：`ADD COLUMN pinned BOOLEAN NOT NULL DEFAULT false`（SQLite/PG 都可直接执行，无需 batch）。
2. 存量 Book 全部非置顶，行为与现在完全一致。
3. 回滚：`alembic downgrade -1` 删列，顺序回到纯权重排序。
