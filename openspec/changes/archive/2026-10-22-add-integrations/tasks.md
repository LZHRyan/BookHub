# Tasks

## 1. 数据

- [x] 1.1 `Webhook` / `WebhookDelivery` 模型（含 `events`、`is_active`、`last_status`、`attempts`）+ 迁移 `0013_webhooks`（两表 + 索引 + downgrade）

## 2. 服务层

- [x] 2.1 `app/services/webhooks.py`：`create/list/delete`、`sign(secret, body)`、`dispatch(session, event, payload)`、`deliver(delivery)`、`retry(delivery)`
- [x] 2.2 校验：URL 必须是 http(s)、事件取值合法、至少一个事件；密钥一次性返回
- [x] 2.3 在 `chapters.set_status`（发布/撤回）与 `replace_content`（改稿）后触发事件，失败只记录不抛错
- [x] 2.4 单测：签名正确、非 2xx 记录状态码、异常记录错误、停用不投递、重试更新记录

## 3. 对外端点

- [x] 3.1 `GET /sitemap.xml`：首页 + 公开 Book + 已发布章节，绝对地址与 `lastmod`；排除 unlisted / 草稿 / 已删除
- [x] 3.2 `GET /metrics`：Prometheus 文本（books / chapters / media bytes / audit / tokens）
- [x] 3.3 单测：sitemap 内容与排除、metrics 文本格式与指标名

## 4. 管理 API

- [x] 4.1 `GET/POST /api/v1/admin/webhooks`、`DELETE /api/v1/admin/webhooks/{id}`（停用）
- [x] 4.2 `POST /api/v1/admin/webhooks/{id}/test`、`GET /api/v1/admin/webhooks/{id}/deliveries`、`POST /api/v1/admin/deliveries/{id}/retry`
- [x] 4.3 `admin` 作用域 + 审计 `webhook.create` / `webhook.delete` / `webhook.test` / `webhook.retry`

## 5. CI

- [x] 5.1 `.github/workflows/ci.yml`：Python 3.12，装依赖 → `ruff check` → `pytest -q` → `docker build`

## 6. 文档

- [x] 6.1 `docs/ai.md`：Webhook 事件体、签名头与验签示例（Python）、重试流程
- [x] 6.2 `docs/deploy.md`：`/metrics` 抓取与反代限制、CI 说明
- [x] 6.3 `README.md`：功能清单补 Webhook / sitemap / metrics / CI

## Workflow follow-up

- `openspec validate add-integrations --strict` 通过后归档该变更，并把归档目录提交入库。
