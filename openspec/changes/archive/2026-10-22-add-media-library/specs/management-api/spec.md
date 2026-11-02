# Spec Delta

## ADDED Requirements

### Requirement: 媒体资源管理 MUST 通过管理 API 完整可得

管理 API MUST 提供媒体资源的列表、multipart 上传、删除与未引用清理四类操作。它们 MUST 沿用既有的 `read`/`write` 作用域、幂等重放、`dry_run` 预览、`confirm` 显式确认与 Token 审计归属约定，MUST 返回与网页端一致的资源表示。

#### Scenario: 上传返回可直接引用的地址

- **WHEN** 使用具备 `write` 作用域的 Token 向某 Book 上传一张图片（`multipart/form-data`）
- **THEN** 响应 201，包含资源 id、原始文件名、字节数、类型与站内访问地址
- **AND** 正文里可直接使用该地址引用

#### Scenario: 列表包含引用状态与配额用量

- **WHEN** 请求某 Book 的媒体列表
- **THEN** 每项包含是否被正文引用的标记
- **AND** 响应包含该 Book 的配额上限与当前占用

#### Scenario: 删除需要显式确认并支持预览

- **WHEN** 调用删除媒体接口但未带 `confirm=true`
- **THEN** 返回 4xx 并说明需要确认
- **AND** 带 `dry_run=true` 时只返回该操作的影响面而不改动数据

#### Scenario: 清理默认只预览

- **WHEN** 调用未引用清理接口且未带 `confirm=true`
- **THEN** 返回将被删除的资源清单与字节数合计
- **AND** 没有任何资源被删除

#### Scenario: 只读 Token 被拒绝

- **WHEN** 使用只具备 `read` 作用域的 Token 上传媒体
- **THEN** 返回 403 且错误码指出缺少 `write` 作用域
- **AND** 不产生文件与记录
