# Spec Delta

## MODIFIED Requirements

### Requirement: Book 创建与必填校验

系统 SHALL 允许管理员创建 Book 并保存标题、所属组、简介、图标与可见性等元数据。系统 MUST 拒绝标题缺失或仅含空白字符的创建请求，MUST 拒绝未指定组的创建请求，且校验失败时 MUST NOT 产生任何 Book 记录，并返回指明缺失字段的可读错误。

#### Scenario: 缺少标题时创建失败

- **WHEN** 管理员提交不含标题、或标题仅含空白字符的 Book 创建请求
- **THEN** 系统拒绝保存并返回 4xx 状态码
- **AND** 错误信息指明「标题」字段必填
- **AND** 访客端列表与管理端列表中都不出现新记录

#### Scenario: 缺少组时创建失败

- **WHEN** 管理员提交了标题但没有指定组
- **THEN** 系统返回 4xx 并提示必须选择组
- **AND** 不产生 Book 记录

#### Scenario: 必填项齐全时创建成功

- **WHEN** 管理员提交标题为「运维手册」并选择了一个组
- **THEN** 系统创建该 Book 并返回其标识与最终 slug
- **AND** 该 Book 出现在所选组的分区里

#### Scenario: 可选元数据可省略

- **WHEN** 管理员只提交标题与组就创建 Book
- **THEN** 创建成功，简介与图标为空值

## ADDED Requirements

### Requirement: Book 表示 MUST 带所属组

Book 的对外表示（只读 API 与详细响应）MUST 包含 `group` 对象，至少含 `id`、`slug`、`title`；MUST NOT 只给一个裸 id。

#### Scenario: API 表示含组

- **WHEN** 请求 Book 列表或详情
- **THEN** 每项都带 `group.slug` 与 `group.title`
- **AND** 用 `?group=<slug>` 可以只列该组的 Book
