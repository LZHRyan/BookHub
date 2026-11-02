# Design

## Context

当前 `chapters.format` 是章节级可选值（`markdown` | `html`），`books` 表没有格式字段（见 `app/models.py`、`openspec/specs/book-catalog/spec.md`）。要让"整本同格式"成立，必须把格式上移到 Book，并让章节在写入时只继承、不选择。约束：已有数据不能丢、API 只能加字段不能改语义、管理端表单要保持字段名与现有测试兼容。

## Goals / Non-Goals

**Goals:**

- Book 级格式成为唯一真相，章节写入路径全部经同一处校验。
- 存量数据平滑迁移：按现有章节推断格式，无章节的默认 `markdown`。
- 上传场景下"扩展名与 Book 类型不符"能给出明确错误，而不是落库后渲染异常。

**Non-Goals:**

- 不做"把已有 HTML 章节批量转换成 Markdown"（有损，且不是本需求）。
- 不引入第三种格式（如 AsciiDoc），也不做 Book 内分卷级格式。

## Decisions

### D1. 格式存 `books.format`，`chapters.format` 保留但被约束

保留 `chapters.format` 而不是删掉它：渲染、导出、API 都依赖它，且删除会让迁移与外部契约变复杂。写入时由服务层强制赋值为 `book.format`，读路径不受影响。

- 备选被否：删列 + 运行时从 Book 取 → API 章节表示会少字段（破坏兼容），且历史版本 `chapter_versions.format` 也要跟着改。

### D2. 迁移：加列 + 回填，SQLite/Postgres 通用

```sql
ALTER TABLE books ADD COLUMN format VARCHAR(16) NOT NULL DEFAULT 'markdown';
UPDATE books SET format = COALESCE(
  (SELECT c.format FROM chapters c WHERE c.book_id = books.id ORDER BY c.sort_order, c.id LIMIT 1),
  'markdown');
```

回填规则取"排序最靠前的章节"的格式；如果一本书里本来就有两种格式（历史数据），以第一章为准，其余章节**不改**（避免渲染结果突变），仅在管理端显示为"混合（历史数据）"提示，待管理员手动统一。

### D3. 校验放在服务层，Web 与测试共用

`books.create_book(format=...)` 校验取值；`books.update_book` 在 Book 有未删除章节时拒绝改格式（`ValidationFailed`）；`chapters.create_chapter/replace_content` 比对 `chapter.book.format`（或传入的 book），不一致抛 `ValidationFailed`。

- 备选被否：只在路由层校验 → 服务层仍可能被脚本绕过，且测试要重复写。

### D4. 表单：Book 选类型，章节只读展示

Book 表单新增 `<select name="format">`（必填、无空选项）。编辑有章节的 Book 时该字段 `disabled` 并附说明。章节表单把原来的 `<select name="format">` 换成只读徽章 + 说明（服务端忽略该字段，仍接受传入以兼容旧表单）。

### D5. 上传：先按扩展名判定，再与 Book 类型比对

`detect_format(filename)` 得出扩展名对应格式；与 `book.format` 不一致时抛 `ValidationFailed`，错误里带上"这个 Book 是 Markdown/HTML 类型"和实际文件名。文本粘贴路径直接使用 `book.format`，忽略表单提交值。

### D6. 演示数据与 e2e 拆成两本

`seed_demo` 的「研发手册」改为纯 Markdown；新增「HTML 章节示例」Book（`format=html`）承载 HTML 章节。`scripts/e2e_admin_flow.py` 相应改成：建一本 Markdown 书跑完整流程，再建一本 HTML 书验证 HTML 章节与净化。

## Risks / Trade-offs

- **历史混合数据的 Book 仍存在** → 迁移只回填 Book 格式，不强行改写章节；管理端显示"混合"警示，管理员可跑 `scripts/normalize_book_format.py`（本次提供只读报告模式）。
- **API 章节 `format` 与 Book 不一致的旧数据** → 导出 ZIP 按章节自身格式命名（保持行为），文档注明"历史数据可能混排"。
- **表单 `disabled` 字段不随提交发送** → 服务端 `update_book` 的 `format` 参数设为可选（`None` 表示不改），避免误清空。

## Migration Plan

1. 部署新镜像 → entrypoint 自动执行 `alembic upgrade head`（0002）。
2. 回滚：`alembic downgrade 0001` 会删除 `books.format` 列；旧版本代码不读该列，可安全回退。
3. 前端兼容：章节表单不再提交 `format` 也能工作（服务端取 Book 的值）。

## Open Questions

- 是否需要在管理端提供"把整本历史混排数据统一成 Book 格式"的一键操作（需要逐章转换，有损）——留待确认后再做。
