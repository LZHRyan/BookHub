# Proposal

## Why

技术文档最需要的是图：架构图、流程图、报错截图、接口示例，以及 PDF / 日志 / 配置样例这类附件。当前 BookHub 只能在正文里贴外链图片——服务端只挂了 `/static`，CSP 的 `img-src` 仅允许 `self data: https:`，`DATA_DIR` 也只用于放 SQLite。由此带来三个现实问题：内网或离线部署时外链图直接裂掉；外部图床失效或限流后历史文档集体变成裂图；公司内部截图被迫先传到外部图床。附件则完全无处安放。

## What Changes

- 新增媒体库数据模型 `media_assets`：记录归属 Book、原始文件名、存储名、MIME、字节数、SHA-256、类型（`image` / `attachment`）、上传者与时间，软删除。
- 存储布局 `{DATA_DIR}/media/{book_slug}/{sha256[:16]}-{safe_name}`：内容寻址天然去重，同名重复上传复用同一份文件；落盘前做 MIME 探测 + 扩展名白名单 + 大小上限 + 每 Book 配额校验，只允许写入 `DATA_DIR` 之下（拒绝路径穿越）。
- 公开读取走应用路由 `GET /media/{book_slug}/{stored_name}`（不是裸 `StaticFiles`）：校验 Book 存在未删除、`unlisted` 语义与草稿章节的登录可见性，输出 `Cache-Control: public, max-age=31536000, immutable`、`Content-Disposition`、`X-Content-Type-Options: nosniff`。
- 管理端上传入口：章节编辑器支持**粘贴截图 / 拖拽文件 / 点选上传**，按光标位置插入 `![alt](/media/...)`（Markdown Book）或 `<img src="/media/..." alt="...">`（HTML Book）；Book 详情页新增「媒体库」区块，显示资源、字节数、是否被引用，可删除。
- 管理 API：`POST /api/v1/admin/books/{ref}/media`（multipart 上传）、`GET .../media`（列表，含未引用标记与配额用量）、`DELETE .../media/{media_id}`，沿用 Token 作用域、幂等键、`dry_run` 与审计归属 `api:<token 名>`，让 AI 工具能代替人贴图。
- 未引用资源清理：`POST /api/v1/admin/books/{ref}/media/cleanup`（默认预览，`confirm=true` 才真删），扫描该 Book 全部章节与历史版本的 `content_raw` 判定引用。
- 部署前缀：正文中的站内媒体地址在渲染阶段按 `ROOT_PATH` 重写，子路径部署下不裂图。
- 新增配置：`MEDIA_MAX_BYTES`（单文件上限，默认 20 MiB）、`MEDIA_QUOTA_BYTES`（每 Book 配额，默认 500 MiB）、`MEDIA_ALLOWED_TYPES`（允许的扩展名集合）。

## Capabilities

### New Capabilities

- `media-library`: 媒体资源的所有权与存储契约（目录布局、内容校验、类型与大小上限、配额、内容寻址去重）、读取时的访问控制与缓存语义、正文引用格式、写入入口（编辑器交互与管理 API）、未引用资源的识别与清理。

### Modified Capabilities

- `management-api`: 媒体资源的列表、上传、删除与未引用清理 MUST 通过管理 API 完整可得，并沿用既有的 Token 作用域、幂等重放、审计归属与 `dry_run` 约定。
- `chapter-content`: 正文中的站内媒体地址 MUST 按部署前缀解析，渲染与净化流程 MUST 保留站内媒体引用。

## Impact

- **数据**：新增 Alembic 迁移 `0007_media_assets`（建表 + `(book_id, deleted_at)` 索引 + `stored_name` 唯一约束），有 downgrade。
- **服务层**：新增 `app/services/media.py`（校验、落盘、去重、引用扫描、配额统计、清理）。
- **路由**：新增 `app/web/media.py`（公开读取）；`app/api/admin.py` 追加 4 个端点；`app/web/admin.py` 追加编辑器上传端点与媒体库页面动作。
- **配置**：`app/config.py` 三个新配置项，写进 `public_dict()` 与 `.env.example`。
- **渲染**：`app/services/render.py` 增加媒体地址前缀重写。
- **前端**：`app/static/app.js` 编辑器粘贴 / 拖拽上传与光标插入、媒体库删除确认；`app/static/style.css` 媒体网格与附件列表样式。
- **测试**：新增 `tests/test_media.py`（校验、去重、访问控制、配额、清理、前缀重写、编辑器插入），`tests/test_admin_api.py` 补媒体端点；既有 225 条用例保持通过。
- **文档**：`README.md`、`docs/authoring.md`（上传与引用）、`docs/ai.md`（媒体 API）、`docs/deploy.md`（卷与配额）、`docs/content-model.md`（新表）。
- **非目标**：不做缩略图 / 图片裁剪、不做媒体版本化、不做对象存储或 CDN、不做病毒扫描与图片 EXIF 清洗、不接管历史外链图片的本地化。
