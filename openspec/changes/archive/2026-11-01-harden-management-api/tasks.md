# Tasks

## 1. Token 权限收敛（P0）

- [x] 1.1 `tokens.ensure_scope_combination()`：`admin` + 非空 Book 范围抛 `ValidationFailed`
- [x] 1.2 `issue_token()` 先归一化再校验，用同一份结果落库
- [x] 1.3 `current_principal()`：存量 `admin` + Book 范围的行直接 403，提示吊销重签
- [x] 1.4 `POST /tokens`：作用域按包含关系不得超越签发者，Book 范围必须是签发者范围的子集
- [x] 1.5 网页 Token 表单补「admin 不能与 Book 范围共存」提示

## 2. 范围覆盖列表类端点（P1）

- [x] 2.1 `books.list_books(scope_ids=...)`：范围内过滤，空范围用 `false()` 而不是「不过滤」
- [x] 2.2 `GET /books` 传 `principal.book_ids`
- [x] 2.3 `GET /trash` 按范围过滤 Book/章/节，并新增 `sections` 列表
- [x] 2.4 `GET /audit`、`GET /audit.csv` 对受限 Token 返回 403；`/audit.csv` 收紧为 `admin`

## 3. Webhook 防 SSRF（P1）

- [x] 3.1 `validate_url()` 拒绝 userinfo、`localhost` / `*.localhost`、内网字面量 IP
- [x] 3.2 `_post()` 投递前解析域名，任一地址为内网/本机即拒绝投递
- [x] 3.3 保留 `_NoRedirect`：投递不跟随 3xx

## 4. 媒体与转发头（P1）

- [x] 4.1 SVG 响应加 `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; sandbox`
- [x] 4.2 `_has_credential()` 校验 Token 的 Book 范围是否覆盖该媒体所属 Book
- [x] 4.3 新增 `TRUSTED_PROXIES`，`client_ip()` 只在可信 peer 下采信转发头

## 5. AI 读写闭环与细节（P2/P3）

- [x] 5.1 新增 `GET /books/{ref}`
- [x] 5.2 新增 `GET /books/{book}/chapters/{chapter}/sections/{section}?with_content=1`
- [x] 5.3 幂等键按 `principal.token_id` 命名空间
- [x] 5.4 `chapters_updated_since()` 墓碑不再返回 `title` / `chapter_title`
- [x] 5.5 `MAX_UPLOAD_FILES`（默认 50）：网页上传、API 章节 multipart、API 节 multipart 三处计数校验
- [x] 5.6 `/meta` 的 `limits` 增加 `max_upload_files`

## 6. 验证与文档

- [x] 6.1 新增/调整测试：互斥、存量脏 Token、列表与回收站过滤、审计 403、幂等命名空间、单 Book/单节读取、回收站 `sections`、Webhook 内网与 DNS rebinding、SVG CSP、媒体范围、`client_ip`、上传个数
- [x] 6.2 全量 `pytest` + `ruff` + `node --check` 通过
- [x] 6.3 `docs/ai.md` 补端点与规则（admin 不可限定 Book、审计权限、上传个数、新读取端点）
- [x] 6.4 `docs/deploy.md` / `docs/admin.md` / `.env.example` 补 `TRUSTED_PROXIES` 与 `MAX_UPLOAD_FILES`
- [x] 6.5 容器实测：受限 Token 越界读 Book/回收站/审计全部被拦；Webhook 登记内网地址 400
