## MODIFIED Requirements

### Requirement: 通过表单新增章节

系统 SHALL 允许管理员在指定 Book 下通过表单直接录入正文来新增一章，可同时指定章标题、章 slug、发布状态与首批正文。录入的正文 MUST 作为该章的第一节保存，其格式 MUST 等于所属 Book 的文档类型（显式声明了不同格式时 MUST 拒绝）。节标题默认取章标题。新增成功后 MUST 产生该节第 1 个历史版本；新章 MUST 排在该 Book 目录末尾。

#### Scenario: 表单新增成功

- **WHEN** 管理员在某 Markdown 的 Book 下提交章标题、正文与格式为 `markdown` 的新增请求
- **THEN** 章创建成功并出现在该 Book 的目录末尾
- **AND** 该章下有 1 节，节版本号为 1，内容与提交内容一致

#### Scenario: 未选择状态时默认为草稿

- **WHEN** 管理员新增章时未指定发布状态
- **THEN** 该章以草稿状态保存
- **AND** 访客端目录与章页都看不到它

#### Scenario: 所属 Book 不存在时拒绝新增

- **WHEN** 管理员向一个不存在或已软删除的 Book 新增章
- **THEN** 系统返回 404
- **AND** 不创建章，也不产生版本记录

### Requirement: 通过上传文件新增章节

系统 SHALL 允许管理员上传一个或多个文件来新增一章：每个文件 MUST 生成该章下的一个节。节标题 MUST 由文件名去掉扩展名后推导（第一章的节标题可被显式填写的章标题覆盖），文件扩展名 MUST 与 Book 的文档类型一致（Markdown 书只收 `.md/.markdown/.txt`，HTML 书只收 `.html/.htm`），无法判定或不匹配的扩展名 MUST 被拒绝并返回可读错误，且整次请求 MUST NOT 落库。

#### Scenario: 文件名推导标题

- **WHEN** 管理员在某 Markdown 的 Book 下上传文件 `部署指南.md` 且未填写标题
- **THEN** 新章标题为「部署指南」
- **AND** 该节的内容格式标注为 `markdown`

#### Scenario: 显式标题覆盖推导结果

- **WHEN** 管理员在某 HTML 的 Book 下上传文件 `draft-v3.html` 并显式填写标题「发布流程」
- **THEN** 新章标题为「发布流程」
- **AND** 该节的内容格式标注为 `html`

#### Scenario: 扩展名无法识别时拒绝

- **WHEN** 管理员上传扩展名不属于 Markdown 或 HTML 的文件
- **THEN** 系统返回 4xx 状态码并提示格式不受支持
- **AND** 不创建章，也不创建任何节

#### Scenario: 扩展名与 Book 类型不一致时拒绝

- **WHEN** 管理员向一本 Markdown 的 Book 上传 `guide.html`
- **THEN** 系统返回 4xx 并说明这本书是 Markdown、只接受 `.md/.markdown/.txt`
- **AND** 不创建章，也不创建任何节
