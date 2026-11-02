## Why

上一轮给管理 API 加 Token 与 Book 范围时，范围只作用在「路径里带 `book_ref`」的端点上，其它管理端点按作用域一律放行。对着真实实例做审计后，一个「限定到 1 本书的 admin Token」实际能做到这些事：

- `GET /books`、`GET /trash` 列出全站所有 Book（含未列出与已删除）；
- `GET /audit`、`GET /audit.csv` 读出其它 Book 的操作记录；
- `POST /tokens` 直接再签一个不带范围的 `admin` Token，绕开范围；
- 顺带拿到账号创建、站点设置修改、内网 Webhook 登记等全站能力。

还有几处独立风险：Webhook 只校验 scheme，能登记并投递到内网/本机（SSRF）；`client_ip()` 无条件采信 `X-Forwarded-For`（伪造头可绕过登录失败限流、污染审计 IP）；SVG 媒体以 `inline`、同源方式返回，等同给站点加一个可执行脚本入口；响应里没有任何资源读取端点，AI 写完正文读不回来（只能整章列表翻）；上传只限单文件大小、不限文件个数。

## What Changes

- **admin 与 Book 范围互斥**：`admin` 覆盖账号、站点设置、Token/Webhook 与审计，这些端点没有 Book 可拦；`admin` + Book 范围只能给出「看起来受限、实际全站」的假安全感。签发时拒绝，存量脏 Token 在任何管理端点直接 403 并要求吊销重签。
- **范围覆盖列表类端点**：`GET /books` 只列范围内 Book，`GET /trash` 只列范围内 Book/章/节，`GET /audit` 与 `/audit.csv` 对受限 Token 直接 403；`/audit.csv` 改为要求 `admin`（原先 `read` 就能导出全站）。
- **签发的 Token 不能超越签发者**：作用域按 `read < write < admin` 包含关系比较，Book 范围必须是签发者范围的子集，否则 403。
- **Webhook 防 SSRF**：登记时拒绝本机/内网字面量地址、`localhost`、带用户名密码的 URL；投递前解析域名，任一地址落在内网/本机即拒绝投递（防 DNS rebinding）；继续禁止跟随重定向。
- **转发头按可信代理采信**：新增 `TRUSTED_PROXIES`（IP/CIDR 列表），只有直连 peer 命中时才采信 `X-Forwarded-For` / `X-Real-IP`；默认不信任。
- **SVG 与未列出媒体加固**：SVG 响应带 `Content-Security-Policy: default-src 'none'; …; sandbox`；`unlisted` Book 的媒体除了登录会话，还接受「Book 范围覆盖该 Book」的 API Token，范围外的 Token 一律 401。
- **补齐 AI 读写闭环端点**：新增 `GET /books/{ref}`（单本，含未列出/已删除）与 `GET /books/{book}/chapters/{chapter}/sections/{section}?with_content=1`（默认带正文与 `toc`）；`GET /trash` 增加 `sections` 列表，单节软删也能看到并恢复。
- **收敛细节**：幂等键按 Token 命名空间（跨 Token 不互相回放/抢占）；`/changes` 墓碑条目不再返回标题；批量上传增加 `MAX_UPLOAD_FILES`（默认 50）个数上限；`/meta` 暴露 `max_upload_files`。

## Impact

- 受影响规格：`token-scoping`（互斥、列表/回收站/审计按范围）、`management-api`（读取端点、幂等命名空间、上传个数、审计导出权限）、`webhooks`（SSRF 与重定向）、`media-library`（SVG CSP、媒体鉴权）、`content-api`（墓碑不泄标题）、`service-deployment`（`TRUSTED_PROXIES`、`MAX_UPLOAD_FILES`）。
- 代码：`app/services/{tokens,books,chapters,webhooks}.py`、`app/api/{deps,admin}.py`、`app/web/{admin,media}.py`、`app/{config,middleware}.py`、`app/templates/admin/tokens.html`。
- 兼容性：`admin` + Book 范围的 Token 从「能用」变为「403」，属于有意的破坏性收紧（安全修复）；`/audit.csv` 从 `read` 收紧到 `admin`。其余为新增字段/端点。
- 文档：`docs/ai.md` 的端点表与格式规则、`docs/deploy.md` / `docs/admin.md` 的新变量，`.env.example` 同步。
