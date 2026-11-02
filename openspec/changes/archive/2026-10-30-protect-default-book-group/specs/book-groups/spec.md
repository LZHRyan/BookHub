## ADDED Requirements

### Requirement: 默认分组 MUST 随系统存在且不可删除

系统 MUST 始终存在一个 `slug` 为 `default` 的「默认分组」：由迁移创建，运行时的缺省归属逻辑 MUST 在缺失时补建。它 MUST NOT 可删除——网页端与管理 API 一律拒绝并返回可读错误，MUST NOT 因为「组里没有 Book」而放行。它的 `slug` MUST NOT 可修改（系统按该标识识别默认分组）；标题、简介、图标 MAY 修改。未指定分组的 Book MUST 归入默认分组。

#### Scenario: 默认分组删不掉

- **WHEN** 管理员在分组列表或编辑器里删除默认分组
- **THEN** 请求被拒绝，提示默认分组由系统创建、不能删除
- **AND** 默认分组仍在列表里，其下 Book 的归属不变

#### Scenario: 有其它分组时默认分组仍不可删

- **WHEN** 系统里除默认分组外还有空的自建分组
- **THEN** 自建空分组可以删除
- **AND** 默认分组删除请求仍被拒绝

#### Scenario: 默认分组可改名但标识固定

- **WHEN** 管理员把默认分组的标题改为「未分组」并提交
- **THEN** 保存成功，首页分区显示新标题
- **AND** 它的 `slug` 仍是 `default`；尝试修改 `slug` 会被拒绝并说明原因

#### Scenario: 管理 API 暴露 is_default

- **WHEN** 调用方请求 `GET /api/v1/admin/groups`
- **THEN** 每个分组条目都带 `is_default` 布尔值，默认分组为 `true`
- **AND** 对 `is_default=true` 的组调用 `DELETE` 返回 400，`PATCH` 改 `slug` 返回 400

## MODIFIED Requirements

### Requirement: 删除组 MUST 先腾空且保留最后一个

默认分组 MUST NOT 被删除（见「默认分组 MUST 随系统存在且不可删除」）。其余分组：仍有 Book 的组 MUST 拒绝删除，错误信息 MUST 说明剩余 Book 数量；系统 MUST 至少保留一个组，最后一个组 MUST NOT 被删除（由于默认分组始终存在，实际的「最后一个组」就是它）。

#### Scenario: 非空组删不掉

- **WHEN** 管理员删除一个含 3 本书的组
- **THEN** 请求被拒绝并说明还剩 3 本 Book
- **AND** 组与 Book 都不变

#### Scenario: 空组可删除

- **WHEN** 删除一个没有 Book 且不是默认分组的组
- **THEN** 删除成功
- **AND** 首页不再出现该分区

#### Scenario: 最后一个组不能删

- **WHEN** 系统里只剩默认分组时尝试删除它
- **THEN** 请求被拒绝并说明默认分组不能删除
- **AND** 默认分组与其下 Book 都保持原状
