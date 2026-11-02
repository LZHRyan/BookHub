# Proposal

## Why

管理端的「分组」和「Book 列表」用的是表格，但它们的字段都很少（分组 4 列、Book 7 列），表格把可用宽度均匀摊给每一列，结果是：

- 标题后面一大片空白，`slug`、`Book 数` 被推到很远的右侧，视觉重心散开；
- 操作按钮（改名/删除、编辑/查看/删除）在单元格里**竖向堆叠**，把单行撑到约 100px，一屏只能看 7 条；
- 分组页只有 4 行数据，却铺满整屏，信息密度极低。

这两页的数据形状（少量字段 + 图标 + 需要操作）本来就适合卡片，不适合表格。

## What Changes

- **分组管理**改成卡片网格：每张卡显示图标 + 标题 + slug + 简介，底部一行是「N 本 / 回收站 N / 改名 / 删除」，右上角是上移/下移图标按钮（并排，不再竖向堆叠）。
- **Book 管理**改成卡片网格：卡片左侧是封面（没有封面就用 emoji/矢量图标块），右侧是标题、站点路径、摘要（两行截断），底部分两行放「分组 / 章节数 / 近 7 天访问 / 更新时间」与「编辑 / 查看 / 删除」。
- 两页的筛选、统计卡片、空态、分页行为保持不变；分组筛选入口从「表格里的数字」变成卡片上的「N 本」徽章（链接仍指向 `?group=<slug>`）。
- 卡片网格在宽屏 2–3 列、窄屏单列；操作按钮横向排布，单卡高度比原表格行更低。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `web-presentation`: 分组管理与 Book 管理 MUST 使用卡片网格而非表格；同一张卡内 MUST 把标题、次要信息与操作分成三层；操作按钮 MUST 横向排布且不得把卡高撑大；数字与状态 MUST 用徽章/紧凑文本表达。

## Impact

- **模板**：`admin/dashboard.html`（Book 列表区）、`admin/groups.html`（整页）
- **样式**：`app/static/style.css` 新增 `.admin-card-grid / .admin-card / .admin-card-head / .admin-card-meta / .admin-card-foot`
- **路由**：`dashboard()` 给每项补 `cover`（复用 `media_service.cover_url`）；`groups_page` 已有序号与计数，无需改数据
- **测试**：`tests/test_admin_lists.py`（断言卡片结构、筛选链接、操作按钮横排）；既有断言（`?group=infra-a">1</a>`、分组标题、Book 标题）保持通过
- **非目标**：章节表格不改（字段多、需要批量勾选）、不动统计卡片、不做拖拽排序、不改数据与 API
