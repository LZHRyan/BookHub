## MODIFIED Requirements

### Requirement: Book 元数据更新

Book 的标题、简介、图标、分组、可见性、置顶与封面 MUST 可随时更新，且更新 MUST 立即反映到列表、详情与只读 API。文档类型（`format`）在该 Book 已有章之后 MUST NOT 被修改。访问标识（`slug`）MUST 可改并 MUST 保持全站唯一。任一字段非法时整次更新 MUST NOT 生效。

内置指南 Book（`is_builtin=true`）的 `slug` 与 `format` MUST NOT 被修改：前者是外部集成（链接、MCP 配置、脚本）的锚点，后者决定其 Markdown 正文的渲染方式。其余字段（标题、简介、图标、可见性、置顶、封面）MUST 仍可更新。

#### Scenario: 更新成功后立即生效

- **WHEN** 修改某 Book 的标题或可见性并保存
- **THEN** 列表中立即显示新值
- **AND** `GET /api/v1/books` 的对应条目也带新值

#### Scenario: 部分字段非法时整体不生效

- **WHEN** 同时提交合法标题与非法的可见性取值
- **THEN** 返回 400
- **AND** 标题也没有被改动

#### Scenario: 内置指南只锁定身份字段

- **WHEN** 对 `ai-agent-guide` 提交新的标题与简介
- **THEN** 更新成功并立即生效
- **AND** 同时提交新 slug 或 `format=html` 时返回 400，其余字段不落库

## ADDED Requirements

### Requirement: 内置 Book MUST 不可删除

标记为 `is_builtin=true` 的 Book MUST NOT 被软删除：删除入口 MUST 返回 400 并说明它随系统生命周期存在。不需要读者看到时，MUST 通过改可见性（`unlisted`）或撤回章的发布状态来隐藏，而不是删除。该约束 MUST 在服务层强制，使网页端与 API 的行为一致。

#### Scenario: API 删除被拒绝

- **WHEN** 调用 `POST /api/v1/admin/books/{内置书}/delete?confirm=true`
- **THEN** 返回 400 且 `error.message` 指出内置指南不能删除
- **AND** 回收站中不出现这本书

#### Scenario: 网页端不给按钮

- **WHEN** 管理员查看内容管理列表
- **THEN** 内置 Book 的卡片显示「内置 · 不可删除」而不是删除按钮
- **AND** 直接构造表单 POST 同样返回 400
