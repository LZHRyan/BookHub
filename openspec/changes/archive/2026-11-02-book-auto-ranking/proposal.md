# Proposal

## Why

Book 的首页顺序现在是管理员手工填的整数 `sort_order`（数字越小越靠前）。实际使用中这个字段几乎没人维护：新书填 0 就顶到最前面、老书越堆越沉，最后首页顺序变成"谁最后编辑过表单谁说了算"，与这本书到底有多少人看毫无关系。读者真正想看到的是**常用、热门、刚更新**的文档排在前面，而不是编辑者随手填的数字。

把权重交给系统算：访问越多的书越靠前，创建越晚的书起点越靠前，管理员不再需要（也不能）设置任何排序值。

## What Changes

- **BREAKING**：删除 `books.sort_order` 列与首页/API 按它排序的行为。Book 表单、服务层参数、API payload 都不再接受或返回 `sort_order`。
- 新增 `book_view_daily` 表：按「Book × UTC 日期」聚合访问次数，作为热度的唯一数据源（不存访问明细）。
- 新增访问计数：访客打开 Book 页或任意章节页时给该书 +1；同一 IP 对同一本书 30 分钟内只计一次；登录用户（编辑/管理员）的访问不计入；统计写库失败只记日志，不影响阅读页。
- 新增自动权重（`app/services/ranking.py`，请求时实时计算，不落库）：
  `weight = 100·ln(1+近7天访问) + 25·ln(1+累计访问) + 60·2^(-创建天数/14)`
- 列表排序改为 `weight DESC, created_at DESC, id DESC`；分页在同一份排序结果上切片，total 与之来自同一集合。
- `/api/v1/books` 与 `/api/v1/books/{ref}` 用 `weight`、`view_count`、`recent_view_count` 取代 `sort_order`。
- 管理端：Book 表单去掉「排序权重」输入框；Book 详情页显示「热度权重 / 近 7 天访问 / 累计访问」；Book 列表增加「近 7 天访问」列。

## Capabilities

### New Capabilities

- `book-ranking`: 访问热度的采集口径（计数对象、去重、匿名口径、失败降级），以及权重公式的性质（热度↑、创建时间↑、顺序稳定、只读不可人工设置）与列表分页语义。

### Modified Capabilities

- `book-catalog`: 创建/更新 Book 的元数据不再包含排序权重；Book 列表改为按自动权重降序排列。

## Impact

- **数据**：新增 Alembic 迁移 `0003_book_auto_weight`（建 `book_view_daily`、删 `books.sort_order`、重建 `ix_books_listing`），SQLite/Postgres 均可执行，有 downgrade。
- **服务层**：`books.create_book/update_book` 去掉 `sort_order` 参数；`books.list_books` 改为"取全量 → 算权重 → 排序 → 切片"；新增 `ranking`、`visits` 两个模块。
- **对外 API**：Book 表示字段变更（`sort_order` → `weight` / `view_count` / `recent_view_count`），需要客户端同步。
- **Web**：`/b/{book}` 与 `/b/{book}/{chapter}` 增加访问计数（带进程内去重），`app.state.visit_deduper` 注册在应用工厂。
- **测试**：新增 `tests/test_ranking.py`（14 条用例），既有 182 条用例全部保持通过。
- **文档**：`README.md`、`docs/api.md`、`docs/authoring.md`、`docs/content-model.md` 同步更新。
- **非目标**：不做趋势图/访问报表、不做人工置顶或干预、不做机器人流量识别、不做历史访问数据的自动清理任务。
