# Proposal

## Why

管理端现在只有 HTML 表单 + 会话 Cookie + CSRF 一条路径：人可以点，程序点不了。这带来三个现实问题——(1) 想把 AI 工具（Claude/Cursor/自研 agent）接进来批量整理文档时，没有任何稳定的机器接口；(2) 几十个章节的批量建、批量改状态只能靠人一遍遍点；(3) CI 或脚本想同步文档，只能绕过应用直接改库或模拟表单提交，既脆弱又容易漏审计。既然读侧已经有 `/api/v1`，写侧也应该有一套等价、可鉴权、可审计、对模型友好的接口。

## What Changes

- **新增管理写 API `/api/v1/admin/*`**，逐一覆盖现有 29 个管理端操作：Book 增改删/恢复、章节新建（含文件上传）/替换/发布撤回/排序/删除/恢复、版本列表/详情/对比/回滚、回收站、账号增改停用重置、站点设置、审计查询。
- **新增程序化凭据**：API Token（`Authorization: Bearer <token>`），数据库只存哈希、可命名、可设作用域（`read` / `write` / `admin`）、可设过期、可吊销、记录最近使用时间；管理端新增「API Token」页面用于签发与吊销。现有 `API_KEY`（公共读）与人类会话不受影响。
- **为 AI 工具设计的契约面**：稳定的 `operationId`、中文 summary/description、显式请求/响应 Schema、机器可读错误码；破坏性操作支持 `dry_run` 预览与必填 `confirm`；批量接口返回逐条结果而不是整体失败。
- **并发与幂等**：写接口接受 `base_version`（章节）与 `If-Match`；支持 `Idempotency-Key`，重放同一请求返回同一结果，避免 AI 重试造成重复章节。
- **审计与可追溯**：每条写操作记 `actor = token 名称`、`via = api`、目标对象与版本变化；Token 的 `last_used_at` 同步更新。
- **文档**：`docs/ai.md` 给出工具清单、调用示例与提示词片段，说明如何把 OpenAPI 直接交给模型做 function calling。

## Capabilities

### New Capabilities

- `management-api`: 面向程序的管理写接口契约——覆盖范围、鉴权与作用域、请求/响应形状、批量与逐条结果、破坏性操作护栏、并发与幂等、审计归属、错误模型、OpenAPI 可发现性。

### Modified Capabilities

- `admin-auth`: 在人类会话之外，新增「程序化凭据（API Token）」这一身份来源：作用域、过期、吊销、哈希存储与最后使用时间。

## Impact

- **数据**：新增 `api_tokens` 表（名称、哈希、作用域、过期、吊销、创建者、最近使用）与 `idempotency_keys` 表（键、请求指纹、响应快照、过期），各带一个迁移。
- **代码**：新增 `app/api/admin.py`（路由）、`app/services/tokens.py`（签发/校验/吊销）、`app/api/deps.py`（Bearer 认证与作用域依赖）、`app/services/idempotency.py`；`app/web/admin.py` 增加 Token 管理页面（HTML 侧）。
- **接口**：新增 `/api/v1/admin/**`；`/openapi.json` 增加 `admin` tag 与操作定义；公共读 API 与 `API_KEY` 语义不变。
- **安全**：Token 只显示一次、库内存哈希；作用域最小化；破坏性操作二次确认；软删除保证可恢复；所有写操作限流并审计。
- **测试**：新增管理 API 的端到端用例（鉴权、作用域、CRUD、上传、并发冲突、幂等、dry_run、审计归属），并确保现有 207 个用例不回归。
- **协作注意**：当前仓库有并行会话在改 `app/web/admin.py` 与 `app/services/books.py`，本变更实现需等这些改动落盘后再动，避免覆盖。
