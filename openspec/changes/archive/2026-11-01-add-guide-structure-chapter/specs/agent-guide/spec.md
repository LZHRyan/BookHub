## MODIFIED Requirements

### Requirement: 站点 MUST 自带一份 AI Agent 接入使用指南

每个实例 MUST 内置一本《AI Agent 接入使用指南》Book：固定访问标识 `ai-agent-guide`、文档类型 Markdown、可见性 public、创建后置顶。标题 MUST 表达「接入」这一用途（讲怎么把本库接进 Agent，而不是 Agent 原理），默认标题 MUST 为「AI Agent 接入使用指南」；标题默认值的变更 MUST 由数据迁移完成，且 MUST 只影响标题仍为旧默认值的内置 Book。

内容 MUST 用 Book → 章 → 节 组织（可被网页阅读、被 `/api/v1` 读取、被全文检索命中），并 MUST 覆盖六块：快速上手、**内容组织与上传格式要求**、HTTP API、MCP、SKILL、常见问题。其中「内容组织」MUST 讲清知识库 / 分组 / Book / 章 / 节 的层级与各自职责、一条资料该放在哪一层、页面地址与只读 API 的对应关系；「上传格式要求」MUST 讲清整本单一格式与接受的扩展名、编码识别、数量与体积上限、多文件与节的对应关系、图片附件的白名单与配额。

#### Scenario: 每一块内容都在

- **WHEN** 通读该书
- **THEN** 能找到「站点地址 + Token + 读写 curl」的快速上手
- **AND** 能找到分组 / Book / 章 / 节的层级说明、资料归位清单与页面地址到 API 的映射
- **AND** 能找到 Markdown 与 HTML 各自接受的扩展名、编码规则（UTF-8 / GB18030）、大小与个数上限、图片附件白名单
- **AND** 能找到作用域与 Book 范围、端点清单、一次完整的建书/写正文/读回/发布流程、格式与幂等规则
- **AND** 能找到 MCP 客户端配置与一份可直接运行的最小服务器代码，以及 `SKILL.md` 模板
- **AND** 能找到状态码语义、中文标题的 slug 回退与子路径部署说明

#### Scenario: 新实例启动后就有说明书

- **WHEN** 一个空库的实例完成启动
- **THEN** 存在 slug 为 `ai-agent-guide` 的 Book，标题为「AI Agent 接入使用指南」，其章依次为「开始之前 / 内容怎么组织 / 用 HTTP API / 接入 MCP / 接入 SKILL / 常见问题」
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

#### Scenario: 升级补章不挂在最后

- **WHEN** 一个老实例缺少「内容怎么组织」这一章，随后启动新版本
- **THEN** 该章被补到第 2 位，目录顺序与新装实例一致
- **AND** 只在确实新增章时重排一次，用户此前手工调整过的顺序不会被反复重置
