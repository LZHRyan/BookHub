# Proposal

## Why

现在一个 Book 里所有章节是一条平铺列表。研发文档一多就是三四十条并排：接口文档、部署手册、事故复盘、规范混在一起，读者只能靠标题自己找边界，主编也没法表达「这几章属于同一个主题」。知识库缺的是**分卷**这一层结构。

## What Changes

- 章节新增两个字段：`kind`（`doc` / `group`）与 `parent_id`（自引用外键）。`group` 是**分卷**：只有标题与位置，没有正文、没有版本、不进搜索结果。
- 层级只支持**一层**：分卷下挂章节，分卷不能再嵌套分卷，章节不能有子章节。理由见 `design.md`（保持所有章节 URL 不变、结构与交互都不复杂化）。
- 排序作用域从「整个 Book」改为「同一父级」：分卷与未分卷章节在根层共用一串 `sort_order`，分卷内的章节在组内各自排序；上移/下移只在同级之间交换。
- 章节移动支持跨父级：`POST /api/v1/admin/books/{ref}/chapters/{chapter}/move` 增加 `parent` 参数（分卷 slug / id / `null`），网页端在章节表单里用下拉框设置归属。
- 分卷管理：新建、改名/改 slug、删除。删除有子章节的分卷 MUST 被拒绝（先把章节移出去），避免"删一个卷一锅端"。
- 读者侧：Book 页目录按分卷分组显示并编号（`1.`、`1.1`），章节页侧边目录同样分组；直接访问分卷的章节地址返回 Book 页（分卷没有正文）。
- 管理端：Book 详情页按分卷分区渲染（每组一个小标题 + 该组的章节表格 + 组内上移/下移/改名/删除），增加「新建分卷」入口。
- 管理 API：新增 3 个分卷端点，章节表示里补 `kind` 与 `parent`；`/meta` 能力列表补 `groups`。

## Capabilities

### New Capabilities

- `chapter-taxonomy`: 分卷（组）与章节归属的契约：什么能成为分卷、层级深度上限、归属变更规则、删除分卷的前置条件，以及目录/侧边导航对外呈现的分组与编号语义。

### Modified Capabilities

- `chapter-lifecycle`: 排序与移动的作用域从整个 Book 收窄到同一父级，并新增跨父级移动与「删除分卷需先清空子章节」的约束。
- `management-api`: 分卷的增删改 MUST 通过管理 API 可得，章节的 `parent` 也必须能通过 API 读写。
- `book-catalog`: Book 详情的章节目录 MUST 反映分卷分组与编号。

## Impact

- **数据**：迁移 `0009_chapter_groups`（加 `kind`、`parent_id` 与 `(book_id, parent_id, sort_order)` 索引，存量行 `kind='doc'`、`parent_id=NULL`），有 downgrade。
- **服务层**：`app/services/chapters.py` 增加 `create_group` / `update_group` / `delete_group` / `tree` / `children_of` / `move_to_parent`，`next_sort_order`、`move_chapter`、`published_chapters` 改为按父级作用域。
- **Web**：`app/web/admin.py`（分卷表单页与动作、章节表单的归属下拉、Book 详情分区）、`app/web/public.py`（按树渲染）。
- **API**：`app/api/admin.py` 新增 3 个端点，`ChapterCreate`/`ChapterReplace` 接受 `parent`。
- **模板**：`admin/book_detail.html`、`admin/group_form.html`（新）、`admin/chapter_form.html`、`book.html`、`chapter.html`、`_sidebar` 部分。
- **测试**：新增 `tests/test_groups.py`；排序、搜索、API、展示相关的既有用例同步适配。
- **文档**：`docs/authoring.md`（分卷怎么用）、`docs/content-model.md`（字段与排序语义）、`docs/ai.md`（分卷端点）、`docs/api.md`。
- **非目标**：不做多层嵌套、不做分卷级权限或可见性、不做分卷封面、不做跨 Book 移动章节。
