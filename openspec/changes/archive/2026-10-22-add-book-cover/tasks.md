# Tasks

## 1. 数据与服务

- [x] 1.1 `Book.cover_media_id`（FK `media_assets.id`，可空）+ 迁移 `0011_book_cover`（batch 加列 + 命名外键 + downgrade），实测 `upgrade → downgrade → upgrade` 均通过
- [x] 1.2 `books.set_cover()`：校验本 Book / 图片 / 未删除，成功写 `book.cover` 审计（含 from/to）
- [x] 1.3 `media.delete_media()` 解绑封面（置空 + 审计 `unbound: true`），测试覆盖「删封面图后 cover_media_id 为 None」
- [x] 1.4 `media.cover_url()` 统一取封面地址；`_book_json` 输出 `cover`（根相对地址），`/api/v1` 输出绝对地址

## 2. 管理端

- [x] 2.1 媒体库页面：图片卡片显示「设为封面 / 当前封面 + 取消封面」，页面顶部回显 `?error=`
- [x] 2.2 `POST /admin/books/{id}/cover`：`media_id` 为空表示清除，CSRF + 审计 + 303 回媒体库
- [x] 2.3 Book 编辑页显示当前封面缩略图与「打开媒体库」入口
- [x] 2.4 管理 API：`BookUpdate.cover_media_id`（`int | None`，用 `model_fields_set` 区分「不传」与「显式 null」）

## 3. 读者端

- [x] 3.1 `index.html`：卡片改为封面图 + 图标回退，摘要截断 2 行；实测有/无封面卡片高度与文字基线一致
- [x] 3.2 `book.html`：hero 区在有封面时展示 108px 缩略图
- [x] 3.3 `style.css`：`.book-cover`（148px、`object-fit: cover`）、`book-card` 改纵向、`.cover-preview` 等

## 4. 测试与文档

- [x] 4.1 `tests/test_cover.py`（11 条）：设置/清除、跨 Book 拒绝、附件拒绝、已删资源拒绝、删图自动解绑、媒体库按钮、编辑页预览、首页与详情页渲染、API 设置与越权
- [x] 4.2 全量 `pytest` 与 `ruff check app tests scripts` 通过；`tests/test_emoji.py` 的图标回退断言同步为 `book-cover-fallback`
- [x] 4.3 `docs/authoring.md`（设置封面与建议尺寸）、`docs/ai.md`（`cover_media_id`）、`docs/content-model.md`（字段）、`README.md` 功能清单

## Workflow follow-up

- `openspec validate add-book-cover --strict` 通过后归档该变更，并把归档目录提交入库。
