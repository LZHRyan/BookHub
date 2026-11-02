# Tasks

## 1. 数据与迁移

- [x] 1.1 `BookGroup` 模型（`slug` 唯一、`title`、`description`、`icon`、`sort_order`）+ `Book.group_id`（FK、NOT NULL）
- [x] 1.2 迁移 `0014_book_groups`：建表 → 插入「默认分组」→ 加 `group_id`（nullable）→ 回填 → 收紧 NOT NULL；downgrade 删列删表
- [x] 1.3 在既有库上实测 `upgrade → downgrade → upgrade`，并确认 `group_id` 无 NULL

## 2. 服务层

- [x] 2.1 `app/services/book_groups.py`：`ensure_default` / `list_groups` / `get_group` / `resolve`（slug 或 id）/ `create` / `update` / `delete` / `move` / `counts`
- [x] 2.2 删除约束：非空组 400（带数量）、最后一个组 400；全部写审计
- [x] 2.3 `books.create_book(group=...)` 校验必填并解析；`update_book` 支持改归属；`list_books(group=...)` 过滤
- [x] 2.4 `book_groups.overview(session, visibility)`：按组位置分组、组内按 `rank_books` 排序、丢掉空分区
- [x] 2.5 单测：必填校验、归属变更不影响章节、组排序重写、删除约束、overview 分桶与排序

## 3. 管理端

- [x] 3.1 `/admin/groups`：组列表（含 Book 数）+ 新建/改名/删除/上下移
- [x] 3.2 `admin/group_form.html`（新建/编辑复用一张表单）
- [x] 3.3 Book 表单：组必选下拉（新建默认不选、编辑预选当前组），未选时字段级报错
- [x] 3.4 Book 列表：加「组」列与按组筛选，保留章节数显示
- [x] 3.5 页面测试：组管理页渲染、必选校验、筛选生效

## 4. 读者端

- [x] 4.1 首页按组分区渲染（组标题可点，跳 `/?group=<slug>`），空组不渲染，全空时显示空态
- [x] 4.2 `/?group=<slug>` 过滤态：单一网格 + 「查看全部」入口
- [x] 4.3 Book 页面包屑加组名
- [x] 4.4 测试：分区顺序、分区归属、空组隐藏、筛选页、面包屑

## 5. 对外 API

- [x] 5.1 `GET/POST /api/v1/admin/groups`、`PATCH/DELETE /api/v1/admin/groups/{ref}`、`POST .../groups/{ref}/move`
- [x] 5.2 Book 的创建/更新接受 `group`（slug 或 id），缺少时 4xx；Book 表示补 `group` 对象
- [x] 5.3 `/api/v1/books?group=<slug>` 过滤；`/meta` 能力列表补 `groups`
- [x] 5.4 API 测试：组 CRUD、非空组删除被拒、缺组建 Book 被拒、过滤生效

## 6. 文档

- [x] 6.1 `docs/authoring.md`：组怎么用、与「分卷」的区别、迁移后怎么整理默认分组
- [x] 6.2 `docs/content-model.md`：`book_groups` 表与 `books.group_id`
- [x] 6.3 `docs/ai.md` / `docs/api.md`：组端点与 Book 的 `group` 字段
- [x] 6.4 `README.md` 功能清单

## Workflow follow-up

- `openspec validate add-book-groups --strict` 通过后归档该变更，并把归档目录提交入库。
