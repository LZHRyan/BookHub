# Tasks

## 1. 数据与配置

- [x] 1.1 `ApiToken.book_scope`（TEXT 默认 `""`）+ 迁移 `0012_token_book_scope`（直接加列，含 downgrade）
- [x] 1.2 `Settings.audit_retention_days`（默认 180，0 = 永久），写入 `public_dict()` 与 `.env.example`

## 2. 鉴权

- [x] 2.1 `tokens.issue_token(book_ids=...)` / `book_scope_of()` / `describe()` 补范围
- [x] 2.2 `Principal.book_scope`，`require_scope` 在存在 `book_ref` 路径参数时校验范围并返回 403
- [x] 2.3 单测：范围内读写放行、范围外读写 403、全站级端点不受影响、空范围 = 全部

## 3. 审计导出与保留

- [x] 3.1 `audit.query_rows()` 抽出共用过滤；查询端点改用它
- [x] 3.2 `audit.export_csv()`：UTF-8 BOM、表头、limit 上限；`GET /api/v1/admin/audit.csv`
- [x] 3.3 `audit.cleanup(days)`：返回删除条数 / 最老记录 / 截止时间；启动任务调用；`POST /api/v1/admin/audit/cleanup`（默认预览）
- [x] 3.4 单测：导出过滤与空结果、BOM、保留期清理、`0` 不删、预览不删

## 4. 管理端界面

- [x] 4.1 Token 页：签发表单加 Book 多选；列表加「范围」「过期/闲置」标记
- [x] 4.2 审计页：加「导出 CSV」链接（带上当前过滤条件）
- [x] 4.3 页面测试：Token 页显示范围、审计页有导出链接

## 5. 文档

- [x] 5.1 `docs/ai.md`：Token 范围、导出与清理端点
- [x] 5.2 `docs/admin.md` 或 `docs/authoring.md`：怎么用范围 Token 对接团队/AI 工具
- [x] 5.3 `docs/deploy.md`：`AUDIT_RETENTION_DAYS` 说明；`README.md` 功能清单

## Workflow follow-up

- `openspec validate add-governance --strict` 通过后归档该变更，并把归档目录提交入库。
