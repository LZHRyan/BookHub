# Spec Delta

## Purpose

让审计日志可以带过滤条件导出成表格文件供合规核对，并按可配置的保留期自动清理，避免无限增长。

## ADDED Requirements

### Requirement: 审计 MUST 支持带过滤条件的 CSV 导出

管理 API MUST 提供审计 CSV 导出，过滤条件 MUST 与审计查询一致（Book、操作者、动作、时间范围）。导出文件 MUST 是 UTF-8（带 BOM，便于 Excel 直接打开）且首行是表头，列 MUST 至少包含时间、操作者、动作、目标、Book、IP 与 detail。

#### Scenario: 导出带过滤条件

- **WHEN** 请求带 `book_id` 与 `actor` 参数的导出
- **THEN** 返回 CSV，只包含符合条件的记录
- **AND** 响应头 `Content-Type` 为 `text/csv`

#### Scenario: 无匹配时仍是合法 CSV

- **WHEN** 过滤条件没有命中任何记录
- **THEN** 返回只有表头的 CSV，状态码 200

### Requirement: 审计 MUST 按保留期清理

系统 MUST 支持配置审计保留天数（`AUDIT_RETENTION_DAYS`，默认 180，`0` 表示永久保留）。清理 MUST 在应用启动时执行一次，并 MUST 可通过管理 API 手动触发；手动触发默认只预览将被删除的条数与最老时间，确认后才删除。

#### Scenario: 启动时清理过期审计

- **WHEN** 应用中存在超过保留期的审计记录
- **THEN** 启动后这些记录被删除，并记录一条清理日志
- **AND** 保留期内的记录不受影响

#### Scenario: 手动清理默认预览

- **WHEN** 调用清理端点但未带确认参数
- **THEN** 返回将被删除的条数与最老记录时间
- **AND** 没有任何记录被删除

#### Scenario: 零表示永久保留

- **WHEN** `AUDIT_RETENTION_DAYS=0`
- **THEN** 启动与手动清理都不会删除任何审计记录
