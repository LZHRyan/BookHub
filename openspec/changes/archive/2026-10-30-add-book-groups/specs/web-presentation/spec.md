# Spec Delta

## ADDED Requirements

### Requirement: 首页 MUST 按组分区渲染

首页 MUST 以组为单位分区展示 Book：每个分区有一个组标题（可带图标与简介）与其下的 Book 卡片网格，分区之间 MUST 有可见的分隔。MUST NOT 把所有组的 Book 混排成一个网格。

#### Scenario: 两个组各自成区

- **WHEN** 首页存在「基础设施」与「规范制度」两个组且都有公开 Book
- **THEN** 页面出现两个分区，各自有组标题
- **AND** 每个分区只包含该组的 Book

#### Scenario: 组标题可点击筛选

- **WHEN** 读者点击某分区标题
- **THEN** 跳到按该组筛选的列表（`/?group=<slug>`）
- **AND** 该页只显示这一组的 Book

### Requirement: 管理端 MUST 提供组管理入口与可视化归属

管理端 MUST 有「组」管理页（列表 + 新建/改名/删除/上下移）与 Book 侧的组入口：Book 列表 MUST 显示所属组，Book 表单 MUST 用必选下拉呈现组。

#### Scenario: Book 表单必选组

- **WHEN** 打开新建 Book 表单
- **THEN** 组是必选下拉，默认不选中
- **AND** 提交时未选组会看到字段级错误

#### Scenario: Book 列表可按组筛选

- **WHEN** 在管理端 Book 列表选择某个组
- **THEN** 列表只剩该组的 Book
- **AND** 仍在显示已发布/全部章节数
