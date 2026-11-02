# Spec Delta

## ADDED Requirements

### Requirement: Token 创建 MUST 接受 Book 范围

Token 创建接口 MUST 接受可选的 Book 列表（slug 或 id）；未提供表示全部 Book。Token 表示 MUST 带 `books`（每项含 id 与 slug）与 `scopes`。非法的 Book 引用 MUST 被拒绝并返回可辨识错误。

#### Scenario: 创建带范围的 Token

- **WHEN** 调用 `POST /api/v1/admin/tokens` 并传 `{"name": "team-a", "scopes": ["write"], "books": ["ops-handbook"]}`
- **THEN** 返回 201，`books` 中只有该 Book
- **AND** 用该 Token 访问其它 Book 的端点返回 403

#### Scenario: 非法 Book 被拒绝

- **WHEN** `books` 中包含不存在的 slug
- **THEN** 返回 4xx 并说明哪个引用无效
- **AND** 不产生 Token

### Requirement: 审计 MUST 支持导出与保留清理端点

管理 API MUST 提供 `GET /api/v1/admin/audit.csv`（与查询接口相同的过滤参数）与 `POST /api/v1/admin/audit/cleanup`（默认预览，`?confirm=true` 执行）。两者 MUST 受 `read` / `admin` 作用域约束并与网页端行为一致。

#### Scenario: 导出需要读权限

- **WHEN** 使用缺少 `read` 作用域的 Token 请求导出
- **THEN** 返回 403

#### Scenario: 清理默认预览

- **WHEN** 调用清理端点未带 `confirm=true`
- **THEN** 返回将被删除的条数
- **AND** 审计记录数量不变
