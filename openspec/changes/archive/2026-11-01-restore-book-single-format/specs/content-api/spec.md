## RENAMED Requirements

- FROM: `### Requirement: Book 表示 MUST 暴露默认文档类型`
- TO: `### Requirement: Book 表示 MUST 暴露文档类型`

## MODIFIED Requirements

### Requirement: Book 表示 MUST 暴露文档类型

`/api/v1` 的 Book 列表项与 Book 详情 MUST 包含 `format` 字段，取值与站点内一致（`markdown` 或 `html`），表示整本书唯一的文档类型。每个节的 `format` MUST 与该 Book 的 `format` 相同；外部程序 MUST 能只凭 Book 的 `format` 判断整本的渲染方式。

#### Scenario: 列表项包含 format

- **WHEN** 外部程序请求 `GET /api/v1/books`
- **THEN** 每个 `items` 元素都带 `format` 字段
- **AND** 取值只会是 `markdown` 或 `html`

#### Scenario: 详情与章节格式一致

- **WHEN** 外部程序请求某个 Book 的详情及其下任意章
- **THEN** Book 的 `format` 与其中每个节的 `format` 相同
- **AND** 同一本书内不会出现两种格式
