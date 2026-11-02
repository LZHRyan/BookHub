# Spec Delta

## ADDED Requirements

### Requirement: Book MUST 声明单一文档类型

每个 Book MUST 声明一个文档类型，取值为 `markdown` 或 `html`，且 MUST NOT 存在"混合"取值。创建 Book 时未指定类型或取值非法 MUST 被拒绝，且 MUST NOT 产生 Book 记录。Book 的列表、详情与管理端展示 MUST 呈现该类型。

#### Scenario: 创建时必须选择类型

- **WHEN** 管理员提交创建 Book 的请求但没有指定文档类型
- **THEN** 系统拒绝创建并返回 4xx，错误信息指明「文档类型」必填
- **AND** 不产生任何 Book 记录

#### Scenario: 非法类型被拒绝

- **WHEN** 创建请求的文档类型取值为 `mixed` 或空字符串
- **THEN** 系统拒绝创建并明确指出取值只能是 `markdown` 或 `html`

#### Scenario: 类型在列表与详情中可见

- **WHEN** 创建了一个类型为 `html` 的 Book
- **THEN** 管理端列表与该 Book 的详情都显示 `html`
- **AND** 同一 Book 不会同时显示两种类型

### Requirement: Book 的文档类型在有章节后 MUST 不可变更

当 Book 下存在任何未删除的章节时，修改其文档类型 MUST 被拒绝，且 MUST NOT 影响任何字段。当 Book 下没有任何未删除章节时，允许修改类型。

#### Scenario: 有章节时修改被拒绝

- **WHEN** 管理员对已有 3 个章节的 Book 提交把 `markdown` 改成 `html` 的更新
- **THEN** 系统返回 4xx 并说明「已有章节，不能修改文档类型」
- **AND** 该 Book 的类型、标题、简介等字段全部保持原值

#### Scenario: 空 Book 可以切换类型

- **WHEN** 管理员对一个没有任何章节的 Book 把类型改为 `html`
- **THEN** 更新成功，随后可以在其中创建 HTML 章节
