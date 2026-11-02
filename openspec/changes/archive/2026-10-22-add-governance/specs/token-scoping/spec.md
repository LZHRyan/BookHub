# Spec Delta

## Purpose

让 API Token 的权限可以收窄到特定 Book，并在越界时给出明确错误，使「给某个团队或某个 AI 工具发一个只能改自己文档的凭据」成为可落地的做法。

## ADDED Requirements

### Requirement: Token MUST 可限定到指定 Book

签发 Token 时 MUST 可以选择它能操作的 Book 集合；未选择表示全部 Book。范围 MUST 持久化在 Token 上，并在 Token 表示中可见（Book 的 id 与 slug）。

#### Scenario: 签发时限定范围

- **WHEN** 管理员签发一个只包含「部署手册」的 `write` Token
- **THEN** Token 列表显示其范围为「部署手册」
- **AND** Token 表示里带该 Book 的 id 与 slug

#### Scenario: 不限定范围表示全部

- **WHEN** 签发 Token 时不选择任何 Book
- **THEN** 该 Token 可操作全部 Book（仍受作用域限制）

### Requirement: 越界访问 MUST 被拒绝

带 Book 范围的 Token 访问范围外 Book 的管理端点时 MUST 返回 403，错误信息 MUST 指出 Token 无权操作该 Book。校验 MUST 覆盖读与写端点，且 MUST NOT 因为端点是否修改数据而放宽。

#### Scenario: 读端点也被拦截

- **WHEN** 限定到 Book A 的 Token 请求 Book B 的章节列表
- **THEN** 返回 403 并说明无权操作 Book B

#### Scenario: 范围内的写操作正常

- **WHEN** 同一 Token 请求 Book A 的章节列表或创建章节
- **THEN** 正常返回 200 / 201

#### Scenario: 全站级端点不受 Book 范围限制

- **WHEN** 该 Token 请求 `/api/v1/admin/meta` 或用户列表
- **THEN** 按作用域正常放行或拒绝，不因 Book 范围而失败

### Requirement: 范围变更 MUST 可追溯

签发与吊销 MUST 记入审计，审计 detail MUST 包含作用域与 Book 范围，便于事后核对「这个 Token 当时能改什么」。

#### Scenario: 签发留痕

- **WHEN** 管理员签发一个限定范围的 Token
- **THEN** 审计中出现 `token.create` 记录
- **AND** detail 里带 scopes 与 book 范围
