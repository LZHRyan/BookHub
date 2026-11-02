# Tasks

## 1. 样式

- [x] 1.1 `style.css` 新增 `.admin-card-grid` / `.admin-card` / `.admin-card-head` / `.admin-card-icon` / `.admin-card-desc` / `.admin-card-meta` / `.admin-card-foot`，`minmax(340px, 1fr)` 自适应 3→2→1 列
- [x] 1.2 卡片内标题与摘要用 `line-clamp` 截断，`min-width: 0` 防溢出；底部操作 `flex-wrap` 兼容窄屏

## 2. 分组页

- [x] 2.1 `admin/groups.html`：表格 → 卡片网格；卡片含图标、标题、slug、简介、`N 本` 徽章（链接 `?group=<slug>`）、回收站徽标、改名/删除
- [x] 2.2 上移/下移改为卡片右上角两个并排的图标表单
- [x] 2.3 空态与「共 N 个分组」统计保持

## 3. Book 列表

- [x] 3.1 `dashboard()`：每项补 `cover`（`media_service.cover_url`）
- [x] 3.2 `admin/dashboard.html`：表格 → 卡片网格；卡片含封面/图标、标题（链接到详情）、`/b/<slug>`、分组徽章、`已发布/全部` 章节数、近 7 天访问、更新时间、编辑/查看/删除
- [x] 3.3 筛选表单、统计卡片、分页、空态保持不变

## 4. 测试

- [x] 4.1 `tests/test_admin_lists.py`：分组页无 `<table>` 且有 `.group-card`；Book 页无 `<table>` 且有 `.book-admin-card`；筛选链接 `?group=<slug>` 仍在；删除仍是带 `data-confirm` 的表单
- [x] 4.2 既有断言（`?group=infra-a">1</a>`、分组标题、Book 标题、筛选生效）保持通过
- [x] 4.3 全量 `pytest` 与 `ruff check app tests scripts` 通过

## 5. 文档

- [x] 5.1 `docs/authoring.md`：分组页/Book 列表的描述改为「卡片」
- [x] 5.2 `README.md`：功能清单不需要改（属界面细节），但把「管理端」描述里提到的表格措辞核对一遍

## Workflow follow-up

- `openspec validate polish-admin-lists --strict` 通过后归档该变更，并把归档目录提交入库。
