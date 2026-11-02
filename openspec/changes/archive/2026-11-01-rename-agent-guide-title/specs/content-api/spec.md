## MODIFIED Requirements

### Requirement: 站点 MUST 暴露内置指南的地址与标记

`GET /api/v1/site` MUST 返回 `guide` 字段，指向站点内置的《AI Agent 接入使用指南》：`slug`、`title`、`url`（读者页）与 `api_url`（只读 API）。指南不存在或已被关闭时该字段 MUST 为 `null`，MUST NOT 让端点失败。Book 表示（列表项、详情、管理 API）MUST 带布尔字段 `is_builtin`，使外部工具能一眼识别内置 Book。指南改名 MUST NOT 改变 `slug` 与 `guide` 的结构，外部工具不需要跟着改配置。

#### Scenario: site 给出指南地址

- **WHEN** 外部程序请求 `GET /api/v1/site`
- **THEN** `guide.slug` 为 `ai-agent-guide`，`guide.url` 与 `guide.api_url` 可直接请求
- **AND** 请求 `guide.api_url` 能拿到该书的目录，其 `title` 为「AI Agent 接入使用指南」

#### Scenario: 关闭后 guide 为 null

- **WHEN** 部署关闭了内置指南（或该 slug 被用户的书占用，系统放弃创建）
- **THEN** `GET /api/v1/site` 仍返回 200
- **AND** `guide` 为 `null`

#### Scenario: Book 表示带 is_builtin

- **WHEN** 请求 `GET /api/v1/books` 或 `GET /api/v1/admin/books`
- **THEN** 每个条目都带 `is_builtin` 布尔值
- **AND** 内置指南的条目为 `true`，用户创建的书为 `false`
