## MODIFIED Requirements

### Requirement: 读取 MUST 遵守 Book 可见性与登录态

公开读取 MUST 校验 Book 存在且未删除；`unlisted` Book 的资源 MUST 仅在带有效会话或有效 Token 时返回；被删除资源的公开地址 MUST 返回 404。读取路径 MUST NOT 暴露目录列表。

Token 凭据 MUST 自身 Book 范围覆盖该媒体所属 Book：带 Book 范围的 Token MUST NOT 用它解开范围外 `unlisted` Book 的资源（仍按 401 处理），未限定范围的 Token 与登录会话等价。

#### Scenario: 未列出 Book 的资源需要身份

- **WHEN** 匿名访客请求 `unlisted` Book 的媒体地址
- **THEN** 系统返回 404 或 401 且不返回文件内容
- **AND** 携带有效管理会话或 Token 的同一请求返回文件

#### Scenario: 范围外的 Token 解不开未列出资源

- **WHEN** 用一个 Book 范围不含该 Book 的 Token 请求 `unlisted` Book 的媒体地址
- **THEN** 返回 401
- **AND** 换成范围包含该 Book 的 Token 后同一地址返回文件

#### Scenario: 不存在的资源返回 404

- **WHEN** 请求的存储文件名不存在或属于其他 Book
- **THEN** 系统返回 404，且响应体不泄露其他 Book 的信息

### Requirement: 读取响应 MUST 可长期缓存且带安全头

命中资源的响应 MUST 携带 `Cache-Control` 长缓存与不可变语义、准确的 `Content-Type`、`X-Content-Type-Options: nosniff`，并对非图片资源给出下载文件名。HTML 原始文档模式的资源策略 MUST 允许加载同源媒体。

SVG 是可以内嵌脚本的“图片”，以 `image/svg+xml` 内联返回时 MUST 附带 `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; sandbox`，使同源直接打开该地址也无法执行脚本。

#### Scenario: 图片响应可被浏览器长期缓存

- **WHEN** 访客读取一个已存在的图片资源
- **THEN** 响应头包含 `Cache-Control: public, max-age=31536000, immutable`
- **AND** `Content-Type` 与上传时的探测结果一致

#### Scenario: 附件以原文件名下载

- **WHEN** 访客读取一个 `attachment` 类资源
- **THEN** 响应头 `Content-Disposition` 带原始文件名
- **AND** 浏览器按下载处理而不是内联渲染

#### Scenario: SVG 响应带沙箱 CSP

- **WHEN** 访客读取一个 `image/svg+xml` 资源
- **THEN** 响应头包含 `Content-Security-Policy`，且值中含 `default-src 'none'` 与 `sandbox`
- **AND** `X-Content-Type-Options: nosniff` 仍然存在
