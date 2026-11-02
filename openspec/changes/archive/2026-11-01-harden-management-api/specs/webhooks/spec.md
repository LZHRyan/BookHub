## MODIFIED Requirements

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

## ADDED Requirements

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
