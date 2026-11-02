# Tasks

## 1. 数据与配置

- [x] 1.1 `app/models.py` 新增 `MEDIA_IMAGE` / `MEDIA_ATTACHMENT` / `MEDIA_KINDS` 常量与 `MediaAsset` 模型（`media_assets`，`(book_id, stored_name)` 唯一 + `(book_id, deleted_at)` 索引），`import app.models` 可加载
- [x] 1.2 新增迁移 `0007_media_assets`（建表 + 索引）与 `0008_media_scope_index`（把全局唯一改成按 Book 唯一，让两个 Book 能各自保存同一份文件），`alembic upgrade head` 在既有库上直接跑通
- [x] 1.3 `app/config.py` 增加 `media_max_bytes`(20 MiB)、`media_quota_bytes`(500 MiB)、`media_purge_grace_days`(7)、`media_allowed_types`，写入 `public_dict()`；`tests/test_deploy.py` 的 env 映射同步
- [x] 1.4 `.env.example` 与 `docs/deploy.md` 补媒体配置与「媒体目录必须同卷备份」提示

## 2. 媒体服务层

- [x] 2.1 `app/services/media.py`：扩展名 → (kind, mime, 魔数) 判定表与 `detect_media_type()`，覆盖 png/pdf/zip/未知类型/SVG 含脚本/扩展名与内容不符
- [x] 2.2 `safe_name()` + `storage_path()`：剥离路径与控制字符、目标路径必须落在媒体根目录内（`../` 与非法 slug 均拒绝）
- [x] 2.3 `save_media()`：大小校验 → SHA-256 → 内容寻址落盘（原子 rename）→ 同 Book 内幂等复用 → 写审计；超限返回 413 且不落盘
- [x] 2.4 `list_media()` / `usage()`：列表与 `used/limit/remaining` 配额视图，软删除资源不计入占用
- [x] 2.5 `delete_media()`：软删除 + 重复删除幂等 + 两次都记审计
- [x] 2.6 `scan/referenced_names()` 与 `cleanup()`：扫描章节与历史版本正文，预览与确认两条路径；确认时软删未引用资源、物理回收超期已删除资源
- [x] 2.7 `stale_references()`：找出正文里指向不存在资源的 `/media/` 地址（改 slug 后失效），媒体库页提示

## 3. 公开读取

- [x] 3.1 `app/web/media.py`：`GET /media/{book_slug}/{stored_name}`，校验 Book 未删除、`unlisted` 需会话或 Bearer Token、资源未软删
- [x] 3.2 响应头：`Cache-Control: public, max-age=31536000, immutable`、`X-Content-Type-Options: nosniff`、`Cross-Origin-Resource-Policy: same-site`，附件加 `Content-Disposition`
- [x] 3.3 路径穿越（`..%2f`）、其他 Book 的资源名、不存在的存储名一律 404
- [x] 3.4 `app/main.py` 注册路由并在启动时创建 `DATA_DIR/media`，既有启动测试仍通过

## 4. 管理端界面

- [x] 4.1 `POST /admin/books/{id}/media`（会话 + CSRF，multipart）返回 JSON；未登录 401、缺 CSRF 403、类型非法 415 都以 JSON 错误体返回
- [x] 4.2 `app/static/app.js`：粘贴 / 拖拽 / 点选三种入口，逐文件串行上传，按光标 `setRangeText` 插入 Markdown 或 HTML 引用，失败就地提示且不动正文
- [x] 4.3 `app/templates/admin/chapter_form.html`：正文外包 `editor-shell`，加投放区、点选上传与实时状态条
- [x] 4.4 `app/templates/admin/media.html` + `book_detail.html` 入口：缩略图/附件卡片、字节数与 MIME、引用状态、复制地址、删除、失效地址提示、清理区块
- [x] 4.5 `app/web/admin.py` 媒体库页面与删除/清理动作（CSRF + 审计 + 303 回跳）
- [x] 4.6 `app/static/style.css`：媒体网格、附件行、投放区高亮、状态条颜色，三态主题下均使用既有设计令牌

## 5. 管理 API

- [x] 5.1 `POST /api/v1/admin/books/{ref}/media` 复用 `_write` 幂等包装，指纹含文件 SHA-256；`read` 作用域返回 403
- [x] 5.2 `GET .../media`（列表 + `referenced` + `usage`）、`DELETE .../media/{id}`（`dry_run` 预览、`confirm` 必填）
- [x] 5.3 `POST .../media/cleanup`：默认预览，`confirm=true` 执行，返回删除清单、释放字节数与最新配额
- [x] 5.4 `tests/test_admin_api.py` 新增 6 条用例（上传+列表 / 只读拒绝 / 幂等重放 / 删除需确认 / 清理预览 / meta 能力），`/meta` 的 capabilities 与 limits 补 media
- [x] 5.5 `docs/ai.md`：端点表补 4 个媒体端点，示例给出上传→贴进正文→清理预览的完整 curl 流程与幂等说明

## 6. 渲染与导出

- [x] 6.1 媒体地址前缀重写放在 `app/services/media.py::prefix_media_urls`，由 Jinja 过滤器 `media_urls` 在渲染输出阶段套用（`ROOT_PATH=/kb` 时输出 `/kb/media/...`）
- [x] 6.2 净化白名单保留 `<img src alt>`；渲染测试断言站内图片不被丢弃
- [x] 6.3 原文与导出通道保持作者写的 `/media/...` 原样（`tests/test_media.py` 断言 `content_raw` 不被重写）

## 7. 集成与文档

- [x] 7.1 全量 `pytest`（225 + 新增 24 条）与 `ruff check app tests scripts` 通过
- [x] 7.2 `scripts/api_smoke.py` 扩到 12 步，新增「上传图片 → 正文引用 → 公开读取（含 immutable 头）→ 清理预览」，在容器实例上实跑通过
- [x] 7.3 `docs/authoring.md` 新增「2.4 插入图片与附件（媒体库）」：三种入口、引用格式、配额、软删除、slug 变更与原始版式模式的注意事项
- [x] 7.4 `docs/content-model.md` 新增 `MediaAsset` 一节；`README.md` 功能清单增加「图片与附件」

## Workflow follow-up

- `openspec validate add-media-library --strict` 通过后归档该变更，并把归档目录提交入库。
