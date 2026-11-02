# Spec Delta

## ADDED Requirements

### Requirement: 程序化访问 MUST 通过 API Token 完成

除人类会话登录外，系统 MUST 支持以 API Token 作为身份来源。Token MUST 可命名、可设作用域（`read` / `write` / `admin`）、可选过期时间、可吊销；创建时 MUST 只显示一次明文，数据库 MUST 只保存不可逆哈希。系统 MUST 记录每个 Token 的最近使用时间与创建者。

#### Scenario: 创建后只显示一次

- **WHEN** 管理员在管理端创建一个 Token 并离开页面
- **THEN** 明文只在创建成功时显示，之后无法再次查看
- **AND** 列表中只显示名称、作用域、创建时间与最近使用时间

#### Scenario: 吊销后立即失效

- **WHEN** 管理员吊销某个 Token 后，客户端再用它调用接口
- **THEN** 请求被拒绝（401）
- **AND** 不影响其他 Token 与人类会话

#### Scenario: 过期 Token 不可用

- **WHEN** 使用已超过过期时间的 Token 调用接口
- **THEN** 返回 401 并说明凭据已过期
