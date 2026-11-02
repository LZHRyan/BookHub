## ADDED Requirements

### Requirement: 站点 MUST 自带一份 AI Agent 使用指南

每个实例 MUST 内置一本《AI Agent 使用指南》Book，固定访问标识 `ai-agent-guide`，文档类型 Markdown，可见性 public，创建后置顶。内容 MUST 覆盖四类信息，且 MUST 用 Book → 章 → 节 的正常结构组织（可被网页阅读、被 `/api/v1` 读取、被全文检索命中）：

1. 快速上手：站点地址、Token、读写各一条 curl；
2. HTTP API：作用域与 Book 范围、端点清单、一次完整的「建书 → 写正文 → 读回 → 发布」流程、格式/幂等/上传/删除规则；
3. MCP：客户端配置示例，以及一份可直接运行的最小 MCP 服务器代码（工具至少覆盖检索、读节、建节、改节）；
4. SKILL：`SKILL.md` 模板与写作要点；

并 MUST 有一节常见问题，覆盖状态码语义、中文标题的 slug 回退、子路径部署的地址拼接。

#### Scenario: 新实例启动后就有说明书

- **WHEN** 一个空库的实例完成启动
- **THEN** 存在 slug 为 `ai-agent-guide` 的 Book，其章为「开始之前 / 用 HTTP API / 接入 MCP / 接入 SKILL / 常见问题」
- **AND** 每章都是已发布状态，且至少有一节正文

#### Scenario: 说明书写到了 MCP 与 SKILL

- **WHEN** 读取「接入 MCP」与「接入 SKILL」两章的正文
- **THEN** 前者包含客户端配置 JSON 与含 `FastMCP` 的服务端代码，后者包含 `SKILL.md` 的完整模板
- **AND** 「用 HTTP API」一章包含带 `/api/v1/admin` 的调用示例与端点表

#### Scenario: 读者与 API 都能读到

- **WHEN** 访客打开 `/b/ai-agent-guide`，或外部程序请求 `GET /api/v1/books/ai-agent-guide`
- **THEN** 都能拿到完整目录与正文
- **AND** 全文检索也能命中其中内容

### Requirement: 内置指南 MUST 幂等创建且不覆盖既有内容

创建 MUST 是幂等的：重复启动 MUST NOT 产生重复的 Book、章或节。已存在的章与节 MUST NOT 被覆盖——站内编辑以用户为准。升级带来的**新增**章/节 MUST 能补进已有实例。若 `ai-agent-guide` 已被用户自己的 Book 占用，系统 MUST 放弃创建（MUST NOT 抢注、MUST NOT 改名用户的书），并在启动日志中说明原因。

#### Scenario: 重启不重复

- **WHEN** 同一实例连续启动两次
- **THEN** 该书仍是 5 章 10 节，章与节的 id 不变

#### Scenario: 用户改动被保留

- **WHEN** 管理员把「接入 MCP」某节改成自己的文字，随后重启
- **THEN** 该节正文仍是管理员改过的内容
- **AND** 若库里缺了某一节（例如直接删库），重启后这一节会被补回

#### Scenario: slug 被占用时让路

- **WHEN** 库中已存在一本 slug 为 `ai-agent-guide` 的普通 Book（`is_builtin=false`）
- **THEN** 系统不修改这本书，也不创建指南
- **AND** 启动日志记录跳过原因

### Requirement: 内置指南 MUST 随系统生命周期存在

该书 MUST NOT 被软删除或物理删除；访问标识与文档类型 MUST 锁定；其中的章与节 MUST NOT 被删除。标题、简介、可见性、图标、正文 MUST 仍可编辑，章与节的顺序与发布状态 MUST 可调整（撤回即对访客隐藏）。拒绝 MUST NOT 是静默失败：接口 MUST 返回 400 并说明原因，网页端 MUST NOT 展示删除入口。

#### Scenario: 删整本被拒绝

- **WHEN** 用 `write` 作用域的 Token 调用 `POST /api/v1/admin/books/ai-agent-guide/delete?confirm=true`
- **THEN** 返回 400，消息说明内置指南不能删除
- **AND** 该书仍在列表与站点地图中

#### Scenario: 删章或删节被拒绝

- **WHEN** 删除该书下任意章或节
- **THEN** 返回 400 并说明内置指南的章/节不能删除
- **AND** 目录结构不变

#### Scenario: 标识与格式锁定但内容可改

- **WHEN** 尝试把 slug 改成别的值或把 format 改成 html
- **THEN** 返回 400；改标题、简介、可见性、正文仍然成功

#### Scenario: 网页端不给删除入口

- **WHEN** 管理员打开内容管理首页与该书详情页
- **THEN** 卡片与详情上显示「内置指南」标记
- **AND** 页面上没有该书的删除表单，章与节的删除按钮也不出现
