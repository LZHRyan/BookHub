# Design

## Context

`book_form.html` 用一个模板同时服务新建与编辑（`mode` 变量区分），slug 段落目前两者都渲染。服务层 `create_book(slug_raw="")` 已经会调用 `resolve_slug()` 自动生成；`book_new_submit` 的 `slug: str = Form(default="")` 在字段缺失时也拿得到空串。

## Goals / Non-Goals

**Goals:**

- 新建流程不出现 slug，减少一次无意义决策；不影响编辑期改 URL 的能力。
- 对旧客户端保持兼容（仍接受可选 `slug` 表单字段）。

**Non-Goals:**

- 不改变 slug 生成规则与唯一性策略。
- 不把 slug 从数据库或 API 中隐藏（它仍是 URL 与 API 的定位键）。

## Decisions

- **模板层用 `{% if mode == 'edit' %}` 包住 slug 字段**，而不是新增一套表单：改动最小、两个模式仍共享字段顺序与样式。
- **处理器保留 `slug` 参数**：删除它会让带 `slug` 的旧表单/脚本 400；保留后仍可被显式指定（测试与脚本需要）。
- 编辑页的 slug 说明里明确"改动会让旧链接失效"，避免误操作。

## Risks / Trade-offs

- **中文标题一律得到 `book-xxxxxx`**：这是既有设计（拼音转写不在本期），编辑页可改；新建页不再提供修改入口，属于有意取舍。
- **同时创建同名 Book**：`resolve_slug()` 的冲突后缀逻辑不变，两个都叫「运维手册」会得到 `book-aaa111` 与 `book-bbb222`。

## Migration Plan

纯模板变更，重建镜像即可；无数据迁移。回滚 = revert。

## Open Questions

无。
