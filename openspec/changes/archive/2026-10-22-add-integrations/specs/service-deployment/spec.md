# Spec Delta

## ADDED Requirements

### Requirement: Webhook MUST 通过管理 API 管理

管理 API MUST 提供 Webhook 的列表、创建、删除、测试投递、以及失败投递的重试端点。创建 MUST 返回一次性密钥；删除 MUST 为停用（保留历史投递记录）。全部操作 MUST 复用 `admin` 作用域与审计约定。

#### Scenario: 创建与列表

- **WHEN** 使用 `admin` 作用域创建 Webhook
- **THEN** 返回 201，含 id、`secret`（仅此一次）与订阅的事件
- **AND** 列表返回的项不含 `secret`

#### Scenario: 测试投递

- **WHEN** 调用某 Webhook 的测试端点
- **THEN** 立即向该地址发送一条 `webhook.test` 事件
- **AND** 响应里返回该次投递的状态码或错误

#### Scenario: 重试失败投递

- **WHEN** 调用某条投递记录的重试端点
- **THEN** 重新发送同一请求体并更新记录
- **AND** 返回新的状态码与尝试次数

### Requirement: CI MUST 校验 lint、测试与镜像构建

仓库 MUST 提供持续集成工作流：安装依赖后执行 `ruff check`、`pytest`，并构建 Docker 镜像。任一步失败 MUST 让工作流失败。工作流 MUST 不需要任何密钥即可跑通（测试使用临时 SQLite 与内存数据）。

#### Scenario: 推送触发校验

- **WHEN** 向仓库推送提交
- **THEN** CI 依次执行 lint、测试与镜像构建
- **AND** 测试使用仓库内的 `.venv` 之外的干净环境安装依赖
