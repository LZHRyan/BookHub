# Design

## Context

`chapters` 目前是扁平表：`sort_order` 全 Book 共享一串，`ordered_chapters` 按它排序，`move_chapter` 在同级集合里交换并整体重写为 10/20/30。Book 页、管理页、`/api/v1/books/{ref}` 都直接消费这个平铺列表。任何引入层级的方案都要同时回答三个问题：URL 怎么变、排序怎么写、旧数据怎么办。动机见 `proposal.md`。

## Goals / Non-Goals

**Goals:**

- 让「同一主题的几章」在目录与侧边导航里成组出现，并且编号能表达层级。
- 分卷只是结构，不是内容：不引入第二套权限、第二套发布流程、第二套版本。
- 存量数据零迁移风险：所有旧章节自动就是「根层普通章节」。

**Non-Goals:**

- 任意深度嵌套（卷 → 章 → 节）。这会把 URL 变成路径树、把移动操作变成子树搬迁，收益远小于成本。
- 分卷级可见性/权限、分卷封面、跨 Book 搬章节。

## Decisions

### D1. 用同一张表 + `kind` 区分，而不是新建 `chapter_groups` 表

`chapters` 增加 `kind`（`doc` / `group`）与自引用 `parent_id`。

- **理由**：分卷需要和章节共用同一串排序（根层里二者交错排列），也要共用软删除、slug 唯一性、审计与回收站；拆表就得写两套排序、两套回收站、两套 slug 唯一性，还得在查询里 UNION。
- **备选**：独立 `chapter_groups` 表 + 章节上的 `group_id`——查询更"干净"，但排序要在两张表之间做归并，`sort_order` 语义会分裂。放弃。

### D2. 层级硬限制为一层，在服务层校验

`parent_id` 只能指向 `kind='group'` 的行，且分卷自身的 `parent_id` 必须为 `NULL`。

- **理由**：一层已经能表达「分卷」，且**所有章节 URL 保持不变**（`/b/{book}/{chapter}`），读者收藏的链接不会因为分组失效；移动操作仍然是"同级交换 + 改归属"。
- 校验点：`create_chapter` / `move_to_parent` / `create_group` 三处，统一抛 `ValidationFailed`。

### D3. `sort_order` 的作用域 = 同一父级

`next_sort_order`、`move_chapter`、`_rewrite_order` 全部按 `parent_id` 过滤/重写。

- **理由**：组内顺序与根层顺序互不干扰，一次上移只重写一个集合，改动面最小。
- 根层里分卷与未分卷章节共用一串序号，因此「分卷 A、独立章节、分卷 B」这种交错顺序是天然支持的。
- 索引 `(book_id, parent_id, sort_order)` 支撑这几种查询。

### D4. 分卷没有状态、没有正文、没有版本

创建分卷时直接 `status='published'`、`content_raw=''`，不调用 `_apply_content`（不写版本、不写 `chapter_fts`）。

- **理由**：分卷是不是"应该出现"由它是否被删与所属 Book 决定；给它一个 draft 状态会让"章节已发布但分卷是草稿"这种组合出现，读者侧就得写特例。
- 读者侧只显示「有已发布子章节」或「空分卷」的分卷标题；空分卷保留标题是为了让主编能先搭骨架。

### D5. 删除非空分卷直接拒绝

而不是级联删子章节、也不是把子章节自动提回根层。

- **理由**：级联删除对知识库太危险；自动提回会让目录结构在一次点击里被静默改写。拒绝并要求先移动，是有摩擦但可控的行为。
- 空分卷删除走既有软删除通道，回收站可恢复。

### D6. 目录编号在展示层算，不落库

`tree()` 返回 `[{group, items}]`，编号（`1.`、`1.1`）在模板里按序数生成。

- **理由**：编号是派生产物，落库就要在每次移动/增删时重算并写库，且和 `sort_order` 语义重复。

### D7. 分卷地址重定向而不是 404

`/b/{book}/{group-slug}` → 302 到 `/b/{book}`。

- **理由**：分卷确实"存在"，只是没有正文；404 会让读者以为链接坏了。重定向后目录里能直接看到该分卷。

## Risks / Trade-offs

- [GET Book 详情的目录结构变化，老客户端按平铺列表消费] → 目录仍是一个有序数组（分卷作为 `kind='group'` 的条目混在其中），只是多了两个字段；平铺消费方仍然能按数组顺序渲染，不破坏兼容。
- [`sort_order` 语义从"全 Book"变成"同级"，历史数据里 10/20/30 的间隔仍在] → 存量行 `parent_id` 全为 `NULL`，因此全部落在根层，语义与之前完全一致。
- [分卷标题与章节标题在搜索/目录里可能重复] → 分卷不进搜索索引，不会重复命中。
- [跨父级移动可能让 `sort_order` 出现大量重复值] → 每次移动都对该父级整体重写为 10/20/30，不会累积重复。
- [管理页从单表格变成分区渲染，改动面较大] → 模板按 `sections` 数据结构渲染，章节行复用同一段宏，避免两份表格。

## Migration Plan

1. `0009_chapter_groups`：`ADD COLUMN kind VARCHAR(16) NOT NULL DEFAULT 'doc'`、`ADD COLUMN parent_id INTEGER REFERENCES chapters(id)`、建索引 `ix_chapters_tree (book_id, parent_id, sort_order)`；downgrade 反向删除。
2. 不需要回填：默认值即「根层普通章节」，与旧行为等价。
3. 回滚：`alembic downgrade -1` 后所有分组信息丢失，章节回到平铺顺序（顺序值不变），可接受。

## Open Questions

- 是否要给分卷加「折叠/展开」状态并记忆到 localStorage：纯前端偏好，后续可加，不影响接口。
