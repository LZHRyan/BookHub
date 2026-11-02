# Design

## Context

仓库当前为空（仅有 OpenSpec 脚手架），因此这是一次 greenfield 架构选型，而不是在既有代码上改造。约束来自三处：

- **使用形态**（见 `proposal.md` - Why）：读者数量大但几乎全是只读；写入只来自 3~5 名管理员，且是低频的"上传/替换/删除章节"操作。读写比极度不对称。
- **内容形态**：章节是整份 HTML 或 Markdown 文档（几百 KB 级别，不是结构化块），需要能被外部程序按 URL 原样取回，同时要能被人读。
- **运维形态**：研发部内网自托管，要求 `docker compose up -d` 即可跑起来，不能依赖外部 SaaS、CDN 或需要专人调优的中间件（Elasticsearch / Redis / 对象存储都不应成为启动前提）。

## Goals / Non-Goals

**Goals:**

- 单容器起步：一个镜像 + 一个数据卷即可提供完整功能；无外部服务强依赖。
- 内容保真：Markdown 原文与 HTML 原文都按字节级保存，API 能取回原文而不是"再转换一遍的结果"。
- 安全默认：管理员上传的 HTML 视为不可信，净化 + CSP 双层防御，且可被测试验证。
- API 优先：Web 界面与外部程序走同一套服务层，避免"页面能看但 API 取不到"的漂移。
- 可演进：数据访问走 ORM，允许后续切 Postgres、加 SSO、加图片附件而不改动契约。

**Non-Goals:**

- 不做实时协同编辑（无 OT/CRDT、无 WebSocket 推送）。
- 不做多租户与按 Book 的细粒度权限（只有管理员/编辑者/访客三种身份）。
- 不做 Elasticsearch 级别的相关度排序、同义词、拼音检索。
- 不做文档内嵌资源的二进制托管（图片暂用外链或 data URI，图片上传留给后续变更）。

## Decisions

### D1. 技术栈：Python 3.12 + FastAPI + Jinja2 服务端渲染

| 方案 | 优点 | 缺点 | 结论 |
| --- | --- | --- | --- |
| **FastAPI + Jinja2**（选中） | 单进程单容器；Pydantic 校验 + 自动 OpenAPI；Markdown/HTML 处理库成熟（markdown-it-py、nh3）；异步静态文件与流式响应好写 | 需要自己写模板和少量 JS；CPU 密集渲染依赖缓存 | 采用 |
| Node.js + NestJS + React | 前后端生态统一，SSR 可选 | 需要前端构建链（两层镜像/两进程），运维面更大；对内网小团队是过度设计 | 否 |
| Go + Gin + html/template | 单二进制、内存最小、并发强 | Markdown 生态（GFM 插件、代码高亮、净化）要自研或绑 CGO；开发速度慢 | 否 |

理由：本系统的复杂度集中在"内容处理 + 契约稳定"，不在高并发；Python 的 `markdown-it-py` / `nh3` / `pygments` 组合能覆盖 GFM、净化、高亮三件事，且都是纯 Python 或预编译 wheel，镜像构建无需编译器。

### D2. 渲染策略：服务端渲染 + 渐进增强，不引入 SPA

页面由 Jinja2 输出完整 HTML，交互（新建/编辑表单、拖拽排序、搜索建议）用少量原生 JS（约 1 个 `app.js`，无打包步骤）。

- 好处：首屏无白屏、SEO/内网爬虫友好、无 Node 构建产物进入镜像、CSP 更容易收紧。
- 代价：排序等交互需要手写 fetch 调用，接受。

### D3. 存储：SQLite（WAL）+ SQLAlchemy 2.0 ORM，内容存库不存文件

- 正文（原文 + 渲染缓存）以 `TEXT` 存库：单文件备份、事务内原子替换、版本对比无需读盘。
- `journal_mode=WAL`、`synchronous=NORMAL`、`busy_timeout=5000`；写操作短事务。
- 数据卷 `/data` 只放 `bookhub.db` 与备份/上传临时文件，便于整体打包。
- 通过 `DATABASE_URL` 可切 Postgres（compose 里提供 `postgres` profile）；**默认与测试基线是 SQLite**，Postgres 走同一 ORM 路径但只做冒烟验证。
- 备选被否：正文存文件 + DB 存元数据（备份要保证两者一致，替换章节时可能半成功）；MongoDB（引入新运维组件，收益不抵成本）。

### D4. Markdown 管线：markdown-it-py（CommonMark + GFM 插件）→ 净化 → 高亮 → 缓存

顺序固定为：`原文` → `markdown-it-py`（`html=False`，插件：table / strikethrough / tasklists / footnote / deflist / anchors）→ `nh3` 白名单净化 → 生成 TOC 与标题锚点 → 写入 `content_rendered` 缓存。

- `html=False` 让 Markdown 里的裸 HTML 不直接穿透，避免"作者以为安全其实不安全"。
- 渲染结果落库缓存，按 `content_checksum` 失效；章节页只是一次 SELECT + 模板渲染。
- 备选被否：`python-markdown`（扩展分散、GFM 支持靠第三方）、`mistune`（插件生态较弱）、客户端渲染（破坏 API 的 `format=html` 通道与首屏）。

### D5. HTML 净化与 XSS 防御：nh3 白名单 + 严格 CSP

- `nh3.clean()` 允许标签白名单（标题、段落、列表、表格、代码、图片、链接、details 等），禁止 `script`/`iframe`/`object`/`form`/`style` 属性、`on*` 事件、`javascript:`/`data:`（图片 `data:image/*` 单独放行与否由配置决定）。
- 站内页面响应 `Content-Security-Policy: default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'`，杜绝内联脚本执行。
- 管理端表单加 CSRF token（会话内签发，`SameSite=Lax` 之上再加一层）。
- 明确不使用 iframe 隔离正文：会破坏站内锚点、搜索高亮与打印，改为"净化 + CSP"双保险并配单测。

### D6. 认证与会话：bcrypt 密码 + itsdangerous 签名 Cookie 会话

- 密码：`bcrypt`（cost 12，72 字节截断前置校验）；不引入 passlib（与新版 bcrypt 存在兼容坑）。
- 会话：`itsdangerous` 签名 cookie（`HttpOnly`、`SameSite=Lax`、`Secure` 由 `COOKIE_SECURE` 控制），服务端只存 `user_id` 与 `session_epoch`，改密码/禁用即失效。
- 角色两级：`admin`（内容 + 账号 + 站点设置 + 审计）与 `editor`（仅内容）。首个管理员由 `BOOKHUB_INITIAL_ADMIN_USER/PASSWORD` 在启动时幂等创建。
- 备选被否：JWT（浏览器场景需要自己处理续期与登出失效，无收益）、OAuth/OIDC（本期不做，但认证入口收敛在 `services/auth.py` 便于替换）。

### D7. 章节变更模型：快照版本 + 软删除

- 每次内容写入（新建、替换、回滚）都追加一条 `chapter_versions` 记录（含 `version_no`、原文、格式、备注、操作者）。
- `chapters` 上保留 `current_version_no` 与 `content_checksum`；API 的 `ETag` 由章节 `id + current_version_no` 派生，保证"内容变了 ETag 必变，元数据变了内容不变时也可控"。
- 删除为软删除（`deleted_at`），回收站可恢复；对外 API 与站内一律视为 404。

### D8. 全文检索：应用层中文二元组 + FTS5

- 索引写入前把 `标题 + 正文纯文本` 归一化：ASCII 词按词切分小写化，CJK 连续片段切成**二元组**（"知识库" → "知识 识库"），拼成待索引文本写入 `chapter_fts`（FTS5 `unicode61`）。
- 查询做同样切分后用短语/AND 组合，因此 2 字中文词也能命中；单字查询降级为 `LIKE`。
- `chapter_fts` 与 `chapters` 通过 `rowid = chapter_id` 关联，章节写入事务内同步重建；只索引 `status=published` 且未删除的章节。
- Postgres 路径退化为 `ILIKE`（在 `docs` 中标注相关度差异）。
- 备选被否：FTS5 `trigram`（2 字查询失效、索引膨胀）、Elasticsearch（新增运维组件，违背 Non-Goal）。

### D9. 数据模型

```text
users(id, username UQ, display_name, password_hash, role[admin|editor], is_active,
      session_epoch INT, created_at, last_login_at)

books(id, slug UQ, title, summary, icon, sort_order, visibility[public|unlisted],
      created_at, updated_at, created_by, deleted_at)

chapters(id, book_id FK, slug, title, format[markdown|html], content_raw TEXT,
         content_rendered TEXT, content_checksum, word_count, sort_order,
         status[draft|published], current_version_no, published_at, created_at,
         updated_at, updated_by, deleted_at)
         UNIQUE(book_id, slug) WHERE deleted_at IS NULL

chapter_versions(id, chapter_id FK, version_no, title, format, content_raw TEXT,
                 note, created_by, created_at)
                 UNIQUE(chapter_id, version_no)

audit_logs(id, actor_id, actor_name, action, target_type, target_id, target_label,
           detail JSON, ip, created_at)

site_settings(key PK, value TEXT, updated_at)

chapter_fts USING fts5(title, body, tokenize='unicode61 remove_diacritics 2')
           -- rowid = chapters.id
```

约定：所有时间戳为 UTC ISO-8601；`slug` 只允许 `[a-z0-9-]`，冲突时自动追加 `-2`/`-3`；`sort_order` 为整数，重排时整体重写该 Book 下的顺序（一次事务）。

### D10. 对外 API 契约（`/api/v1`，只读）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/books` | Book 列表（`page`/`page_size`/`visibility`），返回 `id, slug, title, summary, chapter_count, updated_at` |
| GET | `/api/v1/books/{slug_or_id}` | Book 详情 + 有序章节目录（不含正文） |
| GET | `/api/v1/books/{book}/chapters/{chapter}` | 单章节；默认 JSON（含 `content_raw` 与 `content_rendered`），`?format=raw\|rendered` 或 `Accept: text/markdown\|text/html` 只取其一 |
| GET | `/api/v1/books/{book}/export` | 整本导出：`format=json`（manifest）或 `format=zip`（`book.json` + 每章 `.md`/`.html`） |
| GET | `/api/v1/search?q=` | 全站检索，返回带片段高亮的结果与命中 Book/章节 |
| GET | `/api/v1/changes?since=ISO8601` | 增量同步：返回该时间点之后发布/更新/删除的章节与 Book 变更摘要（含 `deleted: true`墓碑） |
| GET | `/api/v1/site` | 站点元信息（名称、版本、能力开关） |
| GET | `/healthz` `/readyz` | 存活 / 就绪（就绪含 DB 可写探测） |

横切约定：

- **错误**：`{"error": {"code": "...", "message": "...", "request_id": "..."}}`；未发布或已删除一律 `404`（不泄露存在性），未授权 `401`，无权限 `403`，限流 `429` 带 `Retry-After`。
- **缓存**：章节/Book 响应带 `ETag: "c<version>-<checksum8>"` 与 `Last-Modified`；`If-None-Match` 命中返回 `304`。
- **分页**：`page`/`page_size`（默认 20，上限 100），响应含 `items`、`total`、`page`、`page_size`。
- **鉴权**：`API_KEY` 未配置时 `/api/v1` 完全公开；配置后要求 `X-API-Key`（`/healthz`、`/api/v1/site` 除外）。
- **限流**：进程内滑动窗口（按 IP + 路径组），默认 120 req/min，`RATE_LIMIT_ENABLED` 可关；单实例部署，无需 Redis。
- **CORS**：`CORS_ORIGINS` 逗号分隔白名单，默认 `*` 仅用于 GET 且不带凭证。
- **文档**：`/docs`（Swagger UI）与 `/openapi.json`，`API_DOCS_ENABLED` 可关。

站内路由（服务端渲染）：`/`（Book 列表 + 搜索框）、`/b/{book_slug}`（目录）、`/b/{book_slug}/{chapter_slug}`（含 TOC/上下篇）、`/search`、`/admin/*`（登录、Book/章节 CRUD、版本、回收站、账号、设置、审计）。

### D11. 部署：单镜像多阶段构建 + compose 编排

- `Dockerfile` 多阶段：`builder` 阶段用 `pip wheel` 预编译依赖；`runtime` 阶段基于 `python:3.12-slim`，只复制 wheel 与源码，创建非 root 用户 `bookhub`（uid 10001），`/data` 与 `/app` 归属该用户。
- 启动用 `docker/entrypoint.sh`：等待 `/data` 可写 → `alembic upgrade head` → 幂等创建初始管理员 → 可选种子数据 → `exec uvicorn`。
- **单 worker**：SQLite 单写入者模型下默认 `WEB_CONCURRENCY=1`；容器 healthcheck 打 `/healthz`；`--proxy-headers` 与 `FORWARDED_ALLOW_IPS` 适配反向代理。
- `docker-compose.yml`：`bookhub` 服务 + 命名卷 `bookhub-data:/data` + `env_file`；另加 `profiles: ["postgres"]` 的 `db` 服务，用于切换 Postgres 时启用。
- 配置全部来自环境变量，`.env.example` 覆盖每一项并给出默认值与说明；`ROOT_PATH` 支持子路径反代。
- 备份/恢复：`docker/backup.sh`（`sqlite3 .backup` 语义的在线备份 + 内容卷 tar）与 `docker/restore.sh`；升级 = 拉新镜像重启（迁移自动执行），回滚 = 停服 → 恢复备份 → 回退镜像 tag。

### D12. 测试策略

- `pytest` + `httpx.ASGITransport`，每个测试函数一个临时 SQLite 文件（`tmp_path`），启动时跑迁移。
- 必测面：登录/会话/CSRF/角色边界；Book 与章节 CRUD + 软删除 + 版本回滚；上传编码归一化（UTF-8/BOM/GB18030）；Markdown 渲染与 HTML 净化（`<script>`、`onerror=`、`javascript:` 必须被剔除）；草稿对外不可见；ETag/304；搜索中文 2 字命中；限流；导出 ZIP 内容。
- 部署冒烟：`scripts/smoke.py` 对运行中的实例跑一遍 API 流程，供 compose 部署后验证。

### D13. 契约细则（把 spec 里必须确定的取值定死）

规格只描述可观测行为，但下列取值不写死会让实现与测试各按一套理解走，故在此定案：

| 项 | 定案 | 理由 |
| --- | --- | --- |
| slug 派生结果为空（纯中文/纯符号标题） | 回退为 `book-<6位十六进制>` / `chapter-<6位十六进制>`，创建成功，不要求人工填 slug | 团队标题几乎全是中文，强制手填 slug 会让"上传即用"无法成立 |
| slug 唯一性 | Book 全局唯一、章节在 Book 内唯一，都用**部分唯一索引**（`WHERE deleted_at IS NULL`）；恢复时若 slug 已被新记录占用，自动加 `-2` 后缀 | 与"删除后可重建同名"一致；恢复不能因唯一冲突失败 |
| 默认值 | 新 Book 可见性 `public`；新章节状态 `draft`；新章节 `sort_order = 该 Book 最大值 + 10` | 草稿默认避免半成品外泄；`+10` 留出手工插入空间 |
| 正文上限 | 单文件 `MAX_UPLOAD_BYTES=5 MiB`（超出 413）、正文 `MAX_CONTENT_CHARS=500000` 字符（超出 422） | 覆盖上千页手册，同时挡住误传大文件 |
| 并发替换 | 表单/请求带 `base_version`；与当前版本不一致返回 **409** 且不写库；不带该字段时按写入者胜出（仍有版本记录与审计） | 兼容脚本化调用，同时给网页端保护 |
| Book 软删除 | 只标记 `books.deleted_at`，不改章节行；所有读路径 `JOIN` 过滤 `book.deleted_at IS NULL`；恢复整本即恢复全部章节 | 避免"级联软删 + 恢复"两套状态机 |
| 版本对比 | 行级 unified diff（`difflib`），只读视图；单次最多渲染 5000 行差异，超出截断并提示 | 避免超大文档把管理页拖死 |
| 站点设置键 | 仅 `site_name`、`site_footer`、`home_intro` 三键，缺省时用内置默认文案 | 与 proposal 对齐，不做通用 KV 后台 |
| `page_size` 越界 | 静默裁剪到 100（不报错）；`page<1` 或非整数返回 400 | 宽松兼容比报错更适合只读 API |
| `changes` 缺 `since` | 返回 400（参数校验错误），不默认全量 | 全量同步用 `/export`，语义更清晰 |
| API Key 作用域 | 仅 `/api/v1/*`；`/healthz`、`/readyz`、`/api/v1/site` 免鉴权 | 探针与能力发现不能依赖密钥 |
| `visibility` 过滤 | 取值 `public` / `unlisted` / `all`，缺省 `public`；`all` 仅对已配置 API Key 的调用生效 | 防止匿名枚举隐藏 Book |
| `ROOT_PATH` | 接受带或不带尾斜杠，内部归一化去掉尾斜杠；OpenAPI `servers` 与模板链接都带该前缀 | 反代子路径是最常见部署形态 |
| 登录限流 | 同 IP+用户名 5 次失败 / 5 分钟窗口 → 429；成功登录清零；凭据校验用恒定时间比较 | 内网也需要挡住弱口令爆破 |
| 密码策略 | 新密码 / 重置密码最少 10 字符，不得与用户名相同；仅大小写或纯数字视为弱密码拒绝 | 兼顾内网可记忆性与基本强度 |
| 审计细节落点 | `audit_logs.detail` JSON 存 `from_version` / `to_version` / `fields`；审计记录只允许追加，不提供修改/删除入口 | `audit_logs` 不加列，避免迁移负担 |
| 初始管理员变量缺失 | 跳过创建并打印 warn；`SECRET_KEY` 缺失才阻止启动 | 已有实例续跑时不该因变量缺失而崩 |
| 单字中文查询 | 二元组无法命中时退化为 `LIKE '%字%'`，结果按更新时间倒序，标注"精确度较低" | 保证不返回空且不报错 |
| Postgres 备份 | `pg_dump -Fc` + 内容卷打包；SQLite 用在线 backup API | profile 切换后备份路径必须同步明确 |
| HTML 章节的"原文"通道 | 库内同时存 `content_raw`（管理员上传的原样内容，仅管理端可见）与 `content_safe`（净化后的版本）；对外 API 的 JSON `content_raw`、`?format=raw`、导出 ZIP 一律返回 `content_safe` | 外部程序会把内容嵌进自己的页面，绝不能给未净化 HTML；同时管理员编辑时还能看到原始上传 |

## Risks / Trade-offs

- **[存储型 XSS：管理员上传的 HTML 被执行]** → nh3 白名单 + 页面 CSP + 单测覆盖常见 payload；渲染缓存也存净化后结果，避免"净化只发生在展示路径"。
- **[中文检索召回不足]** → 二元组切分 + 短语查询，单字退化为 LIKE；在 `docs/api.md` 写明查询语义与限制。
- **[SQLite 写并发瓶颈]** → 短事务、WAL、单 worker；写操作仅管理员低频触发；提供 Postgres profile 作为逃生通道。
- **[大文档渲染阻塞请求]** → 渲染只在内容变更时发生并落库缓存，读路径零渲染。
- **[版本表无限膨胀]** → `VERSION_RETENTION`（默认保留最近 50 个版本）在写入时裁剪，且永不裁剪当前版本。
- **[编码误判导致乱码]** → 检测顺序 UTF-8 BOM → UTF-8 严格解码 → GB18030 试探 → 报错；表单可显式指定 `encoding` 覆盖。
- **[单 worker 下重启有短暂不可用]** → compose `restart: unless-stopped` + healthcheck；文档说明多副本需切 Postgres 并共享卷。
- **[`sort_order` 整体重写的写放大]** → 单 Book 章节数量有限（数十到数百），一次事务内 `UPDATE ... CASE` 成本可接受。

## Migration Plan

1. 全新环境：`cp .env.example .env` → 填 `SECRET_KEY` 与初始管理员 → `docker compose up -d --build`；首次启动自动建库、迁移、建管理员。
2. 升级：`docker compose pull && docker compose up -d`；entrypoint 里的 `alembic upgrade head` 幂等执行。
3. 回滚：`docker compose down` → `docker/restore.sh <backup>` → 用旧 tag 启动；数据库降级不自动执行（向前兼容的迁移脚本遵守"只加不删"原则）。
4. 迁移到 Postgres：启动 `postgres` profile → 修改 `DATABASE_URL` → 用 `scripts/export_import.py` 导出 JSON 再导入（章节原文与版本都在 JSON 中）。

## Open Questions

- 图片/附件托管是否纳入下一期（决定是否引入对象存储或磁盘二进制目录）——不影响本期数据模型与 API 契约。
- SSO（OIDC/LDAP）接入时机——认证入口已收敛，可在不改契约的前提下追加 provider。
- 是否需要按 Book 授权给指定部门——当前只有全局角色，若需要则在 `books` 上加 `access_policy` 字段并扩展 API。
