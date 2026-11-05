# 管理 API 与 AI 工具接入

BookHub 的**全部后台操作**都有对应的 HTTP 接口，前缀 `/api/v1/admin`。人和 AI 工具用的是同一套服务层，所以两条路径的结果一致。

- 只读读者用 `/api/v1`（见 [api.md](api.md)），不需要鉴权（除非配置了 `API_KEY`）。
- 管理写操作用 `/api/v1/admin`，需要 **API Token**（`Authorization: Bearer <token>`）。

> **先看站点自带的《AI Agent 接入使用指南》**：每个实例启动时都会创建一本内置 Book
> （slug `ai-agent-guide`，`is_builtin: true`），里面写了知识库 / 分组 / Book / 章 / 节
> 的组织关系与上传格式要求、HTTP API 的读写闭环、MCP 的配置与一份可直接跑的最小 MCP
> 服务器代码、SKILL 模板、错误码对照。`GET /api/v1/site` 的 `guide` 字段直接给出它的
> 地址；也可以让人直接在网页上读 `/b/ai-agent-guide`。
> 它整本不可删除（章/节也不可删），但内容和普通 Book 一样可编辑，升级不会覆盖。
> 用 `BUILTIN_GUIDE_ENABLED=false` 可关掉创建（已创建的书不会被删）。

## 1. 拿到 Token

签发时可以做两件事收窄权限（见「API Token」页）：

| 选项 | 作用 |
| --- | --- |
| 作用域 | `read` < `write` < `admin`，逐级包含 |
| 可操作的 Book | 勾选后该 Token 只能读写这些 Book；访问其它 Book 的管理端点返回 403。不勾 = 全部 |

**`admin` 不能与 Book 范围共存**：admin 覆盖账号、站点设置、Token 与审计，这些端点没有 Book 可拦，勾了范围也拦不住。要限定 Book 就只勾 `read` / `write`；历史上签发过的这种组合会被直接拒绝（403），需要吊销重签。

Book 范围的边界很清楚：**带 Book 引用的端点** 越界 403；**不带引用但返回多本 Book 数据** 的端点（`GET /books`、`GET /trash`）只返回范围内的条目；**全站审计**（`GET /audit`、`/audit.csv`）对带范围的 Token 一律 403。

示例：给某个团队的 AI 助手发一个 write + 只勾「部署手册」的 Token，它就无法碰其它文档；再配一个 30 天有效期，到期自动失效。

两种方式：

1. **管理端页面**（推荐）：登录 → 侧栏「API Token」→ 填名称、勾作用域、可直接签发。明文只显示一次。
2. **环境变量引导**：设置 `ADMIN_API_TOKEN=bh_xxx` 后重启，启动时会幂等落库一个 `admin` 作用域的同值 Token（适合 CI/容器冷启动）。

作用域是递增包含关系：`admin` ⊃ `write` ⊃ `read`。

| 作用域 | 能做 |
| --- | --- |
| `read` | 列表、详情、版本、回收站、`meta` |
| `write` | 上面全部 + Book/章节/版本/回收站的写操作 |
| `admin` | 上面全部 + 账号管理、站点设置、Token 签发与吊销、**审计查询与导出** |

## 2. 调用前先看 `meta`

```bash
curl -s -H "Authorization: Bearer $BOOKHUB_TOKEN" \
  http://localhost:8000/api/v1/admin/meta
```

返回当前 Token 的名称、作用域、上传与正文上限（`max_upload_bytes`、`max_upload_files`、`max_content_chars`、媒体配额等）、限流阈值，以及能力清单。**AI 工具建议第一步就调它**，避免用错作用域或超出体积/个数限制。

## 3. 端点一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/admin/books` | Book 列表（含 unlisted / 已删除，`include_deleted=true`）；带 Book 范围的 Token 只看到范围内的书 |
| GET | `/api/v1/admin/books/{ref}` | 单本 Book 详情（含 unlisted / 已删除）：读回刚改过的书的唯一入口 |
| POST | `/api/v1/admin/books` | 创建 Book（`title`、`group`（**必填**，分组的 slug 或 id）、`format`、`visibility`、`icon`） |
| PATCH | `/api/v1/admin/books/{ref}` | 修改 Book（标题/slug/简介/**分组**/可见性/`pinned`/`cover_media_id`，有章节时不能改 format） |
| GET | `/api/v1/admin/groups` | **Book 分组**列表（含每组的 `book_count`；分组是 Book 的上一层分类，见 3.1） |
| POST | `/api/v1/admin/groups` | 新建 Book 分组（`title` 必填，`slug`/`description`/`icon` 可选） |
| PATCH | `/api/v1/admin/groups/{ref}` | 改 Book 分组（标题 / slug / 简介 / 图标） |
| DELETE | `/api/v1/admin/groups/{ref}` | 删 Book 分组（**默认分组**、非空组与最后一个组会被拒绝） |
| POST | `/api/v1/admin/groups/{ref}/move` | 调整分组顺序：`{"direction": -1}` 上移 / `{"direction": 1}` 下移 |
| POST | `/api/v1/admin/books/{ref}/delete` | 软删除（先 `?dry_run=true`，真删加 `?confirm=true`） |
| POST | `/api/v1/admin/books/{ref}/restore` | 从回收站恢复 |
| GET | `/api/v1/admin/books/{ref}/chapters` | 章列表（含草稿/已删除；每章带 `sections[]`） |
| POST | `/api/v1/admin/books/{ref}/chapters` | 新建章：JSON（`title` + 可选 `content`）或 `multipart/form-data`（`file`/`upload`，**可多文件 = 多节**） |
| PATCH | `/api/v1/admin/books/{ref}/chapters/{chapter}` | 只改章标题 / slug（正文请用节级 PATCH） |
| POST | `.../{chapter}/status` | 发布 / 撤回（`{"status": "published"}`，作用在整章） |
| POST | `.../{chapter}/move` | `{"direction": -1}` 或 `{"position": 1}` |
| POST | `.../{chapter}/delete` \| `/restore` | 删除（`confirm=true`，连带其下节下架）/ 恢复 |
| GET | `.../{chapter}/sections` | 该章的所有节（`include_deleted=true` 含已删除） |
| GET | `.../{chapter}/sections/{section}` | **单节详情**：默认带 `content_raw` / `content_rendered` / `toc`，`?with_content=0` 只取元信息 |
| POST | `.../{chapter}/sections` | 新建节：JSON 或 multipart（多文件 = 多节） |
| PATCH | `.../{chapter}/sections/{section}` | 替换节内容 / 改标题 / slug / 格式（`base_version` 或 `If-Match`） |
| POST | `.../sections/{section}/move` \| `/delete` \| `/restore` | 章内排序（`direction`/`position`）/ 软删（`confirm=true`）/ 恢复 |
| GET | `.../sections/{section}/versions` \| `/versions/{n}` \| `/diff?a=&b=` | 节级版本与对比 |
| POST | `.../sections/{section}/rollback/{n}` | 回滚（生成新版本，章状态不变） |
| POST | `/api/v1/admin/books/{ref}/chapters/batch` | 批量发布/撤回/删除，逐条返回结果 |
| POST | `/api/v1/admin/books/{ref}/chapters/reorder` | 提交 `{"chapter_ids": [...]}` 整体排序 |
| GET | `/api/v1/admin/trash` | 回收站：`books` / `chapters` / `sections`（单节软删只在这里能看到并恢复）；带 Book 范围时只列范围内 |
| GET/POST | `/api/v1/admin/users` | 账号列表 / 创建 |
| POST | `/api/v1/admin/users/{id}/toggle` \| `/password` | 启停 / 重置密码 |
| GET/PUT | `/api/v1/admin/settings` | 站点设置 |
| GET | `/api/v1/admin/audit` | 审计查询（`book_id`、`actor`、分页）；需要 `admin`，带 Book 范围的 Token 一律 403 |
| GET/POST/DELETE | `/api/v1/admin/tokens` | Token 列表 / 签发（可带 `books` 限定范围，但 `admin` 作用域不能配范围）/ 吊销（吊销后立即失效，但记录还在） |
| POST | `/api/v1/admin/tokens/{id}/delete` | 删除**已吊销或已过期**的 Token 记录（`?dry_run=true` 预览、`?confirm=true` 执行）。仍有效的 Token 会 400：必须先吊销，两步分开才能在审计里留下失效时间 |
| GET | `/api/v1/admin/audit.csv` | 审计导出 CSV（`book_id`、`actor`、`action`、`limit`）；需要 `admin` |
| POST | `/api/v1/admin/audit/cleanup` | 按 `AUDIT_RETENTION_DAYS` 清理审计（默认预览，`?confirm=true` 执行） |
| GET/POST | `/api/v1/admin/webhooks` | Webhook 列表 / 登记（密钥只返回一次；地址不能指向内网/本机，投递前还会再查一次解析结果） |
| DELETE | `/api/v1/admin/webhooks/{id}` | 停用 Webhook（保留投递记录） |
| POST | `/api/v1/admin/webhooks/{id}/test` | 发一条 `webhook.test` 事件 |
| GET | `/api/v1/admin/webhooks/{id}/deliveries` | 最近投递记录（状态码/错误/次数） |
| POST | `/api/v1/admin/deliveries/{id}/retry` | 重试一条失败投递 |
| GET | `/api/v1/admin/books/{ref}/media` | 媒体列表（含 `referenced` 引用标记与 `usage` 配额） |
| POST | `/api/v1/admin/books/{ref}/media` | 上传图片/附件（`multipart/form-data`，字段 `file` 或 `upload`） |
| DELETE | `/api/v1/admin/books/{ref}/media/{id}` | 软删除（`?dry_run=true` 预览，`?confirm=true` 执行） |
| POST | `/api/v1/admin/books/{ref}/media/cleanup` | 清理未引用资源（默认预览，`?confirm=true` 执行） |

`{ref}` 可以写 slug 或数字 ID，`{chapter}` 同理。

### 3.1 Book 分组（`/groups`）与「章 / 节」

`/groups` 只有一个含义：**Book 分组**。分卷已经删除（迁移 `0015_chapter_sections`），章节侧的结构变成「章 → 节」。

| 路径 | 是什么 | 层级 | 决定什么 | 需要的 scope |
| --- | --- | --- | --- | --- |
| `/api/v1/admin/groups` | **Book 分组**（表 `book_groups`） | Book 的上一层：`组 → Book → 章 → 节` | 首页分区与分区顺序 | `admin`（读也要） |
| `/api/v1/admin/books/{ref}/chapters` | **章**（表 `chapters`） | Book 内部的一层 | 目录里的 `1.` / `2.`、发布状态 | 读 `read`，写 `write` |
| `.../chapters/{chapter}/sections` | **节**（表 `chapter_sections`） | 章的下一层 | 正文、格式、字数、版本、节页 URL | 读 `read`，写 `write` |

`GET /api/v1/admin/meta` 的 `capabilities` 里对应 `book_groups`、`chapters`、`sections`、`versions`。

> 注意 scope 差异：Book 与章/节的写操作要 `write`，而**分组端点要求 `admin`**——只给了 `write` 的 AI Token 能建 Book（并指定 `group`），但建不了新分组。

**章的表示**（`GET /chapters` 的 `items[]`、`POST /chapters` 与 `PATCH /chapters/{ref}` 的响应）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` / `book_id` | int | |
| `slug` / `title` | string | 章在 Book 内唯一 |
| `status` | string | `draft` \| `published`（**只有章有状态**） |
| `sort_order` | int | Book 内顺序 |
| `sections` | array | 每项 `{id, slug, title, format, version, word_count, updated_at, url}` |
| `published_at` / `created_at` / `updated_at` / `deleted` | | |

章**没有** `content` / `format` / `version` / `word_count`：这些都下沉到节。`POST /chapters` 里带的 `content` 只是"顺手建第一节"的便捷写法（`with_content=true` 时 `sections[].content_raw` 也会返回）。

**节的表示**：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` / `chapter_id` | int | |
| `slug` / `title` | string | 节在章内唯一 |
| `format` | string | `markdown` \| `html`；整本统一，等于所属 Book 的 `format` |
| `version` | int | 该节自己的 `current_version_no` |
| `word_count` / `checksum` | int / string | |
| `url` | string | 读者地址 `/b/<book>/<chapter>/<section>` |
| `content_raw` / `content_rendered` / `toc` | | 仅在 `with_content` 时返回 |

**改正文的正确姿势**：`PATCH .../chapters/{chapter}/sections/{section}`，body `{"content": "...", "base_version": 2}`。`PATCH .../chapters/{chapter}` 只接受 `title` / `slug`。

**Book 分组的表示**（`GET /groups` 的 `items[]`、`POST /groups` 与 `PATCH /groups/{ref}` 的响应）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | int | 主键，可作为其它端点的 `{ref}` |
| `slug` | string | 站内唯一；只用于 API 与 `?group=` 筛选，不出现在读者地址栏 |
| `title` | string | 分区标题（最长 120 字符） |
| `description` | string | 分区说明，未填为空串 |
| `icon` | string | 图标名（内置 SVG 图标集，如 `book-open`）；未填为空串，页面回退默认图标 |
| `sort_order` | int | 组之间的顺序，10/20/30… |
| `book_count` | int | 该组下**未删除**的 Book 数（不含回收站） |
| `is_default` | bool | 是否为系统内置的「默认分组」（`slug=default`）：不能删除、slug 不能改 |

- `{ref}` 可写分组的 slug 或**纯数字 id**；不存在返回 `404`（`分组不存在`）。
- `POST /groups/{ref}/move` 的响应是**重排后的完整分组列表**（`{"items": [...]}`），可以直接拿它刷新本地缓存。
- `DELETE /groups/{ref}` 成功返回 `{"deleted": true, "id": …, "slug": …, "title": …}`；默认分组（`is_default=true`）、组下还有 Book（**含回收站里的**）或它是最后一个组时返回 `400`，message 说明原因。组的删除不可撤销，没有回收站。
- `PATCH /groups/{ref}` 对默认分组改 `slug` 返回 `400`；标题/简介/图标仍可改。

**创建 Book 时 `group` 是必填契约**：

- `POST /api/v1/admin/books` 的 `group` 接受分组的 **slug 或 id**（`"infra"` 与 `2` 都行）；
- 缺失或空串 → `400`「创建 Book 必须选择分组：请在 group 里给出分组的 slug 或 id」；
- 给了但不存在的分组 → `404`「分组不存在」，不会静默落成"未分组"的书；
- `PATCH /api/v1/admin/books/{ref}` 用 `group` 改归属，不传或传 `null` 表示不动（不会把书塞回默认分组）。

Book 的表示（`/books`、`/books/{ref}` 的响应）里多了只读的 `group` 字段：`{"id": 2, "slug": "infra", "title": "基础设施"}`。只读 API 的 `GET /api/v1/books?group=<slug|id>` 也能按组过滤，见 [api.md](api.md) 第 4 章。

## 4. 三个对 AI 特别重要的约定

**幂等**：给写请求加 `Idempotency-Key: <任意唯一串>`。网络超时后原样重试，服务端直接回放首次结果（响应带 `Idempotent-Replay: true`），不会重复建章节；同一 key 配不同请求体会返回 409。键按 Token 分命名空间：两个 Token 用同一个键互不影响（不会回放别人的响应，也不会互相 409）。

**先预览再删**：

```bash
curl -X POST -H "Authorization: Bearer $BOOKHUB_TOKEN" \
  "http://localhost:8000/api/v1/admin/books/dev-handbook/chapters/welcome/delete?dry_run=true"
# → {"dry_run": true, "would_delete": {...}}   数据没动

curl -X POST -H "Authorization: Bearer $BOOKHUB_TOKEN" \
  "http://localhost:8000/api/v1/admin/books/dev-handbook/chapters/welcome/delete?confirm=true"
```

删除是软删除，随时可以 `POST .../restore` 恢复。

**并发**：替换**节**内容时带 `base_version`（或 `If-Match: "<version>"`）。版本对不上返回 409，不会覆盖别人的改动。

## 5. 常见调用

```bash
# 创建 Book（默认 Markdown；group 必填，写分组的 slug 或 id）
curl -s -X POST http://localhost:8000/api/v1/admin/books \
  -H "Authorization: Bearer $BOOKHUB_TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"运维手册","format":"markdown","group":"infra","summary":"内部运维文档"}'

# 一次上传三个文件 = 一章三节（标题取文件名、格式按扩展名）
curl -s -X POST http://localhost:8000/api/v1/admin/books/ops-handbook/chapters \
  -H "Authorization: Bearer $BOOKHUB_TOKEN" \
  -F "title=第 1 章 部署" -F "status=published" \
  -F "file=@01-概述.md" -F "file=@02-架构.md" -F "file=@03-示例.html"

# 给已有章追加一节
curl -s -X POST http://localhost:8000/api/v1/admin/books/ops-handbook/chapters/deploy/sections \
  -H "Authorization: Bearer $BOOKHUB_TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"回滚方案","content":"# 回滚\n","slug":"rollback"}'

# 发布一批章（逐条结果；其下所有节一起可见）
curl -s -X POST http://localhost:8000/api/v1/admin/books/ops-handbook/chapters/batch \
  -H "Authorization: Bearer $BOOKHUB_TOKEN" -H "Content-Type: application/json" \
  -d '{"action":"publish","chapter_ids":[1,2,3]}'

# 上传图片，拿到可直接写进正文的地址
curl -s -X POST http://localhost:8000/api/v1/admin/books/ops-handbook/media \
  -H "Authorization: Bearer $BOOKHUB_TOKEN" \
  -H "Idempotency-Key: media-arch-2026-10" \
  -F "file=@arch.png"
# → {"id":7,"url":"/media/ops-handbook/9f2c1d3e4b5a6c7d-arch.png","kind":"image",...}

# 把附件贴进某一节（把上面返回的 url 放进 Markdown 图片/链接语法）
curl -s -X PATCH "http://localhost:8000/api/v1/admin/books/ops-handbook/chapters/deploy/sections/architecture" \
  -H "Authorization: Bearer $BOOKHUB_TOKEN" -H "Content-Type: application/json" \
  -d '{"content":"## 架构\n\n![部署拓扑](/media/ops-handbook/9f2c1d3e4b5a6c7d-arch.png)\n"}'

# 清理未被任何章/节引用的资源（先预览，再确认）
curl -s -X POST http://localhost:8000/api/v1/admin/books/ops-handbook/media/cleanup \
  -H "Authorization: Bearer $BOOKHUB_TOKEN"
curl -s -X POST "http://localhost:8000/api/v1/admin/books/ops-handbook/media/cleanup?confirm=true" \
  -H "Authorization: Bearer $BOOKHUB_TOKEN"
```

> 媒体上传的幂等指纹包含文件 SHA-256：同一个 `Idempotency-Key` 重传同一份文件会回放首次结果，换了文件则返回 409。图片在正文里一律写**根相对地址**（`/media/...`），部署在子路径时应用会在渲染阶段自动补前缀，模型不需要关心 `ROOT_PATH`。

### 5.1 Webhook（内容变更推送）

登记回调后，章的**发布 / 撤回**、章标题变化、节的**内容替换**都会向它 POST 一个 JSON：

```json
{
  "event": "section.updated",
  "occurred_at": "2026-10-22T10:30:00",
  "book_slug": "ops-handbook",
  "chapter_slug": "deploy",
  "chapter": {"id": 12, "slug": "deploy", "title": "部署", "status": "published"},
  "section": {"id": 34, "slug": "architecture", "title": "架构", "format": "markdown", "version": 3, "word_count": 812, "updated_at": "..."},
  "section_slug": "architecture"
}
```

事件清单：

| 事件 | 何时发 |
| --- | --- |
| `chapter.published` / `chapter.unpublished` | 章的发布状态变化（`chapter.published` 之后每个节还会各发一条 `section.published`） |
| `section.published` | 章发布时逐节发出（订阅方据此拿到节粒度信号） |
| `section.updated` | 节内容/标题/格式/slug 变化（**只有真的产生新版本时才发**） |
| `chapter.updated` | 章级字段（标题 / 顺序）变化；改正文**不会**触发它 |
| `book.created` / `book.deleted` | Book 生命周期 |

请求头：

| 头 | 说明 |
| --- | --- |
| `X-BookHub-Event` | 事件名（见上表） |
| `X-BookHub-Signature` | `sha256=` + HMAC-SHA256(secret, 原始请求体) 的十六进制 |

验签（Python）：

```python
import hashlib, hmac
expected = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
assert hmac.compare_digest(expected, request.headers["X-BookHub-Signature"])
```

- 投递超时 5 秒；失败**不影响**内容保存，只会写一条投递记录（状态码 / 错误 / 次数）。
- 用 `GET .../deliveries` 查失败记录，用 `POST .../deliveries/{id}/retry` 重试；`POST .../webhooks/{id}/test` 可先验证连通性。
- 注册返回的 `secret` 只出现一次，请当凭据保存。

### 5.2 分组：建组 → 建 Book → 按组过滤

```bash
# 1) 建一个分组（需要 admin 作用域的 Token）
curl -s -X POST http://localhost:8000/api/v1/admin/groups \
  -H "Authorization: Bearer $BOOKHUB_TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"基础设施","slug":"infra","description":"机房、网络与中间件"}'
# → {"id":2,"slug":"infra","title":"基础设施","description":"机房、网络与中间件","icon":"","sort_order":20,"book_count":0}

# 2) 建一本 Book 并归进该组（group 必填；slug 与 id 都行）
curl -s -X POST http://localhost:8000/api/v1/admin/books \
  -H "Authorization: Bearer $BOOKHUB_TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"运维手册","format":"markdown","group":"infra","summary":"内部运维文档"}'

# 3) 只读 API 按组过滤（不用带 Token，除非配置了 API_KEY；分组不存在返回 404）
curl -s "http://localhost:8000/api/v1/books?group=infra"

# 4) 把 infra 上移一位，响应是重排后的完整分组列表
curl -s -X POST http://localhost:8000/api/v1/admin/groups/infra/move \
  -H "Authorization: Bearer $BOOKHUB_TOKEN" -H "Content-Type: application/json" \
  -d '{"direction":-1}'
```

- 换组：`PATCH /api/v1/admin/books/{ref}` 带 `{"group":"ops"}`；不传 `group` 表示不动。
- 组的 `book_count` 只统计未删除的 Book，而删除校验把回收站里的 Book 也算占用——所以会出现"显示 0 却删不掉"的情况，先确认回收站。
- 组之间用 `move` 上下移（重写 10/20/30）；**组内 Book 没有手工序号**，仍按「置顶 + 热度 + 创建时间」自动排，想调整只能 `PATCH /books/{ref}` 改 `pinned` 或靠真实访问量。

## 6. 把接口交给模型（function calling）

1. 取 `http://<host>/openapi.json`。每个管理操作都有稳定的 `operationId`、中文 `summary`/`description` 和完整 Schema。
2. 只保留 `tags` 含 `admin` 的路径，作为工具集注入模型（读侧 `/api/v1` 可另作只读工具）。
3. 在系统提示里写明：
   - 所有调用都要带固定请求头 `Authorization: Bearer <token>`（由宿主代填，不要让模型看到明文）；
   - 删除类操作先 `dry_run=true` 汇报影响面，得到用户确认后再 `confirm=true`；
   - 写操作统一带 `Idempotency-Key`（可以用 `uuid4`）；
   - 章节格式由 Book 决定，不要尝试混用。
   - 建 Book 必须带 `group`（分组的 slug 或 id）；不确定有哪些分组时先 `GET /api/v1/admin/groups`。
4. 建议给 AI 一个 **`write` 作用域**的独立 Token（需要的话再加 Book 范围），账号与站点设置这类 `admin` 操作留给人。注意 `admin` **不能**配 Book 范围：要限制范围就只能用 `read` / `write`。

## 7. 安全建议

- 一个工具一个 Token，名字写清楚（会出现在审计日志里，形如 `api:docs-bot`）。
- 按需给作用域，不用就给 `read`；临时工具设过期天数。
- 泄漏时立即在「API Token」页吊销（吊销后立即 401），然后重建。
- 管理接口按 Token 限流（默认 60 次/分钟，`ADMIN_API_RATE_LIMIT` 可调），超限返回 429 与 `Retry-After`。
- **一次上传的文件个数有上限**：`max_upload_files`（默认 50，`MAX_UPLOAD_FILES` 可调）。超了返回 400 且整次不落库；批量导入请分批，每批控制在 10～20 个文件。
- 审计（`/audit`、`/audit.csv`）覆盖全站，只有 `admin` 能读；带 Book 范围的 Token 一律 403。

## 8. 冒烟脚本

```bash
python scripts/api_smoke.py --base-url http://localhost:8000 --token "$BOOKHUB_TOKEN"
```

会依次创建 Book、上传章节、发布、回滚、预览删除、删除、恢复，并在失败时退出码 1。
