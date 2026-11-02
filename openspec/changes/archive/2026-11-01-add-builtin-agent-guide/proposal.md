## Why

知识库已经把「给 AI 读写」做完整了（管理 API、Token 作用域、MCP 可接），但怎么用这件事只写在仓库的 `docs/ai.md` 里：读者进站点看不到，AI 工具第一次连上来也无从知道「这个库的接口长什么样、该配哪个 MCP、SKILL 怎么写」。结果每个接入方都要人工带一遍。

一个新建的实例应该自带一份说明书，而且这份说明书本身就该是知识库里的一本书——用同一套 Book / 章 / 节结构组织，读者能读、API 能取、AI 能检索。

## What Changes

- 新增**内置 Book**《AI Agent 使用指南》：固定 slug `ai-agent-guide`，Markdown，首页置顶，启动时幂等创建。
- 内容覆盖四件事（5 章 10 节）：
  1. 这本书是什么 + 30 秒版快速上手（curl 三连）；
  2. HTTP API：Token 与作用域、端点清单、写一篇文档并读回、必须知道的规则（格式/范围/幂等/上传/删除）；
  3. MCP：为什么接、客户端配置 JSON、一份可直接跑的 80 行最小 MCP 服务器（`FastMCP`，5 个工具）；
  4. SKILL：`SKILL.md` 模板与写作要点；
  5. 常见问题：状态码对照、中文标题的 slug、子路径部署、这本书能不能删。
- **跟随系统生命周期**：整本不可删除，访问标识与文档类型锁定，章与节也不可删除（可改正文、加节、排序、发布/撤回）。约束在服务层强制，网页端与 API 得到同一个拒绝原因；网页端隐藏删除按钮并显示「内置」标记。
- **升级不覆盖**：`ensure_guide()` 只补库里完全没有的章/节，用户改过的正文保持原样；slug 被用户自己的书占用时放弃创建而不是抢注。
- 对外可发现：`GET /api/v1/site` 增加 `guide`（`slug` / `title` / `url` / `api_url`），Book 表示增加 `is_builtin`；`BUILTIN_GUIDE_ENABLED`（默认 `true`）可关掉创建。

## Impact

- 新增能力规格 `agent-guide`；修改 `book-catalog`（内置 Book 的不可变性）、`content-api`（`site.guide` 与 `is_builtin`）、`service-deployment`（启动步骤与新配置项）。
- 代码：`app/services/{builtin,guide}.py`（新增）、`app/services/{books,chapters,sections}.py`（删除/标识守卫）、`app/api/{v1,admin}.py`、`app/main.py`、`app/config.py`、`alembic/versions/0017_book_builtin.py`、`app/templates/admin/{dashboard,book_detail,chapter_form,book_form}.html`。
- 数据：`books` 增加 `is_builtin`（存量全为 false，无需回填）。
- 测试：新增 `tests/test_guide.py`（创建/幂等/补齐/不可删/标识锁定/同名不抢/site 暴露/网页标记）；测试辅助 `make_settings` 默认关闭内置指南，避免影响既有断言。
- 文档：`docs/ai.md`（先读指南）、`docs/api.md`（`guide` 与 `is_builtin`）、`docs/admin.md`、`docs/deploy.md`、`.env.example`。
