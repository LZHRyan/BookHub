# Tasks

## 1. 数据与模型

- [x] 1.1 `app/models.py`：`CHAPTER_KIND_DOC` / `CHAPTER_KIND_GROUP` / `CHAPTER_KINDS`，`Chapter.kind` 与 `Chapter.parent_id`（自引用 FK），索引 `ix_chapters_tree (book_id, parent_id, sort_order)`；`import app.models` 通过
- [x] 1.2 迁移 `0009_chapter_groups`：加两列（`kind` server_default `'doc'`）、建索引、含 downgrade；在既有库上 `alembic upgrade head` 跑通

## 2. 服务层

- [x] 2.1 `next_sort_order(session, book_id, parent_id=None)` 按父级取最大值；`children_of(session, book_id, parent)` 返回同级有序列表
- [x] 2.2 `create_group()`：标题必填、slug 唯一、`kind='group'`、无正文无版本；单测覆盖「分卷不写 `chapter_versions`」
- [x] 2.3 `update_group()` 改名/改 slug；`delete_group()` 对非空分卷抛 4xx 语义错误并带子章节数量
- [x] 2.4 `create_chapter(..., parent=...)`：校验 parent 属于同一 Book 且是分卷；`next_sort_order` 落到该父级
- [x] 2.5 `move_chapter()` 改为同级交换（按 `parent_id` 过滤）；新增 `move_to_parent()` 跨父级移动并落到目标末尾
- [x] 2.6 `tree(session, book_id, published_only=False)` 返回 `[{group, items}]` 结构；`published_chapters` 排除分卷
- [x] 2.7 单测：分卷不能嵌套、章节不能当父级、移出后变空分卷、删除非空分卷被拒、组内移动不影响根层

## 3. 管理端

- [x] 3.1 Book 详情页改为按 `sections` 分区渲染：分卷标题行（改名/上下移/删除）+ 该组章节表格 + 根层独立章节区
- [x] 3.2 新增 `admin/group_form.html` 与 `GET/POST /admin/books/{id}/groups/new`、`/groups/{gid}/edit`、`/groups/{gid}/delete`
- [x] 3.3 章节表单增加「归属分卷」下拉（不归入分卷 + 各分卷），保存时写入 `parent_id`
- [x] 3.4 章节行与分卷行的上移/下移都只在同级内生效（模板传 `parent` 上下文）
- [x] 3.5 `tests/test_groups.py` 覆盖网页端：新建分卷、把章节移入、删除非空分卷报错、删除空分卷

## 4. 读者端

- [x] 4.1 `book.html` 按分卷分组渲染目录，编号 `1.` / `1.1`，空分卷只显示标题
- [x] 4.2 `chapter.html` 侧边目录同样分组编号
- [x] 4.3 `/b/{book}/{group-slug}` 重定向到 Book 页（不返回 404/500）
- [x] 4.4 `tests/test_groups.py` 覆盖：分组渲染与编号、空分卷、分卷地址重定向

## 5. 对外 API

- [x] 5.1 `ChapterCreate` / `ChapterReplace` 接受 `parent`（slug / id / null）；非法 parent 返回 4xx
- [x] 5.2 新增 `POST /api/v1/admin/books/{ref}/groups`、`PATCH .../groups/{ref}`、`POST .../groups/{ref}/delete`（`dry_run` 预览，删除需 `confirm`）
- [x] 5.3 章节表示补 `kind` 与 `parent`；Book 详情目录项补 `kind` 与 `parent`；`/meta` 能力列表补 `groups`
- [x] 5.4 `tests/test_groups.py` 与 `tests/test_api.py` 覆盖 API 契约（创建分卷、parent 归属、非法 parent、非空分卷删除）

## 6. 集成与文档

- [x] 6.1 全量 `pytest` 与 `ruff check app tests scripts` 通过
- [x] 6.2 `docs/authoring.md` 新增「用分卷组织章节」一节（一层限制、编号规则、删除前置条件）
- [x] 6.3 `docs/content-model.md` 更新 `Chapter` 字段与排序语义；`docs/ai.md` 补分卷端点；`README.md` 功能清单加一行
- [x] 6.4 容器重建后手工核对 Book 页与管理页分组渲染与控制台无报错

## Workflow follow-up

- `openspec validate add-chapter-groups --strict` 通过后归档该变更，并把归档目录提交入库。
