## MODIFIED Requirements

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

#### Scenario: 格式不符被拒绝

- **WHEN** 向 `markdown` 类型的 Book 上传 `.html` 文件
- **THEN** 返回 400 与明确错误码
- **AND** 不产生章节目录或版本记录

#### Scenario: 超出文件个数上限被拒绝

- **WHEN** `MAX_UPLOAD_FILES=2` 时一次请求上传 3 个文件
- **THEN** 返回 400 并说明一次最多上传几个文件
- **AND** 不产生章节目录或节

### Requirement: 审计 MUST 支持导出与保留清理端点

管理 API MUST 提供 `GET /api/v1/admin/audit.csv`（与查询接口相同的过滤参数）与 `POST /api/v1/admin/audit/cleanup`（默认预览，`?confirm=true` 执行）。审计覆盖全站所有 Book 的操作记录，因此两者 MUST 要求 `admin` 作用域（只有 `read` 不够），并且带 Book 范围的 Token MUST 一律返回 403。

#### Scenario: 导出需要读权限

- **WHEN** 使用只有 `read` 作用域的 Token 请求 `GET /api/v1/admin/audit.csv`
- **THEN** 返回 403 并说明需要 admin 作用域

#### Scenario: 清理默认预览

- **WHEN** 调用清理端点未带 `confirm=true`
- **THEN** 返回将被删除的条数
- **AND** 审计记录数量不变

## ADDED Requirements

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
