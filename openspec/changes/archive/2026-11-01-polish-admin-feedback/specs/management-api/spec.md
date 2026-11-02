## ADDED Requirements

### Requirement: 建章 MUST 明确标题来源

通过管理 API 建章时，标题 MUST 有确定来源，不容忍"悄悄回落"：

- `application/json` 请求 MUST 提供非空 `title`；只给空白标题时 MUST 返回 400（理由：JSON 请求没有文件名可回落，空标题会让章变成「正文」并生成 `chapter-xxxxxx` 这类随机 slug）；
- `multipart/form-data` 请求 MAY 省略 `title`，此时 MUST 用第一个上传文件的文件名（去扩展名）作为章标题——这是既有契约；
- 两种情况下失败 MUST NOT 落库（MUST NOT 留下空标题或随机 slug 的章）。

#### Scenario: JSON 建章缺标题被拒绝

- **WHEN** 用 `POST /api/v1/admin/books/{book}/chapters` 发 JSON，`title` 为空串或纯空白
- **THEN** 返回 400，`error.message` 说明章标题必填
- **AND** 该 Book 下没有新增章

#### Scenario: 上传文件时仍可省略标题

- **WHEN** 用 multipart 上传 `01-intro.md` 且不传 `title`
- **THEN** 返回 201，章标题为 `01-intro`
- **AND** 该章下恰好有一个节
