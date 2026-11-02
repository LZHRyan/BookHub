## MODIFIED Requirements

### Requirement: 越界访问 MUST 被拒绝

带 Book 范围的 Token 访问范围外 Book 的管理端点时 MUST 返回 403，错误信息 MUST 指出 Token 无权操作该 Book。校验 MUST 覆盖读与写端点，且 MUST NOT 因为端点是否修改数据而放宽。

范围 MUST NOT 只作用于「路径里带 Book 引用」的端点：列 Book、回收站这类**不带 Book 引用但会返回多本 Book 数据**的端点 MUST 按范围过滤；审计（含 CSV 导出）涉及全站其它 Book 的操作记录，对带 Book 范围的 Token MUST 直接返回 403。

#### Scenario: 读端点也被拦截

- **WHEN** 限定到 Book A 的 Token 请求 Book B 的章节列表
- **THEN** 返回 403 并说明无权操作 Book B

#### Scenario: 范围内的写操作正常

- **WHEN** 同一 Token 请求 Book A 的章节列表或创建章节
- **THEN** 正常返回 200 / 201

#### Scenario: 全站级端点不受 Book 范围限制

- **WHEN** 该 Token 请求 `/api/v1/admin/meta`
- **THEN** 按作用域正常放行或拒绝，不因 Book 范围而失败

#### Scenario: Book 列表只含范围内的书

- **WHEN** 限定到 Book A 的 Token 请求 `GET /api/v1/admin/books`
- **THEN** `total` 只统计范围内的 Book，`items` 中不出现范围外的 Book
- **AND** 范围为空（Token 未限定）时才返回全部

#### Scenario: 回收站按范围过滤

- **WHEN** 范围外的 Book 与范围内的 Book 都被软删除后，该 Token 请求 `GET /api/v1/admin/trash`
- **THEN** 响应中的 `books` / `chapters` / `sections` 只包含范围内的条目
- **AND** 范围外的删除记录连标识都不出现

#### Scenario: 审计对受限 Token 关闭

- **WHEN** 带 Book 范围的 Token 请求 `GET /api/v1/admin/audit` 或 `GET /api/v1/admin/audit.csv`
- **THEN** 返回 403 并说明受限 Token 不能读取全站审计

## ADDED Requirements

### Requirement: admin 作用域 MUST NOT 与 Book 范围共存

`admin` 覆盖账号、站点设置、Token/Webhook 管理与审计，这些端点没有 Book 可拦。因此签发 Token 时 MUST 拒绝「`admin` + 非空 Book 范围」的组合，并 MUST 提示改用 `read` / `write` 来限定 Book。存量数据中已存在的该组合 MUST 在任何管理端点被拒绝（403），MUST NOT 以「范围生效」的假象继续放行。

#### Scenario: 签发时拒绝组合

- **WHEN** 调用 `POST /api/v1/admin/tokens`，`scopes` 含 `admin` 且 `books` 非空
- **THEN** 返回 400 并说明 admin 不能限定 Book 范围
- **AND** 不产生 Token

#### Scenario: 存量组合无法使用

- **WHEN** 数据库中已存在一个 `scopes=admin` 且带 Book 范围的 Token，用它对任意管理端点发起请求
- **THEN** 返回 403 并提示吊销后重签
- **AND** 该 Token 不会因为带了范围而被当作受限 Token 放行

### Requirement: 签发的 Token MUST NOT 超越签发者

用 Token 调用 `POST /api/v1/admin/tokens` 时，新 Token 的作用域 MUST 在签发者作用域之内（按 `read < write < admin` 包含关系比较，而不是集合相等），Book 范围 MUST 是签发者 Book 范围的子集。超出时 MUST 返回 403 且 MUST NOT 产生 Token。

#### Scenario: 不能借 Token 提权

- **WHEN** 一个只有 `write` 作用域的 Token 请求签发 `scopes=["admin"]` 的新 Token
- **THEN** 返回 403
- **AND** 不产生 Token

#### Scenario: 受限 Token 不能扩大 Book 范围

- **WHEN** 限定到 Book A 的 Token 请求签发一个覆盖 Book A 与 Book B 的 Token
- **THEN** 返回 403
- **AND** 用它签发只覆盖 Book A 的 Token 仍可成功
