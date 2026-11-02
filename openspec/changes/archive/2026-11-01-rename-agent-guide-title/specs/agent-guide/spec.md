## RENAMED Requirements

- FROM: `### Requirement: 站点 MUST 自带一份 AI Agent 使用指南`
- TO: `### Requirement: 站点 MUST 自带一份 AI Agent 接入使用指南`

## MODIFIED Requirements

### Requirement: 站点 MUST 自带一份 AI Agent 接入使用指南

每个实例 MUST 内置一本《AI Agent 接入使用指南》Book，固定访问标识 `ai-agent-guide`，文档类型 Markdown，可见性 public，创建后置顶。标题 MUST 表达「接入」这一用途（不是讲 Agent 原理），且随系统创建的默认标题 MUST 为「AI Agent 接入使用指南」。内容 MUST 覆盖四类信息，且 MUST 用 Book → 章 → 节 的正常结构组织（可被网页阅读、被 `/api/v1` 读取、被全文检索命中）：

1. 快速上手：站点地址、Token、读写各一条 curl；
2. HTTP API：作用域与 Book 范围、端点清单、一次完整的「建书 → 写正文 → 读回 → 发布」流程、格式/幂等/上传/删除规则；
3. MCP：客户端配置示例，以及一份可直接运行的最小 MCP 服务器代码（工具至少覆盖检索、读节、建节、改节）；
4. SKILL：`SKILL.md` 模板与写作要点；

并 MUST 有一节常见问题，覆盖状态码语义、中文标题的 slug 回退、子路径部署的地址拼接。

标题的默认值变更 MUST 通过数据迁移落地：MUST 只改标题仍是旧默认值的 `is_builtin=1` 行，MUST NOT 覆盖管理员改过的标题，MUST NOT 影响 `is_builtin=0` 的用户书籍。

#### Scenario: 新实例启动后就有说明书

- **WHEN** 一个空库的实例完成启动
- **THEN** 存在 slug 为 `ai-agent-guide` 的 Book，标题为「AI Agent 接入使用指南」，其章为「开始之前 / 用 HTTP API / 接入 MCP / 接入 SKILL / 常见问题」
- **AND** 每章都是已发布状态，且至少有一节正文

#### Scenario: 说明书写到了 MCP 与 SKILL

- **WHEN** 读取「接入 MCP」与「接入 SKILL」两章的正文
- **THEN** 前者包含客户端配置 JSON 与含 `FastMCP` 的服务端代码，后者包含 `SKILL.md` 的完整模板
- **AND** 「用 HTTP API」一章包含带 `/api/v1/admin` 的调用示例与端点表

#### Scenario: 读者与 API 都能读到

- **WHEN** 访客打开 `/b/ai-agent-guide`，或外部程序请求 `GET /api/v1/books/ai-agent-guide`
- **THEN** 都能拿到完整目录与正文
- **AND** 全文检索也能命中其中内容

#### Scenario: 升级时只改未编辑过的标题

- **WHEN** 一个存量实例的内置指南标题仍为「AI Agent 使用指南」，执行升级
- **THEN** 标题变为「AI Agent 接入使用指南」
- **AND** 管理员改过标题的内置书、以及 slug 相同的用户书籍保持原样
