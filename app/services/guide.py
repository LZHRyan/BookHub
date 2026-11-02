"""内置《AI Agent 接入使用指南》：内容与幂等创建。

这本书回答三个问题，也是它自己的三章：

1. 这个知识库的 HTTP API 怎么调（读写闭环、作用域、限制）；
2. 怎么把它接成 MCP 工具（配置 + 一份可直接跑的最小服务器代码）；
3. 怎么把「怎么用知识库」固化成 SKILL（模板与写作规则）。

内容以 Markdown 常量写在代码里，启动时创建一次；之后**以站内编辑为准**，不会被
覆盖。整本不可删除、slug 与文档类型锁定（见 `app/services/builtin.py`）。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    FORMAT_MARKDOWN,
    STATUS_PUBLISHED,
    VISIBILITY_PUBLIC,
    Book,
    Chapter,
    ChapterSection,
)
from app.services import builtin
from app.services import chapters as chapters_service
from app.services import sections as sections_service
from app.services.books import create_book

_WHAT_IS_THIS = """# 这本书是什么

这是一份**给 AI Agent（以及替它配置环境的人）看的说明书**：这个知识库里有什么、
怎么读、怎么写、怎么接成 MCP 工具、怎么包成一个可复用的 SKILL。

它由系统内置，随系统生命周期存在：**整本不能删除**，访问标识固定为
`ai-agent-guide`。内容可以照常编辑（改正文、加节、调整顺序），但删除章/节会被拒绝。

## 30 秒版

下文用 `$HUB` 表示站点地址，例如 `http://localhost:8000`；部署在子路径时是
`http://host/kb`（对应 `ROOT_PATH`）。所有接口都在 `$HUB/api/v1` 下。

```bash
# 1) 只读：先拿书，再拿目录，最后拿正文
curl -s "$HUB/api/v1/books"
curl -s "$HUB/api/v1/books/dev-handbook"
curl -s "$HUB/api/v1/books/dev-handbook/chapters/welcome?section=main"

# 2) 写入：用 write 作用域 Token（见 3.1）
curl -s -X POST "$HUB/api/v1/admin/books/dev-handbook/chapters/welcome/sections" \\
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\
  -d '{"title": "新节", "content": "# 标题\\n\\n正文"}'

# 3) 不确定怎么调：看一眼自己的作用域与限制，再读完整契约
curl -s "$HUB/api/v1/admin/meta" -H "Authorization: Bearer $TOKEN"
# 机器可读的完整契约（可以直接喂给会 function calling 的模型）
curl -s "$HUB/openapi.json"
```

## 从哪开始

| 你要做的事 | 看哪一章 |
| --- | --- |
| 搞清楚「分组 / Book / 章 / 节」怎么摆、资料该放哪、文件有什么格式要求 | 第 2 章「内容怎么组织」 |
| 直接调 HTTP 读写文档 | 第 3 章「用 HTTP API」 |
| 把它变成 MCP 工具，让 Agent 自己挑工具 | 第 4 章「接入 MCP」 |
| 把一套固定流程固化成 SKILL | 第 5 章「接入 SKILL」 |
| 报错看不懂 | 第 6 章「常见问题」 |

## 三条硬规则（先记住，细节在各章）

1. **一本 Book 只有一种格式**：Book 是 Markdown，它下面所有节都必须是 Markdown；
   是 HTML 就全是 HTML。写错格式会被 400 拒绝。
2. **写操作需要 Token**：`read` < `write` < `admin` 逐级包含；`admin` 覆盖账号、
   站点设置、Token 与审计，**不能**再限定 Book 范围。
3. **删除都是软删除**：先 `?dry_run=true` 看影响面，再 `?confirm=true` 执行；
   删错了用 `.../restore` 恢复。
"""

_STRUCTURE = """# 知识库、分组、Book、章、节

这个站点是**五层结构**，从上到下越来越具体：

```
站点（BookHub 实例）
└── 分组 book_groups      ← 首页的分区：这一排书叫什么、排在第几排
    └── Book（一本书）     ← 整本一种格式，有可见性、封面、置顶
        └── 章 chapters    ← 目录里的一行：标题 + 顺序 + 发布状态（没有正文）
            └── 节 sections ← 真正的正文文件：格式、字数、版本、URL
```

| 层级 | 是什么 | 关键属性 | 可见性由谁决定 |
| --- | --- | --- | --- |
| 分组 | 首页分区（如「基础设施」「产品文档」） | 标题、slug、`sort_order` | 分组只是归类，不控制可见性 |
| Book | 一套文档 | slug（全站唯一）、整本格式、`visibility`、`pinned`、封面 | `public` 进列表；`unlisted` 不进列表但可直链；软删进回收站 |
| 章 | 目录里的一行 | slug（书内唯一）、`sort_order`、状态 `draft`/`published` | **只有章有状态**：撤回=整章对访客消失 |
| 节 | 一份正文文件 | slug（章内唯一）、`format`（=书的格式）、版本号、字数 | 没有独立状态，始终跟随所在章 |

## 为什么章没有正文

正文与版本都挂在节上，章只负责「顺序 + 发布开关」。好处：

- 一章可以由多个文件组成（一个文件一节），改一节不影响同章其它节；
- 发布/撤回作用于整章，不会出现「半章可见」；
- 版本、diff、回滚都以节为单位。

## 一条资料该放哪

1. 是**另一个主题**（另一套文档）→ 新建 Book，并选一个分组；
2. 是同一本书里的**新主题块**→ 在书里新建一章；
3. 是某一章里的**一段内容**→ 新建一节（或改写已有节）。

拿不定主意时：把「读者会想单独点开的标题」当章，「章里的小标题」当节。

## 地址与接口怎么对应

| 读者页面 | 只读 API |
| --- | --- |
| `/b/<book>` 目录 | `GET /api/v1/books/<book>` |
| `/b/<book>/<chapter>`（多节章显示节索引，单节章直接显示正文） | `GET /api/v1/books/<book>/chapters/<chapter>` |
| `/b/<book>/<chapter>/<section>` | `GET /api/v1/books/<book>/chapters/<chapter>?section=<section>` |

写操作都在 `/api/v1/admin` 下，路径形状与上表一致（见第 3 章）。

## 四条容易踩的规则

- **每个 Book 必属于一个分组**：新建时必须给 `group`（分组 slug 或 id）；「默认分组」（`default`）由系统创建，不能删。
- **slug 只保留 `[a-z0-9-]`**：中文标题派生不出 slug，会自动生成 `book-3f7a1c` / `chapter-…` 这类随机标识；想让链接好读、MCP 配置好写，就**显式传英文 slug**。
- **顺序由序号决定**：分组、章、节都按 `sort_order`（步长 10）排；调整用 `move` / `reorder` 接口或管理端上下移，不要手工改库。
- **删除是软删除**：Book/章/节都会进回收站，恢复后回到原位；内置《AI Agent 接入使用指南》整本不可删（见第 6 章）。
"""

_FORMATS = """# 上传资料的格式要求

## 第一原则：一本 Book 只有一种格式

`Book.format` 只能是 `markdown` 或 `html`，它下面**每个节**都必须用同一种。往 Markdown 书里传 `.html` 会被整批拒绝（不会「传一半成功」）；书里已有章之后也不能再改格式。

| 书的格式 | 接受的扩展名 | 怎么渲染 |
| --- | --- | --- |
| `markdown` | `.md` `.markdown` `.mdown` `.mkd` `.txt` | 站内渲染：表格、代码高亮、标题锚点、目录 |
| `html` | `.html` `.htm` `.xhtml` | 白名单净化后展示（或按 Book 设置原样输出） |

Word（`.docx`）与 PDF **不能**直接当正文：先在本地转成 Markdown 或 HTML 再上传。

## 编码

- 优先 **UTF-8**（带不带 BOM 都行）；
- 不是 UTF-8 时按 **GB18030** 兜底（中文 Windows 常见编码）；
- 含 NUL 字节的文件按二进制拒绝；
- 换行统一成 LF（CRLF / CR 都会被规范化）。

报「无法识别文件编码」时，用编辑器另存为 UTF-8 再传。

## 数量与体积

| 限制 | 默认值 | 超了会怎样 |
| --- | --- | --- |
| 单文件大小 `MAX_UPLOAD_BYTES` | 5 MiB | 413 |
| 单次文件个数 `MAX_UPLOAD_FILES` | 50 | 400 |
| 单节正文字符数 `MAX_CONTENT_CHARS` | 500 000 | 422 |

真实数值以 `GET /api/v1/admin/meta` 的 `limits` 为准，别把默认值写死进脚本。

## 多文件上传 = 多节

一次传多个文件时，**一个文件生成一节**：

- 标题取文件名（去扩展名）：`01-概述.md` → 标题 `01-概述`；
- 顺序按上传顺序，每个递增 10；
- 文件名里的序号会留在标题里。想要干净的标题与链接，用 API 显式给 `title` 与 `slug`。

## 图片与附件是另一套

正文里要放图或附件时走媒体接口 `POST /api/v1/admin/books/{book}/media`：

- 扩展名白名单：`png jpg jpeg gif webp svg avif bmp pdf txt md csv json log yaml yml zip`（`MEDIA_ALLOWED_TYPES` 可调）；
- 单文件 20 MiB、每本书 500 MiB（`MEDIA_MAX_BYTES` / `MEDIA_QUOTA_BYTES`）；
- SVG 会被净化，内含 `<script>` 之类直接拒绝；
- 上传后返回站内地址 `/media/<book>/<file>`，正文里直接引用；子路径部署时渲染阶段自动补前缀。

## 常见拒绝与改法

| 现象 | 原因 | 改法 |
| --- | --- | --- |
| 400「不支持的文件类型」 | 扩展名不在白名单 | 转成 `.md` / `.html` 文本；Word、PDF 不能当正文 |
| 400 格式与书不一致 | `.html` 传进了 Markdown 书（或反之） | 换文件，或另建一本对应格式的书 |
| 400「一次最多上传 N 个文件」 | 一批文件太多 | 分批，建议每批 10～20 个 |
| 413 文件超过上限 | 单文件太大 | 拆分或压缩 |
| 422 正文超过上限 | 单节字符数超了 | 拆成多节 |
| 400「无法识别文件编码」 | 既不是 UTF-8 也不是 GB18030，或含 NUL | 另存为 UTF-8 |

## 推荐流程

1. 本地把资料整理成「一节一个文件」的 Markdown，文件名用英文 + 序号（`01-intro.md`）；
2. 用 `status: "draft"` 导入，先检查目录与渲染效果；
3. 确认后 `POST /api/v1/admin/books/{book}/chapters/{chapter}/status` 发布整章；
4. 图片走媒体上传，正文里用 `/media/<book>/<file>` 引用。
"""

_HTTP_AUTH = """# 拿到 Token 与作用域

管理接口是 `$HUB/api/v1/admin`，每个请求带 `Authorization: Bearer <token>`。
Token 在网页端「API Token」页签发，明文只显示一次。

## 作用域

| 作用域 | 能做 |
| --- | --- |
| `read` | 列表、详情、版本、回收站、`meta` |
| `write` | 上面全部 + Book / 章 / 节 / 版本 / 回收站的写操作 |
| `admin` | 上面全部 + 账号、站点设置、Token 与 Webhook、审计查询与导出 |

`admin` **不能**与「可操作的 Book」共存：admin 覆盖的那些端点没有 Book 可拦，
勾了范围也拦不住，签发时会直接 400。

## Book 范围

签发时可以勾选若干 Book，之后：

- 带 Book 引用的端点（`/books/{ref}/...`）访问范围外的书 → **403**；
- 不带引用但返回多本 Book 数据的端点（`GET /books`、`GET /trash`）只返回范围内的条目；
- 全站审计（`GET /audit`、`/audit.csv`）→ **403**（审计天然跨 Book）。

给某个团队的 Agent 发 Token 的推荐做法：`write` + 只勾它负责的那几本书 + 有效期。

## 先问 meta

```bash
curl -s "$HUB/api/v1/admin/meta" -H "Authorization: Bearer $TOKEN"
```

返回当前 Token 的名称与作用域、上传与正文上限（`max_upload_bytes`、
`max_upload_files`、`max_content_chars`、媒体配额）以及能力清单。**Agent 的第一步
都应该是它**：避免用错作用域、避免传超限的文件。

## 用 Token 再签 Token

`POST /api/v1/admin/tokens` 也接受 Token 鉴权，但新 Token 不能超过签发者：
作用域按包含关系比较（`read` ⊂ `write` ⊂ `admin`），Book 范围必须是签发者范围的子集。
这样就能让一个 `write` Token 给下级工具发更窄的凭据，而拿不到全站权限。
"""

_HTTP_ENDPOINTS = """# 端点清单

完整契约见 `$HUB/openapi.json`（每个操作都有稳定的 `operationId` 与中文说明）。
下面是最常用的部分，`{book}` / `{chapter}` / `{section}` 都可以用 slug 或数值 id。

## 只读（`/api/v1`，不需要 Token，除非配置了 `API_KEY`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/site` | 站点名、版本、能力开关；本指南的地址在 `guide` 字段 |
| GET | `/api/v1/books` | Book 列表（`page`、`page_size`、`group`、`visibility`） |
| GET | `/api/v1/books/{book}` | Book 详情 + 章节目录（不含正文） |
| GET | `/api/v1/books/{book}/chapters/{chapter}` | 章 + 节列表；单节章在顶层平铺正文 |
| GET | `/api/v1/books/{book}/chapters/{chapter}?section={section}` | 指定节的 JSON |
| GET | `/api/v1/books/{book}/chapters/{chapter}?section={section}&format=raw` | 只要原文（也可用 `Accept: text/markdown`） |
| GET | `/api/v1/books/{book}/export?format=json\\|zip` | 整本导出 |
| GET | `/api/v1/search?q=` | 全文检索，返回命中的书/章/节与片段 |
| GET | `/api/v1/changes?since=` | 增量同步（节级；墓碑不带标题） |

## 写入（`/api/v1/admin`，需要 Token）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/meta` | 自己的作用域与限制 |
| GET | `/books`、`/books/{book}` | 管理视角列表 / 单本（含未列出与已删除） |
| POST | `/books` | 建 Book（`title`、`group` **必填**、`format`、`visibility`） |
| PATCH | `/books/{book}` | 改标题/slug/简介/分组/可见性/`pinned`/封面 |
| GET | `/books/{book}/chapters` | 章列表（含草稿与已删除） |
| POST | `/books/{book}/chapters` | 建章（可带 `content` 或 `multipart/form-data`，多文件 = 多节） |
| POST | `/books/{book}/chapters/{chapter}/status` | 发布 / 撤回整章 |
| GET | `/books/{book}/chapters/{chapter}/sections` | 该章的节列表 |
| GET | `/books/{book}/chapters/{chapter}/sections/{section}` | **单节详情（默认带正文与 `toc`）** |
| POST | `.../sections` | 新建节 |
| PATCH | `.../sections/{section}` | 替换正文 / 改标题 / 改 slug（带 `base_version` 防覆盖） |
| POST | `.../sections/{section}/delete\\|restore` | 软删除 / 恢复 |
| GET | `.../sections/{section}/versions\\|/diff?a=&b=` | 版本与对比 |
| POST | `.../sections/{section}/rollback/{n}` | 回滚（生成新版本） |
| GET / POST | `/trash`、`/groups`、`/tokens`、`/webhooks`、`/users`、`/settings` | 其余管理能力 |
| GET | `/audit`、`/audit.csv` | 审计查询与导出（需要 `admin`） |

> 路径都在 `/api/v1/admin` 下；上表为省空间省略了前缀（`/meta` 即
> `/api/v1/admin/meta`）。`/api/v1` 是只读的，对它发 `POST/PATCH/DELETE` 一律 405。
"""

_WRITE_READ_BACK = """# 写一篇文档并读回

一次完整的「建书 → 写正文 → 读回 → 发布」流程。中文标题会自动派生不出 slug，
**显式给 `slug`**，否则会拿到 `chapter-3f9a1c` 这种随机标识。

```bash
export HUB=http://localhost:8000
export TOKEN=bh_xxx            # write 作用域

# 1) 建一本 Markdown 书（group 必填，可以写分组 slug 或 id）
curl -s -X POST "$HUB/api/v1/admin/books" \\
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\
  -d '{"title": "接入笔记", "slug": "onboarding-notes", "group": "default"}'

# 2) 建一章，同时写入第一节正文（draft：先不给读者看）
curl -s -X POST "$HUB/api/v1/admin/books/onboarding-notes/chapters" \\
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\
  -d '{"title": "第一步", "slug": "first-step", "status": "draft",
       "content": "# 第一步\\n\\n这是正文，支持 Markdown。"}'

# 3) 读回刚写的内容：默认就带 content_raw / content_rendered / toc
curl -s "$HUB/api/v1/admin/books/onboarding-notes/chapters/first-step/sections/first-step" \\
  -H "Authorization: Bearer $TOKEN"
# 只要元信息（省流量）：追 ?with_content=0

# 4) 发布整章，读者与只读 API 才能看到
curl -s -X POST "$HUB/api/v1/admin/books/onboarding-notes/chapters/first-step/status" \\
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\
  -d '{"status": "published"}'

# 5) 用读者视角确认（不需要 Token）
curl -s "$HUB/api/v1/books/onboarding-notes/chapters/first-step?section=first-step&format=raw"
```

## 改正文要防覆盖

替换节正文时带上你读到的版本号，别人先改了就会 409 而不是被覆盖：

```bash
curl -s -X PATCH "$HUB/api/v1/admin/books/onboarding-notes/chapters/first-step/sections/first-step" \\
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\
  -d '{"content": "# 新正文", "base_version": 1}'
```

## 批量上传多节

`POST .../chapters` 与 `POST .../sections` 都接受 `multipart/form-data`：
字段 `file` 或 `upload` 可以重复，**每个文件变成一节**，标题取文件名。
整本只有一种格式，所以 `.md` 书里混一个 `.html` 会被整批拒绝。
"""

_RULES = """# 必须知道的规则

## 格式：一本 Book 一种格式

- `Book.format` 决定整本：`markdown` 或 `html`，它下面每个节的 `format` 必须相同；
- 书里已经有章之后，`PATCH /books/{book}` 不能改 `format`（会先被 400 拒绝）；
- 上传文件时按书的类型校验扩展名，`multipart` 里混进另一种后缀整批不落库。

## 作用域与范围

- `read` < `write` < `admin`；`admin` 不能限定 Book 范围（见 3.1）；
- 受限 Token 的 `GET /books`、`GET /trash` 只返回范围内的书，审计直接 403。

## 幂等：`Idempotency-Key`

写请求带上 `Idempotency-Key: <唯一串>`。同键同内容在有效期内只会执行一次，重复
提交回放首次结果（响应头带 `Idempotent-Replay: true`）；同键不同内容 → 409。
键按 Token 分命名空间，两个 Token 用同一个键互不影响。

## 上传限制

| 限制 | 默认 | 超了会怎样 |
| --- | --- | --- |
| 单文件大小 `MAX_UPLOAD_BYTES` | 5 MiB | 413 |
| 单次文件个数 `MAX_UPLOAD_FILES` | 50 | 400 |
| 单节正文字符数 `MAX_CONTENT_CHARS` | 500000 | 422 |
| 媒体单文件 / 每本书配额 | 20 MiB / 500 MiB | 413 |

具体数值以 `GET /api/v1/admin/meta` 的 `limits` 为准，别把默认值写死进脚本。

## 删除：两步走

```bash
# 先看影响面（数据不动）
curl -s -X POST "$HUB/api/v1/admin/books/onboarding-notes/delete?dry_run=true" \\
  -H "Authorization: Bearer $TOKEN"
# 确认后执行（软删除，可在 /trash 恢复）
curl -s -X POST "$HUB/api/v1/admin/books/onboarding-notes/delete?confirm=true" \\
  -H "Authorization: Bearer $TOKEN"
```

## Webhook 地址

登记回调时不能指向本机/内网（`127.0.0.1`、`localhost`、`10.0.0.0/8`、`169.254.169.254` 等），
投递前还会再解析一次域名；重定向不跟随。内网服务想收通知请走反向隧道或公网入口。
"""

_MCP_WHY = """# MCP 是什么，为什么要接

MCP（Model Context Protocol）是「模型 ↔ 工具」的通用协议：客户端（IDE、编辑器、
Agent 运行时）启动或连接一个 MCP 服务器，服务器把一组**带参数 schema 的工具**暴露
出来，模型自己决定什么时候调哪个。

直接调 HTTP 也能用，但每换一个运行时都要重新教它「有哪些接口、参数怎么填」。接成
MCP 之后：

- 工具清单与参数 schema 由服务器声明，模型不需要背文档；
- 凭证留在服务器进程里，不进入模型的上下文；
- 读、写、发布这类动作可以按需拆细（只读工具 / 写入工具分开授权）。

## 两种接法

| 接法 | 适合 | 代价 |
| --- | --- | --- |
| 自己写一个薄服务器（推荐） | 只要 5～10 个工具、想控制权限面 | 一份约 80 行的 Python 文件 |
| 用通用 OpenAPI → MCP 网关 | 想一次暴露全部接口 | 工具数量爆炸，模型容易选错 |

本指南给的是第一种：一个可读、可改、没有隐藏行为的 stdio 服务器。
"""

_MCP_CONFIG = """# 配置一个 MCP 服务器

## 文件位置

把 3.3 的 `bookhub_mcp.py` 存到一个固定路径，例如 `/opt/bookhub-mcp/bookhub_mcp.py`，
按需装依赖：

```bash
pip install "mcp[cli]" httpx
```

## 客户端配置

不同客户端的配置文件位置不一样，但结构都是「服务器名 → 启动命令 + 环境变量」：

```json
{
  "mcpServers": {
    "bookhub": {
      "command": "python",
      "args": ["/opt/bookhub-mcp/bookhub_mcp.py"],
      "env": {
        "BOOKHUB_BASE_URL": "http://localhost:8000",
        "BOOKHUB_TOKEN": "bh_换成你的_token"
      }
    }
  }
}
```

常见位置：项目内 `.mcp.json`、用户目录 `~/.mcp.json`、客户端自身的设置文件。
ACECode 用 `mcporter` 管理时可以这样加：

```bash
mcporter add bookhub -- python /opt/bookhub-mcp/bookhub_mcp.py
```

## 配置要点

- **Token 放环境变量，不要写进工具描述**：模型的上下文里不应该出现凭据；
- **用 `write` 作用域 + Book 范围**：只给它负责的那几本书，别用 `admin`；
- 子路径部署时 `BOOKHUB_BASE_URL` 要带前缀（`http://host/kb`），服务器自己拼
  `/api/v1/...`；
- 先用 `read` Token 跑通「搜索 + 读节」，确认工具列表正常，再换成 `write`；
- 改完配置重启客户端；MCP 服务器是子进程，配置只在启动时读一次。
"""

_MCP_SERVER = """# 一个最小可用的 MCP 服务器

把下面这份存成 `bookhub_mcp.py` 即可。它只暴露 5 个工具：搜索、列书、读节、建节、
改节；凭证从环境变量读，模型的上下文里看不到 Token。

```python
import os

import httpx
from mcp.server.fastmcp import FastMCP

BASE = os.environ.get("BOOKHUB_BASE_URL", "http://localhost:8000").rstrip("/")
TOKEN = os.environ["BOOKHUB_TOKEN"]

client = httpx.Client(headers={"Authorization": f"Bearer {TOKEN}"}, timeout=30.0)
mcp = FastMCP("bookhub")


def _request(method: str, path: str, **kwargs) -> dict:
    response = client.request(method, f"{BASE}{path}", **kwargs)
    response.raise_for_status()
    return response.json()


@mcp.tool()
def search(query: str, page_size: int = 10) -> list[dict]:
    \"\"\"按关键词搜索已发布内容，返回命中的书 / 章 / 节标识与片段。\"\"\"
    data = _request(
        "GET", "/api/v1/search", params={"q": query, "page_size": page_size}
    )
    return [
        {
            "book": item["book"]["slug"],
            "chapter": item["chapter"]["slug"],
            "section": item["section"]["slug"],
            "title": item["section"]["title"],
            "url": item["url"],
            "snippet": item["snippet"],
        }
        for item in data["items"]
    ]


@mcp.tool()
def list_books() -> list[dict]:
    \"\"\"列出可见的 Book（不含未列出与已删除）。\"\"\"
    data = _request("GET", "/api/v1/books", params={"page_size": 100})
    return [
        {
            "slug": item["slug"],
            "title": item["title"],
            "format": item["format"],
            "chapters": item["chapter_count"],
        }
        for item in data["items"]
    ]


@mcp.tool()
def read_section(book: str, chapter: str, section: str) -> dict:
    \"\"\"读一节正文：返回 Markdown 原文、渲染后的 HTML 与目录 toc。\"\"\"
    return _request(
        "GET", f"/api/v1/admin/books/{book}/chapters/{chapter}/sections/{section}"
    )


@mcp.tool()
def create_section(
    book: str, chapter: str, title: str, content: str, slug: str = ""
) -> dict:
    \"\"\"在一章下新建一节（正文用 Markdown）。写操作需要 write 作用域。\"\"\"
    body: dict = {"title": title, "content": content}
    if slug:
        body["slug"] = slug
    return _request(
        "POST", f"/api/v1/admin/books/{book}/chapters/{chapter}/sections", json=body
    )


@mcp.tool()
def replace_section(
    book: str, chapter: str, section: str, content: str, base_version: int
) -> dict:
    \"\"\"替换一节正文；base_version 对不上会 409，不会覆盖别人的改动。\"\"\"
    return _request(
        "PATCH",
        f"/api/v1/admin/books/{book}/chapters/{chapter}/sections/{section}",
        json={"content": content, "base_version": base_version},
    )


if __name__ == "__main__":
    mcp.run()
```

## 想加工具的时候

- 发布/撤回整章：`POST /api/v1/admin/books/{book}/chapters/{chapter}/status`
  传 `{"status": "published"}` 或 `{"status": "draft"}`；
- 建章：`POST /api/v1/admin/books/{book}/chapters`，带 `title`、`slug`（英文）、`content`；
- 删除一律做成「先 dry_run 返回影响面」的工具，别让模型一步删掉东西。

加工具时只加**一个动词一个端点**，参数保持扁平（`book`、`chapter`、`section`、`content`），
模型选错的概率最低。
"""

_SKILL_MD = """# 把流程固化成 SKILL

SKILL 是「给 Agent 的一段可复用操作说明」：一个目录 + 一份 `SKILL.md`，开头是
YAML 元信息（`name`、`description`），正文写**什么时候用、按什么步骤做、出错了怎么办**。

## 目录结构

```
~/.acecode/skills/bookhub-wiki/SKILL.md          # ACECode
~/.claude/skills/bookhub-wiki/SKILL.md           # 其他遵循同一约定的客户端
<项目>/.agents/skills/bookhub-wiki/SKILL.md      # 跟着仓库走，团队共享
```

## 模板

```markdown
---
name: bookhub-wiki
description: 查询与维护 BookHub 知识库时使用：需要读内部文档、把结论写回知识库、
  或整理某本书的目录结构时触发。
---

# BookHub 知识库

## 何时用

- 用户问到内部文档、规范、流程：先在这里检索，不要凭记忆回答；
- 用户要把调研结论、变更记录写回知识库；
- 需要整理某本书的章节结构。

## 环境

- `HUB`：站点地址，子路径部署时带前缀（如 `http://host/kb`）；
- `TOKEN`：`write` 作用域，且只覆盖相关 Book（不要用 admin）。

## 步骤

1. 先确认自己的权限与限制：
   `curl -s "$HUB/api/v1/admin/meta" -H "Authorization: Bearer $TOKEN"`
2. 检索：`curl -s "$HUB/api/v1/search?q=<关键词>"`，命中后按
   `book/chapter/section` 三个 slug 取正文；
3. 读正文：`GET $HUB/api/v1/books/<book>/chapters/<chapter>?section=<section>&format=raw`；
4. 写回：先 `POST .../delete?dry_run=true` 之类的预览，再 `?confirm=true`；
   新建用 `POST .../sections`，改写用 `PATCH` 并带 `base_version`；
5. 写完必须用单节详情端点读回，确认正文与版本号；
6. 回报时给读者可点的链接：`$HUB/b/<book>/<chapter>/<section>`。

## 约束

- 一本 Book 只有一种格式：Markdown 书里不要塞 HTML 节；
- 一次最多 50 个文件、单文件 5 MiB、单节 50 万字符（以 meta 返回为准）；
- 不删除 Book，不碰账号与设置；失败就如实报告，不要绕路。

## 错误对照

| 状态 | 含义 | 处理 |
| --- | --- | --- |
| 401 | Token 无效或过期 | 请管理员重签，不要重试 |
| 403 | 作用域或 Book 范围不够 | 换合适的 Token，不要绕过 |
| 404 | 书/章/节不存在或未发布 | 先列目录确认 slug |
| 409 | `base_version` 已过期 | 重新读正文、合并后再写 |
| 422 | 正文超长或参数非法 | 拆成多节 |
```

## 写作要点

1. **`description` 决定要不要加载**：写清触发条件（「问到内部文档时」），而不是
   「这是一个知识库工具」。一句话里带上关键词。
2. **正文只写确定性步骤**：命令、参数、顺序、校验方式。把「完整的端点表」留给
   本指南（第 3 章）和 `/openapi.json`，SKILL 里放链接与最小示例，避免副本过期。
3. **把校验写进流程**：`meta → 搜索 → 读 → 写 → 读回`，每一步都能自证。
4. **不写凭据**：SKILL 只描述从环境变量取，不写 Token 值。
5. **错误码要有处置**：401/403 不重试、409 先重读——模型最容易在这里打转。
"""

_FAQ = """# 常见问题

## 状态码

| 状态 | 典型原因 | 怎么办 |
| --- | --- | --- |
| 400 | 参数非法、缺少 `group`、格式与书不一致 | 读 `error.message`，它写的是人话 |
| 401 | 没带 Token、Token 无效/过期/已吊销 | 重新签发；吊销后立刻失效 |
| 403 | 作用域不足、Book 不在范围、admin 与范围共存 | 换 Token，别用 admin 去绕 |
| 404 | 书/章/节不存在、未发布、已删除 | 先列目录、确认发布状态 |
| 405 | 对只读的 `/api/v1` 发了写方法 | 写操作走 `/api/v1/admin` |
| 409 | `base_version` 或幂等键内容冲突 | 重新读、再合并 |
| 413 | 文件超过 `MAX_UPLOAD_BYTES` 或媒体配额 | 压缩或分拆 |
| 422 | 正文超过 `MAX_CONTENT_CHARS` | 拆成多节 |
| 429 | 触发限流 | 按 `Retry-After` 等待，别并发重试 |

## 为什么我的中文标题变成了 `chapter-3f9a1c`

slug 只保留 `[a-z0-9-]`，中文标题派生不出可用 slug，于是回退成随机标识。
中文标题请显式传 `slug`（英文短横线风格），否则后续链接和配置都不好写。

## 部署在子路径（`/kb`）时

所有地址都要带前缀：`$HUB=http://host/kb`，接口就是 `$HUB/api/v1/...`；
前端页面链接是 `$HUB/b/<book>/<chapter>/<section>`。不要自己把前缀拼两次。

## 这本书能删吗

不能。它是内置指南，随系统生命周期存在：整本不可删除、slug 与文档类型锁定、
章与节也不可删除（可以改正文、加节、排序、发布/撤回）。

- 不想让读者看到：把可见性改成「未列出」，或把章撤回成草稿；
- 内容过时：直接编辑正文，系统不会覆盖你的修改；
- 想要一份自己的副本：新建一本 Book，把内容复制过去。

## `/changes` 里删除的条目没有标题

故意的。墓碑只回 `id`、slug 与时间戳，避免增量同步变成「偷看未发布标题」的旁路。
客户端按 `deleted: true` 删本地副本即可。

## 为什么 `GET /books` 只返回了一部分书

你用的 Token 限定了 Book 范围（见 3.1）。范围外的书不会出现在列表、回收站里，
审计接口则直接 403。
"""

# 章 → 节的结构。slug 全部显式写死：中文标题派生不出可用 slug，也方便外部
# 直接用 `/b/ai-agent-guide/mcp/mcp-server` 这类稳定地址引用。
CHAPTERS: list[dict[str, object]] = [
    {
        "title": "开始之前",
        "slug": "start",
        "sections": [
            {"title": "这本书是什么", "slug": "what-is-this", "raw": _WHAT_IS_THIS},
        ],
    },
    {
        "title": "内容怎么组织",
        "slug": "structure",
        "sections": [
            {
                "title": "知识库、分组、Book、章、节",
                "slug": "hierarchy",
                "raw": _STRUCTURE,
            },
            {"title": "上传资料的格式要求", "slug": "formats", "raw": _FORMATS},
        ],
    },
    {
        "title": "用 HTTP API",
        "slug": "http-api",
        "sections": [
            {"title": "拿到 Token 与作用域", "slug": "auth", "raw": _HTTP_AUTH},
            {"title": "端点清单", "slug": "endpoints", "raw": _HTTP_ENDPOINTS},
            {"title": "写一篇文档并读回", "slug": "write-read-back", "raw": _WRITE_READ_BACK},
            {"title": "必须知道的规则", "slug": "rules", "raw": _RULES},
        ],
    },
    {
        "title": "接入 MCP",
        "slug": "mcp",
        "sections": [
            {"title": "MCP 是什么，为什么要接", "slug": "why", "raw": _MCP_WHY},
            {"title": "配置一个 MCP 服务器", "slug": "config", "raw": _MCP_CONFIG},
            {"title": "一个最小可用的 MCP 服务器", "slug": "server", "raw": _MCP_SERVER},
        ],
    },
    {
        "title": "接入 SKILL",
        "slug": "skill",
        "sections": [
            {"title": "SKILL 模板与写作要点", "slug": "template", "raw": _SKILL_MD},
        ],
    },
    {
        "title": "常见问题",
        "slug": "faq",
        "sections": [
            {"title": "常见问题", "slug": "faq", "raw": _FAQ},
        ],
    },
]

_SUMMARY = "给 AI Agent 的说明书：内容怎么组织、上传格式要求、读写 HTTP API、接入 MCP 与配置 SKILL。"
_ICON = "🤖"


def _chapter_by_slug(session: Session, book_id: int, slug: str) -> Chapter | None:
    return session.execute(
        select(Chapter).where(Chapter.book_id == book_id, Chapter.slug == slug)
    ).scalar_one_or_none()


def _section_by_slug(session: Session, chapter_id: int, slug: str) -> ChapterSection | None:
    return session.execute(
        select(ChapterSection).where(
            ChapterSection.chapter_id == chapter_id, ChapterSection.slug == slug
        )
    ).scalar_one_or_none()


def find_guide(session: Session) -> Book | None:
    """取内置指南（未删除时才返回）；`/api/v1/site` 用它告诉外部去哪读说明。"""
    book = session.execute(
        select(Book).where(Book.slug == builtin.BUILTIN_SLUG, Book.deleted_at.is_(None))
    ).scalar_one_or_none()
    if book is None or not builtin.is_builtin(book):
        return None
    return book


def ensure_guide(session: Session) -> Book | None:
    """幂等创建内置指南，并补齐缺失的章/节。

    已存在的章与节**一律不覆盖**（站内编辑以用户为准）：只补「库里完全没有」的
    章和节，所以升级带来的新增章节能补上，而用户改过的正文不会被动。
    返回 None 表示这个 slug 被用户自己的书占了，我们不抢。
    """
    book = session.execute(
        select(Book).where(Book.slug == builtin.BUILTIN_SLUG)
    ).scalar_one_or_none()
    if book is not None and not builtin.is_builtin(book):
        return None
    if book is None:
        book = create_book(
            session,
            title=builtin.BUILTIN_TITLE,
            slug_raw=builtin.BUILTIN_SLUG,
            summary=_SUMMARY,
            icon=_ICON,
            fmt=FORMAT_MARKDOWN,
            visibility=VISIBILITY_PUBLIC,
        )
        book.is_builtin = True
        book.pinned = True
    else:
        # 内置标记可能来自迁移前的老行；删除只可能来自手工改库，这里兜一下
        book.is_builtin = True
        book.deleted_at = None
    session.flush()

    created_chapters = False
    for chapter_spec in CHAPTERS:
        chapter = _chapter_by_slug(session, book.id, str(chapter_spec["slug"]))
        if chapter is None:
            chapter = chapters_service.create_chapter(
                session,
                book,
                title=str(chapter_spec["title"]),
                slug_raw=str(chapter_spec["slug"]),
                status=STATUS_PUBLISHED,
                note="内置指南",
            )
            created_chapters = True
        elif chapter.deleted_at is not None:
            chapters_service.restore_chapter(session, chapter)
        for section_spec in chapter_spec["sections"]:  # type: ignore[union-attr]
            if _section_by_slug(session, chapter.id, str(section_spec["slug"])) is not None:
                continue
            sections_service.create_section(
                session,
                chapter,
                title=str(section_spec["title"]),
                raw=str(section_spec["raw"]),
                slug_raw=str(section_spec["slug"]),
                note="内置指南",
            )
    # 新补进来的章默认追加在末尾；整体按 SPEC 顺序重排一次，让升级后的目录与
    # 新装实例一致。只在新章出现时排序，之后用户自己的调整不会被启动流程覆盖。
    if created_chapters:
        _reorder_to_spec(session, book)
    session.flush()
    return book


def _reorder_to_spec(session: Session, book: Book) -> None:
    existing = chapters_service.ordered_chapters(session, book.id)
    by_slug = {chapter.slug: chapter for chapter in existing}
    spec_order = [str(spec["slug"]) for spec in CHAPTERS]
    ordered_ids = [by_slug[slug].id for slug in spec_order if slug in by_slug]
    ordered_ids += [chapter.id for chapter in existing if chapter.slug not in spec_order]
    chapters_service.reorder_chapters(session, book.id, ordered_ids)
