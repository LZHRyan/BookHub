# Proposal

## Why

管理 API 已经能改写全站内容，但「一个 Token 能干所有事」这件事在对接 AI 工具后成了最大的风险：给某个团队/某个机器人发一个 `write` Token，它就能改所有 Book，包括它根本不该碰的。审计日志也只进不出——想拿去做季度合规核对只能手写脚本查库，日志本身还会无限增长。

## What Changes

- **Token 可按 Book 限定范围**：签发 Token 时可勾选它能操作的 Book（不选 = 全部）。带范围的 Token 访问其他 Book 的管理端点 MUST 返回 403，且只读与写入端点同样受限。
- **审计可导出**：新增 `GET /api/v1/admin/audit.csv`（可带与查询接口相同的过滤条件）与审计页「导出 CSV」链接，输出 UTF-8 BOM 的 CSV 以兼容 Excel。
- **审计保留策略**：新增 `AUDIT_RETENTION_DAYS`（默认 180，`0` 表示永久保留），启动时按它清理过期审计，并提供管理 API 手动触发清理（默认预览）。
- **Token 过期与闲置提醒**：Token 列表展示「已过期 / N 天后过期 / 超过 N 天未使用」标记，签发页说明范围与过期设置的影响。

## Capabilities

### New Capabilities

- `token-scoping`: Token 的授权范围语义——按 Book 限定的读写边界、越界时的错误、签发与修改范围的方式，以及范围在审计里的可辨识性。
- `audit-retention`: 审计日志的导出（过滤条件、CSV 形态、编码）与保留清理（保留期、清理时机、预览与确认）。

### Modified Capabilities

- `management-api`: Token 创建 MUST 接受 Book 范围，Token 表示 MUST 暴露范围；审计 MUST 支持 CSV 导出与保留清理端点。
- `admin-auth`: Token 的授权判定 MUST 同时考虑作用域与 Book 范围。

## Impact

- **数据**：迁移 `0012_token_book_scope`（`api_tokens.book_scope` TEXT 默认 `""`，存逗号分隔的 Book id）。
- **服务层**：`tokens.issue_token(book_ids=...)`、`tokens.book_scope_of()`、`tokens.describe()` 补范围；新增 `audit.export_rows()` 与 `audit.cleanup()`。
- **鉴权**：`app/api/deps.py` 的 `require_scope` 依赖在拿到 `book_ref` 路径参数时校验范围（一处收口，覆盖全部 Book 级端点）。
- **配置**：`AUDIT_RETENTION_DAYS`，写入 `public_dict()` 与 `.env.example`；启动任务调用清理。
- **UI**：Token 页签发表单加 Book 多选、列表加范围列与过期/闲置标记；审计页加导出按钮。
- **测试**：`tests/test_governance.py`（范围拦截、导出 CSV、保留清理、Token 表示）。
- **非目标**：不做按章节/按操作细粒度授权、不做审计写入外部系统、不做 Token 自助轮换。
