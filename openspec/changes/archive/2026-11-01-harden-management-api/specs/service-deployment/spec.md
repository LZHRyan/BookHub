## MODIFIED Requirements

### Requirement: 配置 MUST 全部来自环境变量

所有运行配置 MUST 通过环境变量提供，且 MUST 随仓库提供一份覆盖全部配置项、默认值与说明的示例清单。缺少必需配置时进程 MUST 启动失败，并以明确的错误信息指出缺失的配置项；MUST NOT 使用不安全的内置默认值静默启动。

其中与安全直接相关的两项 MUST 可配置且默认取安全值：

- `TRUSTED_PROXIES`：可信反向代理的 IP/CIDR 列表，非法条目 MUST 让启动失败；默认为空，表示**不采信任何** `X-Forwarded-For` / `X-Real-IP`，客户端 IP 取直连 peer。
- `MAX_UPLOAD_FILES`：单次批量上传的文件个数上限，默认 50。

#### Scenario: 缺少必需配置时启动失败并指名

- **WHEN** 部署者未提供会话签名密钥等必需配置就启动容器
- **THEN** 容器以非零退出码退出
- **AND** 日志明确指出缺少哪一项配置，且服务未对外监听

#### Scenario: 未提供的可选配置使用默认值

- **WHEN** 部署者只提供必需配置，未设置可选配置项
- **THEN** 服务使用文档中声明的默认值正常启动
- **AND** 启动日志可看出各配置项的实际生效值（敏感值除外）

#### Scenario: 未配置可信代理时不采信转发头

- **WHEN** 部署未设置 `TRUSTED_PROXIES`，请求携带伪造的 `X-Forwarded-For`
- **THEN** 限流与审计使用直连地址，伪造头被忽略
- **AND** 伪造不同取值不会换来新的限流额度

#### Scenario: 配了可信代理才采信转发头

- **WHEN** `TRUSTED_PROXIES` 包含反向代理所在网段，且直连 peer 落在该网段
- **THEN** `X-Forwarded-For` 的第一跳被用作客户端 IP
- **AND** 不在该网段的直连请求即使带该头也仍取直连地址

#### Scenario: 非法的可信代理条目让启动失败

- **WHEN** `TRUSTED_PROXIES` 中出现不是合法 IP 或 CIDR 的条目
- **THEN** 配置解析失败并给出明确的配置错误信息
- **AND** 服务不启动
