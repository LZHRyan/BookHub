# Spec Delta

## ADDED Requirements

### Requirement: 章节格式来源 MUST 由 Book 决定

章节的内容格式 MUST 来自所属 Book 的文档类型，而不是章节自身的可选项。渲染路径 MUST 继续按格式分流：`markdown` 走 Markdown 渲染管线，`html` 走白名单净化；但由于整本同格式，同一 Book 内所有章节 MUST 使用同一条渲染路径。

#### Scenario: 同一 Book 内渲染路径唯一

- **WHEN** 阅读一个 `markdown` 类型 Book 下的任意章节
- **THEN** 所有章节都由 Markdown 渲染管线产出
- **AND** 不会出现某个章节被当作 HTML 原文直接展示

#### Scenario: HTML Book 的所有章节都经过净化

- **WHEN** 阅读一个 `html` 类型 Book 下的任意章节
- **THEN** 每个章节都经过白名单净化
- **AND** 章节之间的净化规则完全一致
