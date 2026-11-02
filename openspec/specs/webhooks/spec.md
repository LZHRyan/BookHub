# webhooks Specification

## Purpose
让外部系统在内容发生变化时被动收到通知：可登记回调地址、按事件推送带签名的 JSON、并保留每次投递的结果以便排查与重试。

## Requirements

### Requirement: Webhook 登记 MUST 校验地址与事件

系统 MUST 支持登记回调地址，地址 MUST 是 `http://` 或 `https://` 的绝对 URL。登记时 MUST 至少订阅一个事件，事件取值来自固定集合（`chapter.published`、`chapter.unpublished`、`chapter.updated`、`section.published`、`section.updated`、`book.created`、`book.deleted`）。签名密钥 MUST 在创建时生成并只在创建响应里返回一次。

地址的**主机**同样 MUST 校验：MUST 拒绝 `localhost` 与 `*.localhost`、MUST 拒绝内网/本机/链路本地/保留地址的字面量 IP（含 IPv6 与云元数据地址），MUST 拒绝带用户名或密码的 URL。域名是否解析到内网 MUST 在投递时复查，登记阶段 MUST NOT 依赖 DNS（避免登记接口被 DNS 故障拖住）。

#### Scenario: 登记成功返回密钥

- **WHEN** 管理员登记一个订阅 `section.published` 的回调
- **THEN** 响应包含该 Webhook 的 id 与一次性返回的签名密钥
- **AND** 列表里能看到它但看不到密钥明文

#### Scenario: 非法地址与空事件被拒绝

- **WHEN** 提交的地址不是 http(s) 绝对 URL，或事件列表为空
- **THEN** 返回 4xx 并说明原因
- **AND** 不产生任何记录

#### Scenario: 内网与本机地址被拒绝

- **WHEN** 提交 `http://127.0.0.1:8080/hook`、`http://localhost/hook`、`http://[::1]/hook`、`http://169.254.169.254/latest/meta-data/` 或 `http://10.1.2.3/hook`
- **THEN** 每次都返回 400 并说明不能指向内网/本机
- **AND** 公网域名的登记仍然返回 201

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

投递 MUST NOT 在写事务内同步发出网络请求：事件 MUST 先以「待投递」记录落库，事务提交后才由后台执行（独立会话、独立线程）。事务回滚时对应的待投递记录 MUST 被丢弃、MUST NOT 发送。这样即使某个回调不可达（最长超时 5 秒），也不会占着数据库写锁或拖慢内容写入与启动流程。

#### Scenario: 回调 500 不影响发布

- **WHEN** 章发布时回调返回 500
- **THEN** 章仍然发布成功
- **AND** 投递记录里该次尝试的状态码为 500 且可重试

#### Scenario: 停用的 Webhook 不投递

- **WHEN** Webhook 被删除（停用）
- **THEN** 后续事件不再向它投递

#### Scenario: 提交前不发请求

- **WHEN** 内容写入产生了 webhook 事件但事务尚未提交
- **THEN** 没有任何 HTTP 请求被发出
- **AND** 提交之后才投递，且内容写入的响应时间不受回调 latency 影响

#### Scenario: 回滚的写入不投递

- **WHEN** 写入产生事件后事务被回滚
- **THEN** 对应的待投递记录被丢弃
- **AND** 不会发出任何 HTTP 请求

### Requirement: 失败投递 MUST 可手动重试

系统 MUST 提供重试入口：对某条投递记录重新发送同一请求体，并更新该记录的状态码、错误与尝试次数。

#### Scenario: 重试成功后状态更新

- **WHEN** 手动重试一条失败的投递且接收方返回 200
- **THEN** 该记录状态码变为 200、尝试次数 +1
- **AND** 不再出现在「最近失败」列表里

### Requirement: 投递 MUST 拒绝内网目标与重定向

每次投递前 MUST 解析目标主机；只要解析结果中任一地址属于内网/本机/链路本地/保留地址，MUST 放弃投递并记录失败原因，MUST NOT 向该地址发出请求。这样域名在登记后才把 A 记录改到内网（DNS rebinding）也无法借 Webhook 打内网。

投递 MUST NOT 跟随 3xx 重定向：重定向目标可以指向内网，绕过登记与投递时的地址校验。

#### Scenario: DNS rebinding 被拦下

- **WHEN** 已登记的域名在投递时解析到 `127.0.0.1`
- **THEN** 本次投递不发出任何 HTTP 请求，结果记为失败并说明解析到内网
- **AND** 内容写入本身不受影响

#### Scenario: 重定向不被跟随

- **WHEN** 回调地址返回 302 指向另一个地址
- **THEN** 客户端不跟随跳转，本次投递按非 2xx 记为失败
- **AND** 失败记录可被手动重试
