# Proposal

## Why

知识库现在是纯「拉」模型：IM 机器人、聚合页、搜索引擎都得自己轮询。团队发完一章没人知道；搜「bookhub 运维手册」也搜不到站内页面。同时仓库没有任何 CI——280 条测试全靠手工跑，改完不敢确定没坏。

## What Changes

- **Webhook 变更推送**：登记回调地址后，章节发布 / 撤回 / 内容替换会向回调地址 POST 一个 JSON 事件，带 HMAC-SHA256 签名头与投递记录（状态码、错误、重试次数）。失败可在管理 API 里重试，不阻塞编辑器保存。
- **`/sitemap.xml`**：公开的站点地图，列出所有公开 Book 与已发布章节，带 `<lastmod>`，方便搜索引擎与内部爬虫发现内容。
- **`/metrics`**：Prometheus 文本格式的最小指标集（Book / 章节 / 媒体字节 / 审计行数 / Token 数），供内部监控抓取。
- **CI**：新增 GitHub Actions 工作流，跑 `ruff check`、`pytest` 与 Docker 镜像构建，PR 与 push 都触发。

## Capabilities

### New Capabilities

- `webhooks`: 回调地址的登记与生命周期、事件与签名格式、投递的失败处理与重试、以及「投递失败不影响内容写入」的保证。
- `site-discovery`: 站点地图与指标端点的内容、格式与访问控制。

### Modified Capabilities

- `management-api`: MUST 提供 Webhook 的增删查、测试投递与失败重试端点。
- `service-deployment`: MUST 提供可执行的 CI 校验（lint + 测试 + 镜像构建）。

## Impact

- **数据**：迁移 `0013_webhooks`（`webhooks` 与 `webhook_deliveries` 两张表）。
- **服务层**：新增 `app/services/webhooks.py`（登记、签名、投递、重试）；`chapters.set_status` 与 `chapters.replace_content` 在成功后触发事件。
- **Web**：新增 `GET /sitemap.xml`、`GET /metrics`（后者的访问控制沿用「无鉴权但可被反代限制」的约定，文档说明）。
- **API**：新增 5 个端点（列表 / 创建 / 删除 / 测试 / 重试）。
- **CI**：`.github/workflows/ci.yml`。
- **测试**：`tests/test_integrations.py`（签名、投递记录、失败不阻塞、重试、sitemap、metrics）。
- **非目标**：不做事件总线/消息队列、不做 Webhook 重试的后台调度（改为手动与下次事件时补投）、不做 RSS/Atom、`/metrics` 不做鉴权、**序列化去重（共享 presenter）另开变更**——它要同时改 4 处返回结构，混在本变更里会让 280 条测试的失败原因难以定位。
