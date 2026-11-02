## ADDED Requirements

### Requirement: 节管理 MUST 通过管理 API 可得

管理 API MUST 提供节的完整写能力：按章列出节、创建节（可同时上传文件）、修改节（标题/slug/格式/正文）、调整节顺序、软删除与恢复节，以及查看版本、对比版本与回滚。它们 MUST 沿用既有的 Token 作用域、幂等重放、`dry_run` 预览、`confirm` 显式确认与审计归属约定，MUST 返回与网页端一致的节表示（含 `id`、`slug`、`title`、`format`、`version`、`word_count`、`url`）。

#### Scenario: 创建节返回表示

- **WHEN** 使用具备 `write` 作用域的 Token 在某个章下创建节
- **THEN** 响应 201，包含该节的 id、slug、title、format 与 `version = 1`
- **AND** 之后可以在同一章下继续创建更多节

#### Scenario: 修改节内容生成新版本

- **WHEN** 对某节 `PATCH` 新正文并带 `base_version`
- **THEN** 响应中的 `version` 递增 1
- **AND** 用旧 `base_version` 再次提交返回 409 冲突

#### Scenario: 回滚节只影响该节

- **WHEN** 对某章的第二节点调用回滚到 `version = 1`
- **THEN** 该节内容变为 v1 的内容并生成更大的版本号
- **AND** 同章其它节与章状态保持不变

#### Scenario: 删除节可预览影响面

- **WHEN** 对某节调用删除接口并带 `dry_run=true`
- **THEN** 返回该节当前版本与访问路径等影响面信息
- **AND** 不带 `confirm=true` 的实际删除被拒绝

## MODIFIED Requirements

### Requirement: 响应 MUST 返回资源表示且错误 MUST 机器可读

成功响应 MUST 返回创建/更新后的资源表示（字段与只读 API 的表示一致，至少包含 id、slug、版本号与时间戳；章没有正文与版本，正文与版本在节上）。错误响应 MUST 使用统一结构 `{"error": {"code", "message", "request_id"}}`，并 MUST 区分参数错误、未认证、无权限、不存在、冲突与限流。

#### Scenario: 创建成功返回资源

- **WHEN** 创建章成功
- **THEN** 响应包含该章的 id、slug、published 状态与它下面的 `sections`（每节带 format、version）
- **AND** 单节章还会在顶层带该节的正文与版本字段

#### Scenario: 错误码可编程判断

- **WHEN** 请求一个不存在的 Book
- **THEN** 返回 404 且 `error.code` 为稳定的机器可读值

### Requirement: 排序与置顶 MUST 通过管理 API 可得

管理 API MUST 提供「按有序 id 整体重排整本 Book 的章」与「Book 置顶开关」两个写操作，MUST 沿用既有的 Token 作用域、幂等重放、`dry_run` 预览与审计归属约定；重排 MUST 校验 id 集合与该 Book 的章一致。

#### Scenario: 重排成功返回新顺序

- **WHEN** 使用具备 `write` 作用域的 Token 提交某 Book 的有序章 id 列表
- **THEN** 响应中返回该 Book 的新顺序
- **AND** 只读 API 的 Book 目录随之变化

#### Scenario: 置顶通过 PATCH 设置

- **WHEN** 调用 `PATCH /api/v1/admin/books/{ref}` 传 `{"pinned": true}`
- **THEN** 该 Book 的 `pinned` 变为真
- **AND** 列表顺序与审计同步变化

#### Scenario: 缺权限被拒绝

- **WHEN** 使用只具备 `read` 作用域的 Token 调用重排
- **THEN** 返回 403 且错误码指出缺少 `write` 作用域

## REMOVED Requirements

### Requirement: 分卷管理 MUST 通过管理 API 可得

**Reason**: 分卷这一层已从数据模型与路由中删除（迁移 `0015_chapter_sections`），不再有分卷的创建、改名与删除接口，章节也不再接受 `parent`。

**Migration**: 结构改由「章 → 节」承担：节的写接口见本能力新增的「节管理 MUST 通过管理 API 可得」；章的顺序调整仍用重排接口。
