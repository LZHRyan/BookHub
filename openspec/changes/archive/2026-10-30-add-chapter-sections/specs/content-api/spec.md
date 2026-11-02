## RENAMED Requirements

- FROM: `### Requirement: 单章节 MUST 支持 JSON 默认表示与原文/渲染单通道`
- TO: `### Requirement: 章与节 MUST 支持 JSON 默认表示与原文/渲染单通道`
- FROM: `### Requirement: Book 表示 MUST 暴露文档类型`
- TO: `### Requirement: Book 表示 MUST 暴露默认文档类型`

## MODIFIED Requirements

### Requirement: Book 资源 MUST 提供列表与详情两种表示

`GET /api/v1/books` SHALL 返回分页的 Book 列表，元素含 `id`、`slug`、`title`、`summary`、`chapter_count`、`updated_at`，并支持 `page`、`page_size` 与 `visibility` 过滤。`GET /api/v1/books/{slug_or_id}` SHALL 返回 Book 元信息与按顺序排列的章节目录：每个章条目含章元信息与它的 `sections` 简要列表（目录与节条目都不含正文）；路径参数 MUST 同时接受 slug 与数值 ID。

#### Scenario: 列表分页与字段完整

- **WHEN** 外部程序请求 `GET /api/v1/books` 且未提供分页参数
- **THEN** 响应含 `items`、`total`、`page`、`page_size`，其中 `page` 为 1
- **AND** `items` 中每一项都包含 `id`、`slug`、`title`、`summary`、`chapter_count`、`updated_at`

#### Scenario: 详情返回有序目录且不含正文

- **WHEN** 外部程序以 slug 请求 `GET /api/v1/books/{slug_or_id}`
- **THEN** 响应包含 Book 元信息与按展示顺序排列的章列表，每章带按顺序排列的 `sections`
- **AND** 目录项只含标识、slug、标题、格式、版本等元信息，不含任何正文

### Requirement: 章与节 MUST 支持 JSON 默认表示与原文/渲染单通道

`GET /api/v1/books/{book}/chapters/{chapter}` MUST 默认返回 JSON：章元信息加 `sections[]`（每节的标识、slug、标题、格式、版本、checksum、访问路径），单节章还会在顶层平铺该节的 `content_raw`、`content_rendered`、`toc`、`format`、`version`、`word_count` 并附带 `section` 结构，以保持 v1 旧契约可用。`?section=<slug|id>` MUST 返回该节的 JSON（含正文）。`?format=raw` 或 `Accept: text/markdown` MUST 只返回节原文（`Content-Type: text/markdown; charset=utf-8`），`?format=rendered` 或 `Accept: text/html` MUST 只返回该节的渲染结果（`Content-Type: text/html; charset=utf-8`）。多节章取正文通道 MUST 用 `?section=` 指明是哪一节，缺省时返回 400。`format` 参数 MUST 优先于 `Accept` 头。

#### Scenario: 默认请求返回 JSON

- **WHEN** 外部程序请求某已发布章且未指定格式
- **THEN** 响应 `Content-Type` 为 `application/json`
- **AND** 响应体包含 `sections` 列表；单节章还同时包含原文与渲染结果以及版本元数据

#### Scenario: 按 Accept 头取回原文

- **WHEN** 外部程序请求同一章的某一节并携带 `Accept: text/markdown`
- **THEN** 响应 `Content-Type` 为 `text/markdown; charset=utf-8`
- **AND** 响应体为该节的原始内容，不包含 JSON 包装

#### Scenario: format 参数优先于 Accept

- **WHEN** 外部程序同时给出 `?format=rendered`、`?section=` 与 `Accept: text/markdown`
- **THEN** 响应按 `format=rendered` 返回该节渲染后的 HTML
- **AND** 响应 `Content-Type` 为 `text/html; charset=utf-8`

#### Scenario: 多节章必须指明节

- **WHEN** 外部程序对一个多节章请求 `?format=raw` 但没有给 `?section=`
- **THEN** 返回 400 与统一错误体，提示需要指定节
- **AND** 不返回任何一节的正文

### Requirement: 接口 MUST 只暴露已发布内容且不泄露存在性

`/api/v1` SHALL 只返回「章已发布、节未软删除」的内容。草稿章下的节、回收站中的节，以及所属 Book 已软删除的资源 MUST 返回 404，错误体 MUST NOT 暗示该资源是否存在。`unlisted` Book MUST 可通过 slug 或 ID 直接定位，但 MUST NOT 出现在 Book 列表结果中。

#### Scenario: 草稿章节返回 404

- **WHEN** 外部程序按 slug 请求某个状态为草稿的章，或请求它下面的节
- **THEN** 返回 404 与统一错误体
- **AND** 响应中不出现该章或该节的标题、正文或草稿状态等信息

#### Scenario: unlisted Book 可直链访问但不在列表中

- **WHEN** 外部程序直接请求某 `unlisted` Book 的详情，并另一次请求 Book 列表
- **THEN** 详情请求成功返回该 Book 及其目录
- **AND** 列表响应的 `items` 中不包含该 Book

### Requirement: 整本导出 MUST 提供 JSON manifest 与 ZIP 两种形态

`GET /api/v1/books/{book}/export` MUST 支持 `format=json` 与 `format=zip`。JSON manifest MUST 含 Book 元信息、章总数、节总数，以及按顺序排列的章条目（每章带顺序排列的节条目：标识、slug、标题、格式、版本、访问路径与相对文件路径）；ZIP MUST 内含一份 `book.json` manifest 与每节一个内容文件，文件路径为 `<章 slug>/<节 slug>.<md|html>`。两种形态都 MUST 只包含已发布章中未删除的节。

#### Scenario: JSON manifest 结构完整

- **WHEN** 外部程序请求 `GET /api/v1/books/{book}/export?format=json`
- **THEN** 响应为 JSON，包含 Book 元信息、章总数、节总数与有序章条目（每章含有序 `sections`）
- **AND** 条目中的顺序与站点目录顺序一致

#### Scenario: ZIP 包含 manifest 与每章一个文件

- **WHEN** 外部程序请求同一 Book 的 `format=zip`
- **THEN** 响应 `Content-Type` 为 ZIP 类型，解包后含 `book.json` 与每节一个 `.md` 或 `.html` 文件；单节章的章目录里只有这一个文件
- **AND** ZIP 内文件数量等于节数加一

#### Scenario: ZIP 按章分目录

- **WHEN** 解包一个含多节章的 Book 的导出 ZIP
- **THEN** 该章的节文件位于以章 slug 命名的目录下
- **AND** 文件名是该节 slug 加对应格式后缀

### Requirement: 增量同步 MUST 通过 since 参数提供变更流

`GET /api/v1/changes?since=<ISO-8601>` MUST 返回该时间点之后发布、更新或删除的节变更摘要（响应键为 `sections`），每条含节标识、所属 Book 与章的标识和 slug、变更类型与时间戳；被删除的节（含因整章删除而下架的节）MUST 以 `deleted: true` 的墓碑条目出现而不是从结果中消失。缺少 `since` MUST 返回参数校验错误，格式非法或无法解析 MUST 返回 400。

#### Scenario: 删除以墓碑形式返回

- **WHEN** 某节在 `since` 之后被软删除（或它所属的章被删除），外部程序再次请求 `GET /api/v1/changes?since=...`
- **THEN** 结果中出现该节的条目且带 `deleted: true`
- **AND** 客户端据此可删除本地副本

#### Scenario: 非法 since 被拒绝

- **WHEN** 外部程序以无法解析的 `since` 值请求变更流
- **THEN** 返回 400 与统一错误体
- **AND** 响应不返回任何变更条目

### Requirement: 响应 MUST 支持 ETag 与条件请求

章与节的 GET 响应 MUST 带 `ETag` 与 `Last-Modified` 响应头，且内容或版本变化后 `ETag` MUST 随之改变（章的 ETag MUST 反映其各节的版本）。请求携带 `If-None-Match` 且与当前 `ETag` 匹配时 MUST 返回 304，且 304 响应 MUST NOT 携带正文。

#### Scenario: ETag 命中返回 304

- **WHEN** 外部程序先取回某节响应并记录其 `ETag`，随后携带 `If-None-Match` 用该值再次请求同一节
- **THEN** 返回 304 状态码
- **AND** 响应体为空，且仍带 `ETag` 头

#### Scenario: 内容更新后 ETag 改变

- **WHEN** 节正文被替换为新版本，外部程序用旧 `ETag` 发起条件请求
- **THEN** 返回 200 与新正文
- **AND** 响应中的 `ETag` 与旧值不同

### Requirement: 兼容性 MUST 通过版本前缀保证

`/api/v1` 内的变更 MUST 保持向后兼容，只允许新增可选参数、新增响应字段与新增路径；任何破坏性变更 MUST 在新前缀 `/api/v2` 下提供，且 `/api/v1` 的既有路径、参数与响应字段 MUST 继续可用。本次引入 `sections` 时，单节章的旧字段（`content_raw`、`content_rendered`、`toc`、`format`、`version`、`checksum`、`word_count`）MUST 继续出现在章详情顶层。

#### Scenario: 新增字段不影响既有客户端

- **WHEN** 某次发布在 `/api/v1` 的响应中新增了字段
- **THEN** 既有客户端仍能按原字段解析响应
- **AND** 原路径与原查询参数的行为不变

#### Scenario: 破坏性变更走新前缀

- **WHEN** 需要改变既有字段语义或移除字段
- **THEN** 该变更只在新的版本前缀下提供
- **AND** `/api/v1` 的对应路径保持原语义可用

### Requirement: Book 表示 MUST 暴露默认文档类型

`/api/v1` 的 Book 列表项与 Book 详情 MUST 包含 `format` 字段，取值与站点内一致（`markdown` 或 `html`），表示「新建节时的默认格式」。每个节的 `format` MUST 以节自己的取值为准，同一 Book 内 MAY 出现两种格式；外部程序 MUST 按节条目上的 `format` 判断该节的类型。

#### Scenario: 列表项包含 format

- **WHEN** 外部程序请求 `GET /api/v1/books`
- **THEN** 每个 `items` 元素都带 `format` 字段
- **AND** 取值只会是 `markdown` 或 `html`

#### Scenario: 详情与章节格式一致

- **WHEN** 外部程序请求某个 Book 的详情及其下任意章
- **THEN** Book 的 `format` 表示该 Book 新建节时的默认值
- **AND** 每个节条目都带自己的 `format`，可以与 Book 的默认值不同
