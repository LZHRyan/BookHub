## MODIFIED Requirements

### Requirement: 增量同步 MUST 通过 since 参数提供变更流

`GET /api/v1/changes?since=<ISO-8601>` MUST 返回该时间点之后发布、更新或删除的节变更摘要（响应键为 `sections`），每条含节标识、所属 Book 与章的标识和 slug、变更类型与时间戳；被删除的节（含因整章删除而下架的节）MUST 以 `deleted: true` 的墓碑条目出现而不是从结果中消失。缺少 `since` MUST 返回参数校验错误，格式非法或无法解析 MUST 返回 400。

墓碑条目 MUST 只回标识与 slug：已删除或已撤回的内容 MUST NOT 再对外返回 `title` 或 `chapter_title`，避免增量流成为泄露未发布标题的旁路。

#### Scenario: 删除以墓碑形式返回

- **WHEN** 某节在 `since` 之后被软删除（或它所属的章被删除），外部程序再次请求 `GET /api/v1/changes?since=...`
- **THEN** 结果中出现该节的条目且带 `deleted: true`
- **AND** 客户端据此可删除本地副本

#### Scenario: 墓碑不返回标题

- **WHEN** 增量流中出现 `deleted: true` 的条目
- **THEN** 该条目不包含 `title` 与 `chapter_title` 字段
- **AND** `book_slug`、`chapter_slug`、`slug`、`updated_at` 等定位字段仍然存在

#### Scenario: 非法 since 被拒绝

- **WHEN** 外部程序以无法解析的 `since` 值请求变更流
- **THEN** 返回 400 与统一错误体
- **AND** 响应不返回任何变更条目
