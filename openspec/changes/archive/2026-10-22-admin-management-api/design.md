# Design

## Context

网页管理端有 29 个操作（见 `app/web/admin.py` 的路由表），全部走「会话 Cookie + CSRF 表单」。服务层（`app/services/books.py`、`chapters.py`、`users.py`、`settings.py`、`audit.py`）已经把这些能力抽出来了，但**没有一处是面向程序调用的**：没有 Bearer 认证、没有 JSON 写接口、没有幂等与并发语义，也没有可供模型直接消费的 OpenAPI 描述。

约束：

- 并行会话正在修改 `app/web/admin.py`、`app/services/books.py` 与模板，实现必须等这些改动落盘，且**不能把业务逻辑写进路由层**，否则会和他们的改动互相踩踏。
- 现有公共读 API `/api/v1` 与 `API_KEY` 语义不能变。
- 破坏性操作必须可恢复（现有软删除已满足）。

## Goals / Non-Goals

**Goals:**

- 网页端能做的事，Token 持有者都能做，且行为一致（同一服务层）。
- 让 AI 工具「读 OpenAPI 就能调」，无需理解 CSRF、表单字段名与 HTML。
- 误操作可预防（dry_run / confirm / 软删除）与可追溯（审计归属 Token）。

**Non-Goals:**

- 不做 GraphQL / gRPC / Webhook 推送。
- 不做按 Book 的细粒度授权（Token 作用域只到 read/write/admin 三档）。
- 不做附件/图片上传（属于独立能力，后续变更处理）。
- 不改网页端的交互与鉴权方式。

## Decisions

### D1. Token 存哈希，作用域三档，明文只出现一次

表 `api_tokens`：`id, name, token_hash(sha256), prefix(前 8 位用于展示), scopes(csv), created_by, created_at, expires_at, revoked_at, last_used_at`。校验时对传入值做 sha256 后按哈希查表，命中再判吊销/过期/作用域。

- 备选被否：存明文（泄露即灾难）；JWT（需要额外密钥轮换，且吊销要黑名单，反而更复杂）。
- 前缀保留 8 位只为列表可辨识，不参与鉴权。

### D2. 路由布局 `/api/v1/admin/**`，与读 API 并列

保持 `/api/v1` 只读契约不变，管理写接口集中在新前缀下，统一 `tags=["admin"]`、`security: bearer`。资源路径与网页端一一对应：

| 方法 | 路径 | 对应网页操作 |
| --- | --- | --- |
| POST | `/api/v1/admin/books` | 新建 Book |
| PATCH | `/api/v1/admin/books/{ref}` | 编辑 Book（标题/简介/图标/可见性/format） |
| POST | `/api/v1/admin/books/{ref}/delete` | 软删除 Book |
| POST | `/api/v1/admin/books/{ref}/restore` | 恢复 Book |
| POST | `/api/v1/admin/books/{ref}/chapters` | 新建章节（JSON 或 multipart 上传） |
| PATCH | `/api/v1/admin/books/{ref}/chapters/{chapter}` | 替换内容/改标题/slug/format 校验 |
| POST | `/api/v1/admin/books/{ref}/chapters/{chapter}/status` | 发布 / 撤回 |
| POST | `/api/v1/admin/books/{ref}/chapters/{chapter}/move` | 上移 / 下移 / 指定位置 |
| POST | `/api/v1/admin/books/{ref}/chapters/{chapter}/delete` \| `/restore` | 删除 / 恢复 |
| GET | `/api/v1/admin/books/{ref}/chapters/{chapter}/versions` | 版本列表 |
| GET | `.../versions/{version_no}` | 单版本 |
| GET | `.../diff?a=&b=` | 版本对比 |
| POST | `.../rollback/{version_no}` | 回滚 |
| GET | `/api/v1/admin/trash` | 回收站 |
| GET/POST | `/api/v1/admin/users` | 账号列表 / 新建 |
| POST | `/api/v1/admin/users/{id}/toggle` \| `/password` | 启停 / 重置密码 |
| GET/PUT | `/api/v1/admin/settings` | 站点设置 |
| GET | `/api/v1/admin/audit` | 审计查询 |
| GET/POST/DELETE | `/api/v1/admin/tokens` | Token 管理（仅 `admin` 作用域） |
| POST | `/api/v1/admin/books/{ref}/chapters/batch` | 批量发布 / 移动 / 删除（逐条结果） |

### D3. 路由只做协议转换，全部复用服务层

新增 `app/api/admin.py` 负责：解析参数、调服务层、把领域异常映射成错误码。**不复制业务规则**（slug 生成、format 约束、版本裁剪、审计写入都在服务层）。这样并行会话改服务层时不会与 API 冲突，也保证网页端与 API 行为一致。

### D4. 破坏性操作：dry_run 预览 + confirm 确认 + 软删除兜底

- `dry_run=true`：返回 `{"would_delete": [{id,title,slug,chapters_count}], "count": n}`，不写库。
- 真实删除：必须 `confirm=true`，否则 400 `confirmation_required`。
- 删除是软删除，回收站可恢复；恢复接口不需要 confirm。

### D5. 并发：base_version（章节）+ If-Match（Book）

章节写入复用现有 `base_version` 语义（403→409）。Book 的 `If-Match` 用 `updated_at` 派生的弱 ETag，与服务层比较后冲突返回 409。

### D6. 幂等：`Idempotency-Key` 落库 24 小时

表 `idempotency_keys`：`key PK, token_id, request_hash, status_code, response_json, created_at, expires_at`。命中且请求体哈希一致 → 直接回放；哈希不同 → 409 `idempotency_conflict`。过期行由启动/定时清理（复用 bootstrap 时机）。

- 备选被否：进程内字典（重启即丢，多副本不一致）。

### D7. 审计归属：`actor = "api:<token name>"`，detail 加 `via: api`

`app/services/audit.py` 已接受 `actor: User | None`；为不改签名，API 层传一个轻量 `Principal`（鸭子类型：有 `id=None`、`display_name="api:docs-bot"`、`username`），审计记录里体现来源。Token 的 `last_used_at` 在同一事务内更新。

### D8. OpenAPI 面向模型：operationId、中文 summary、显式 Schema

每个端点在装饰器里写 `operation_id`、`summary`、`description`、`responses`；请求/响应统一用 Pydantic 模型（`app/api/schemas.py`），避免 `dict[str, Any]`。作用域要求写进 `description`，因为 OpenAPI 没有 scope 的标准位置。

### D9. 限流按 Token，独立桶

`RateLimiter` 增加按 `token:<id>` 的桶（默认 60 次/分钟，可配 `ADMIN_API_RATE_LIMIT`），与公共读的 IP 桶互不影响。

### D10. Token 管理页复用管理端 shell

`GET/POST /admin/tokens` 页面：列表（名称/作用域/创建/最近使用/状态）+ 新建（名称、作用域多选、可选过期）+ 吊销。创建成功后一次性展示明文并提供复制按钮（`data-copy`，由 `app.js` 处理，避免内联脚本）。

## Risks / Trade-offs

- **Token 泄露** → 哈希存储、作用域最小化、可吊销、可选过期、最近使用时间可审计；文档建议给每个工具单独签发。
- **AI 误删内容** → 软删除 + 回收站 + dry_run + confirm；批量接口逐条返回，不会"一刀切"。
- **API 与网页逻辑漂移** → 强制共用服务层；新增用例覆盖两条路径结果一致。
- **幂等表增长** → 24 小时 TTL + 启动清理；键只存哈希。
- **并行会话冲突** → 实现前先确认 `admin.py`/`books.py` 无未提交改动；API 路由放新文件，避免改动既有路由。
- **OpenAPI 变胖** → 管理接口单独 `tags`，读 API 文档体积基本不变。

## Migration Plan

1. 新增迁移：`api_tokens`、`idempotency_keys`（只加表，不动既有表）。
2. 部署后由管理员在「API Token」页签发第一个 Token；也可用环境变量 `ADMIN_API_TOKEN` 引导（等价于一个 `admin` 作用域 Token，仅首次启动写入）。
3. 回滚：删除两张新表即可，旧功能不受影响（API 路由随镜像回退）。

## Open Questions

- 是否需要按 Token 限制"只能操作指定 Book"（细粒度授权）——本期用三档作用域，等出现多团队共用实例时再评估。
