# token-scoping Specification

## Purpose
让 API Token 的权限可以收窄到特定 Book，并在越界时给出明确错误，使「给某个团队或某个 AI 工具发一个只能改自己文档的凭据」成为可落地的做法。

## Requirements

### Requirement: Token MUST 可限定到指定 Book

签发 Token 时 MUST 可以选择它能操作的 Book 集合；未选择表示全部 Book。范围 MUST 持久化在 Token 上，并在 Token 表示中可见（Book 的 id 与 slug）。管理端的选择器 MUST 在 Book 数量很多时仍可用：MUST 支持按分组筛选、按标题或访问标识搜索、以及分页；已勾选的 Book MUST 跨页与跨筛选保留，并 MUST 随表单一起提交。

#### Scenario: 签发时限定范围

- **WHEN** 管理员签发一个只包含「部署手册」的 `write` Token
- **THEN** Token 列表显示其范围为「部署手册」
- **AND** Token 表示里带该 Book 的 id 与 slug

#### Scenario: 不限定范围表示全部

- **WHEN** 签发 Token 时不选择任何 Book
- **THEN** 该 Token 可操作全部 Book（仍受作用域限制）

#### Scenario: Book 很多时靠分组与搜索定位

- **WHEN** 站点有 100 本 Book，管理员要选其中一本
- **THEN** 可以用分组下拉把它缩小到某个分组，或在搜索框里按标题/访问标识过滤
- **AND** 列表按每页 8 本分页，翻页不改变筛选条件

#### Scenario: 跨页勾选不丢失

- **WHEN** 管理员在第 1 页勾选 2 本，翻到第 2 页再勾选 1 本后提交
- **THEN** 签发出的 Token 范围正好是这 3 本
- **AND** 「已选」区始终显示已勾选的 Book，可单条移除或一键清空

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

### Requirement: 范围变更 MUST 可追溯

签发与吊销 MUST 记入审计，审计 detail MUST 包含作用域与 Book 范围，便于事后核对「这个 Token 当时能改什么」。

#### Scenario: 签发留痕

- **WHEN** 管理员签发一个限定范围的 Token
- **THEN** 审计中出现 `token.create` 记录
- **AND** detail 里带 scopes 与 book 范围

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
