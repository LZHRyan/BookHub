# Design

## Context

- 目前 Book 顺序来自 `books.sort_order`（管理员手工填的整数，升序排列），见 `app/services/books.py` 的 `list_books` 与 `app/templates/admin/book_form.html`。
- Book 数量级是「几十到几百」；列表在首页（每页 12）、管理端（每页 20）与 `/api/v1/books`（每页最多 100）三处使用。
- 站点没有任何后台任务/定时器，`app.startup` 只做初始管理员与演示数据；只有 SQLite（默认，WAL）与 Postgres 两种后端，且必须都不引入新依赖。
- 现有可复用的组件：`app/services/ratelimit.py` 的进程内滑动窗口（`threading.Lock` + `deque`）、`app.logging_setup.log_event`、`app.middleware.client_ip`。

## Goals / Non-Goals

**Goals:**

- 首页顺序自动反映「多少人看」与「多新」，管理员无需维护排序。
- 热度口径可解释：管理端能看到权重与访问数，公式写进文档。
- 零新增依赖、零后台任务；SQLite 与 Postgres 行为一致。
- 阅读页不因统计失败而报错；刷新不能刷热度。

**Non-Goals:**

- 不做访问明细、趋势图、UV/PV 报表（要明细就会带来隐私与存储成本）。
- 不做人工置顶/降权开关（本次的核心诉求就是"不靠人设置"）。
- 不做机器人识别、Cron 清理历史视图行（需要时手工删 90 天前的行即可）。

## Decisions

### D1. 权重在请求时实时计算，不落库

`ranking.stats_for()` 一次聚合查询拿到「累计 / 近 7 天」两个数，再在 Python 里套公式。权重不写回 `books`，因此没有"过期权重"问题。

- 备选被否：写入 `books.weight` 列 → 需要一个定时任务或写时全表刷新，且新鲜度项随时间变化，本质上是过期数据。
- 备选被否：纯 SQL 计算 → 指数衰减需要 `exp/power`，SQLite 无内置数学函数，跨后端写法不可移植。

### D2. 排序在内存里做，分页也在内存里切

`list_books` 先取满足 `deleted_at/visibility` 的全部 Book，排序后切片。代价是 O(N log N)/请求（N 为 Book 总数，实际几百），换来的是：分页的 `total` 与各页内容出自同一份排序结果，天然不重不漏。

- 备选被否：SQL 里排序 + `LIMIT/OFFSET` → 权重依赖聚合统计，得先 `JOIN` 子查询再排序，索引失效且公式仍无法在 SQL 表达。
- 若将来 Book 上万，可加一层"每小时把权重物化成列"的缓存；当前规模不值得。

### D3. 热度数据用「按天聚合」而不是明细或单一计数列

`book_view_daily(book_id, day, views)`，联合主键定位当天的行，行数上限是「Book 数 × 有访问的天数」，与访问量无关。

- 近 7 天窗口只要 `WHERE day >= 今天-6` 的一次 `SUM`，不需要滚动衰减任务。
- 备选被否：`books.view_count` 单列 → 无法表达"近期热度"，老书靠历史流量永久霸榜。
- 备选被否：每次访问一行明细 → 表会迅速膨胀，且站点并不需要明细报表。

### D4. 公式与参数

```text
weight = 100·ln(1+近7天访问) + 25·ln(1+累计访问) + 60·2^(-创建天数/14)
```

- **对数**：访问量线性增长时权重只缓慢上升，避免一条爆款文章永久占坑；也让第 1 次访问的边际收益最大。
- **累计访问打 1/4 折**：长期受欢迎的书仍有加成，但不会压过近期活跃的书。
- **新鲜度半衰期 14 天**：全新书 +60 分，14 天后 +30，28 天后 +15，两个月后≈0。新书因此能自然获得曝光，同时不会长期赖在榜首。
- **相对顺序与请求时刻无关**：同一次请求里所有 Book 共用一个 `now`，`2^(-(now-created)/14) = 2^(-now/14)·2^(created/14)`，公共正因子不影响比较结果。所以只要访问量不变，刷新多少次顺序都一样（测试 `test_order_stable_when_view_counts_unchanged` 覆盖）。
- 参数是模块常量（`HOT_VIEW_WEIGHT` 等）而非环境变量：调参属于改产品行为，应该走一次变更，而不是让每个部署各不相同。

### D5. 计数的去重与口径

- 计数点：`GET /b/{slug}`（Book 页）与 `GET /b/{slug}/{chapter}`（章节页）；章节阅读是更强的兴趣信号，同样 +1。
- 去重：进程内 `VisitDeduper`（`app.state.visit_deduper`），key = `book_id:client_ip`，窗口 30 分钟；最多记 2 万条，超限先清过期项。
- 只计匿名访问：`current_user(request, session) is None` 才计数，避免编辑自己刷自己的书。
- `request.method != "GET"` 不计（HEAD/预取不加热度）。
- 写库异常被吞掉并记 `visit.record.error`，阅读页保持 200。

**代价与取舍**：进程内去重意味着多副本部署时每个副本各自去重（热度最多被高估副本数倍），且重启后窗口清空；对"排序权重"这种用途完全可接受，换来的是零依赖、零存储。`X-Forwarded-For` 由 `client_ip()` 取第一段，信任边界与现有登录限流一致。

### D6. 数据库变更

迁移 `0003_book_auto_weight`：

1. 建 `book_view_daily`（FK `books.id` ON DELETE CASCADE，`(book_id, day)` 联合主键，`day` 单列索引）。
2. 删 `ix_books_listing` → `batch_alter_table` 删 `books.sort_order` → 重建 `ix_books_listing(deleted_at, visibility)`。
   先删索引是因为 SQLite 的 batch 模式会重建整张表，索引里还引用着 `sort_order` 就会一起失败。
3. downgrade 反向：加回 `sort_order`（默认 0）、恢复三列索引、删表。

`uq_books_slug_active` 这个带 `WHERE deleted_at IS NULL` 的部分唯一索引在 batch 重建中被 SQLAlchemy 的 SQLite 反射正确保留（已在临时库上实测升级/降级各两轮）。

### D7. API 兼容性

Book 表示用 `weight`（float，2 位小数）、`view_count`、`recent_view_count` 取代 `sort_order`。这是一次**破坏性字段变更**，理由是保留 `sort_order` 只会让客户端误以为它还能决定顺序。站点目前是内部工具，没有已知外部消费者。

`ETag` 不把权重/访问数算进指纹：热度变化不应让客户端缓存失效。

## Risks / Trade-offs

- **刷热度**：同 IP 30 分钟只计一次，且登录用户不计；但换 IP 或脚本仍可刷。这是"热度"类功能的固有风险，本次不做机器人识别，文档中明示。
- **内存去重表**：单进程最多 2 万条 key（约几 MB）；多副本部署时去重不共享，热度会被高估副本数倍。
- **列表全量加载**：Book 上千后首页每次请求都要取全表；已记录为将来的物化缓存触发条件。
- **迁移破坏性**：删列后旧版本代码（回滚镜像）会因缺少 `sort_order` 报错；回滚必须同时执行 `alembic downgrade 0002_book_format`。
- **权重不透明感**：管理员看不到排序为何变化 → 用 Book 详情页的三个徽章把输入量出来，并在 `docs/authoring.md` 写明公式。

## Migration Plan

1. 部署前备份数据库（`docs/deploy.md` 的备份流程）。
2. 启动时执行 `alembic upgrade head`（容器 entrypoint 已包含）。
3. 上线后首页顺序会按"新建优先 + 已有点击"重排；访问统计从上线时刻开始积累，历史热度无法回填（没有历史访问数据可回填）。
4. 回滚：`alembic downgrade 0002_book_format` + 回滚镜像；`sort_order` 会以 0 回填，顺序退化为"创建时间升序"，不会丢文档。

## Open Questions

无。公式参数（100/25/60/14 天/7 天窗口/30 分钟去重）以常量形式固化，若后续要按运营诉求调整，另起变更。
