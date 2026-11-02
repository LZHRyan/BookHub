# Spec Delta

## ADDED Requirements

### Requirement: Book 表示 MUST 暴露 HTML 阅读方式

`/api/v1` 的 Book 表示 MUST 包含 `html_view` 字段，取值为 `inline` 或 `document`，供调用方判断该书的章节在站点上是站内渲染还是原始文档。Markdown Book 的该字段 MUST 恒为 `inline`。新增字段 MUST NOT 改变既有字段的语义或分页契约。

#### Scenario: 列表与详情都带阅读方式

- **WHEN** 调用方请求 Book 列表或 Book 详情
- **THEN** 每个 Book 元素包含 `html_view`
- **AND** 取值与该 Book 在管理端的设置一致

#### Scenario: Markdown Book 恒为站内渲染

- **WHEN** 调用方请求一个 Markdown 类型 Book 的表示
- **THEN** `html_view` 为 `inline`
