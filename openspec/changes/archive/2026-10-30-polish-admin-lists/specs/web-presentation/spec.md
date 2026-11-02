# Spec Delta

## ADDED Requirements

### Requirement: 分组与 Book 管理 MUST 使用卡片网格

管理端「分组」页与「Book 列表」MUST 用卡片网格呈现条目，MUST NOT 用表格。卡片 MUST 分三层：头部（图标 + 标题 + 次要标识）、正文（简介/摘要，最多两行截断）、底部（状态信息与操作）。同一行卡片高度 MUST 一致。

#### Scenario: 分组页是卡片而不是表格

- **WHEN** 打开 `/admin/groups`
- **THEN** 每个分组是一张卡片，含图标、标题、slug、Book 数
- **AND** 页面里没有 `table` 元素

#### Scenario: Book 列表是卡片

- **WHEN** 打开 `/admin`
- **THEN** 每本 Book 是一张卡片，含封面或图标、标题、分组、章节数、访问量、更新时间
- **AND** 分页与分组筛选仍然有效

### Requirement: 卡片操作 MUST 横向排布且不撑高卡片

卡片底部的操作（改名/删除、编辑/查看/删除）MUST 横向排布，MUST NOT 竖向堆叠；破坏性操作 MUST 在视觉上可区分并保留二次确认。卡片的次要信息 MUST 用徽章或小字号文本，不得换行撑高整行。

#### Scenario: 操作按钮在一行

- **WHEN** 查看任意分组卡或 Book 卡
- **THEN** 该卡的操作按钮在同一行内
- **AND** 删除按钮仍是危险色且点击后要确认

### Requirement: 列表信息密度 MUST 高于原表格布局

在 1440px 宽视口下，Book 列表 MUST 至少一屏显示 6 张卡片（原表格约 7 行但行高接近 100px）；分组卡片的单卡高度 MUST 明显低于原表格行高（≈100px），且卡内文字 MUST 不因截断而丢失关键信息（标题、分组、数量）。

#### Scenario: 一屏看到更多条目

- **WHEN** 在 1440×900 视口打开 Book 列表且有 12 本书
- **THEN** 首屏可见不少于 6 张卡片
- **AND** 每张卡的标题与分组完整可读
