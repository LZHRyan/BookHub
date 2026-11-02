## MODIFIED Requirements

### Requirement: Webhook 登记 MUST 校验地址与事件

系统 MUST 支持登记回调地址，地址 MUST 是 `http://` 或 `https://` 的绝对 URL。登记时 MUST 至少订阅一个事件，事件取值来自固定集合（`chapter.published`、`chapter.unpublished`、`chapter.updated`、`section.published`、`section.updated`、`book.created`、`book.deleted`）。签名密钥 MUST 在创建时生成并只在创建响应里返回一次。

#### Scenario: 登记成功返回密钥

- **WHEN** 管理员登记一个订阅 `section.published` 的回调
- **THEN** 响应包含该 Webhook 的 id 与一次性返回的签名密钥
- **AND** 列表里能看到它但看不到密钥明文

#### Scenario: 非法地址与空事件被拒绝

- **WHEN** 提交的地址不是 http(s) 绝对 URL，或事件列表为空
- **THEN** 返回 4xx 并说明原因
- **AND** 不产生任何记录

### Requirement: 事件投递 MUST 带签名且可验证

每次投递 MUST 是 `POST`，`Content-Type: application/json`，请求体包含 `event`、`occurred_at`、`book`、`chapter` 与 `section`（如适用）。请求头 MUST 带 `X-BookHub-Event` 与 `X-BookHub-Signature`，签名是 `sha256=` 加上「密钥 + 原始请求体」的 HMAC-SHA256 十六进制。

#### Scenario: 签名可被接收方验证

- **WHEN** 接收方用同一密钥对原始请求体计算 HMAC-SHA256
- **THEN** 结果与 `X-BookHub-Signature` 的十六进制部分一致

#### Scenario: 事件体含最小上下文

- **WHEN** 某章被发布
- **THEN** 请求体里 `event` 为 `chapter.published`，该章每个可见节还会各收到一条 `section.published`
- **AND** 含该节的 `book_slug`、`chapter_slug`、`section_slug` 与版本号

### Requirement: 投递失败 MUST NOT 影响内容写入

投递 MUST 在内容写入成功之后进行，任一回调失败（超时、非 2xx、连接错误）MUST 只记录到投递记录里，MUST NOT 让保存请求失败或回滚数据。投递 MUST 记录状态码、错误摘要与尝试次数。

#### Scenario: 回调 500 不影响发布

- **WHEN** 章发布时回调返回 500
- **THEN** 章仍然发布成功
- **AND** 投递记录里该次尝试的状态码为 500 且可重试

#### Scenario: 停用的 Webhook 不投递

- **WHEN** Webhook 被删除（停用）
- **THEN** 后续事件不再向它投递
- **AND** 历史投递记录仍可查询

### Requirement: 失败投递 MUST 可手动重试

系统 MUST 提供重试入口：对某条投递记录重新发送同一请求体，并更新该记录的状态码、错误与尝试次数。

#### Scenario: 重试成功后状态更新

- **WHEN** 手动重试一条失败的投递且接收方返回 200
- **THEN** 该记录状态码变为 200、尝试次数 +1
- **AND** 不再出现在「最近失败」列表里
