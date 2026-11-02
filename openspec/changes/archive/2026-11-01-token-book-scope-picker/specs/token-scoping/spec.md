## MODIFIED Requirements

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
