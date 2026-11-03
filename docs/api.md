# BookHub 只读 API v1 手册

面向内部同事的接口手册。本文档描述 BookHub 对外只读 HTTP API `/api/v1`，全部端点均为 `GET`，不接受写入方法（`POST`/`PUT`/`PATCH`/`DELETE` 一律返回 `405`，错误体 `code` 为 `http_error`）。

内容的唯一事实来源是 `app/api/v1.py`、`app/main.py`、`app/middleware.py`、`app/errors.py`、`app/config.py` 与 `app/services/` 下的实现，文档与代码不一致时以代码为准。

## 1. 通用约定

### 1.1 Base URL

服务默认监听 `http://localhost:8000`，所有业务端点前缀 `/api/v1`。如果部署时用环境变量 `ROOT_PATH` 把服务挂在子路径下（例如 `ROOT_PATH=/docs`），实际路径要再拼上该前缀，例如 `http://localhost:8000/docs/api/v1/books`。

`ROOT_PATH` 还会影响响应体里的 `url` / `api_url` 字段，见 1.7。

### 1.2 认证

`API_KEY` 环境变量配置后，`/api/v1` 下除 `GET /api/v1/site` 外的所有端点都要求请求头携带 `X-API-Key`，值必须与 `API_KEY` 完全一致（常量时间比较）。缺失或不匹配返回 `401`，错误体 `code` 为 `unauthorized`。

未配置 `API_KEY`（默认）时 `/api/v1` 匿名可读，但仍受 1.8 的限流约束。详见第 10 章。

### 1.3 分页参数规则

`GET /api/v1/books` 与 `GET /api/v1/search` 共用同一套分页解析逻辑（`_paging`），参数都以字符串形式接收：

| 参数 | 默认值 | 规则 |
| --- | --- | --- |
| `page` | `1` | 必须是大于等于 1 的整数。非整数（如 `page=abc`）或 `page<1`（如 `page=0`）→ `400`，`code=validation_error` |
| `page_size` | 空（等价于 `20`） | 必须是整数，非整数 → `400`，`code=validation_error`。取值会被**静默裁剪**到 `[1, 100]`：`page_size=500` 返回 200 且响应里 `page_size` 为 `100`；`page_size=0` 返回 200 且 `page_size` 为 `1` |

- 分页是偏移式：`offset = (page - 1) * page_size`。
- `total` 是**过滤条件下的全量总数**，不是当前页条数；`items` 可能为空而 `total > 0`（页码越界时）。
- 两个端点的响应都会回显实际生效的 `page` 与 `page_size`，请以响应为准，不要假设请求值被原样采用。

### 1.4 时间格式

- 响应里的所有时间字段都是 UTC 的 ISO-8601 字符串，形如 `2026-10-21T05:47:12.345678Z`（`_iso()`：naive 时间按 UTC 处理，输出用 `Z` 结尾，微秒非零时保留）。
- 数据库按 UTC 存 naive 时间；`published_at` 可能为 `null`（从未发布过的章节不会出现在只读 API 中，该字段在 API 可见章节里理论上非空，但仍按可能为 `null` 处理）。
- 请求参数里需要时间的只有 `/api/v1/changes?since=`，接受 ISO-8601，详见第 8 章。

### 1.5 响应头

所有响应由中间件补上：

| 响应头 | 说明 |
| --- | --- |
| `X-Request-ID` | 每个请求生成的 16 位十六进制 id，错误体里的 `request_id` 与之一致，排查问题时请带上 |
| `X-Content-Type-Options` | 固定 `nosniff` |
| `X-Frame-Options` | 固定 `DENY` |
| `Referrer-Policy` | 固定 `same-origin` |
| `Permissions-Policy` | 固定 `geolocation=(), microphone=(), camera=()` |
| `Content-Security-Policy` | 仅当响应 `Content-Type` 是 `text/html` 时添加 |
| `ETag` / `Last-Modified` | 仅 Book 详情与章节详情端点返回，含 `304` 响应 |
| `Retry-After` | 仅 `429` 响应返回，单位秒 |
| `Content-Disposition` | 仅 `export?format=zip` 返回，形如 `attachment; filename="dev-handbook.zip"` |

### 1.6 CORS

`CORS_ORIGINS` 未设置时默认 `*`。两种情况都会注册 CORS 中间件，允许的方法固定为 `GET`、`HEAD`、`OPTIONS`，允许的请求头固定为 `X-API-Key`、`If-None-Match`、`Accept`，对客户端暴露的响应头固定为 `ETag`、`X-Request-ID`、`Retry-After`，且 `allow_credentials=False`。

`CORS_ORIGINS` 是逗号分隔的 origin 列表，例如 `https://wiki.example.com,https://ops.example.com`。

浏览器端集成要点：想读到 `ETag` 必须靠上面的 `expose_headers`；想发 `If-Modified-Since` 之外的请求头需要服务端显式允许，当前允许列表里没有 `If-Modified-Since`（它属于 CORS 安全列表请求头以外的一类，自定义场景请优先用 `If-None-Match`）。

### 1.7 `url` 与 `api_url` 的拼接方式

所有 payload 里的 `url`、`api_url` 都是**以 `ROOT_PATH` 为前缀的路径**，不是绝对 URL（`_base_url()` 直接返回 `settings.root_path`，默认空串）：

| 字段 | 拼接规则 |
| --- | --- |
| book.`url` | `{ROOT_PATH}/b/{book.slug}` |
| book.`api_url` | `{ROOT_PATH}/api/v1/books/{book.slug}` |
| chapter.`url` | `{ROOT_PATH}/b/{book.slug}/{chapter.slug}` |
| chapter.`api_url` | `{ROOT_PATH}/api/v1/books/{book.slug}/chapters/{chapter.slug}` |
| search item.`url` | `{ROOT_PATH}/b/{book_slug}/{chapter_slug}` |

默认部署（`ROOT_PATH` 为空）下字段值形如 `/b/dev-handbook`、`/api/v1/books/dev-handbook`。客户端应自行加上站点 origin，不要假设字段里带协议和域名。

### 1.8 限流

`RATE_LIMIT_ENABLED`（默认 `true`）为真时，`/api/v1` 下每个来源 IP 每分钟最多 `RATE_LIMIT_PER_MINUTE`（默认 `120`）次请求，超限返回 `429`，错误体 `code=rate_limited`，并带 `Retry-After`（秒，最小 1）。限流在 API Key 校验之前生效，因此未带 `X-API-Key` 的请求也可能先收到 `429` 而不是 `401`。来源 IP 取 `X-Forwarded-For` 第一段，其次 `X-Real-IP`，最后是 TCP 对端地址。

## 2. 端点总表

| # | 方法 | 路径 | 说明 | 成功状态码 | 需 `X-API-Key` | 条件请求 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | GET | `/api/v1/site` | 站点元信息与能力声明 | `200` | 否（始终豁免） | 无 |
| 2 | GET | `/api/v1/books` | Book 列表（分页） | `200` | 配置了 `API_KEY` 时需要 | 无 |
| 3 | GET | `/api/v1/books/{book_ref}` | Book 详情 + 章节简要列表 | `200` / `304` | 配置了 `API_KEY` 时需要 | `ETag` / `Last-Modified` |
| 4 | GET | `/api/v1/books/{book_ref}/chapters/{chapter_ref}` | 章节详情（json / raw / rendered 三种通道） | `200` / `304` | 配置了 `API_KEY` 时需要 | `ETag` / `Last-Modified` |
| 5 | GET | `/api/v1/books/{book_ref}/export` | 导出整本 Book（json 清单或 zip 包） | `200` | 配置了 `API_KEY` 时需要 | 无 |
| 6 | GET | `/api/v1/search` | 全文检索（分页） | `200` | 配置了 `API_KEY` 时需要 | 无 |
| 7 | GET | `/api/v1/changes` | 增量同步（按 `since` 取变更） | `200` | 配置了 `API_KEY` 时需要 | 无 |

不属于 `/api/v1` 但同属服务对外能力（供探活与自描述）：

| 方法 | 路径 | 说明 | 成功状态码 |
| --- | --- | --- | --- |
| GET | `/healthz` | 进程存活探针，返回 `{"status":"ok","version":"1.0.0"}` | `200` |
| GET | `/readyz` | 数据库可写探针（建临时表并写删一行），不可写时 `503` | `200` / `503` |
| GET | `/docs` | Swagger UI（`API_DOCS_ENABLED` 默认 `true`，关闭后路由不存在） | `200` |
| GET | `/openapi.json` | OpenAPI 3 描述文件（同上，关闭后路由不存在） | `200` |

`/healthz`、`/readyz`、`/docs`、`/openapi.json` 都不在 `/api/v1` 前缀下，因此**不校验** `X-API-Key`、**不受**限流约束。`/healthz` 与 `/readyz` 被排除在 OpenAPI 文档之外（`include_in_schema=False`）。

未声明的路径与不允许的方法都返回 `405`（`/api/v1` 列表端点收到 `POST` 等）或 `404`，错误体 `code` 均为 `http_error`。可通过 `GET /openapi.json` 自行核对全部已注册路径与参数。

## 3. GET /api/v1/site

站点自描述，客户端可据此判断服务端启用了哪些能力。**永远不需要 `X-API-Key`**（中间件豁免名单里写死 `/api/v1/site`），但受限流约束。

### 请求

无 Query 参数、无请求体、无特殊请求头。

### 成功响应 `200` `application/json`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `name` | string | 站点名称，来自环境变量 `SITE_NAME`（默认 `BookHub 知识库`） |
| `version` | string | 应用版本，当前为 `1.0.0`（`app/__init__.py` 的 `__version__`） |
| `capabilities.formats` | string[] | 支持写作的源格式，固定 `["markdown","html"]` |
| `capabilities.rendered` | bool | 是否提供服务端渲染结果（`content_rendered` 与 `?format=rendered`），固定 `true` |
| `capabilities.export` | string[] | 导出格式，固定 `["json","zip"]` |
| `capabilities.incremental` | bool | 是否支持 `/api/v1/changes` 增量同步，固定 `true` |
| `capabilities.search` | bool | 是否支持 `/api/v1/search`，固定 `true` |
| `capabilities.api_key_required` | bool | 是否配置了 `API_KEY`。为 `true` 时除本端点外都要带 `X-API-Key`；同时决定 `visibility=all`、`visibility=unlisted` 是否可用 |
| `api.version` | string | API 版本，固定 `"v1"` |
| `api.docs` | string \| null | `API_DOCS_ENABLED` 为真时是 `{ROOT_PATH}/docs`（默认 `/docs`），否则 `null` |
| `guide` | object \| null | 站点内置的《AI Agent 接入使用指南》：`{slug, title, url, api_url}`；关闭 `BUILTIN_GUIDE_ENABLED` 或该书被改名后为 `null`。**外部工具读它一次就知道「怎么用这个库」** |

```bash
curl -s http://localhost:8000/api/v1/site
```

```json
{
  "name": "BookHub 知识库",
  "version": "1.0.0",
  "capabilities": {
    "formats": ["markdown", "html"],
    "rendered": true,
    "export": ["json", "zip"],
    "incremental": true,
    "search": true,
    "api_key_required": false
  },
  "api": {
    "version": "v1",
    "docs": "/docs"
  },
  "guide": {
    "slug": "ai-agent-guide",
    "title": "AI Agent 接入使用指南",
    "url": "/b/ai-agent-guide",
    "api_url": "/api/v1/books/ai-agent-guide"
  }
}
```

`guide` 指向的是一本**内置 Book**（`is_builtin: true`）：内容讲这个站点的 HTTP API、
MCP 接入与 SKILL 写法。它随系统创建、不可删除，内容可编辑，升级不会覆盖。

### 错误

| 状态码 | code | 触发条件 |
| --- | --- | --- |
| `429` | `rate_limited` | 该 IP 超过 `RATE_LIMIT_PER_MINUTE` |

本端点不会返回 `401`（即使配置了 `API_KEY`）。

## 4. GET /api/v1/books

列出 Book。只返回未软删除的 Book，`chapter_count` 只统计**已发布且未删除**的章节。

### Query 参数

| 名称 | 类型 | 默认值 | 约束 |
| --- | --- | --- | --- |
| `page` | string（按整数解析） | `1` | 必须 `>= 1`，否则 `400 validation_error` |
| `page_size` | string（按整数解析） | `""` → `20` | 裁剪到 `[1, 100]`，非整数 `400 validation_error` |
| `visibility` | string | `""` → `public` | 取值 `public` / `unlisted` / `all`（首尾空白会被 strip）。其他值 → `400 validation_error` |
| `group` | string | `""` | 分组的 slug 或**纯数字 id**（首尾空白会被 strip）。只返回该组下的 Book；分组不存在 → `404 not_found` |

`visibility` 三个分支的差异：

| 取值 | 返回范围 | 额外条件 |
| --- | --- | --- |
| `public`（默认） | 仅 `visibility=public` 的 Book | 无需认证 |
| `unlisted` | 仅 `visibility=unlisted` 的 Book | 要求服务端配置了 `API_KEY`，否则 `400 validation_error`（`visibility=unlisted 仅在配置 API_KEY 后可用`） |
| `all` | `public` + `unlisted` 全部 Book | 要求服务端配置了 `API_KEY`，否则 `400 validation_error`（`visibility=all 仅在配置 API_KEY 后可用`） |

注意判断依据是**服务端是否配置了 `API_KEY`**，而不是请求是否带了 `X-API-Key`。配置了 `API_KEY` 时中间件本身就要求该头，两个条件在实际使用中同时满足。

排序：按自动权重 `weight` 降序 → `created_at` 降序 → `id` 降序。权重由服务端按访问热度与创建时间实时算出（见 [content-model.md](content-model.md) 的 4.1 节），**没有可手工设置的排序字段**。`total` 是该 `visibility` 条件下的全量 Book 数。

`group` 只做过滤，**不改变排序口径**：返回的仍是同一套权重排出来的一串，不会按"组内顺序"重排，也不返回组信息本身（组只在每个 Book 的 `group` 字段里出现）。按组分区展示是网页首页（`/?group=<slug>`）的行为，API 侧等价于"先在组内排好序再取这一组"。

### 成功响应 `200` `application/json`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `items` | object[] | 当前页的 Book 数组，元素结构见下表 |
| `total` | int | 过滤条件下的 Book 总数（不受分页影响） |
| `page` | int | 实际生效的页码（回显） |
| `page_size` | int | 实际生效的每页条数（回显，可能已被裁剪） |

`items[]` 元素（`_book_payload`）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | int | Book 主键 |
| `slug` | string | 唯一短名，可用于 `/api/v1/books/{book_ref}` 的 `book_ref` |
| `title` | string | 标题 |
| `group` | object \| null | 所属**分组**的轻量表示 `{"id","slug","title"}`，只读；`books.group_id` 非空，所以正常不会为 `null`。分组决定首页分区，组内顺序仍按权重 |
| `summary` | string | 摘要，未填写为空串 |
| `icon` | string | 图标标识，未填写为空串 |
| `format` | string | **整本文档类型**：`markdown` 或 `html`；同一 Book 下所有章节的 `format` 恒等于它 |
| `html_view` | string | HTML Book 的阅读方式：`document`（默认，站点 `/<slug>/<chapter>/raw` 原样输出，新标签页打开）或 `inline`（站内净化渲染）；Markdown Book 恒为 `inline` |
| `visibility` | string | `public` 或 `unlisted` |
| `is_builtin` | bool | 是不是系统内置 Book（当前只有《AI Agent 接入使用指南》：不可删除、slug 固定） |
| `weight` | float | 自动排序权重（越大越靠前），保留 2 位小数；只读，由热度与创建时间算出 |
| `view_count` | int | 累计访问次数（不含登录用户的访问） |
| `recent_view_count` | int | 近 7 天访问次数（权重的主要来源） |
| `chapter_count` | int | 已发布章节数 |
| `created_at` | string | 创建时间（ISO-8601 UTC，`Z` 结尾） |
| `updated_at` | string | Book 行更新时间（不随章节改动自动变化） |
| `url` | string | `{ROOT_PATH}/b/{slug}` |
| `api_url` | string | `{ROOT_PATH}/api/v1/books/{slug}` |

列表端点返回的元素**不含** `chapters` 数组，需要章节列表请调 `/api/v1/books/{book_ref}`。

```bash
curl -s "http://localhost:8000/api/v1/books?page=1&page_size=20" \
  -H "X-API-Key: $BOOKHUB_API_KEY"

# 只要「基础设施」这一个分组（slug 或 id 都行，分组不存在返回 404）
curl -s "http://localhost:8000/api/v1/books?group=infra" \
  -H "X-API-Key: $BOOKHUB_API_KEY"
```

```json
{
  "items": [
    {
      "id": 1,
      "slug": "dev-handbook",
      "title": "研发手册",
      "summary": "入职流程与发布规范",
      "icon": "book",
      "visibility": "public",
      "weight": 76.42,
      "view_count": 12,
      "recent_view_count": 4,
      "chapter_count": 2,
      "created_at": "2026-10-20T02:11:05.123456Z",
      "updated_at": "2026-10-21T05:47:12.345678Z",
      "url": "/b/dev-handbook",
      "api_url": "/api/v1/books/dev-handbook"
    },
    {
      "id": 2,
      "slug": "ops-runbook",
      "title": "运维手册",
      "summary": "",
      "icon": "",
      "visibility": "public",
      "weight": 58.11,
      "view_count": 0,
      "recent_view_count": 0,
      "chapter_count": 0,
      "created_at": "2026-10-20T03:00:00Z",
      "updated_at": "2026-10-20T03:00:00Z",
      "url": "/b/ops-runbook",
      "api_url": "/api/v1/books/ops-runbook"
    }
  ],
  "total": 2,
  "page": 1,
  "page_size": 20
}
```

### 错误

| 状态码 | code | 触发条件 | 示例 message |
| --- | --- | --- | --- |
| `400` | `validation_error` | `page` 非整数或小于 1 | `page 必须是大于等于 1 的整数` |
| `400` | `validation_error` | `page_size` 非整数 | `page_size 必须是整数` |
| `400` | `validation_error` | `visibility` 取值非法 | `visibility 取值应为 public、unlisted 或 all` |
| `400` | `validation_error` | `visibility=all/unlisted` 但未配置 `API_KEY` | `visibility=all 仅在配置 API_KEY 后可用` / `visibility=unlisted 仅在配置 API_KEY 后可用` |
| `404` | `not_found` | `group` 指定的分组不存在（`slug` 与 `id` 都查不到） | `分组不存在` |
| `401` | `unauthorized` | 配置了 `API_KEY` 但 `X-API-Key` 缺失或错误 | `缺少或错误的 X-API-Key` |
| `429` | `rate_limited` | 超过每分钟限额 | `请求过于频繁，请稍后重试` |

`visibility=all` 只放宽可见性过滤，**不会**包含已软删除的 Book。

## 5. GET /api/v1/books/{book_ref}

Book 详情：在列表元素的基础上多一个 `chapters` 数组，内容是**已发布章节的简要信息**（不含正文），顺序与 Web 目录页一致（`sort_order` → `created_at` → `id` 升序）。支持 `ETag` / `Last-Modified` 条件请求。

### Path 参数

| 名称 | 类型 | 说明 |
| --- | --- | --- |
| `book_ref` | string | Book 的 `slug`，或**纯数字**的 `id`（`ref.isdigit()` 为真时按 `id` 查，否则按 `slug` 查） |

注意：解析顺序先判数字，所以纯数字的 slug 无法通过本端点访问，只能用 `id`；同时若某个数字 `id` 恰好存在、而调用者本意是作为 slug 使用，会命中 `id` 对应的 Book。

已软删除的 Book 一律 `404`。可见性语义：`visibility=unlisted` 的 Book **在本端点可以被直接读取**（unlisted 只是不出现在列表里，不做访问控制）；真正的访问控制只有 `API_KEY` 与中间件限流。

### 成功响应 `200` `application/json`

响应体 = `items[]` 元素结构与第 4 章完全相同的 Book 字段，额外增加 `chapters`。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` / `slug` / `title` / `group` / `summary` / `icon` / `format` / `visibility` / `weight` / `view_count` / `recent_view_count` | — | 同第 4 章 `_book_payload` |
| `chapter_count` | int | 已发布章节数，等于 `chapters` 数组长度 |
| `created_at` / `updated_at` | string | 同第 4 章 |
| `url` / `api_url` | string | 同第 4 章 |
| `chapters` | object[] | 已发布章节简要数组，结构见下表 |

`chapters[]` 元素（`_chapter_brief`）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | int | 章节主键 |
| `slug` | string | 章节短名 |
| `title` | string | 章节标题 |
| `format` | string | 源格式：`markdown` 或 `html` |
| `status` | string | 在本端点里恒为 `published`（只返回已发布章节） |
| `version` | int | 当前版本号（`current_version_no`） |
| `checksum` | string | 正文 `content_raw` 的 SHA-256 十六进制全串（64 字符） |
| `word_count` | int | 字数（中文按字、英文按词粗略统计） |
| `published_at` | string \| null | 首次发布时间 |
| `updated_at` | string | 章节内容更新时间 |
| `url` | string | `{ROOT_PATH}/b/{book.slug}/{chapter.slug}` |
| `api_url` | string | `{ROOT_PATH}/api/v1/books/{book.slug}/chapters/{chapter.slug}` |

响应头：`ETag` 见第 9 章；`Last-Modified` 取「最新已发布章节的 `updated_at`」，若没有已发布章节则取 `book.updated_at`。

```bash
curl -s http://localhost:8000/api/v1/books/dev-handbook \
  -H "X-API-Key: $BOOKHUB_API_KEY"

# 用 id 访问
curl -s http://localhost:8000/api/v1/books/1 \
  -H "X-API-Key: $BOOKHUB_API_KEY"
```

```json
{
  "id": 1,
  "slug": "dev-handbook",
  "title": "研发手册",
  "summary": "入职流程与发布规范",
  "icon": "book",
  "visibility": "public",
  "weight": 76.42,
  "view_count": 12,
  "recent_view_count": 4,
  "chapter_count": 2,
  "created_at": "2026-10-20T02:11:05.123456Z",
  "updated_at": "2026-10-21T05:47:12.345678Z",
  "url": "/b/dev-handbook",
  "api_url": "/api/v1/books/dev-handbook",
  "chapters": [
    {
      "id": 11,
      "slug": "welcome",
      "title": "欢迎使用",
      "format": "markdown",
      "status": "published",
      "version": 3,
      "checksum": "9f2c1d4e5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d",
      "word_count": 128,
      "published_at": "2026-10-20T02:11:05.123456Z",
      "updated_at": "2026-10-21T05:47:12.345678Z",
      "url": "/b/dev-handbook/welcome",
      "api_url": "/api/v1/books/dev-handbook/chapters/welcome"
    },
    {
      "id": 12,
      "slug": "deploy",
      "title": "部署指南",
      "format": "markdown",
      "status": "published",
      "version": 1,
      "checksum": "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b",
      "word_count": 342,
      "published_at": "2026-10-20T02:20:00Z",
      "updated_at": "2026-10-20T02:20:00Z",
      "url": "/b/dev-handbook/deploy",
      "api_url": "/api/v1/books/dev-handbook/chapters/deploy"
    }
  ]
}
```

### 条件请求 `304`

带 `If-None-Match`（命中）或 `If-Modified-Since`（不早于 `Last-Modified`）时返回 `304`，无响应体，但**仍带 `ETag` 与 `Last-Modified`**。

```bash
curl -s -o /dev/null -D - -H 'If-None-Match: "b1-1792485432"' \
  http://localhost:8000/api/v1/books/dev-handbook \
  -H "X-API-Key: $BOOKHUB_API_KEY"
```

### 错误

| 状态码 | code | 触发条件 | 示例 message |
| --- | --- | --- | --- |
| `404` | `not_found` | `book_ref` 对应的 Book 不存在或已软删除 | `Book 不存在` |
| `401` | `unauthorized` | 配置了 `API_KEY` 但 `X-API-Key` 缺失或错误 | `缺少或错误的 X-API-Key` |
| `429` | `rate_limited` | 超过每分钟限额 | `请求过于频繁，请稍后重试` |

本端点没有 Query 参数，因此不会因参数问题返回 `400`。

## 6. GET /api/v1/books/{book_ref}/chapters/{chapter_ref}

单个章节。同一个 URI 支持三种内容通道：JSON 元信息 + 正文、原始源文 `raw`、服务端渲染结果 `rendered`。只暴露已发布且未删除的章节，草稿、已软删除章节、所属 Book 已软删除的章节一律 `404`。

### Path 参数

| 名称 | 类型 | 说明 |
| --- | --- | --- |
| `book_ref` | string | Book 的 `slug` 或纯数字 `id`（同第 5 章） |
| `chapter_ref` | string | 章节的 `slug`，或纯数字的 `id`。按 `id` 查时会额外校验 `chapter.book_id == book.id`，跨 Book 的 id 不会泄露 |

### Query 参数

| 名称 | 类型 | 默认值 | 约束 |
| --- | --- | --- | --- |
| `format` | string | `""` | 取值 `json` / `raw` / `rendered`（首尾空白去掉、转小写后比较，因此 `RAW`、` raw ` 均可用）。非法值 → `400 validation_error` |

### 通道协商顺序

1. 先做条件请求判断：`ETag` 命中（`If-None-Match`）或 `If-Modified-Since` 满足 → 直接 `304`，**此时不会校验 `format` 的合法性**。
2. 若 `format` 非空，以它为准（显式参数优先于 `Accept`）。
3. 若 `format` 为空，看 `Accept` 请求头（转小写后做子串包含判断，不解析 q 值）：
   - 含 `text/markdown` → `raw`
   - 否则含 `text/html` → `rendered`
   - 都不含 → `json`（默认）

### 三种通道的响应

| `format` | 状态码 | `Content-Type` | 响应体 |
| --- | --- | --- | --- |
| `json`（默认） | `200` | `application/json` | 完整章节 payload（下表） |
| `raw` | `200` | 章节 `format=markdown` → `text/markdown; charset=utf-8`；`format=html` → `text/html; charset=utf-8` | 原文（**不做渲染**）。Markdown 章节返回上传的原始文本；HTML 章节返回**白名单净化后**的 HTML（`content_safe`），脚本、事件属性、iframe/form、`javascript:` 链接都已被剔除 |
| `rendered` | `200` | `text/html; charset=utf-8` | 服务端渲染并净化后的 `content_rendered` |

两种非 JSON 通道都**只返回正文文本**，不带元信息；需要 `version`、`checksum`、`toc` 时请用 `json` 通道。

`json` payload 字段（`_chapter_payload` = `_chapter_brief` + 5 个字段，故字段顺序如此）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | int | 章节主键 |
| `slug` | string | 章节短名 |
| `title` | string | 标题 |
| `format` | string | 源格式 `markdown` / `html` |
| `status` | string | 恒为 `published` |
| `version` | int | 当前版本号 |
| `checksum` | string | `content_raw` 的 SHA-256 全串 |
| `word_count` | int | 字数 |
| `published_at` | string \| null | 首次发布时间 |
| `updated_at` | string | 内容更新时间 |
| `url` | string | `{ROOT_PATH}/b/{book_slug}/{chapter_slug}` |
| `api_url` | string | `{ROOT_PATH}/api/v1/books/{book_slug}/chapters/{chapter_slug}` |
| `book` | object | 所属 Book 的最简信息，仅 `id`、`slug`、`title` 三个键 |
| `content_raw` | string | 原文。Markdown 章节是上传文本；HTML 章节是**净化后**的 HTML（与 `?format=raw` 同一份内容，`content_safe`）。管理员上传的未净化原样只保留在管理端 |
| `content_rendered` | string | 渲染并净化后的 HTML 片段（Markdown 章节为 CommonMark 渲染结果；HTML 章节为净化 + 补锚点后的结果） |
| `toc` | object[] | 标题大纲，元素为 `{"level": int, "text": string, "anchor": string}` |
| `created_at` | string | 章节创建时间（注意：`chapters[]` 简要数组里没有这个字段） |

`toc` 说明：`level` 是标题层级（`h1` → `1`），`text` 是标题纯文本，`anchor` 是注入到 `<h{level} id="...">` 上的锚点 id（同章节内重复标题会做去重后缀）；正文没有标题时为 `[]`。

```bash
# 默认 JSON
curl -s http://localhost:8000/api/v1/books/dev-handbook/chapters/welcome \
  -H "X-API-Key: $BOOKHUB_API_KEY" \
  -H "Accept: application/json"

# 原始 Markdown
curl -s "http://localhost:8000/api/v1/books/dev-handbook/chapters/welcome?format=raw" \
  -H "X-API-Key: $BOOKHUB_API_KEY"

# 用 Accept 协商拿渲染后的 HTML 片段
curl -s http://localhost:8000/api/v1/books/dev-handbook/chapters/welcome \
  -H "X-API-Key: $BOOKHUB_API_KEY" \
  -H "Accept: text/html"
```

```json
{
  "id": 11,
  "slug": "welcome",
  "title": "欢迎使用",
  "format": "markdown",
  "status": "published",
  "version": 3,
  "checksum": "9f2c1d4e5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d",
  "word_count": 128,
  "published_at": "2026-10-20T02:11:05.123456Z",
  "updated_at": "2026-10-21T05:47:12.345678Z",
  "url": "/b/dev-handbook/welcome",
  "api_url": "/api/v1/books/dev-handbook/chapters/welcome",
  "book": {
    "id": 1,
    "slug": "dev-handbook",
    "title": "研发手册"
  },
  "content_raw": "# 欢迎\n\n知识库起步说明\n\n## 约定\n\n- 提交前跑 lint",
  "content_rendered": "<h1 id=\"欢迎\">欢迎</h1>\n<p>知识库起步说明</p>\n<h2 id=\"约定\">约定</h2>\n<ul>\n<li>提交前跑 lint</li>\n</ul>",
  "toc": [
    { "level": 1, "text": "欢迎", "anchor": "欢迎" },
    { "level": 2, "text": "约定", "anchor": "约定" }
  ],
  "created_at": "2026-10-20T02:11:05.123456Z"
}
```

响应头始终包含 `ETag` 与 `Last-Modified`（`304` 也带），构成见第 9 章。

### 错误

| 状态码 | code | 触发条件 | 示例 message |
| --- | --- | --- | --- |
| `404` | `not_found` | Book 不存在或已软删除 | `Book 不存在` |
| `404` | `not_found` | 章节不存在、已软删除、属于其他 Book，或 `status != published`（草稿） | `章节不存在` |
| `400` | `validation_error` | `format` 不是 `json`/`raw`/`rendered` | `format 取值应为 json、raw 或 rendered` |
| `401` | `unauthorized` | 配置了 `API_KEY` 但 `X-API-Key` 缺失或错误 | `缺少或错误的 X-API-Key` |
| `429` | `rate_limited` | 超过每分钟限额 | `请求过于频繁，请稍后重试` |

`chapters/{id}` 形式的 `id` 若属于其他 Book，返回 `404 章节不存在`（不会串 Book）。

## 7. GET /api/v1/books/{book_ref}/export

整本导出，用于离线归档、构建静态站点或迁移。**只包含已发布章节**（草稿与已软删除章节不导出），顺序与目录页一致。

### Path 参数

| 名称 | 类型 | 说明 |
| --- | --- | --- |
| `book_ref` | string | Book 的 `slug` 或纯数字 `id`（同第 5 章） |

### Query 参数

| 名称 | 类型 | 默认值 | 约束 |
| --- | --- | --- | --- |
| `format` | string | `json` | 取值 `json` / `zip`（仅转小写比较，**不做首尾空白裁剪**，`" ZIP"` 会 `400`）。非法值 → `400 validation_error` |

### `format=json`：导出清单

状态码 `200`，`Content-Type: application/json`。清单字段（顺序即字典构造顺序）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `book` | object | 仅 6 个键：`id`、`slug`、`title`、`summary`、`visibility`、`updated_at` |
| `chapter_count` | int | 导出的章节数 |
| `chapters` | object[] | 章节清单数组，结构见下表 |
| `exported_at` | string | 生成本次清单的时间（ISO-8601 UTC，每次请求不同，因此导出响应不适合做缓存比对） |

`chapters[]` 元素：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | int | 章节主键 |
| `slug` | string | 章节短名 |
| `title` | string | 标题 |
| `format` | string | `markdown` / `html` |
| `version` | int | 当前版本号 |
| `checksum` | string | `content_raw` 的 SHA-256 全串 |
| `path` | string | zip 内的文件名：markdown 章节为 `{slug}.md`，html 章节为 `{slug}.html` |
| `api_path` | string | 相对 API 根的路径：`/api/v1/books/{book.slug}/chapters/{chapter.slug}`（**不含** `ROOT_PATH` 前缀，也不同于 payload 里的 `api_url`） |
| `updated_at` | string | 章节更新时间 |

清单里**没有** `icon`、`weight`、`view_count`、`status`、`word_count`、`published_at`、`url`、`api_url`，需要这些字段请用第 5 章或第 6 章。

```bash
curl -s "http://localhost:8000/api/v1/books/dev-handbook/export?format=json" \
  -H "X-API-Key: $BOOKHUB_API_KEY"
```

```json
{
  "book": {
    "id": 1,
    "slug": "dev-handbook",
    "title": "研发手册",
    "summary": "入职流程与发布规范",
    "visibility": "public",
    "updated_at": "2026-10-21T05:47:12.345678Z"
  },
  "chapter_count": 2,
  "chapters": [
    {
      "id": 11,
      "slug": "welcome",
      "title": "欢迎使用",
      "format": "markdown",
      "version": 3,
      "checksum": "9f2c1d4e5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d",
      "path": "welcome.md",
      "api_path": "/api/v1/books/dev-handbook/chapters/welcome",
      "updated_at": "2026-10-21T05:47:12.345678Z"
    },
    {
      "id": 12,
      "slug": "deploy",
      "title": "部署指南",
      "format": "markdown",
      "version": 1,
      "checksum": "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b",
      "path": "deploy.md",
      "api_path": "/api/v1/books/dev-handbook/chapters/deploy",
      "updated_at": "2026-10-20T02:20:00Z"
    }
  ],
  "exported_at": "2026-10-21T06:00:00.987654Z"
}
```

### `format=zip`：压缩包

状态码 `200`，`Content-Type: application/zip`，`Content-Disposition: attachment; filename="{book.slug}.zip"`（例如 `attachment; filename="dev-handbook.zip"`；filenames 直接用 slug 原值，未做转义）。

包内是**扁平结构**，没有子目录：

```
dev-handbook.zip
├── book.json          # 与 format=json 的清单内容相同，indent=2、ensure_ascii=false
├── welcome.md         # 章节 slug + 源格式对应后缀，内容是 content_safe 原文
└── deploy.md
```

- 文件后缀由章节 `format` 决定：`markdown` → `.md`，`html` → `.html`。
- 文件内容就是 `content_safe`（Markdown 为原文，HTML 为净化后的 HTML），不写入渲染结果；渲染请用 `?format=rendered` 或自行渲染。
- 文件名会再做一次白名单过滤（只保留字母数字与 `._-`），避免异常 slug 造成 zip slip。
- 没有任何已发布章节时，压缩包里只有 `book.json`（`chapter_count` 为 `0`）。
- 压缩方式为 `ZIP_DEFLATED`。

```bash
curl -s -OJ "http://localhost:8000/api/v1/books/dev-handbook/export?format=zip" \
  -H "X-API-Key: $BOOKHUB_API_KEY"
```

### 错误

| 状态码 | code | 触发条件 | 示例 message |
| --- | --- | --- | --- |
| `404` | `not_found` | Book 不存在或已软删除 | `Book 不存在` |
| `400` | `validation_error` | `format` 不是 `json` / `zip` | `format 取值应为 json 或 zip` |
| `401` | `unauthorized` | 配置了 `API_KEY` 但 `X-API-Key` 缺失或错误 | `缺少或错误的 X-API-Key` |
| `429` | `rate_limited` | 超过每分钟限额 | `请求过于频繁，请稍后重试` |

本端点**不支持** `ETag`/`304`，也不分页：整本一次性返回，超大 Book 请自行评估流量。

## 8. GET /api/v1/search

全文检索。只检索**公开 Book** 下的**已发布、未删除**章节：SQL 过滤条件固定为 `c.status='published'`、`c.deleted_at IS NULL`、`b.deleted_at IS NULL`、`b.visibility='public'`。因此 unlisted Book 里的内容永远不会出现在检索结果里（即使 `API_KEY` 已配置）。

### Query 参数

| 名称 | 类型 | 默认值 | 约束 |
| --- | --- | --- | --- |
| `q` | string | `""` | 首尾空白会被去掉后再计算长度，长度 > `500` → `400 validation_error`。空串合法，返回空结果 |
| `page` | string（按整数解析） | `1` | 必须 `>= 1`，否则 `400` |
| `page_size` | string（按整数解析） | `""` → `20` | 裁剪到 `[1, 100]` |
| `book` | string | `""` | 限定到某个 Book，可传 `slug` 或纯数字 `id`（首尾空白去掉）。**该 Book 不存在时不报 404，而是返回空 `items`** |

`book` 存在但不可检索（unlisted Book、或该 Book 下没有命中）时同样返回 `200` + 空 `items`。

### 检索召回策略

- Markdown/HTML 章节会被渲染成纯文本后建立索引（SQLite 用 FTS5 虚拟表 `chapter_fts`）。
- 中文按**二元组（bigram）**切分，单字成词时保留单字；ASCII 按词切分并转小写，允许 `+ # . - _` 等字符出现在词中。
- 多个词按 **AND** 组合（`"词1" AND "词2"`），去重后最多使用 **24 个** token，超出的 token 被静默忽略。
- 排序：FTS5 分支按相关度（`f.rank`）排序；降级分支按 `updated_at` 倒序。
- 降级到 `LIKE` 分支的两种情况：数据库不是 SQLite（例如 Postgres），或查询词是**单个中文字符**（`needs_like_fallback`）。降级分支对 `title` 与 `content_raw` 做 `%q%` 匹配，并会去掉查询词里的 `%` 与 `_`。
- 索引由写入侧维护（新建/替换内容/删除章节时同步）；历史数据可用运维脚本重建索引。索引缺失会导致 FTS 分支漏召回，排查时可用 `LIKE` 分支（单个中文字符查询）横向对比。

### 成功响应 `200` `application/json`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `items` | object[] | 命中条目 |
| `total` | int | 命中总数（不受分页影响） |
| `page` | int | 实际生效页码 |
| `page_size` | int | 实际生效每页条数 |
| `query` | string | 实际使用的查询词（已 strip）。用于区分「空查询」与「有查询但无结果」 |

`items[]` 元素（注意：检索结果**没有** `api_url`、`format`、`version`、`word_count`）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `book` | object | 仅 `id`、`slug`、`title` |
| `chapter` | object | 仅 `id`、`slug`、`title` |
| `url` | string | `{ROOT_PATH}/b/{book_slug}/{chapter_slug}` |
| `snippet` | string | 命中片段，HTML 片段：命中词被 `<mark>` 包裹，其余内容已 HTML 转义，首尾可能带 `…` |
| `updated_at` | string | 章节更新时间 |

`snippet` 已经是可安全插入页面的 HTML，前端渲染时**不要再次转义**（否则 `<mark>` 会变成字面量），也不要直接塞进属性值。片段截取半径为命中位置前后各 90 个字符（`SNIPPET_RADIUS=90`）。

```bash
curl -s "http://localhost:8000/api/v1/search?q=部署&page=1&page_size=20" \
  -H "X-API-Key: $BOOKHUB_API_KEY"

# 限定 Book + 限定页码
curl -s "http://localhost:8000/api/v1/search?q=%E9%83%A8%E7%BD%B2&book=dev-handbook&page_size=5" \
  -H "X-API-Key: $BOOKHUB_API_KEY"
```

```json
{
  "items": [
    {
      "book": {
        "id": 1,
        "slug": "dev-handbook",
        "title": "研发手册"
      },
      "chapter": {
        "id": 12,
        "slug": "deploy",
        "title": "部署指南"
      },
      "url": "/b/dev-handbook/deploy",
      "snippet": "<h1 id=\"部署\">部署</h1> <p>用 docker <mark>部署</mark>服务，前需先配置 SECRET_KEY…</p>",
      "updated_at": "2026-10-20T02:20:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "query": "部署"
}
```

### 错误

| 状态码 | code | 触发条件 | 示例 message |
| --- | --- | --- | --- |
| `400` | `validation_error` | 查询词超过 500 字符 | `查询词不能超过 500 个字符` |
| `400` | `validation_error` | `page` 非整数或 `< 1` | `page 必须是大于等于 1 的整数` |
| `400` | `validation_error` | `page_size` 非整数 | `page_size 必须是整数` |
| `401` | `unauthorized` | 配置了 `API_KEY` 但 `X-API-Key` 缺失或错误 | `缺少或错误的 X-API-Key` |
| `429` | `rate_limited` | 超过每分钟限额 | `请求过于频繁，请稍后重试` |

`book` 参数不会产生 `404`；`q` 为空也不会报错，只是 `items=[]`、`total=0`。

## 9. GET /api/v1/changes

增量同步端点：返回**修改时间严格大于** `since` 的**节**（`chapter_sections`），按 `updated_at` 升序，用于客户端做镜像/缓存更新。响应包含墓碑（删除）信息。

### Query 参数

| 名称 | 类型 | 默认值 | 约束 |
| --- | --- | --- | --- |
| `since` | string | `""` | **必填**（ISO-8601 时间）。缺失/空 → `400 validation_error`；无法解析 → `400 validation_error` |

`since` 的解析细节：

1. 先做 `raw.replace("Z", "+00:00")`，然后 `datetime.fromisoformat()`。因此推荐写法是 `2026-10-20T00:00:00Z`（带 `Z`）或 `2026-10-20T08:00:00+08:00`（带偏移），也接受不带时区的 `2026-10-20T00:00:00`。
2. 带时区（含 `+00:00`、`+08:00`）时统一换算成 UTC 后再比较。
3. **不带时区时被直接当作 UTC**，不会按服务器本地时区解释。传本地时间不加偏移会偏移 8 小时（东八区）。
4. 比较是**严格大于** `>`：`updated_at == since` 的章节不会返回。
5. `since` 的支持精度到微秒，库里按微秒存储。

### 成功响应 `200` `application/json`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `since` | string | 回显规范化后的 `since`（UTC、`Z` 结尾）。客户端做记录时用请求值，不要用这个字段做下次游标 |
| `server_time` | string | 生成本次响应时的服务端 UTC 时间，**作为下一次请求的 `since`** |
| `sections` | object[] | 变更条目（节级），按 `updated_at` 升序 |
| `count` | int | `sections` 的长度 |

`sections[]` 元素（注意键名与其它端点不同：这里用扁平的 `book_id`/`book_slug`，没有嵌套 `book` 对象，也没有 `url`/`api_url`）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | int | 节主键 |
| `book_id` | int | 所属 Book id |
| `book_slug` | string | 所属 Book slug |
| `chapter_id` | int | 所属章 id |
| `chapter_slug` | string | 所属章 slug |
| `slug` | string | 节 slug |
| `title` | string | 节标题。**墓碑条目没有该字段** |
| `chapter_title` | string | 章标题。**墓碑条目没有该字段** |
| `format` | string | `markdown` 或 `html`（等于所属 Book 的类型） |
| `version` | int | 该节的当前版本号 |
| `updated_at` | string | 节内容更新时间 |
| `deleted` | bool | 墓碑标记：节自身已软删除，**或**其所属章/Book 已软删除 |
| `published` | bool | 当前是否可读：所属章已发布且节未删 |

墓碑语义（重要）：

- `deleted=true`：该节在服务端已不可读（含「章被删」「Book 被删」连带下架的情况）。客户端应从本地镜像中移除或标记失效。**墓碑只回 `id` / slug / 时间戳，不再返回 `title` 与 `chapter_title`**——避免增量流变成泄露未发布标题的旁路。
- `deleted=false && published=false`：节所在章被**取消发布**（退回草稿），服务端对外也不可读。客户端同样应当移除，但可以据此区分「草稿」与「删除」。
- `deleted=false && published=true`：正常可读内容，客户端按 `book_slug`+`chapter_slug`+`slug` upsert，然后按需拉正文。
- 没有任何已删除标记的「物理删除」不会出现：本服务的删除都是软删除（`deleted_at`），因此墓碑一定能在 `/api/v1/changes` 里被观测到。

```bash
curl -s "http://localhost:8000/api/v1/changes?since=2026-10-20T00:00:00Z" \
  -H "X-API-Key: $BOOKHUB_API_KEY"
```

```json
{
  "since": "2026-10-20T00:00:00Z",
  "server_time": "2026-10-21T06:12:30.456789Z",
  "sections": [
    {
      "id": 11,
      "book_id": 1,
      "book_slug": "dev-handbook",
      "chapter_id": 3,
      "chapter_slug": "welcome",
      "slug": "main",
      "chapter_title": "欢迎使用",
      "title": "欢迎使用",
      "format": "markdown",
      "version": 3,
      "updated_at": "2026-10-21T05:47:12.345678Z",
      "deleted": false,
      "published": true
    },
    {
      "id": 12,
      "book_id": 1,
      "book_slug": "dev-handbook",
      "chapter_id": 4,
      "chapter_slug": "deploy",
      "slug": "main",
      "format": "markdown",
      "version": 4,
      "updated_at": "2026-10-21T05:50:00Z",
      "deleted": true,
      "published": false
    }
  ],
  "count": 2
}
```

> 第二条是墓碑：`deleted: true` 的条目不返回 `title` 与 `chapter_title`，只回定位字段与时间戳。

### 增量同步算法

```
cursor = 客户端持久化的 since（首次同步用 "1970-01-01T00:00:00Z" 或建库时间）
loop:
    resp = GET /api/v1/changes?since={cursor}
    对 resp.sections 逐条处理：
        if entry.deleted or not entry.published:
            本地镜像删除 entry.book_slug/entry.chapter_slug/entry.slug（按 entry.id 去重）
        else:
            if 本地已有 entry.id 且 entry.version 未变 且 entry.updated_at 未变：
                跳过（幂等）
            else:
                拉正文：GET /api/v1/books/{book_slug}/chapters/{chapter_slug}?section={slug}
                        （需要原始源文用 ?format=raw，需要 HTML 用 ?format=rendered）
                upsert 到本地镜像
    if resp.count == 0: sleep(同步间隔)，然后 continue
    cursor = resp.server_time          # 关键：用 server_time，不要用 since + count 推算
    if resp.count < 批量阈值: 可提前结束本轮，等待下一次调度
```

要点：

- **下次的 `since` 必须是本次响应的 `server_time`**。用请求时的 `since` 或本地时间都会漏数据（服务端时间与客户端时钟不保证一致）。
- 比较是严格 `>`，所以用 `server_time` 作为下次游标不会重复返回同一条（除非该条在两次请求之间又被改动）。`server_time` 在查询**之前**取，因此不会漏掉查询与响应之间的更新。
- 保守做法：把 `cursor` 往前回退 1 秒（或用上一次的 `server_time` 再拉一遍并做幂等去重），可覆盖时钟回拨等极端情况；去重条件是 `id + version + updated_at`。
- 首次全量：先用 `/api/v1/books` 翻页拿 Book 列表，再逐本 `/api/v1/books/{book_ref}/export?format=json` 或按章节拉取；之后只用 `/api/v1/changes` 做增量。
- 本端点**不分页、没有 `limit`**，一次返回窗口内全部变更。长时间未同步后首次调用可能返回很大响应，建议按天切分 `since` 逐步推进。
- 只返回 `public` Book 下的条目；从未发布过的草稿不出现；已发布后被删除或撤回的节以 `deleted: true` 的墓碑出现（墓碑不带标题），客户端据此清理本地副本。

### 错误

| 状态码 | code | 触发条件 | 示例 message |
| --- | --- | --- | --- |
| `400` | `validation_error` | 缺少 `since`（未传或空串） | `缺少 since 参数（ISO-8601 时间）` |
| `400` | `validation_error` | `since` 无法解析 | `since 不是合法的 ISO-8601 时间` |
| `401` | `unauthorized` | 配置了 `API_KEY` 但 `X-API-Key` 缺失或错误 | `缺少或错误的 X-API-Key` |
| `429` | `rate_limited` | 超过每分钟限额 | `请求过于频繁，请稍后重试` |

`since` 不带时区不会报错，但会被当作 UTC；这是最常见的同步误差来源。轮询频率请留余量，默认限额是每 IP 每分钟 120 次。

## 10. ETag 与条件请求

只有两个端点支持条件请求：`GET /api/v1/books/{book_ref}` 与 `GET /api/v1/books/{book_ref}/chapters/{chapter_ref}`。其余端点（列表、导出、检索、changes）**不返回** `ETag`。

### 10.1 ETag 的构成

| 端点 | 构成 | 示例 | 变化条件 |
| --- | --- | --- | --- |
| 章节详情 | `"{id}-{current_version_no}-{checksum 前 8 位}"` | `"11-3-9f2c1d4e"` | 内容被替换（版本号 +1、checksum 变化）时变化。仅发布/取消发布状态变化不会改变它（但取消发布后端点变 `404`） |
| Book 详情 | `"b{id}-{int(stamp.timestamp())}"`，`stamp` = 最新已发布章节的 `updated_at`，没有已发布章节时用 `book.updated_at` | `"b1-1792485432"` | 任一已发布章节更新，或 Book 行自身 `updated_at` 变化（改标题/摘要/图标/可见性、软删除）时变化。`weight` 与访问计数会变，但它们**不参与** ETag：热度变化不会让缓存失效 |

两个 ETag 都是**强 ETag**（带双引号，无 `W/` 前缀）。`checksum` 用的是 `content_raw` 的 SHA-256，取前 8 位十六进制。

注意：Book 的 ETag 由「秒级时间戳」参与构成，同一秒内的两次修改可能产生相同 ETag；需要精确判断内容是否变化请用章节级 `version` + `checksum`。

### 10.2 `If-None-Match` 与 `If-Modified-Since` 的优先级

服务端只实现了一条最简单的判断链（`_conditional`）：

1. **请求带了 `If-None-Match`**：按逗号拆分成候选集合，每段 `strip()`、去掉可选的弱校验前缀 `W/` 后与当前 ETag 做字符串比较；`*` 视为命中。
   - 命中 → `304`；
   - 未命中 → 直接按 `200` 返回完整内容，**不再检查 `If-Modified-Since`**（即 `If-None-Match` 存在时它完全覆盖 `If-Modified-Since`）。
2. **没带 `If-None-Match`，带了 `If-Modified-Since`**：用 `parsedate_to_datetime` 解析 HTTP-date；解析失败时忽略该头（当作普通请求，返回 `200`）；不带时区时按 UTC 处理；比较前把 `updated_at` 的微秒截掉（`Last-Modified` 只有秒级精度），当 `last_modified <= since` 时返回 `304`。
3. 两者都没带 → 正常 `200`。

`If-None-Match` 支持多值与通配：

```bash
# 多值（命中第二个）
curl -s -o /dev/null -w '%{http_code}\n' \
  -H 'If-None-Match: "11-2-aaaa1111", "11-3-9f2c1d4e"' \
  http://localhost:8000/api/v1/books/dev-handbook/chapters/welcome \
  -H "X-API-Key: $BOOKHUB_API_KEY"

# 通配，任何资源都视为命中
curl -s -o /dev/null -w '%{http_code}\n' \
  -H 'If-None-Match: *' \
  http://localhost:8000/api/v1/books/dev-handbook \
  -H "X-API-Key: $BOOKHUB_API_KEY"
```

比较接受弱校验前缀：`W/"11-3-9f2c1d4e"` 会去掉 `W/` 后与强 ETag 比较并命中（RFC 7232 的弱比较语义）；回传服务端给的 `ETag` 原值最省事。

`If-Modified-Since` 的行为：`Last-Modified` 按秒输出（`format_datetime(..., usegmt=True)`，微秒被截断），服务端在比较前同样把 `updated_at` 截到秒，因此**把响应里的 `Last-Modified` 原样回传会得到 `304`**。仍然建议优先用 `If-None-Match`：秒级精度在同一秒内多次修改时会显得"没变"。

### 10.3 `304` 响应的形态

- 状态码 `304`，**响应体为空**（`Content-Length: 0`），不返回 `Content-Type`。
- 仍然带 `ETag` 与 `Last-Modified`，客户端可继续用这两个值做下次校验。
- 仍然带中间件补的 `X-Request-ID`。
- 仍然计一次限流配额（限流在路由之前执行）。
- 章节详情里 `304` 的判断在 `format` 参数校验**之前**：`?format=bogus` 若 ETag 命中会得到 `304` 而不是 `400`。

```bash
# 先取 ETag，再用它做条件请求
ETAG=$(curl -s -D - -o /dev/null http://localhost:8000/api/v1/books/dev-handbook/chapters/welcome \
  -H "X-API-Key: $BOOKHUB_API_KEY" | tr -d '\r' | awk -F': ' 'tolower($1)=="etag"{print $2}')
curl -s -i -H "If-None-Match: $ETAG" \
  http://localhost:8000/api/v1/books/dev-handbook/chapters/welcome \
  -H "X-API-Key: $BOOKHUB_API_KEY"
```

PowerShell 等价写法（注意 `curl` 在 Windows PowerShell 里是 `Invoke-WebRequest` 的别名，条件请求请显式用 `curl.exe`）：

```powershell
$h = @{ "X-API-Key" = $env:BOOKHUB_API_KEY }
$etag = (Invoke-WebRequest -Uri "http://localhost:8000/api/v1/books/dev-handbook/chapters/welcome" -Headers $h).Headers.ETag
curl.exe -s -i -H "If-None-Match: $etag" -H "X-API-Key: $env:BOOKHUB_API_KEY" `
  "http://localhost:8000/api/v1/books/dev-handbook/chapters/welcome"
```

## 11. 认证与限额

### 11.1 API Key

| 环境变量 | 是否必填 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `API_KEY` | 否 | 未设置（None） | 设置后启用 API Key 校验。值会 strip，空串等同未设置 |
| `SECRET_KEY` | **是** | 无（缺失启动即失败） | 应用签名密钥，至少 16 字符。API 调用不需要它，但没有它服务起不来 |

开启校验后的行为（`ApiKeyMiddleware`）：

- 作用范围：路径以 `/api/v1` 开头的所有请求。
- 豁免：仅 `/api/v1/site`（实现里是精确匹配 `/api/v1/site`，注意没有尾斜杠；`/api/v1/site/` 不在豁免名单里，配置了 `API_KEY` 时会被要求带 key 而返回 `401`；未配置 `API_KEY` 时带尾斜杠会被 307 重定向到 `/api/v1/site`）。
- 校验方式：请求头 `X-API-Key` 非空且与 `API_KEY` 常量时间相等（`safe_compare`）。
- 失败响应：`401`，响应体 `{"error":{"code":"unauthorized","message":"缺少或错误的 X-API-Key","request_id":"..."}}`。不返回 `WWW-Authenticate` 头。
- 副作用：`API_KEY` 是否配置还决定了 `GET /api/v1/books?visibility=unlisted|all` 是否可用（见第 4 章），以及 `/api/v1/site` 里 `capabilities.api_key_required` 的取值。

```bash
curl -s -i http://localhost:8000/api/v1/books            # 缺 key → 401
curl -s -i http://localhost:8000/api/v1/books -H "X-API-Key: wrong"   # 错 key → 401
curl -s -i http://localhost:8000/api/v1/books -H "X-API-Key: $BOOKHUB_API_KEY"  # 200
curl -s -i http://localhost:8000/api/v1/site             # 无论是否配置 key 都是 200
```

`/healthz`、`/readyz`、`/docs`、`/openapi.json` 不在 `/api/v1` 下，不受 API Key 约束。反过来说：**只要服务暴露在网络上且未配置 `API_KEY`，任何人都能读全部公开内容**（`/api/v1/changes` 只暴露 `public` Book，草稿与 unlisted 内容不会出现）。

### 11.2 限流

| 环境变量 | 是否必填 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `RATE_LIMIT_ENABLED` | 否 | `true` | 是否对 `/api/v1` 限流，接受 `true/false/1/0/yes/no/on/off`（空串视为 false）；非法值启动失败 |
| `RATE_LIMIT_PER_MINUTE` | 否 | `120` | 每 IP 每 60 秒窗口内的最大请求数（最小 1，否则启动失败） |

实现要点（`RateLimitMiddleware` + `app/services/ratelimit.py`）：

- 进程内滑动窗口（`deque` + 单调时钟），窗口固定 60 秒，不存在跨进程共享；多 worker 部署（`WEB_CONCURRENCY > 1`）时每个 worker 独立计数，实际配额约为「配置值 × worker 数」。
- 作用范围：路径以 `/api/v1` 开头，**包含** `/api/v1/site` 与 `304` 条件请求。
- 执行顺序在 API Key 校验之前，所以超限时即使没带 key 也先收到 `429`。
- 超限响应：`429`，响应头 `Retry-After: <秒>`（最小 1），响应体：

```json
{
  "error": {
    "code": "rate_limited",
    "message": "请求过于频繁，请稍后重试",
    "request_id": "9f1c2b3d4e5f6071"
  }
}
```

### 11.3 来源 IP 判定

限流键是 `api:{client_ip}`，`client_ip()` 的取值顺序：

1. `X-Forwarded-For` 的第一段（逗号分隔取最左，strip）；
2. 否则 `X-Real-IP`（strip）；
3. 否则 TCP 对端地址（拿不到时为 `-`，此时所有无来源的请求共用一个桶）。

这意味着：如果服务前面没有可信代理来覆盖/清洗 `X-Forwarded-For`，**客户端可以随便伪造该头来绕过限流**。部署时请让反向代理强制重写这两个头，或只在受信网络内暴露服务。

### 11.4 认证/限额相关的最小配置示例

```bash
export SECRET_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"
export API_KEY="$(python -c 'import secrets;print(secrets.token_hex(24))')"
export RATE_LIMIT_ENABLED=true
export RATE_LIMIT_PER_MINUTE=120
export SITE_NAME="BookHub 知识库"
export ROOT_PATH=""          # 挂在子路径时改成 /docs 之类
export API_DOCS_ENABLED=true
export CORS_ORIGINS="https://wiki.example.com"
python -m uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
```

Windows PowerShell 等价写法：

```powershell
$env:SECRET_KEY = python -c "import secrets;print(secrets.token_urlsafe(48))"
$env:API_KEY = python -c "import secrets;print(secrets.token_hex(24))"
$env:BOOKHUB_API_KEY = $env:API_KEY
python -m uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
```

## 12. 错误码表

### 12.1 统一错误体

`/api/` 开头的路径（以及 `/healthz`、`/readyz`）在出错时返回 JSON，结构固定为：

```json
{
  "error": {
    "code": "not_found",
    "message": "Book 不存在",
    "request_id": "9f1c2b3d4e5f6071"
  }
}
```

- `code` 是机器可读的错误类别，客户端应基于它分支，不要匹配 `message` 文本（`message` 是中文人类可读信息，可能随版本调整）。
- `message` 是当前实现里的具体文案。
- `request_id` 与响应头 `X-Request-ID` 一致，报障时请提供。
- `/api/` 以外的路径（Web 页面）出错时返回 HTML 错误页而不是 JSON。

### 12.2 `code` 与状态码对照（来自 `app/errors.py`）

| code | 状态码 | 异常类 | `/api/v1` 是否会出现 | 说明 |
| --- | --- | --- | --- | --- |
| `bad_request` | `400` | `AppError` | 否（基类默认值） | 通用 400，v1 只读端点没有直接抛它 |
| `validation_error` | `400` | `ValidationFailed` | **是** | 参数非法：`page`/`page_size` 非整数或越界、`visibility` 非法、`format` 非法、`q` 超长、`since` 缺失或无法解析 |
| `not_found` | `404` | `NotFound` | **是** | Book/章节不存在、已软删除、章节未发布、`book_ref`/`chapter_ref` 不匹配 |
| `conflict` | `409` | `Conflict` | 否 | 写入路径的乐观锁冲突（`base_version` 不匹配），只读 API 不涉及 |
| `unauthorized` | `401` | `Unauthorized` / `ApiKeyMiddleware` | **是** | `X-API-Key` 缺失或错误（中间件直接返回，不是异常处理器） |
| `forbidden` | `403` | `Forbidden` | 否 | Web 端权限不足 |
| `file_too_large` | `413` | `PayloadTooLarge` | 否 | 上传文件超限（`MAX_UPLOAD_BYTES`），只读 API 无上传 |
| `content_too_long` | `422` | `ContentTooLong` | 否 | 正文超限（`MAX_CONTENT_CHARS`），只读 API 不写入 |
| `rate_limited` | `429` | `RateLimited` / `RateLimitMiddleware` | **是** | 超过 `RATE_LIMIT_PER_MINUTE`，带 `Retry-After` |
| `http_error` | 随原始异常 | `StarletteHTTPException` | **是** | 路由层 HTTP 异常，v1 实测为 `404`（未知路径）与 `405`（方法不允许）。**没有** `bad_request` 之外的额外 code |

补充说明：

- `405` 一定带 `http_error`。`GET` 端点不支持 `HEAD`（FastAPI 只注册声明的方法），所以 `curl -I` 或 `Invoke-WebRequest -Method Head` 打到 `/api/v1/books` 会得到 `405`。需要探测可用性请用 `GET` 或 `/healthz`。
- `422` 在本服务里**不表示** FastAPI 的参数校验失败：`/api/v1` 的所有 Query 参数都声明为字符串（`str`），非法内容由业务代码转成 `400 validation_error`。因此 `422` 只会是 `content_too_long`（写入路径），v1 看不到。
- `500`：未捕获的异常没有专门处理器，返回 Starlette 默认的纯文本 `Internal Server Error`，**不是**上面的 JSON 结构。客户端对 `5xx` 请按非 JSON 响应处理。
- 错误响应也带 `X-Request-ID` 头；`429` 额外带 `Retry-After`；`304` 不是错误，不带错误体。

### 12.3 各端点的错误组合速查

| 端点 | `400 validation_error` 条件 | `404 not_found` 条件 |
| --- | --- | --- |
| `/api/v1/site` | — | — |
| `/api/v1/books` | `page` / `page_size` 非法；`visibility` 非法或需要 `API_KEY` 而未配置 | — |
| `/api/v1/books/{book_ref}` | — | `book_ref` 不存在或已软删除 |
| `/api/v1/books/{book_ref}/chapters/{chapter_ref}` | `format` 不是 `json`/`raw`/`rendered`（ETag 命中时为 `304`，不校验） | Book 不存在；章节不存在/已删除/未发布/不属于该 Book |
| `/api/v1/books/{book_ref}/export` | `format` 不是 `json`/`zip` | Book 不存在或已软删除 |
| `/api/v1/search` | `q` 超 500 字符；`page`/`page_size` 非法 | —（`book` 不存在返回空结果） |
| `/api/v1/changes` | `since` 缺失或不是合法 ISO-8601 | — |

所有端点都可能返回 `401 unauthorized`（配置了 `API_KEY` 时，`/api/v1/site` 除外）与 `429 rate_limited`（开启限流时）。

## 13. 客户端接入提示

### 13.1 与 API 相关的环境变量（均在 `Settings.from_env` 中读取）

| 环境变量 | 默认值 | 对 API 的影响 |
| --- | --- | --- |
| `SECRET_KEY` | 无（必填，≥16 字符） | 不参与 API 鉴权，但缺失时进程启动失败，API 不可用 |
| `API_KEY` | 未设置 | 设置后 `/api/v1` 除 `/api/v1/site` 外都要 `X-API-Key`；同时解锁 `visibility=unlisted/all` |
| `RATE_LIMIT_ENABLED` | `true` | 是否对 `/api/v1` 限流 |
| `RATE_LIMIT_PER_MINUTE` | `120` | 每 IP 每分钟额度 |
| `SITE_NAME` | `BookHub 知识库` | `/api/v1/site` 的 `name` |
| `ROOT_PATH` | 空 | 拼在请求路径前；并成为 payload 里 `url`/`api_url`/`api.docs` 的前缀 |
| `API_DOCS_ENABLED` | `true` | 关闭后 `/docs` 与 `/openapi.json` 返回 `404`，`/api/v1/site` 的 `api.docs` 为 `null` |
| `CORS_ORIGINS` | `*` | 逗号分隔的 origin 白名单（`*` 时允许所有源） |

`DATABASE_URL`、`DATA_DIR`、`MAX_UPLOAD_BYTES`、`MAX_CONTENT_CHARS`、`VERSION_RETENTION`、`SESSION_COOKIE_NAME`、`SESSION_MAX_AGE`、`COOKIE_SECURE`、`BOOKHUB_INITIAL_ADMIN_USER`、`BOOKHUB_INITIAL_ADMIN_PASSWORD`、`LOGIN_FAIL_LIMIT`、`LOGIN_FAIL_WINDOW`、`LOG_LEVEL`、`SEED_DEMO`、`WEB_CONCURRENCY` 等配置只影响写入侧、Web 会话与运维行为，不改变本文档描述的只读 API 契约（`WEB_CONCURRENCY` 会按第 11 章影响限流的实际配额）。

### 13.2 PowerShell 下的 curl

在 Windows PowerShell 里 `curl` 是 `Invoke-WebRequest` 的别名，**不接受** `-s`、`-o`、`-H 'If-None-Match: ...'` 这类 curl 参数组合，直接用会报参数错误。两种办法：

1. 显式调用 `curl.exe`（推荐，本文所有示例都可直接改用 `curl.exe`）：

```powershell
$env:BOOKHUB_API_KEY = "your-api-key"
curl.exe -s "http://localhost:8000/api/v1/books?page=1&page_size=20" `
  -H "X-API-Key: $env:BOOKHUB_API_KEY"
```

2. 用原生 cmdlet：

```powershell
$h = @{ "X-API-Key" = $env:BOOKHUB_API_KEY; "Accept" = "application/json" }
$books = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/books?page=1&page_size=20" -Headers $h
$books.items | Format-Table slug, title, chapter_count
```

注意事项：

- `Invoke-RestMethod` 会自动解析 JSON 并丢弃响应头；需要读 `ETag` / `Retry-After` 时改用 `Invoke-WebRequest` 的 `.Headers`。
- `Invoke-RestMethod` 遇到 `404`/`429` 等会抛异常（`HttpResponseException`），异常对象的 `Response.StatusCode` 与 `Response.Content` 里有错误体；也可以直接用 `-SkipHttpErrorCheck`（PowerShell 7+）。
- 中文查询词建议直接写在 URI 上让 `Invoke-RestMethod` 自行转义；拼进 URL 的 `q` 一定要 URL 编码（`[uri]::EscapeDataString("部署")`）。
- PowerShell 5.1 默认按 GBK/ANSI 处理管道输出，含中文的响应在控制台可能显示成乱码，用 `curl.exe -s ... | Out-File -Encoding utf8 out.json` 落地后再查看更稳。
- 条件请求不要用 `-Method Head`（服务端没有 `HEAD` 路由，会得到 `405`），用 `GET` 读 `.Headers.ETag`。

### 13.3 接入检查清单

1. `GET /api/v1/site` 确认 `version` 与 `capabilities.api_key_required`，据此决定是否带 `X-API-Key`。
2. 需要目录时用 `GET /api/v1/books` 翻页（`page_size` 最大 100，响应里的 `page_size` 是真实值）。
3. 需要正文时用 `GET /api/v1/books/{book_ref}/chapters/{chapter_ref}`，优先 `json`（拿 `version`/`checksum`/`toc`），需要落地 Markdown 时用 `?format=raw`。
4. 需要缓存时用 `If-None-Match` + 响应 `ETag`，不要依赖 `If-Modified-Since`（见 10.2 的微秒截断问题）。
5. 需要镜像时用 `GET /api/v1/changes?since=...`，并把响应里的 `server_time` 存成下次的 `since`，按 `id + version + updated_at` 去重。
6. 对 `429` 按 `Retry-After` 退避；对 `5xx` 按非 JSON 响应做降级。
7. payload 里的 `url` / `api_url` 是相对路径，拼接站点 origin 后再使用。
