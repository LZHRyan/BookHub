# Spec Delta

## ADDED Requirements

### Requirement: 组 MUST 通过管理 API 完整可得

管理 API MUST 提供组的列表（含 Book 数量）、创建、修改（标题/slug/简介/图标）、删除与上下移。Book 的创建 MUST 接受 `group`（slug 或 id），更新 MUST 支持改归属。全部操作 MUST 复用 `admin` 作用域的 Token 与审计约定。

#### Scenario: 创建组并建 Book

- **WHEN** 使用 `admin` Token 创建组「基础设施」，再创建 Book 并传 `{"group": "infra"}`
- **THEN** 组列表里该书数量为 1
- **AND** Book 表示里的 `group.slug` 为 `infra`

#### Scenario: 删除非空组被拒绝

- **WHEN** 删除仍有 Book 的组
- **THEN** 返回 4xx 并说明剩余数量
- **AND** 组与 Book 都不变

#### Scenario: 缺少组创建 Book 被拒绝

- **WHEN** 创建 Book 时没有 `group` 字段
- **THEN** 返回 4xx 并提示必须指定组
