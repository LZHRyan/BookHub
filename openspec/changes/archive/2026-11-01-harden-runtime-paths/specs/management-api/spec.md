## MODIFIED Requirements

### Requirement: 文件上传 MUST 与服务端约束一致

创建或替换章节时 MUST 支持 `multipart/form-data` 上传单个文件。服务器 MUST 按 Book 的文档类型校验扩展名、按大小上限校验体积、自动识别编码（UTF-8/BOM/GB18030），失败时 MUST 返回机器可读错误且 MUST NOT 落库。

一次请求携带的文件个数 MUST 有上限（`MAX_UPLOAD_FILES`，默认 50）；超出时 MUST 返回 400 且 MUST NOT 落库。上限 MUST 在网页端上传与 API multipart 写入处一致生效，并 MUST 通过 `GET /api/v1/admin/meta` 的 `limits` 对外暴露。

体积校验 MUST 采用**边读边计数**：MUST NOT 先把整个文件读进内存再比较大小。超过上限时 MUST 立即以 413 中止，MUST NOT 读完剩余内容。整个请求体 MUST 还有一层总量上限（`MAX_REQUEST_BYTES`，默认「文件个数 × 单文件上限 + 1 MiB」）：声明了 `Content-Length` 且超限的请求 MUST 在读取正文之前直接返回 413，且响应 MUST 仍带统一的错误结构与 request id。

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
