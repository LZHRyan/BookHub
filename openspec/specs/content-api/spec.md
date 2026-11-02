# content-api Specification

## Purpose
定义 BookHub 对外只读 HTTP 接口 `/api/v1` 的行为契约：Book 与章节的资源表示、内容双通道、导出与增量同步、缓存协商、鉴权与限流、错误模型，以及只读与兼容性约束，供外部程序稳定取用已发布内容。

## Requirements

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

`GET /api/v1/books/{book}/chapters/{chapter}` MUST 默认返回 JSON：章元信息加 `sections[]` 简要。单节章 MUST 继续在顶层平铺该节的正文、渲染结果、`toc`、格式、版本与字数，以保持 v1 旧契约。`?section=<slug|id>` MUST 返回该节的 JSON。`?format=raw|rendered` 或 `Accept` 头 MUST 只返回该节原文或渲染结果；多节章必须给出 `?section=`，`format` 参数优先于 `Accept`。

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

墓碑条目 MUST 只回标识与 slug：已删除或已撤回的内容 MUST NOT 再对外返回 `title` 或 `chapter_title`，避免增量流成为泄露未发布标题的旁路。

#### Scenario: 删除以墓碑形式返回

- **WHEN** 某节在 `since` 之后被软删除（或它所属的章被删除），外部程序再次请求 `GET /api/v1/changes?since=...`
- **THEN** 结果中出现该节的条目且带 `deleted: true`
- **AND** 客户端据此可删除本地副本

#### Scenario: 墓碑不返回标题

- **WHEN** 增量流中出现 `deleted: true` 的条目
- **THEN** 该条目不包含 `title` 与 `chapter_title` 字段
- **AND** `book_slug`、`chapter_slug`、`slug`、`updated_at` 等定位字段仍然存在

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

### Requirement: 错误响应 MUST 使用统一结构

所有错误响应 MUST 使用统一结构 `{"error": {"code", "message", "request_id"}}`，其中 `request_id` 用于跨日志排查对应请求。状态码 MUST 保持语义一致：参数校验失败 400、鉴权失败 401、权限不足 403、资源不存在或不可见 404、方法不允许 405、超出限流 429、请求体过大 413。`message` MUST NOT 暴露内部实现细节或调用栈。

未预期异常 MUST 由统一的兜底处理器接住：`/api/` 与 JSON 请求返回 `error.code = internal_error` 的统一错误体（带 `request_id`，且 `request_id` 与实际日志条目一致），HTML 页面返回同一份错误说明页；MUST NOT 落到框架默认的裸文本 `Internal Server Error`。堆栈与内部路径 MUST 只进日志、不进响应。

#### Scenario: 参数校验失败返回统一错误体

- **WHEN** 外部程序传入非整数分页值或其他不符合约束的参数
- **THEN** 返回 400，响应体含 `error.code`、`error.message`、`error.request_id`
- **AND** `message` 说明哪个参数不合法而不含内部细节

#### Scenario: 服务端异常也返回统一错误体

- **WHEN** 请求处理过程中发生未预期错误
- **THEN** 返回 5xx，响应体仍为统一错误结构并含可追踪的 `request_id`
- **AND** 响应中不包含调用栈或内部路径信息

#### Scenario: 500 的 code 与日志可对上

- **WHEN** 未预期异常发生在 JSON 接口上
- **THEN** 响应 `error.code` 为 `internal_error`，`error.request_id` 与响应头 `X-Request-ID` 相同
- **AND** 服务端日志里能用同一个 request id 找到异常类型与消息

#### Scenario: 请求体过大是 413 而不是 500

- **WHEN** 请求的 `Content-Length` 超过服务端上限
- **THEN** 返回 413 与 `error.code = payload_too_large`
- **AND** 该响应同样带 `request_id`

### Requirement: 可选 API Key MUST 由配置决定是否强制

`API_KEY` 未配置时 `/api/v1` MUST 完全公开，任何请求都不需要鉴权凭据。配置后所有 `/api/v1` 请求 MUST 携带与之匹配的 `X-API-Key` 请求头；缺失或不匹配 MUST 返回 401 与统一错误体。`/healthz` 与 `GET /api/v1/site` MUST 始终无需该头即可访问。

#### Scenario: 未配置 API_KEY 时接口公开

- **WHEN** 部署未配置 `API_KEY`，外部程序不带任何凭据请求章节
- **THEN** 请求正常返回内容
- **AND** 不返回 401

#### Scenario: 配置后缺少或错误 API Key 返回 401

- **WHEN** 部署配置了 `API_KEY`，外部程序不带 `X-API-Key` 或以错误值请求章节
- **THEN** 返回 401 与统一错误体
- **AND** 同时请求 `/healthz` 或 `GET /api/v1/site` 仍然无需该头即可成功

### Requirement: 站点元信息 MUST 可无凭据获取

`GET /api/v1/site` MUST 返回站点名称、服务版本与能力开关等元信息，用于外部程序探测对方是否支持所需能力；该接口 MUST 无需任何凭据即可访问，即使部署配置了 API Key。

#### Scenario: 无凭据读取站点元信息

- **WHEN** 部署配置了 `API_KEY`，外部程序不带 `X-API-Key` 请求 `GET /api/v1/site`
- **THEN** 返回 200 与站点名称、版本、能力开关
- **AND** 响应中不含任何管理端内部信息

### Requirement: 列表类响应 MUST 遵循统一分页契约

所有返回集合的 `/api/v1` 接口 MUST 接受 `page` 与 `page_size`：`page_size` 默认 20、上限 100，取值超过上限时 MUST 被约束为 100 而不是报错；`page` MUST 为大于等于 1 的整数，非法取值 MUST 返回 400。响应 MUST 含 `items`、`total`、`page`、`page_size`，其中 `total` 为忽略分页后的命中总数。

#### Scenario: page_size 超过上限被裁剪

- **WHEN** 外部程序以 `page_size=500` 请求某集合接口
- **THEN** 响应 `page_size` 为 100
- **AND** `items` 长度不超过 100

#### Scenario: 非法 page 返回 400

- **WHEN** 外部程序以 `page=0` 或 `page=abc` 请求某集合接口
- **THEN** 返回 400 与统一错误体
- **AND** 不返回任何条目

### Requirement: 接口 MUST 按来源 IP 限流并可关闭

`/api/v1` SHALL 按来源 IP 与路径组限制请求频率，超出阈值的请求 MUST 返回 429 且响应 MUST 带 `Retry-After` 头表示建议的重试间隔。`RATE_LIMIT_ENABLED` 关闭限流后 MUST NOT 因请求频率返回 429。

#### Scenario: 超过频率阈值返回 429

- **WHEN** 同一来源 IP 在限流窗口内以远超阈值的频率重复请求同一路径组
- **THEN** 超出阈值的请求返回 429 与统一错误体
- **AND** 响应带 `Retry-After` 头

#### Scenario: 关闭限流后不再返回 429

- **WHEN** 部署关闭了限流并重复上述高频请求
- **THEN** 请求不再返回 429
- **AND** 正常返回内容或参数错误

### Requirement: 跨域行为 MUST 由白名单控制

CORS 行为 MUST 由 `CORS_ORIGINS` 白名单决定：来源命中白名单时响应 MUST 带允许该来源的 CORS 响应头；未命中时 MUST NOT 带允许该来源的 `Access-Control-Allow-Origin`。白名单为通配时 MUST 只允许不带凭证的读请求。

#### Scenario: 白名单来源获得 CORS 头

- **WHEN** 位于 `CORS_ORIGINS` 白名单中的来源发起跨域读请求
- **THEN** 响应带允许该来源的 `Access-Control-Allow-Origin`
- **AND** 预检请求返回成功状态

#### Scenario: 非白名单来源不带允许头

- **WHEN** 不在白名单中的来源发起跨域请求
- **THEN** 响应不包含针对该来源的 `Access-Control-Allow-Origin`
- **AND** 浏览器按同源策略拦截读取结果

### Requirement: 接口 MUST 保持只读

`/api/v1` 是只读接口：对该前缀下任何资源使用 `POST`、`PUT`、`PATCH`、`DELETE` MUST 返回 405 与统一错误体，且 MUST NOT 改变任何已存储的内容或元数据。

#### Scenario: 写方法返回 405

- **WHEN** 外部程序对 `/api/v1/books` 或某章节路径发起 `POST`、`PUT`、`PATCH` 或 `DELETE`
- **THEN** 返回 405
- **AND** 随后读取该资源，内容与状态均未改变

### Requirement: 接口文档 MUST 可访问且可关闭

`/openapi.json` 与 `/docs` MUST 描述 `/api/v1` 的实际契约（路径、参数、状态码与响应结构）。`API_DOCS_ENABLED` 关闭时两者 MUST 返回 404，且 MUST NOT 影响 `/api/v1` 本身的可访问性。

#### Scenario: 默认可访问文档

- **WHEN** 部署保持文档开关开启，外部程序请求 `/openapi.json`
- **THEN** 返回描述 `/api/v1` 全部路径的文档
- **AND** 请求 `/docs` 返回可用的交互式文档页面

#### Scenario: 关闭后文档返回 404

- **WHEN** 部署关闭了文档开关，外部程序请求 `/docs` 或 `/openapi.json`
- **THEN** 两者返回 404
- **AND** `/api/v1/books` 仍然正常返回内容

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

### Requirement: Book 表示 MUST 暴露文档类型

`/api/v1` 的 Book 列表项与 Book 详情 MUST 包含 `format` 字段，取值与站点内一致（`markdown` 或 `html`），表示整本书唯一的文档类型。每个节的 `format` MUST 与该 Book 的 `format` 相同；外部程序 MUST 能只凭 Book 的 `format` 判断整本的渲染方式。

#### Scenario: 列表项包含 format

- **WHEN** 外部程序请求 `GET /api/v1/books`
- **THEN** 每个 `items` 元素都带 `format` 字段
- **AND** 取值只会是 `markdown` 或 `html`

#### Scenario: 详情与章节格式一致

- **WHEN** 外部程序请求某个 Book 的详情及其下任意章
- **THEN** Book 的 `format` 与其中每个节的 `format` 相同
- **AND** 同一本书内不会出现两种格式

### Requirement: 站点 MUST 暴露内置指南的地址与标记

`GET /api/v1/site` MUST 返回 `guide` 字段，指向站点内置的《AI Agent 接入使用指南》：`slug`、`title`、`url`（读者页）与 `api_url`（只读 API）。指南不存在或已被关闭时该字段 MUST 为 `null`，MUST NOT 让端点失败。Book 表示（列表项、详情、管理 API）MUST 带布尔字段 `is_builtin`，使外部工具能一眼识别内置 Book。指南改名 MUST NOT 改变 `slug` 与 `guide` 的结构，外部工具不需要跟着改配置。

#### Scenario: site 给出指南地址

- **WHEN** 外部程序请求 `GET /api/v1/site`
- **THEN** `guide.slug` 为 `ai-agent-guide`，`guide.url` 与 `guide.api_url` 可直接请求
- **AND** 请求 `guide.api_url` 能拿到该书的目录，其 `title` 为「AI Agent 接入使用指南」

#### Scenario: 关闭后 guide 为 null

- **WHEN** 部署关闭了内置指南（或该 slug 被用户的书占用，系统放弃创建）
- **THEN** `GET /api/v1/site` 仍返回 200
- **AND** `guide` 为 `null`

#### Scenario: Book 表示带 is_builtin

- **WHEN** 请求 `GET /api/v1/books` 或 `GET /api/v1/admin/books`
- **THEN** 每个条目都带 `is_builtin` 布尔值
- **AND** 内置指南的条目为 `true`，用户创建的书为 `false`
