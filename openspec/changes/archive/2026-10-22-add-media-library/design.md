# Design

## Context

现状：`app/main.py` 只挂了 `/static`（应用自带前端资源），`DATA_DIR` 目前只被 SQLite 使用；`SecurityHeadersMiddleware` 的 CSP 为 `img-src 'self' data: https:`，`app/web/public.py` 里 HTML 原始文档通道用独立的 `RAW_DOCUMENT_CSP`（`sandbox` + `img-src * data: blob:`）。章节正文一律先落 `chapters.content_raw`，再经 `app/services/render.py`（markdown-it + nh3 + pygments）产出 `content_safe` / `content_rendered`。管理端已有会话 + CSRF 表单链路，管理 API 已有 Token + 幂等 + 审计的统一包装（`app/api/admin.py::_write`）。动机见 `proposal.md`。

## Goals / Non-Goals

**Goals:**

- 一张图 / 一个附件从「粘贴」到「出现在读者页面上」不超过一次交互，且不依赖外部服务。
- 资源读取的权限语义与 Book 可见性、章节草稿语义保持一致，不留「猜地址就能拿到内部资料」的口子。
- 存储天然幂等：重复上传不产生副本，删除可回退，磁盘增长可观测、可收敛。

**Non-Goals:**

- 不做图片处理管线（缩略图、格式转换、EXIF 清洗、水印）——本期只托管原始字节。
- 不引入对象存储 / CDN / 独立文件服务；保持「单容器 + 一个数据卷」的部署形态。
- 不接管正文里已经存在的外链图片（不做历史内容本地化）。

## Decisions

### D1. 存储：本地目录 + 内容寻址文件名，元数据入库

写入 `{DATA_DIR}/media/{book_slug}/{sha256[:16]}-{safe_name}`，`media_assets` 表只存元数据。

- **理由**：内容寻址让「去重」「可长期缓存」「幂等重传」三件事同时成立；磁盘上是可读的真实文件，备份 / 迁移 / 手工兜底都不需要额外工具。
- **备选**：① BLOB 入库——SQLite 单文件随图片膨胀，备份与 `VACUUM` 变慢，也无法用 `sendfile`；② 对象存储——多一套凭据与依赖，与「单机 Docker 一条命令起」的定位冲突。二者均放弃。
- 同名不同内容不会互相覆盖（名里有哈希）；同名同内容直接复用。

### D2. 读取走应用路由，而不是再挂一个 `StaticFiles`

`GET /media/{book_slug}/{stored_name}` 由 `app/web/media.py` 实现，用 `FileResponse` 输出。

- **理由**：需要「Book 未删除」「`unlisted` 需要身份」「资源已软删则 404」「附件加 `Content-Disposition`」这些 DB 相关判断，`StaticFiles` 做不到；`FileResponse` 仍走 `sendfile`，大文件性能损失可接受。
- **备选**：`app.mount("/media", StaticFiles(...))` + 中间件鉴权——中间件拿不到 Book 与资源记录，只能粗粒度拦截，放弃。
- 缓存策略：地址含内容哈希，响应可 `public, max-age=31536000, immutable`。

### D3. 类型校验：扩展名白名单 + 魔数嗅探（自实现，零系统依赖）

`app/services/media.py` 内置「扩展名 → (类别, MIME, 魔数前缀)」表，判定规则是两者必须一致。

- **理由**：`python-magic` 依赖 libmagic 动态库，容器要额外装系统包，Windows 本地开发常缺；本项目要判定的类型集合是封闭的，自实现约 40 行且完全可测。
- SVG 是文本格式，按扩展名信任，但内容出现 `<script`、`onload=` 等可执行特征时拒绝——它在站内是 `<img>` 上下文（脚本不执行），但可能被直接打开。
- 默认白名单：图片 `png jpg jpeg gif webp svg avif bmp`；附件 `pdf txt md csv json log yaml yml zip`。可用 `MEDIA_ALLOWED_TYPES` 收窄。

### D4. 配额与上限

`MEDIA_MAX_BYTES`（单文件，默认 20 MiB）、`MEDIA_QUOTA_BYTES`（每 Book 未删除资源占用合计，默认 500 MiB）。上传前用 `SUM(byte_size)` 判断，不加事务锁——并发极端情况下可能略微超出配额，属于可接受的软上限。

- 与既有 `MAX_UPLOAD_BYTES`（章节文档，默认 5 MiB）区分：文档是纯文本，图片是二进制，不该共用一个阈值。

### D5. 软删除 + 「已删除未引用」才允许物理回收

删除只置 `deleted_at`，物理文件保留，已发布章节因此不会裂图（spec 明确要求）。物理回收由清理接口负责：只对 `deleted_at IS NOT NULL` 且超过 `MEDIA_PURGE_GRACE_DAYS`（默认 7 天）仍无引用的资源删文件。

- **理由**：引用扫描是「尽力而为」的文本匹配（见 D6），一旦误删物理文件无法恢复；延后回收给了纠错窗口。

### D6. 引用判定：用存储名做全文匹配

扫描该 Book 所有 `chapters.content_raw` 与 `chapter_versions.content_raw`，用 `stored_name`（含哈希，全局唯一且不可猜）做子串匹配。

- **理由**：不解析 Markdown / HTML 语法就能覆盖「图片语法、`<img>`、裸链接、代码块里的示例」等全部引用形态，误判方向是「多留文件」（安全侧）。
- **代价**：正文里只提到名字而没真正使用时也算引用——可接受。

### D7. 部署前缀在渲染阶段重写

`render.py` 在净化之后对最终 HTML 做一次定点替换：`src="/media/`、`href="/media/` 补上 `ROOT_PATH`。正文原文（`content_raw`）永远保留作者写的 `/media/...`。

- **理由**：正文写死前缀会让同一份内容在换部署前缀后失效；重写放在渲染层可随配置自动生效，且不影响原文导出。
- **备选**：让用户自己写前缀——换个部署就全站裂图，放弃。

### D8. 编辑器交互：一个端点 + 三种触发方式

`POST /admin/books/{id}/media`（会话 + CSRF，返回 JSON）同时服务粘贴、拖拽、点选；前端 `app/static/app.js` 只负责把文件塞进 `FormData`、按光标位置 `setRangeText` 插入引用。

- **理由**：三种入口产物完全一致，不必拆多个端点；返回 JSON 而不是整页重渲染，避免打断正在编辑的正文。
- **失败处理**：`4xx` 的 `error.message` 直接显示在编辑器内的提示条，正文与光标不动。

### D9. 管理 API 复用 `_write` 幂等包装

指纹里带上文件 SHA-256：同一幂等键 + 同一份文件重放返回首次结果，同键不同文件按既有逻辑 409。

### D10. 数据模型

```text
media_assets
  id            INTEGER PK
  book_id       FK books.id, NOT NULL, index
  filename      VARCHAR(255)   原始文件名（展示与下载用）
  stored_name   VARCHAR(200)   {hash16}-{safe_name}，唯一
  mime          VARCHAR(100)
  byte_size     INTEGER
  checksum      VARCHAR(64)    SHA-256（完整）
  kind          VARCHAR(16)    image | attachment
  created_by    FK users.id NULL
  created_at    DATETIME
  deleted_at    DATETIME NULL
  INDEX (book_id, deleted_at)
  UNIQUE (book_id, stored_name)   -- 去重范围限定在同一 Book 内
```

## Risks / Trade-offs

- [磁盘只增不减] → 每 Book 配额 + 未引用清理 + 已删除资源延后物理回收；`GET .../media` 返回占用与配额，运维可见。
- [应用进程承担文件 IO，大附件可能拖慢事件循环] → `FileResponse` 交回 `sendfile`；单文件上限 20 MiB，管理接口独立限流。
- [软删除保留物理文件，读者还能通过旧地址拿到吗] → 不会：地址查询走 DB，软删即 404；文件只是留在盘上供恢复。
- [引用扫描是文本匹配，可能漏判（正文用了却被判未引用）] → 存储名含哈希且长度固定，正常书写必然命中；清理默认只预览，物理回收另有 7 天宽限。
- [HTML 原始文档模式在 `unlisted` Book 下图片需要登录态] → 该模式 CSP 沙箱不带 `allow-same-origin`，浏览器不会带 Cookie，图片会 404。这是既有安全边界（文档自己的脚本也读不到本站），在 `docs/authoring.md` 中明确说明。
- [Book 改 slug 后正文里的旧媒体地址失效] → 渲染层按当前 slug 重写，但 `content_raw` 里仍是旧地址；媒体列表会把这些地址标为「引用已失效」，给出批量替换建议，不自动改写正文。

## Migration Plan

1. 新增迁移 `0007_media_assets`（建表 + 索引 + 唯一约束），`upgrade/downgrade` 都实现；无存量回填，旧库直接可用（媒体库为空）。
2. 部署时确保 `DATA_DIR` 落在持久卷上（`docker-compose.yml` 已挂 `./data`），`media/` 子目录启动时按需创建。
3. 回滚：`alembic downgrade -1` 删表；磁盘上的 `data/media/` 可保留（回滚后成为孤儿文件，可手工删除）。

## Open Questions

- 是否需要「媒体库跨 Book 复用」（同一张图挂到多个 Book）：当前按 Book 隔离，跨书需重复上传，换来权限与清理的简单性。后续若确有需求，可让 `book_id` 为空表示全局资源。
