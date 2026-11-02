# Tasks

## 1. 数据与身份

- [x] 1.1 `books` 增加 `is_builtin`（迁移 `0017_book_builtin`，存量 false）
- [x] 1.2 `app/services/builtin.py`：`BUILTIN_SLUG` / `BUILTIN_TITLE` / `is_builtin()` / 三个守卫（删整本、改标识、删章节）
- [x] 1.3 守卫只认列上的标记：slug 相同不代表内置（用户同名书不能被误锁）

## 2. 内容与创建

- [x] 2.1 `app/services/guide.py`：5 章 10 节的 Markdown 内容（API / MCP / SKILL / FAQ）
- [x] 2.2 `ensure_guide()`：不存在则整本创建（pinned、published、Markdown、默认分组）
- [x] 2.3 已存在则只补缺失的章/节，不覆盖用户编辑；slug 被用户书占用时返回 None 不抢
- [x] 2.4 `find_guide()` 供 `/api/v1/site` 使用

## 3. 约束接入

- [x] 3.1 `books.soft_delete_book()` / `update_book()`（slug、format）走守卫
- [x] 3.2 `chapters.soft_delete_chapter()` / `sections.delete_section()` 走守卫
- [x] 3.3 网页端：仪表盘与 Book 详情显示「内置指南」，隐藏删除按钮；节列表隐藏删除；Book 编辑页 slug 只读 + 说明

## 4. 对外暴露

- [x] 4.1 `GET /api/v1/site` 增加 `guide`（slug / title / url / api_url）
- [x] 4.2 Book 表示（`/api/v1` 与管理 API）增加 `is_builtin`
- [x] 4.3 `BUILTIN_GUIDE_ENABLED`（默认 true）+ `.env.example` + `/meta` 之外的配置文档

## 5. 验证

- [x] 5.1 `tests/test_guide.py`：结构完整、内容含 MCP/SKILL/API、幂等、补齐不覆盖、不可删、标识锁定、同名不抢、site 暴露、网页标记
- [x] 5.2 全量 `pytest` + `ruff` 通过
- [x] 5.3 容器实测：启动后 `/b/ai-agent-guide` 可读、`site.guide` 有值、删除返回 400
- [x] 5.4 文档同步（ai / api / admin / deploy）
