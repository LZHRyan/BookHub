# Tasks

## 1. 数据与排序

- [x] 1.1 `Book.pinned` 字段 + 迁移 `0010_book_pinned`（`server_default=sa.false()`，downgrade 用 batch 删列），既有库可直接升级
- [x] 1.2 `ranking._sort_key` 增加置顶位（置顶优先，组内仍按权重），`tests/test_bulk.py` 覆盖「置顶优先」「多置顶内部按权重」「取消后回原位」
- [x] 1.3 `books.update_book` 接受 `pinned` 并写 `book.pin` / `book.unpin` 审计；`/api/v1` 与 `/api/v1/admin` 的 Book 表示补 `pinned`

## 2. 章节重排

- [x] 2.1 `chapters.reorder_siblings(session, book_id, parent_id, ordered_ids)`：集合一致性校验 + 重写 10/20/30 + 审计（含父级与新顺序）
- [x] 2.2 `POST /admin/books/{id}/chapters/reorder`（会话 + CSRF 头 + JSON），返回新顺序；异常返回 JSON 错误体
- [x] 2.3 `POST /api/v1/admin/books/{ref}/chapters/reorder`，复用 `_write` 幂等包装；`read` 作用域 403
- [x] 2.4 单测：合法重排生效、缺项/多项被拒且顺序不变、组内重排不影响根层、网页端缺 CSRF 被拒

## 3. 管理端交互

- [x] 3.1 `admin/book_detail.html`：目录行加复选框、拖动手柄与 `data-chapter-id`；每个 tbody 带 `data-parent`，分卷区块与散章表各自成容器
- [x] 3.2 `app/static/app.js`：同容器拖拽 + 松手提交 `{parent, chapter_ids}`；跨容器拖动忽略；服务端拒绝时 alert 后 reload
- [x] 3.3 目录上方加批量操作栏（`form="batch-form"` 让复选框跨表格归属同一表单），提交到 `POST /admin/books/{id}/chapters/batch`
- [x] 3.4 网页端 batch 端点：逐条执行、汇总成功/失败，重定向回详情页并用 `?batch=action:ok,failed` 回显
- [x] 3.5 `POST /admin/books/{id}/pin` 切换置顶；详情页按钮按状态显示「置顶到首页 / 取消置顶」
- [x] 3.6 `app/static/style.css`：批量操作栏、拖拽手柄、拖动中行半透明、复选框配色（三态主题）

## 4. 测试

- [x] 4.1 `tests/test_bulk.py`（14 条）：重排服务与端点、CSRF、批量发布/部分失败/删除需确认/空选提示、页面钩子、置顶排序、网页 pin、API reorder+pinned
- [x] 4.2 API 侧 reorder 与 pinned 用例写在 `tests/test_bulk.py::test_api_reorder_and_pin`（含只读公开 API 的 `pinned` 字段）
- [x] 4.3 全量 `pytest` 与 `ruff check app tests scripts` 通过

## 5. 文档

- [x] 5.1 `docs/authoring.md`：拖拽范围与提交语义、批量操作小节（7.0）、置顶说明
- [x] 5.2 `docs/ai.md`：端点表补 reorder
- [x] 5.3 `docs/content-model.md`：`books.pinned` 字段与排序键；`README.md` 功能清单补两行

## Workflow follow-up

- `openspec validate add-sorting-and-batch --strict` 通过后归档该变更，并把归档目录提交入库。
