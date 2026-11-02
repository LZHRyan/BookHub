# Spec Delta

## Purpose

定义面向程序与 AI 工具的管理写接口 `/api/v1/admin/*`：覆盖哪些管理能力、如何鉴权与限权、请求与响应的形状、批量与破坏性操作的行为、并发与幂等语义、审计归属，以及可被模型直接消费的文档形态。

## ADDED Requirements

### Requirement: 管理端能力 MUST 通过 API 完整可得

`/api/v1/admin` MUST 提供与网页管理端等价的操作集合：Book 的创建、修改、软删除、恢复；章节的创建（含文件上传）、整体替换、发布/撤回、排序、软删除、恢复；版本列表、单版本读取、版本对比、回滚；回收站列表；账号创建、启用/停用、重置密码；站点设置读取与保存；审计日志查询。任何一条网页管理端能完成的写操作，MUST 都能通过 API 完成。

#### Scenario: 章节全生命周期可由 API 完成

- **WHEN** 客户端用有效凭据依次调用创建 Book、上传章节文件、替换内容、发布、回滚、删除、恢复
- **THEN** 每一步都返回成功且资源状态与网页端操作一致
- **AND** 网页端随后读取到的内容与 API 写入一致

#### Scenario: 设置与账号也可通过 API 维护

- **WHEN** 客户端读取站点设置并修改站点名，再创建一个 `editor` 账号
- **THEN** 设置与账号变更生效
- **AND** 首页标题与登录能力随之变化

### Requirement: 程序化调用 MUST 使用具备作用域的 Token 鉴权

管理写接口 MUST 要求 `Authorization: Bearer <token>`。Token MUST 具备作用域：`read` 只能查询、`write` 可读写内容（Book/章节/版本/回收站）、`admin` 额外可管理账号与站点设置。缺失或无效 Token MUST 返回 401；作用域不足 MUST 返回 403 且 MUST NOT 产生任何数据变更。Token MUST NOT 以明文形式存储。

#### Scenario: 无 Token 被拒绝

- **WHEN** 未携带 Authorization 头调用创建 Book 接口
- **THEN** 返回 401 与机器可读错误码
- **AND** 不产生 Book 记录

#### Scenario: 作用域不足被拒绝

- **WHEN** 使用仅含 `write` 作用域的 Token 调用创建账号接口
- **THEN** 返回 403 并说明需要 `admin` 作用域
- **AND** 不创建账号

### Requirement: 写操作 MUST 记录审计并归属到 Token

每一条成功的管理写操作 MUST 追加审计记录，包含 Token 名称（作为操作者）、动作、目标类型与标识、变更前后版本号、来源 IP 与时间。通过 API 产生的记录 MUST 可与其他来源区分。

#### Scenario: API 建章可追溯

- **WHEN** 使用名为 `docs-bot` 的 Token 创建章节
- **THEN** 审计日志中出现一条以 `docs-bot` 为操作者的 `chapter.create`
- **AND** 该记录标明来自 API 渠道

### Requirement: 破坏性操作 MUST 提供预览与显式确认

删除类操作 MUST 支持 `dry_run=true`：只返回将被影响的对象清单与数量，MUST NOT 改动数据。不带 `dry_run` 的真实删除 MUST 要求 `confirm=true`，否则 MUST 返回 400 并提示需要确认。删除 MUST 为软删除并可恢复。

#### Scenario: 预览不产生变更

- **WHEN** 以 `dry_run=true` 请求删除某章节
- **THEN** 返回该章节的标识与标题，且不改变其状态
- **AND** 随后读取该章节仍然成功

#### Scenario: 缺少确认被拒绝

- **WHEN** 请求删除章节但未提供 `confirm=true`
- **THEN** 返回 400 并说明需要显式确认
- **AND** 章节仍在原状态

### Requirement: 写接口 MUST 支持并发冲突检测

替换章节内容与修改 Book 时 MUST 接受基准版本（`base_version` 或 `If-Match`）。基准与当前版本不一致时 MUST 返回 409，MUST NOT 覆盖他人改动，MUST NOT 产生新版本。

#### Scenario: 过期基准被拒绝

- **WHEN** 客户端以 `base_version=3` 提交替换，而章节已是第 5 版
- **THEN** 返回 409 与冲突说明
- **AND** 章节仍是第 5 版的内容

### Requirement: 写接口 MUST 支持幂等重放

客户端可携带 `Idempotency-Key`。相同键与相同请求体在有效期内重复提交 MUST 返回首次结果且 MUST NOT 产生第二次副作用；相同键不同请求体 MUST 返回 409。未携带该头时按普通请求处理。

#### Scenario: 重试不产生重复章节

- **WHEN** 创建章节的请求因网络超时被原样重发，两次携带同一 `Idempotency-Key`
- **THEN** 第二次返回与第一次相同的章节标识与状态码
- **AND** 该 Book 下只新增一个章节

### Requirement: 文件上传 MUST 与服务端约束一致

创建或替换章节时 MUST 支持 `multipart/form-data` 上传单个文件。服务器 MUST 按 Book 的文档类型校验扩展名、按大小上限校验体积、自动识别编码（UTF-8/BOM/GB18030），失败时 MUST 返回机器可读错误且 MUST NOT 落库。

#### Scenario: 格式不符被拒绝

- **WHEN** 向 `markdown` 类型的 Book 上传 `.html` 文件
- **THEN** 返回 400 与明确错误码
- **AND** 不产生章节目录或版本记录

### Requirement: 响应 MUST 返回资源表示且错误 MUST 机器可读

成功响应 MUST 返回创建/更新后的资源表示（字段与只读 API 的表示一致，至少包含 id、slug、版本号与时间戳）。错误响应 MUST 使用统一结构 `{"error": {"code", "message", "request_id"}}`，并 MUST 区分参数错误、未认证、无权限、不存在、冲突与限流。

#### Scenario: 创建成功返回资源

- **WHEN** 创建章节成功
- **THEN** 响应包含该章节的 id、slug、format、version 与 published 状态

#### Scenario: 错误码可编程判断

- **WHEN** 请求一个不存在的 Book
- **THEN** 返回 404 且 `error.code` 为稳定的机器可读值

### Requirement: 接口 MUST 可被 AI 工具直接消费

OpenAPI 文档 MUST 覆盖全部管理写接口，每个操作 MUST 具备稳定的 `operationId`、中文 summary 与 description、显式的请求体与响应 Schema，并 MUST 标注所需作用域。文档 MUST NOT 依赖 HTML 表单或 CSRF 令牌等浏览器专有机制。

#### Scenario: 从 OpenAPI 生成工具定义

- **WHEN** 把 `/openapi.json` 交给支持 function calling 的模型
- **THEN** 每个管理操作都能生成一个参数完整、描述可理解的工具定义
- **AND** 调用该工具不会因为缺少浏览器凭据而失败

### Requirement: 管理写接口 MUST 独立限流

管理写接口 MUST 按 Token 限流，阈值独立于公共读接口；超限 MUST 返回 429 并带 `Retry-After`。限流 MUST NOT 因公共读流量增大而误伤。

#### Scenario: 按 Token 计数

- **WHEN** 同一 Token 在窗口内高频调用写接口超过阈值
- **THEN** 返回 429 与 `Retry-After`
- **AND** 换一个 Token 的请求不受影响

### Requirement: 批量操作 MUST 逐条返回结果

接受批量请求的接口 MUST 返回每条操作的结果与错误，MUST NOT 因单条失败而整体回滚或整体 500。部分失败时 MUST 返回可汇总的状态与逐条明细。

#### Scenario: 部分失败不影响其余

- **WHEN** 一次批量发布请求中包含一个不存在的章节
- **THEN** 其余章节发布成功
- **AND** 响应中该条目标记为失败并给出原因
