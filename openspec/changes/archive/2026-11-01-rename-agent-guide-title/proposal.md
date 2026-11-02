## Why

内置的这本书原来的名字是《AI Agent 使用指南》，读起来像是「讲 AI Agent 怎么用」的读物，实际内容却是「怎么把这个知识库接进 AI Agent」：Token 与作用域、HTTP 读写闭环、MCP 服务器配置与代码、SKILL 模板。名字里缺了「接入」，第一次看到的人（和模型）容易误判它的用途。

## What Changes

- 标题改为《AI Agent 接入使用指南》，访问标识 `ai-agent-guide` 不变（外部链接与 MCP 配置不受影响）。
- 新增数据迁移 `0018_guide_title`：把仍是**旧默认标题**的内置 Book 改名。管理员自己改过标题的保留其版本；`is_builtin=0` 的用户书籍一律不动。
- 新建实例直接使用新标题（`BUILTIN_TITLE` 常量）。
- 文档与规格同步（ai / api / admin / deploy、`agent-guide` 能力名、`content-api` 与 `service-deployment` 的措辞）。

## Impact

- 代码：`app/services/builtin.py`（标题常量）、`alembic/versions/0018_guide_title.py`（数据迁移）。
- 数据：只影响 `is_builtin=1 AND title='AI Agent 使用指南'` 的行；可回滚（downgrade 改回旧标题）。
- 兼容性：slug、URL、`/api/v1/site` 的 `guide` 结构都不变，纯展示层改名。
