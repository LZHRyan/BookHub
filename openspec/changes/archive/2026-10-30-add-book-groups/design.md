# Design

## Context

Book 目前是顶层实体：`books` 表没有上级，`books_service.list_books` 一次取全量 → `ranking.rank_books` 按权重排序 → 内存切片分页；首页 `index.html` 直接渲染这一个 `book-grid`。章节侧已经有「分卷」这一层（`chapters.kind='group'`），是**章节内部**的结构。动机与三个已定的产品决策见 `proposal.md`。

## Goals / Non-Goals

**Goals:**

- Book 必属于一个组，且迁移零风险（存量全部落到「默认分组」）。
- 首页分区顺序由组决定，组内顺序完全复用现有热度/置顶规则——不引入第二套排序。
- 组是一个薄实体：只有标题、slug、简介、图标、位置，不带权限/可见性/页面。

**Non-Goals:**

- 多对多归组、组级可见性、组落地页、跨组拖拽。

## Decisions

### D1. 一对多：`book_groups` 表 + `books.group_id` 外键（NOT NULL）

- **理由**：首页分区只需要「这本书归哪个区」；一多会让同一本书重复出现，首页去重、分页与「组内 Book 数」都要特殊处理。
- 组字段：`id, slug(unique), title, description, icon, sort_order, created_at, updated_at`。

### D2. 迁移分三步，保证 NOT NULL 与存量兜底

`0014_book_groups`：

1. `create_table(book_groups)`；
2. 插入一条「默认分组」（slug `default`），拿到 id；
3. `batch_alter_table("books")` 加 `group_id`（nullable，FK 命名）→ `UPDATE books SET group_id=<id>` → 再 batch 一次改为 `nullable=False`。

- **理由**：SQLite 加 NOT NULL 列必须给默认值，而默认值又依赖新插入的组 id；分两步 batch（每次重建表，books 行数很小）最直观。
- **备选**：让 DB 保持 nullable、只在服务层强制——迁移更简单，但「库里有 NULL 的可能」是个长期的坑，放弃。
- 外键命名沿用 0009/0011 的经验（SQLite batch 需要具名约束）。

### D3. 组排序用整数 `sort_order`，上下移时整体重写 10/20/30

与章节一致的手法，组数量是个位数，整体重写最省心。

### D4. 首页分区在服务层组装，模板只负责渲染

`book_groups.overview(session, *, visibility)` 返回 `[{group, books}]`：

- 取全部组（按 `sort_order`）；
- 一次性取所有可见 Book，`rank_books` 排好序后按 `group_id` 分桶（保持组内顺序）；
- 丢掉「没有可见 Book」的组，但如果**只剩下 0 个分区**（全部组都空）就原样返回，交给模板显示空态。

- **理由**：排序只发生一次，分桶是字典操作，不会出现「每个组各算一遍权重」的 N+1。

### D5. 组的筛选走同一入口

`list_books(group=...)` 增加一个 `where` 条件。首页 `/?group=ops` 与管理端列表复用；首页在筛选态下不再分区，只显示一个网格（否则「一个分区里一组」很怪）。

### D6. 删除约束：先腾空 + 保留最后一个

`book_groups.delete()`：有 Book → 400（带数量）；`count(groups) <= 1` → 400。软删除也一起禁止，避免出现「组没了 Book 悬空」。

### D7. Book 表单的组字段必选，服务层兜底

表单 `required` 只解决浏览器侧；`books.create_book(group=...)` 仍然校验：为空 → `ValidationFailed("必须选择组")`；`update_book` 允许改归属。

## Risks / Trade-offs

- [存量迁移把 11 本书都塞进「默认分组」，首页看起来只有一个区] → 正是预期：管理员建几个真组再把 Book 挪过去，挪动只是改 `group_id`。
- [组的 slug 与 Book 的 slug 语义不同（组不参与 URL）] → 组的 slug 目前只用于 API 与筛选参数 `?group=`；文档里说明它不会出现在读者地址栏。
- [`overview()` 每次首页都取全量 Book] → 与现在的 `list_books` 同量级（几十到几百），首页本来就要展示全部卡片；分页在筛选态下仍可用。
- [组名与分卷名都叫「组/分卷」，容易混] → 界面上用「分组」指 Book 组、「分卷」指章节组，文案统一，文档加一节对照。

## Migration Plan

1. `0014_book_groups`（如上三步），有 downgrade：删 `books.group_id` → 删表。
2. 迁移后立即验证：`select count(*) from books where group_id is null` 必须为 0；首页仍列出全部 Book。
3. 回滚：downgrade 后组信息丢失，Book 回到扁平列表，章节与媒体不受影响。
