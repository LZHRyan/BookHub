# Spec Delta

## ADDED Requirements

### Requirement: Book 表示 MUST 暴露文档类型

`/api/v1` 的 Book 列表项与 Book 详情 MUST 包含 `format` 字段，取值与站点内一致（`markdown` 或 `html`），使外部程序无需逐章探测即可知道整本格式。章节表示中的 `format` MUST 与该 Book 的 `format` 相同。

#### Scenario: 列表项包含 format

- **WHEN** 外部程序请求 `GET /api/v1/books`
- **THEN** 每个 `items` 元素都带 `format` 字段
- **AND** 取值只会是 `markdown` 或 `html`

#### Scenario: 详情与章节格式一致

- **WHEN** 外部程序请求某个 Book 的详情及其下任意章节
- **THEN** Book 的 `format` 与章节的 `format` 相同
- **AND** 整本导出（JSON/ZIP）中不会出现两种不同的扩展名
