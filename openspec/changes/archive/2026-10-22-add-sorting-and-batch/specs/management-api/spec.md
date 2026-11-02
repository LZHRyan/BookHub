# Spec Delta

## ADDED Requirements

### Requirement: 排序与置顶 MUST 通过管理 API 可得

管理 API MUST 提供「按有序 id 整体重排」与「Book 置顶开关」两个写操作，MUST 沿用既有的 Token 作用域、幂等重放、`dry_run` 预览与审计归属约定；重排 MUST 校验 id 集合与该父级一致。

#### Scenario: 重排成功返回新顺序

- **WHEN** 使用具备 `write` 作用域的 Token 提交某父级的有序 id 列表
- **THEN** 响应中返回该父级的新顺序
- **AND** 只读 API 的 Book 目录随之变化

#### Scenario: 置顶通过 PATCH 设置

- **WHEN** 调用 `PATCH /api/v1/admin/books/{ref}` 传 `{"pinned": true}`
- **THEN** 该 Book 的 `pinned` 变为真
- **AND** 列表顺序与审计同步变化

#### Scenario: 缺权限被拒绝

- **WHEN** 使用只具备 `read` 作用域的 Token 调用重排
- **THEN** 返回 403 且错误码指出缺少 `write` 作用域
