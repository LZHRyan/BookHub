# Spec Delta

## ADDED Requirements

### Requirement: 章节格式 MUST 与所属 Book 类型一致

章节的内容格式 MUST 继承所属 Book 的文档类型，MUST NOT 由章节自行选择成另一种格式。通过表单录入、文件上传或整体替换写入的格式与 Book 类型不一致时，系统 MUST 拒绝该操作并给出可读错误，且 MUST NOT 写入章节内容、MUST NOT 产生新的历史版本。

#### Scenario: 向 Markdown Book 上传 HTML 文件被拒绝

- **WHEN** 管理员在一个 `markdown` 类型的 Book 下上传 `guide.html`
- **THEN** 系统拒绝创建章节并提示该 Book 只接受 Markdown
- **AND** 不产生章节记录，也不产生历史版本

#### Scenario: 向 HTML Book 上传 Markdown 文件被拒绝

- **WHEN** 管理员在一个 `html` 类型的 Book 下上传 `guide.md`
- **THEN** 系统拒绝创建章节并提示该 Book 只接受 HTML
- **AND** 不产生章节记录

#### Scenario: 替换时提交另一种格式被拒绝

- **WHEN** 管理员对一个 Markdown 章节提交 `format=html` 的整体替换
- **THEN** 系统拒绝该替换并说明格式由 Book 类型决定
- **AND** 章节正文与当前版本号保持不变，历史版本列表不新增记录

#### Scenario: 正确格式正常写入

- **WHEN** 管理员向 `html` 类型的 Book 上传 `release-notes.html`
- **THEN** 章节创建成功，其格式为 `html`
- **AND** 阅读端按 HTML 白名单净化后展示
