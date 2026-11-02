# management-api Specification

## Purpose
定义面向程序与 AI 工具的管理写接口 `/api/v1/admin/*`：覆盖哪些管理能力、如何鉴权与限权、请求与响应的形状、批量与破坏性操作的行为、并发与幂等语义、审计归属，以及可被模型直接消费的文档形态。

## Requirements

### Requirement: 管理端能力 MUST 通过 API 完整可得

`/api/v1/admin` MUST 提供与网页管理端等价的操作集合：Book 的创建、修改、软删除、恢复；章节的创建（含文件上传）、整体替换、发布/撤回、排序、软删除、恢复；版本列表、单版本读取、版本对比、回滚；回收站列表；账号创建、启用/停用、重置密码；站点设置读取与保存；审计日志查询。任何一条网页管理端能完成的写操作，MUST 都能通过 API 完成。

#### Scenario: 章节全生命周期可由 API 完成

- **WHEN** 客户端用有效凭据依次调用创建 Book、上传章节文件、替换内容、发布、回滚、删除、恢复
- **THEN** 每一步都返回成功且资源状态与网页端操作一致
- **AND** 网页端随后读取到的内容与 API 写入一致

#### Scenario: 设置与账号也可通过 API 维护

- **WHEN** 客户端读取站点设置并修改站点名，再创建一个 `editor` 账号
- **THEN** 设置与账号变更生效
- **AND** 首页标题与登录能力随之变化

### Requirement: 程序化调用 MUST 使用具备作用域的 Token 鉴权

管理写接口 MUST 要求 `Authorization: Bearer <token>`。Token MUST 具备作用域：`read` 只能查询、`write` 可读写内容（Book/章节/版本/回收站）、`admin` 额外可管理账号与站点设置。缺失或无效 Token MUST 返回 401；作用域不足 MUST 返回 403 且 MUST NOT 产生任何数据变更。Token MUST NOT 以明文形式存储。

#### Scenario: 无 Token 被拒绝

- **WHEN** 未携带 Authorization 头调用创建 Book 接口
- **THEN** 返回 401 与机器可读错误码
- **AND** 不产生 Book 记录

#### Scenario: 作用域不足被拒绝

- **WHEN** 使用仅含 `write` 作用域的 Token 调用创建账号接口
- **THEN** 返回 403 并说明需要 `admin` 作用域
- **AND** 不创建账号

### Requirement: 写操作 MUST 记录审计并归属到 Token

每一条成功的管理写操作 MUST 追加审计记录，包含 Token 名称（作为操作者）、动作、目标类型与标识、变更前后版本号、来源 IP 与时间。通过 API 产生的记录 MUST 可与其他来源区分。

#### Scenario: API 建章可追溯

- **WHEN** 使用名为 `docs-bot` 的 Token 创建章节
- **THEN** 审计日志中出现一条以 `docs-bot` 为操作者的 `chapter.create`
- **AND** 该记录标明来自 API 渠道

### Requirement: 破坏性操作 MUST 提供预览与显式确认

删除类操作 MUST 支持 `dry_run=true`：只返回将被影响的对象清单与数量，MUST NOT 改动数据。不带 `dry_run` 的真实删除 MUST 要求 `confirm=true`，否则 MUST 返回 400 并提示需要确认。删除 MUST 为软删除并可恢复。

#### Scenario: 预览不产生变更

- **WHEN** 以 `dry_run=true` 请求删除某章节
- **THEN** 返回该章节的标识与标题，且不改变其状态
- **AND** 随后读取该章节仍然成功

#### Scenario: 缺少确认被拒绝

- **WHEN** 请求删除章节但未提供 `confirm=true`
- **THEN** 返回 400 并说明需要显式确认
- **AND** 章节仍在原状态

### Requirement: 写接口 MUST 支持并发冲突检测

替换章节内容与修改 Book 时 MUST 接受基准版本（`base_version` 或 `If-Match`）。基准与当前版本不一致时 MUST 返回 409，MUST NOT 覆盖他人改动，MUST NOT 产生新版本。

#### Scenario: 过期基准被拒绝

- **WHEN** 客户端以 `base_version=3` 提交替换，而章节已是第 5 版
- **THEN** 返回 409 与冲突说明
- **AND** 章节仍是第 5 版的内容

### Requirement: 写接口 MUST 支持幂等重放

客户端可携带 `Idempotency-Key`。相同键与相同请求体在有效期内重复提交 MUST 返回首次结果且 MUST NOT 产生第二次副作用；相同键不同请求体 MUST 返回 409。未携带该头时按普通请求处理。

幂等键 MUST 按签发 Token 分命名空间：两个不同 Token 使用同一个 `Idempotency-Key` 时 MUST 各自独立执行，MUST NOT 回放对方的响应，也 MUST NOT 因对方占用而返回 409。

#### Scenario: 重试不产生重复章节

- **WHEN** 创建章节的请求因网络超时被原样重发，两次携带同一 `Idempotency-Key`
- **THEN** 第二次返回与第一次相同的章节标识与状态码
- **AND** 该 Book 下只新增一个章节

#### Scenario: 不同 Token 的同名键互不影响

- **WHEN** Token A 与 Token B 各自用同一个 `Idempotency-Key` 创建内容相同的资源
- **THEN** 两次请求都各创建一个资源，返回两个不同的标识
- **AND** Token A 再次用该键重发时仍只回放自己的首次结果

### Requirement: 文件上传 MUST 与服务端约束一致

创建或替换章节时 MUST 支持 `multipart/form-data` 上传单个文件。服务器 MUST 按 Book 的文档类型校验扩展名、按大小上限校验体积、自动识别编码（UTF-8/BOM/GB18030），失败时 MUST 返回机器可读错误且 MUST NOT 落库。

一次请求携带的文件个数 MUST 有上限（`MAX_UPLOAD_FILES`，默认 50）；超出时 MUST 返回 400 且 MUST NOT 落库。上限 MUST 在网页端上传与 API multipart 写入处一致生效，并 MUST 通过 `GET /api/v1/admin/meta` 的 `limits` 对外暴露。

体积校验 MUST 采用**边读边计数**，MUST NOT 先把整个文件读进内存再比较。整个请求体 MUST 另有一层总量上限（`MAX_REQUEST_BYTES`），超限 MUST 在读取正文前返回 413。

#### Scenario: 格式不符被拒绝

- **WHEN** 向 `markdown` 类型的 Book 上传 `.html` 文件
- **THEN** 返回 400 与明确错误码
- **AND** 不产生章节目录或版本记录

#### Scenario: 超出文件个数上限被拒绝

- **WHEN** `MAX_UPLOAD_FILES=2` 时一次请求上传 3 个文件
- **THEN** 返回 400 并说明一次最多上传几个文件
- **AND** 不产生章节目录或节

#### Scenario: 超大文件在读的过程中就被拒绝

- **WHEN** 上传的文件超过 `MAX_UPLOAD_BYTES`
- **THEN** 服务端在累计读取超过上限时立即返回 413
- **AND** 不会把整个文件读入内存，也不会因此占用与文件等量的内存

#### Scenario: 请求体超过总量上限直接 413

- **WHEN** 请求的 `Content-Length` 超过 `MAX_REQUEST_BYTES`
- **THEN** 服务端在读取正文前返回 413，`error.code` 为 `payload_too_large`
- **AND** 响应带 `request_id`，便于排查

### Requirement: 响应 MUST 返回资源表示且错误 MUST 机器可读

成功响应 MUST 返回创建/更新后的资源表示（字段与只读 API 的表示一致，至少包含 id、slug、版本号与时间戳；章没有正文与版本，正文与版本在节上）。错误响应 MUST 使用统一结构 `{"error": {"code", "message", "request_id"}}`，并 MUST 区分参数错误、未认证、无权限、不存在、冲突与限流。

#### Scenario: 创建成功返回资源

- **WHEN** 创建章成功
- **THEN** 响应包含该章的 id、slug、published 状态与它下面的 `sections`（每节带 format、version）
- **AND** 单节章还会在顶层带该节的正文与版本字段

#### Scenario: 错误码可编程判断

- **WHEN** 请求一个不存在的 Book
- **THEN** 返回 404 且 `error.code` 为稳定的机器可读值

### Requirement: 接口 MUST 可被 AI 工具直接消费

OpenAPI 文档 MUST 覆盖全部管理写接口，每个操作 MUST 具备稳定的 `operationId`、中文 summary 与 description、显式的请求体与响应 Schema，并 MUST 标注所需作用域。文档 MUST NOT 依赖 HTML 表单或 CSRF 令牌等浏览器专有机制。

#### Scenario: 从 OpenAPI 生成工具定义

- **WHEN** 把 `/openapi.json` 交给支持 function calling 的模型
- **THEN** 每个管理操作都能生成一个参数完整、描述可理解的工具定义
- **AND** 调用该工具不会因为缺少浏览器凭据而失败

### Requirement: 管理写接口 MUST 独立限流

管理写接口 MUST 按 Token 限流，阈值独立于公共读接口；超限 MUST 返回 429 并带 `Retry-After`。限流 MUST NOT 因公共读流量增大而误伤。

#### Scenario: 按 Token 计数

- **WHEN** 同一 Token 在窗口内高频调用写接口超过阈值
- **THEN** 返回 429 与 `Retry-After`
- **AND** 换一个 Token 的请求不受影响

### Requirement: 批量操作 MUST 逐条返回结果

接受批量请求的接口 MUST 返回每条操作的结果与错误，MUST NOT 因单条失败而整体回滚或整体 500。部分失败时 MUST 返回可汇总的状态与逐条明细。

#### Scenario: 部分失败不影响其余

- **WHEN** 一次批量发布请求中包含一个不存在的章节
- **THEN** 其余章节发布成功
- **AND** 响应中该条目标记为失败并给出原因

### Requirement: 媒体资源管理 MUST 通过管理 API 完整可得

管理 API MUST 提供媒体资源的列表、multipart 上传、删除与未引用清理四类操作。它们 MUST 沿用既有的 `read`/`write` 作用域、幂等重放、`dry_run` 预览、`confirm` 显式确认与 Token 审计归属约定，MUST 返回与网页端一致的资源表示。

#### Scenario: 上传返回可直接引用的地址

- **WHEN** 使用具备 `write` 作用域的 Token 向某 Book 上传一张图片（`multipart/form-data`）
- **THEN** 响应 201，包含资源 id、原始文件名、字节数、类型与站内访问地址
- **AND** 正文里可直接使用该地址引用

#### Scenario: 列表包含引用状态与配额用量

- **WHEN** 请求某 Book 的媒体列表
- **THEN** 每项包含是否被正文引用的标记
- **AND** 响应包含该 Book 的配额上限与当前占用

#### Scenario: 删除需要显式确认并支持预览

- **WHEN** 调用删除媒体接口但未带 `confirm=true`
- **THEN** 返回 4xx 并说明需要确认
- **AND** 带 `dry_run=true` 时只返回该操作的影响面而不改动数据

#### Scenario: 清理默认只预览

- **WHEN** 调用未引用清理接口且未带 `confirm=true`
- **THEN** 返回将被删除的资源清单与字节数合计
- **AND** 没有任何资源被删除

#### Scenario: 只读 Token 被拒绝

- **WHEN** 使用只具备 `read` 作用域的 Token 上传媒体
- **THEN** 返回 403 且错误码指出缺少 `write` 作用域
- **AND** 不产生文件与记录

### Requirement: 排序与置顶 MUST 通过管理 API 可得

管理 API MUST 提供「按有序 id 整体重排整本 Book 的章」与「Book 置顶开关」两个写操作，MUST 沿用既有的 Token 作用域、幂等重放、`dry_run` 预览与审计归属约定；重排 MUST 校验 id 集合与该 Book 的章一致。

#### Scenario: 重排成功返回新顺序

- **WHEN** 使用具备 `write` 作用域的 Token 提交某 Book 的有序章 id 列表
- **THEN** 响应中返回该 Book 的新顺序
- **AND** 只读 API 的 Book 目录随之变化

#### Scenario: 置顶通过 PATCH 设置

- **WHEN** 调用 `PATCH /api/v1/admin/books/{ref}` 传 `{"pinned": true}`
- **THEN** 该 Book 的 `pinned` 变为真
- **AND** 列表顺序与审计同步变化

#### Scenario: 缺权限被拒绝

- **WHEN** 使用只具备 `read` 作用域的 Token 调用重排
- **THEN** 返回 403 且错误码指出缺少 `write` 作用域

### Requirement: Book 更新 MUST 支持设置与清除封面

Book 的更新接口 MUST 接受 `cover_media_id`：传媒体资源 id 设为封面，传 `null` 清除封面。设置时必须复用与网页端相同的校验（本 Book、图片、未删除），失败 MUST 返回可辨识错误且不改动原封面。Book 表示 MUST 暴露 `cover` 字段（含 `id` 与可访问 `url`，无封面为 `null`）。

#### Scenario: 通过 API 设置封面

- **WHEN** 用 `PATCH /api/v1/admin/books/{ref}` 传 `{"cover_media_id": 12}`
- **THEN** 响应中的 `cover` 含该资源 id 与站内地址
- **AND** 只读 API 的 Book 表示同步带上 `cover`

#### Scenario: 清除封面

- **WHEN** 传 `{"cover_media_id": null}`
- **THEN** 响应中的 `cover` 为 `null`
- **AND** 首页与详情页回退到图标

#### Scenario: 非法封面被拒绝

- **WHEN** `cover_media_id` 指向其他 Book 的资源或一个附件
- **THEN** 返回 4xx 且错误信息说明原因
- **AND** 原封面保持不变

### Requirement: Token 创建 MUST 接受 Book 范围

Token 创建接口 MUST 接受可选的 Book 列表（slug 或 id）；未提供表示全部 Book。Token 表示 MUST 带 `books`（每项含 id 与 slug）与 `scopes`。非法的 Book 引用 MUST 被拒绝并返回可辨识错误。

#### Scenario: 创建带范围的 Token

- **WHEN** 调用 `POST /api/v1/admin/tokens` 并传 `{"name": "team-a", "scopes": ["write"], "books": ["ops-handbook"]}`
- **THEN** 返回 201，`books` 中只有该 Book
- **AND** 用该 Token 访问其它 Book 的端点返回 403

#### Scenario: 非法 Book 被拒绝

- **WHEN** `books` 中包含不存在的 slug
- **THEN** 返回 4xx 并说明哪个引用无效
- **AND** 不产生 Token

### Requirement: 审计 MUST 支持导出与保留清理端点

管理 API MUST 提供 `GET /api/v1/admin/audit.csv`（与查询接口相同的过滤参数）与 `POST /api/v1/admin/audit/cleanup`（默认预览，`?confirm=true` 执行）。审计覆盖全站所有 Book 的操作记录，因此两者 MUST 要求 `admin` 作用域（只有 `read` 不够），并且带 Book 范围的 Token MUST 一律返回 403。

#### Scenario: 导出需要读权限

- **WHEN** 使用只有 `read` 作用域的 Token 请求 `GET /api/v1/admin/audit.csv`
- **THEN** 返回 403 并说明需要 admin 作用域

#### Scenario: 清理默认预览

- **WHEN** 调用清理端点未带 `confirm=true`
- **THEN** 返回将被删除的条数
- **AND** 审计记录数量不变

### Requirement: 组 MUST 通过管理 API 完整可得

管理 API MUST 提供组的列表（含 Book 数量）、创建、修改（标题/slug/简介/图标）、删除与上下移。Book 的创建 MUST 接受 `group`（slug 或 id），更新 MUST 支持改归属。全部操作 MUST 复用 `admin` 作用域的 Token 与审计约定。

#### Scenario: 创建组并建 Book

- **WHEN** 使用 `admin` Token 创建组「基础设施」，再创建 Book 并传 `{"group": "infra"}`
- **THEN** 组列表里该书数量为 1
- **AND** Book 表示里的 `group.slug` 为 `infra`

#### Scenario: 删除非空组被拒绝

- **WHEN** 删除仍有 Book 的组
- **THEN** 返回 4xx 并说明剩余数量
- **AND** 组与 Book 都不变

#### Scenario: 缺少组创建 Book 被拒绝

- **WHEN** 创建 Book 时没有 `group` 字段
- **THEN** 返回 4xx 并提示必须指定组

### Requirement: 节管理 MUST 通过管理 API 可得

管理 API MUST 提供节的完整写能力：按章列出节、创建节（可同时上传文件）、修改节（标题/slug/格式/正文）、调整节顺序、软删除与恢复节，以及查看版本、对比版本与回滚。它们 MUST 沿用既有的 Token 作用域、幂等重放、`dry_run` 预览、`confirm` 显式确认与审计归属约定，MUST 返回与网页端一致的节表示（含 `id`、`slug`、`title`、`format`、`version`、`word_count`、`url`）。

#### Scenario: 创建节返回表示

- **WHEN** 使用具备 `write` 作用域的 Token 在某个章下创建节
- **THEN** 响应 201，包含该节的 id、slug、title、format 与 `version = 1`
- **AND** 之后可以在同一章下继续创建更多节

#### Scenario: 修改节内容生成新版本

- **WHEN** 对某节 `PATCH` 新正文并带 `base_version`
- **THEN** 响应中的 `version` 递增 1
- **AND** 用旧 `base_version` 再次提交返回 409 冲突

#### Scenario: 回滚节只影响该节

- **WHEN** 对某章的第二节点调用回滚到 `version = 1`
- **THEN** 该节内容变为 v1 的内容并生成更大的版本号
- **AND** 同章其它节与章状态保持不变

#### Scenario: 删除节可预览影响面

- **WHEN** 对某节调用删除接口并带 `dry_run=true`
- **THEN** 返回该节当前版本与访问路径等影响面信息
- **AND** 不带 `confirm=true` 的实际删除被拒绝

### Requirement: 单资源读取 MUST 通过管理 API 可得

管理 API MUST 提供按引用读取单个资源的端点，使 AI 工具写完正文后能读回自己刚写的内容，而不必翻列表：

- `GET /api/v1/admin/books/{book_ref}`：单本 Book 详情，包含未列出与已删除的 Book，表示与 Book 列表项一致；
- `GET /api/v1/admin/books/{book_ref}/chapters/{chapter_ref}/sections/{section_ref}`：单节详情，默认返回正文（`content_raw`、`content_rendered`）与 `toc`，`with_content=0` 时只返回元信息。

两者 MUST 沿用 `read` 作用域与 Book 范围校验；引用 MUST 同时接受 slug 与数值 id；不存在或不在范围内时 MUST 分别返回 404 与 403。

#### Scenario: 写后立刻读回正文

- **WHEN** 用 `write` 作用域的 Token 创建章节并写入正文，随后按章与节的 slug 请求单节详情
- **THEN** 返回 200，`content_raw` 与刚写入的正文一致
- **AND** 响应中包含 `toc`，可用于定位小节

#### Scenario: 只取元信息

- **WHEN** 对同一节请求 `?with_content=0`
- **THEN** 响应中不含 `content_raw` / `content_rendered`
- **AND** `version`、`word_count`、`url` 等元信息仍然完整

#### Scenario: 单本详情也能读到已删除的书

- **WHEN** 用具备范围内权限的 Token 请求一本已软删除 Book 的详情
- **THEN** 返回 200 且 `deleted` 为真
- **AND** 不会退化为列表过滤后的 404

### Requirement: 建章 MUST 明确标题来源

通过管理 API 建章时，标题 MUST 有确定来源，不容忍"悄悄回落"：

- `application/json` 请求 MUST 提供非空 `title`；只给空白标题时 MUST 返回 400（理由：JSON 请求没有文件名可回落，空标题会让章变成「正文」并生成 `chapter-xxxxxx` 这类随机 slug）；
- `multipart/form-data` 请求 MAY 省略 `title`，此时 MUST 用第一个上传文件的文件名（去扩展名）作为章标题——这是既有契约；
- 两种情况下失败 MUST NOT 落库（MUST NOT 留下空标题或随机 slug 的章）。

#### Scenario: JSON 建章缺标题被拒绝

- **WHEN** 用 `POST /api/v1/admin/books/{book}/chapters` 发 JSON，`title` 为空串或纯空白
- **THEN** 返回 400，`error.message` 说明章标题必填
- **AND** 该 Book 下没有新增章

#### Scenario: 上传文件时仍可省略标题

- **WHEN** 用 multipart 上传 `01-intro.md` 且不传 `title`
- **THEN** 返回 201，章标题为 `01-intro`
- **AND** 该章下恰好有一个节
