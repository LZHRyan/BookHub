# Design

## Context

章节的发布/改稿都发生在 `app/services/chapters.py`（`set_status`、`replace_content`），审计已有统一的 `audit.record`。对外只读出口在 `app/web/public.py`（`/b/...`）。部署是单容器 + 一个数据卷，启动任务在 `app/main.py::_startup_tasks`。仓库目前没有 `.github/`。动机见 `proposal.md`。

## Goals / Non-Goals

**Goals:**

- 内容变更后，外部系统能在秒级收到通知，且失败可查、可重试。
- 搜索引擎/内部爬虫能发现全部公开内容，不泄露草稿与未列出 Book。
- CI 能在没有密钥的干净环境里跑通 lint + 测试 + 镜像构建。

**Non-Goals:**

- 事件总线/消息队列、后台重试调度、按 Book 订阅过滤、RSS/Atom。
- 序列化去重（共享 presenter）——单独一个变更做，避免与本次的失败原因混在一起。

## Decisions

### D1. Webhook 用两张表：登记 + 投递记录

`webhooks(id, url, secret, events, is_active, created_by, created_at, last_status, last_error, last_sent_at)`
`webhook_deliveries(id, webhook_id, event, payload, status_code, error, attempts, created_at, delivered_at)`

- **理由**：投递记录是排查与重试的唯一依据；失败原因必须落库，否则「回调挂了三天没人知道」。
- **备选**：只存最后一次结果——无法重试历史失败，放弃。

### D2. 投递同步执行、失败吞掉、结果落库

`webhooks.dispatch(session, event, payload)` 在内容服务里同步调用：挑出匹配的 active hooks，构造请求体，`urllib.request` POST（timeout 5s），把状态码/异常写进 delivery。异常一律捕获。

- **理由**：单机知识库的写入频率极低（一天几十次），同步投递足够；不引线程/队列，避免多 worker 下的重复投递问题（当前 `WEB_CONCURRENCY=1`）。
- 代价：回调慢会拖慢保存。用 5 秒超时 + 只对 active hooks 投递把影响面压住；文档里明确「回调要快」。
- 事件在服务层触发（`set_status` / `replace_content`），因此网页与 API 两条路径都会推送。

### D3. 签名：HMAC-SHA256(secret, 原始请求体)

头：`X-BookHub-Event: chapter.published`、`X-BookHub-Signature: sha256=<hex>`。密钥只在创建响应里出现一次，存储的是明文（需要用它算签名）——与 Token 的哈希存储不同，这是有意的：回调方需要密钥验签，而 Token 是我们自己校验。文档里要求把它当凭据保管。

### D4. 投递不跟随重定向、不重试、只记录

`urllib` 默认跟随重定向；显式用不跟随的 opener，避免回调方把请求转到别处带走签名。重试由管理 API 手动触发。

### D5. sitemap 走公开路由，动态生成

`GET /sitemap.xml`：查 `public` 且未删除的 Book，再取每个 Book 的已发布章节；用 `xml.etree.ElementTree` 拼 `<urlset>`，`loc` 用请求的 base URL。不做缓存（内容量小）。

### D6. `/metrics` 用纯文本手工拼

Prometheus 文本格式足够简单：`# TYPE bookhub_books_total gauge` + `bookhub_books_total 12`。数据来自几个 `COUNT/SUM` 查询。

- 访问控制：不加鉴权（与 `/healthz` 一致），文档建议在反代层限制来源；不暴露任何内容细节。

### D7. CI 用 GitHub Actions，三个 job 串联在一个 workflow 里

`ruff check app tests scripts` → `pytest -q` → `docker build`。Python 3.12，依赖从 `requirements.txt` 装。

- **理由**：与本地命令完全一致，出问题能照抄复现。

## Risks / Trade-offs

- [回调方慢导致保存变慢] → timeout 5s + 只投 active；文档建议回调方先入队再处理。
- [投递记录表增长] → 每次内容变更 × hook 数，量级很小；暂不清理，后续可复用审计保留机制。
- [密钥明文存库] → 与 Token 的哈希策略不同，但回调方必须能验签；数据库已是可信边界，文档标注。
- [sitemap 暴露 Book 结构] → 只含公开内容，`unlisted` 与草稿被排除；与前台可见性一致。
- [`/metrics` 无鉴权] → 仅聚合数字，无内容；文档说明用反代限制。
- [同步投递在事务内执行] → 回调失败不回滚内容，但会占用事务时间；后续若要异步可换 BackgroundTasks。

## Migration Plan

1. `0013_webhooks`：建两张表 + 索引（`webhook_deliveries(webhook_id, created_at)`），含 downgrade。
2. 存量部署无 Webhook，行为不变；`/sitemap.xml` 与 `/metrics` 直接可用。
3. CI 文件随代码生效，不需要迁移。
