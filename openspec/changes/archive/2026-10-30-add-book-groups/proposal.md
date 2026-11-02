# Proposal

## Why

现在首页是「一排 Book 卡片」：11 本书还看得过来，等到 30 本、50 本时，读者只能靠标题猜哪几本属于同一个主题。章节已经有「分卷」组织，但 Book 这一层没有任何分组手段——研发部的文档天然分成「基础设施」「业务系统」「规范制度」几大块，这个信息现在完全丢失。

## What Changes

- 新增**组**（`book_groups`）：一组就是首页上的一个分区，带标题、slug、简介、图标与位置。
- `books.group_id` **必填**：每本 Book 必须属于一个组；新建/编辑表单里是必选下拉。
- 存量 Book 迁移时自动归入一个「默认分组」，界面不会出现「未分组」的空档。
- 首页按组从上到下分区渲染：每组一个标题 + 该组的 Book 卡片；组之间用上移/下移调整顺序，组内沿用现有「置顶 + 热度」排序。
- 组的管理：新建、改名/改 slug/简介/图标、上下移、删除。**非空组不允许删除**（先把 Book 移走），**最后一个组不允许删除**（否则无处安放 Book）。
- Book 页面包屑补上组名（站点 / 组 / Book），读者知道自己处在哪一块。
- 管理端：新增「组」管理页；Book 列表加「组」列与组筛选；Book 表单加必选组下拉。
- 对外 API：新增 `/api/v1/admin/groups`（列表 / 创建 / 修改 / 删除），Book 的创建与更新接受 `group`，Book 表示补 `group` 对象。

## Capabilities

### New Capabilities

- `book-groups`: 组的所有权与约束（Book 必属于一个组、组内排序语义、删除前置条件、默认分组的兜底作用），以及首页按组分区的呈现契约。

### Modified Capabilities

- `book-catalog`: Book 创建/更新 MUST 指定组，Book 表示 MUST 带组信息，列表 MUST 支持按组过滤。
- `management-api`: 组的增删改 MUST 通过管理 API 可得，Book 的创建/更新 MUST 接受 `group`。
- `web-presentation`: 首页 MUST 按组分区渲染，管理端 MUST 提供组的管理入口。

## Impact

- **数据**：迁移 `0014_book_groups`（建 `book_groups`、插入默认分组、`books.group_id` 加列 + 回填 + 收紧为 NOT NULL + 外键）。
- **服务层**：新增 `app/services/book_groups.py`（增删改查、排序、计数、默认组兜底）；`books.create_book/update_book` 接受 `group`，`list_books` 支持 `group` 过滤。
- **Web**：`index.html` 分区渲染；`book.html` 面包屑；新增 `admin/groups.html` 与 `admin/group_form.html`；Book 表单与列表加组。
- **API**：4 个组端点 + Book 契约扩展。
- **测试**：`tests/test_book_groups.py`；`tests/test_api.py`、`tests/test_web.py` 里 Book 创建相关的用例补 `group`。
- **文档**：`docs/authoring.md`、`docs/api.md`、`docs/content-model.md`、`docs/ai.md`、`README.md`。
- **非目标**：不做多对多（一本书只在一个组）、不做组级可见性或权限、不做组首页/组落地页、不做拖拽排序（组内仍按热度，组间用上下移）。
