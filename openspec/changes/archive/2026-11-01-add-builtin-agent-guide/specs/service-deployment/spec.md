## ADDED Requirements

### Requirement: 启动 MUST 准备内置指南（可关闭）

启动流程在数据库迁移与初始管理员就绪之后 MUST 幂等准备内置《AI Agent 使用指南》。失败 MUST NOT 阻止服务对外提供（与其它启动准备项一致：记日志、继续启动）。`BUILTIN_GUIDE_ENABLED`（默认 `true`）为 `false` 时 MUST 跳过创建，MUST NOT 删除已存在的指南。启动日志 MUST 记录本次是否创建/补齐（`guide.ensured`），跳过时 MUST 说明原因（`guide.skipped`）。

#### Scenario: 默认开启时创建

- **WHEN** 未设置 `BUILTIN_GUIDE_ENABLED` 的实例首次启动
- **THEN** 启动日志出现 `guide.ensured`
- **AND** 站点里能读到 `ai-agent-guide`

#### Scenario: 关闭后不创建也不删除

- **WHEN** 设置 `BUILTIN_GUIDE_ENABLED=false` 后重启一个已有指南的实例
- **THEN** 不再尝试创建，也不产生重复内容
- **AND** 已存在的指南仍然可访问

#### Scenario: 准备失败不影响服务启动

- **WHEN** 创建指南过程中抛出异常（例如库暂时锁定）
- **THEN** 服务仍然完成启动并对外提供已有内容
- **AND** 错误被记入启动日志
