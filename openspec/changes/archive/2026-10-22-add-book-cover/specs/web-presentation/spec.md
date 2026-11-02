# Spec Delta

## ADDED Requirements

### Requirement: 首页卡片 MUST 支持封面布局并回退图标

首页 Book 卡片在有封面时 MUST 以固定高度展示封面图（`object-fit: cover`，等比例裁切），无封面时 MUST 回退为 emoji 图标块；两种状态 MUST 保持卡片高度与文字基线一致，标题与摘要 MUST 限制行数并截断，MUST NOT 因为摘要过长而撑破卡片。

#### Scenario: 有封面与无封面卡片对齐

- **WHEN** 首页同时渲染一本有封面与一本无封面的 Book
- **THEN** 两张卡片高度一致
- **AND** 有封面的显示图片，无封面的显示图标块

#### Scenario: 摘要过长不撑破卡片

- **WHEN** 某 Book 的摘要超过三行
- **THEN** 摘要被截断为固定行数并保留省略号
- **AND** 卡片内的章节数与更新时间仍可见

### Requirement: Book 详情 hero MUST 在有封面时展示缩略图

Book 详情页 hero 区在有封面时 MUST 展示封面缩略图（固定宽高、圆角、比例裁切），无封面时只有图标与标题；小屏下封面 MUST 缩为图标尺寸或隐藏，MUST NOT 挤压标题造成换行错乱。

#### Scenario: 详情页显示封面

- **WHEN** 打开一本已设置封面的 Book
- **THEN** hero 区出现封面缩略图
- **AND** 标题、摘要与元信息仍完整可见
