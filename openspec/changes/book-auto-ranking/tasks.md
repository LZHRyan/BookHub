# Tasks

## 1. 数据与迁移

- [x] 1.1 `models.py`：`Book` 删除 `sort_order`，`ix_books_listing` 改为 `(deleted_at, visibility)`；新增 `BookViewDaily(book_id, day, views, updated_at)`，`(book_id, day)` 联合主键
- [x] 1.2 新增迁移 `alembic/versions/0003_book_auto_weight.py`：建表 + 删列 + 重建索引，含 downgrade
- [x] 1.3 在临时 SQLite 库上实测 upgrade → downgrade → upgrade，确认 `uq_books_slug_active` 部分唯一索引未丢失

## 2. 服务层

- [x] 2.1 新增 `app/services/ranking.py`：`compute_weight`、`stats_for`、`stats_of`、`rank_books`、`add_view`，参数常量集中在文件头
- [x] 2.2 新增 `app/services/visits.py`：`VisitDeduper`（30 分钟 / 2 万条上限）、`record_book_view`（仅 GET、写库失败只记日志）
- [x] 2.3 `books.create_book/update_book` 去掉 `sort_order` 参数；`books.list_books` 改为取全量 → 算权重 → 排序 → 切片，`total` 与切片同源
- [x] 2.4 `app/main.py` 注册 `app.state.visit_deduper`

## 3. Web / 管理端 / API

- [x] 3.1 `web/public.py`：Book 页与章节页在匿名访问时调用 `record_book_view`
- [x] 3.2 `web/admin.py`：表单处理器去掉 `sort_order`；Book 详情与列表传入热度统计
- [x] 3.3 `admin/book_form.html` 删除「排序权重」输入框，改为自动排序说明；`admin/book_detail.html` 展示权重与访问数；`admin/dashboard.html` 增加「近 7 天访问」列
- [x] 3.4 `api/v1.py`：`_book_payload` 用 `weight` / `view_count` / `recent_view_count` 取代 `sort_order`，列表与详情都带统计

## 4. 测试

- [x] 4.1 `tests/test_ranking.py`：公式单调性（热度↑、创建时间↑、近 7 天权重高于历史）、新鲜度半衰期、未来时间戳不发散
- [x] 4.2 列表顺序：无访问时新建优先、有热度后热门优先、访问量不变时顺序稳定、分页不重不漏
- [x] 4.3 计数：Book 页去重、章节页计入、登录用户不计、按天分桶、近 7 天窗口过滤
- [x] 4.4 管理端表单无 `sort_order` 且详情显示权重；API payload 字段与排序正确
- [x] 4.5 全量 `pytest`（196 条）与 `ruff check app tests` 通过

## 5. 文档与规格

- [x] 5.1 `docs/content-model.md`：删除 Book 排序字段、新增 `book_view_daily` 章节与权重公式、章节编号顺延
- [x] 5.2 `docs/api.md`：排序说明、payload 字段表、示例 JSON、导出清单缺失字段、ETag 变化条件
- [x] 5.3 `docs/authoring.md`：表单字段表、Book/章节排序分节、FAQ 两条
- [x] 5.4 `README.md`：功能清单与 `/api/v1/books` 示例
- [x] 5.5 `openspec validate book-auto-ranking --strict` 通过

## Workflow follow-up

- 归档本变更，使 `book-catalog` 主规格反映"权重自动计算"，并让新的 `book-ranking` 规格进入 `openspec/specs`。
