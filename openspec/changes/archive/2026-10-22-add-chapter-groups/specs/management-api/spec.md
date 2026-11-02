# Spec Delta

## ADDED Requirements

### Requirement: 分卷管理 MUST 通过管理 API 可得

管理 API MUST 提供分卷的创建、重命名/改 slug、删除三类操作，并 MUST 允许在创建或修改章节时通过 `parent` 字段设置归属。它们 MUST 沿用既有的 Token 作用域、幂等重放、`dry_run` 预览、`confirm` 显式确认与审计归属约定，MUST 返回与网页端一致的分卷表示（含 `kind`、`children_count`）。

#### Scenario: 创建分卷返回表示

- **WHEN** 使用具备 `write` 作用域的 Token 在某个 Book 下创建分卷
- **THEN** 响应 201，包含该分卷的 id、slug、title、kind 与 `children_count = 0`
- **AND** 之后创建的章节可以引用该分卷的 slug 作为 `parent`

#### Scenario: 通过 parent 字段设置归属

- **WHEN** 创建或修改章节时传 `parent` 为某分卷的 slug
- **THEN** 该章节归属到该分卷
- **AND** 传 `parent: null` 时可把章节移回根层

#### Scenario: 非法 parent 被拒绝

- **WHEN** `parent` 指向另一个 Book 的分卷，或指向普通章节
- **THEN** 返回 4xx 且错误信息指明 parent 不合法
- **AND** 章节内容与归属保持原状

#### Scenario: 删除非空分卷被拒绝

- **WHEN** 对含子章节的分卷调用删除接口
- **THEN** 返回 4xx 并说明剩余子章节数量
- **AND** 带 `dry_run=true` 时只返回影响面而不改动数据
