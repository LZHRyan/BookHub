# Design

## Context

`app/api/deps.py` 的 `require_scope(needed)` 是全部管理端点的统一入口：它解析 `Authorization: Bearer`、校验作用域、按 Token 限流，并返回鸭子类型兼容 `User` 的 `Principal`。审计写入统一走 `app/services/audit.record()`，查询在 `app/api/admin.py::audit_log` 与网页端 `admin/audit.html`。启动任务在 `app/main.py::_startup_tasks` 里已经做了幂等键清理，可复用同一位置。动机见 `proposal.md`。

## Goals / Non-Goals

**Goals:**

- 一处收口实现 Book 级授权，避免在每个端点重复判断。
- 审计导出复用既有过滤语义，不做第二套查询。
- 清理有预览、有审计、默认安全。

**Non-Goals:**

- 章节级、动作级授权；Token 自助轮换；审计外送（SIEM/Webhook）。

## Decisions

### D1. 范围存 `api_tokens.book_scope`（逗号分隔 id），在 `require_scope` 里统一校验

`book_scope` 为空字符串表示「全部 Book」。校验点放在 `require_scope` 生成的依赖里：

```python
ref = request.path_params.get("book_ref")
if ref and principal.book_scope:
    book = books_service.get_book(session, ref, include_deleted=True)
    if book.id not in principal.book_scope: raise Forbidden(...)
```

- **理由**：所有 Book 级端点都带 `{book_ref}` 路径参数，一处判断即覆盖全部读写端点；全站级端点（`/meta`、`/users`、`/tokens`）没有该参数，天然不受影响——这正是期望语义。
- **备选**：每个端点显式传 `book=...` 给依赖——要改 20 多个签名，且容易漏。
- 存 id 而不是 slug：Book 改 slug 后范围不会静默失效。

### D2. 签发时接受 slug 或 id，落库统一成 id

`tokens.issue_token(book_ids=[...])` 由调用方（网页表单 / API）先把 slug 解析成 id；解析失败直接 400，不产生 Token。

- **理由**：网页表单里人选的是 slug，API 调用者可能用 id；统一在入口解析，存储层只认 id。

### D3. 审计导出走同一套过滤函数

把现有查询条件抽成 `audit.query_rows(session, book_id, actor, action, since, until, limit)`，查询端点与导出端点都调它；导出用 `csv.writer` 写入 `io.StringIO`，响应加 BOM。

- **理由**：过滤语义只有一份，避免「页面查到 30 条、导出 42 条」这种对不上账的情况。
- BOM 是为了 Excel 直接双击打开不乱码（`\ufeff` 前缀）。

### D4. 保留清理：启动时 + 手动端点，阈值来自配置

`AUDIT_RETENTION_DAYS`（默认 180，0 = 永久）。`audit.cleanup(session, days)` 返回 `{deleted, oldest, cutoff}`；`days == 0` 直接返回 0。

- **理由**：知识库是低写入系统，启动时清一次足够；手动端点给「刚导完，想立刻释放空间」的场景。
- **备选**：后台定时任务——需要调度器，收益不足。

### D5. 过期与闲置标记在展示层算

Token 列表根据 `expires_at` 与 `last_used_at` 计算「已过期 / N 天后过期 / 超过 30 天未使用」，不落库、不新增字段。

## Risks / Trade-offs

- [范围只按 Book 划分，粒度粗] → 明确写在文档里；更细的授权需要新模型，当前用「多签发几个 Token」应对。
- [CSV 导出可能很大] → 加 `limit` 上限（默认 10000 行）并在文档说明；超出时截断并在首行注释列数。
- [启动清理误删] → 删的是超过保留期的数据，且有 `deleted` 日志；`0` 可关闭。
- [BOM 让某些脚本解析首列带 `\ufeff`] → 文档说明；Python `csv` 读时用 `utf-8-sig` 即可。

## Migration Plan

1. `0012_token_book_scope`：`ALTER TABLE api_tokens ADD COLUMN book_scope TEXT NOT NULL DEFAULT ''`（无外键，SQLite 可直接加列）。
2. 存量 Token 的 `book_scope` 为空 = 全部 Book，行为不变。
3. 回滚：删列后范围信息丢失，Token 退回全站权限——回滚前应先吊销带范围的 Token。
