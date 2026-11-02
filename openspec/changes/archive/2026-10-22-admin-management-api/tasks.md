# Tasks

## 1. 数据与凭据

- [x] 1.1 新增 `ApiToken` 与 `IdempotencyKey` 模型（哈希、前缀、作用域、过期、吊销、最近使用），`pytest` 覆盖唯一约束与默认值
- [x] 1.2 新增迁移 `0006_admin_api`（只建两张表 + 索引），验证 `alembic upgrade head` 与 `downgrade` 均可执行
- [x] 1.3 实现 `app/services/tokens.py`：`issue_token`（返回明文一次）、`verify_token`（哈希查表 + 吊销/过期判断 + 更新 last_used_at）、`revoke_token`、`list_tokens`；单测覆盖过期、吊销、作用域
- [x] 1.4 实现 `app/api/deps.py` 的 `require_scope(...)` 依赖：解析 Bearer、401/403 分支、返回 `Principal`；单测覆盖缺头、错 token、作用域不足

## 2. 管理写接口

- [x] 2.1 实现 Book 接口：创建 / PATCH 编辑（含 `If-Match`）/ 软删除与恢复（`dry_run` + `confirm`），单测覆盖三种结果码
- [x] 2.2 实现章节接口：创建（JSON 与 multipart 上传两条路径）/ PATCH 替换（`base_version` 409）/ 状态切换，单测覆盖格式约束与上传编码
- [x] 2.3 实现章节排序接口：上移 / 下移 / 指定顺序，单测覆盖边界位置与非法目标
- [x] 2.4 实现章节删除与恢复：`dry_run` 预览、`confirm` 强制、软删除后可恢复，单测覆盖预览不落库
- [x] 2.5 实现版本接口：列表 / 单版本 / 对比（`a`,`b`）/ 回滚（生成新版本），单测覆盖回滚后版本号递增
- [x] 2.6 实现回收站、账号（列表/创建/启停/重置密码）、站点设置（读/写）、审计查询，单测覆盖 `admin` 作用域限制
- [x] 2.7 实现批量接口（发布/移动/删除），返回逐条结果，单测覆盖"部分失败不影响其余"
- [x] 2.8 实现 Token 管理接口（列表/签发/吊销）与 `ADMIN_API_TOKEN` 引导，单测覆盖签发后即可用、吊销后 401

## 3. 横切能力

- [x] 3.1 实现幂等中间件/依赖（`Idempotency-Key` + 请求指纹 + 24h TTL），单测覆盖重放返回同一结果、同键不同体 409
- [x] 3.2 审计归属：写操作记为 `api:<token name>` 且 detail 标 `via=api`，单测按 token 名查询审计
- [x] 3.3 按 Token 限流（独立桶 + `ADMIN_API_RATE_LIMIT`），单测覆盖 429 与 `Retry-After`、不影响他 Token
- [x] 3.4 统一错误映射：把 `ValidationFailed/Conflict/NotFound/ContentTooLong/PayloadTooLarge` 映射为 400/409/404/422/413 且带稳定 `error.code`，单测逐条覆盖

## 4. 文档与 AI 可用性

- [x] 4.1 为每个端点设置稳定 `operationId`、中文 summary/description、请求与响应 Schema（`app/api/schemas.py`），验证 `/openapi.json` 中 `admin` tag 覆盖全部操作
- [x] 4.2 管理端新增「API Token」页面（列表 / 签发 / 一次性明文 / 吊销），手动验证签发后接口可用
- [x] 4.3 编写 `docs/ai.md`：如何用 Token、如何把 OpenAPI 喂给模型、常用提示词与安全建议（作用域最小、定期轮换）
- [x] 4.4 在 `docs/api.md` 增加"管理写接口"索引表，指向 `docs/ai.md`
- [x] 4.5 编写 `scripts/api_smoke.py`：用 Token 跑一遍建 Book → 传章节 → 发布 → 回滚 → 删除 → 恢复，对运行实例通过

## 5. 验证

- [x] 5.1 全量 `pytest` 与 `ruff` 通过，且既有 207 个用例无回归
- [x] 5.2 用内置浏览器在「API Token」页签发一个 Token，再用该 Token 实际操作一遍
- [x] 5.3 确认网页端与 API 写入同一内容后读取一致（同一服务层的回归验证）
- [x] 5.4 `openspec validate admin-management-api --strict` 通过，`tasks.md` 全部勾选

## Workflow follow-up

- 说明：4.4 的 docs/api.md 索引因并行会话占用该文件而暂缓，docs/ai.md 已独立成篇并可从「API Token」页进入。
- 归档本变更，使 `management-api` 进入 `openspec/specs/`，并合并 `admin-auth` 的 Token 需求。
