# book-pinning Specification

## Purpose
定义 Book 的「置顶」开关：用最低成本的人工干预把重点内容固定在列表最前面，同时保留自动热度排序作为主序，不让编辑行为重新变成任意手工序号。

## Requirements

### Requirement: 置顶 MUST 优先于自动权重

Book MUST 有一个布尔开关 `pinned`。列表排序 MUST 先按 `pinned` 分组（置顶在前），组内 MUST 继续按自动权重降序，权重相同时按创建时间与 id 兜底。MUST NOT 提供任意手工序号字段。

#### Scenario: 置顶书排在热度更高的书前面

- **WHEN** 一本几乎无人访问的 Book 被置顶，而另一本热度很高但未置顶
- **THEN** 首页与 `/api/v1/books` 中置顶的那本排在最前
- **AND** 两本都未置顶时仍按原热度顺序

#### Scenario: 多本置顶内部仍按热度

- **WHEN** 三本 Book 都被置顶
- **THEN** 它们内部按自动权重降序排列
- **AND** 取消其中一本的置顶后它回到非置顶区

### Requirement: 置顶 MUST 可审计且可撤销

置顶与取消置顶 MUST 记入审计（动作、目标 Book、开关后的值），且 MUST 立即可撤销。置顶状态 MUST 出现在管理端清单与只读 API 的 Book 表示中。

#### Scenario: 取消置顶立即生效

- **WHEN** 管理员取消某本书的置顶
- **THEN** 下一次列表请求中它回到按权重计算的位置
- **AND** 审计里能查到这次变更

#### Scenario: API 表示包含置顶状态

- **WHEN** 程序调用方请求 Book 列表或详情
- **THEN** 每个 Book 表示都带 `pinned` 布尔字段
