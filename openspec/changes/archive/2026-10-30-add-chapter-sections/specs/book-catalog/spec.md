## MODIFIED Requirements

### Requirement: Book MUST 声明单一文档类型

每个 Book MUST 声明一个默认文档类型，取值为 `markdown` 或 `html`，且 MUST NOT 存在"混合"取值。创建 Book 时未指定类型或取值非法 MUST 被拒绝，且 MUST NOT 产生 Book 记录。该类型表示「新建节时的默认格式」，不限制已有或新节各自的格式；Book 的列表、详情与管理端展示 MUST 呈现该默认类型。

#### Scenario: 创建时必须选择类型

- **WHEN** 管理员提交创建 Book 的请求但没有指定文档类型
- **THEN** 系统拒绝创建并返回 4xx，错误信息指明「文档类型」必填
- **AND** 不产生任何 Book 记录

#### Scenario: 非法类型被拒绝

- **WHEN** 创建请求的文档类型取值为 `mixed` 或空字符串
- **THEN** 系统拒绝创建并明确指出取值只能是 `markdown` 或 `html`

#### Scenario: 类型在列表与详情中可见

- **WHEN** 创建了一个默认类型为 `html` 的 Book
- **THEN** 管理端列表与该 Book 的详情都显示 `html`（标注为默认格式）
- **AND** 该 Book 的字段只保存一个默认类型值

### Requirement: Book 详情返回有序章节目录

Book 详情 SHALL 返回该 Book 的目录而不含任何正文，目录项 MUST 至少包含章的 id、标题、slug、状态、排序信息，以及它下面按顺序排列的节简要（节 id、slug、标题、格式、版本、访问路径）。目录 MUST 按章的展示顺序返回。访客视角的目录 MUST 只包含已发布且未删除的章与节；管理员视角的目录 MAY 包含草稿并须标明其状态。

#### Scenario: 访客目录只含已发布章节

- **WHEN** 访客请求某 Book 的详情
- **THEN** 返回的目录只包含已发布且未删除的章与节
- **AND** 草稿章、已删除章及其下节都不出现在目录中

#### Scenario: 目录顺序与排序一致

- **WHEN** 某 Book 依次有「章 A（2 节）」与「章 B（1 节）」
- **THEN** 详情返回的目录顺序为章 A、章 B，章 A 的两节按自身顺序排列
- **AND** 每一项都带标识与 slug，节条目还带 `format` 与 `version`

#### Scenario: 目录不携带正文

- **WHEN** 程序调用方请求 Book 详情
- **THEN** 目录项中不包含任何节的正文
- **AND** 响应体大小与节正文长度无关

#### Scenario: 管理员目录标注草稿

- **WHEN** 管理员查看含一个草稿章的 Book 详情
- **THEN** 目录中包含该草稿章及其节，并标明草稿状态

## REMOVED Requirements

### Requirement: Book 的文档类型在有章节后 MUST 不可变更

**Reason**: 文档类型降级为「新建节时的默认格式」，每节自带 `format`，因此有章之后修改 Book 的默认类型不再影响已有内容，也不再有拒绝修改的理由。

**Migration**: 管理员随时可在 Book 编辑页改默认类型；已存在的节保持原有格式。API 侧 `PATCH /api/v1/admin/books/{ref}` 的 `format` 字段语义同步变化（见 `content-api` 的「Book 表示 MUST 暴露默认文档类型」）。
