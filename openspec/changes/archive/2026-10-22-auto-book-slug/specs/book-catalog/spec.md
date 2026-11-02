# Spec Delta

## ADDED Requirements

### Requirement: 新建 Book 时 slug MUST 由系统生成且不出现在界面

创建 Book 的界面 MUST NOT 展示 slug 输入项，也 MUST NOT 要求调用方提供 slug。系统 MUST 在创建时按标题自动生成 slug：可转写为 ASCII 时取规范化结果，无法转写（如纯中文标题）时回退为 `book-` 加 6 位十六进制，全站冲突时自动追加递增后缀。编辑已有 Book 时仍 MUST 允许调整 slug。

#### Scenario: 新建表单不出现 slug

- **WHEN** 管理员打开新建 Book 页面
- **THEN** 页面不包含 slug 输入框或相关说明
- **AND** 提交创建时无需提供 slug

#### Scenario: 中文标题自动获得可用 slug

- **WHEN** 管理员只填标题「运维手册」并提交
- **THEN** Book 创建成功，slug 形如 `book-1a2b3c` 且满足 `[a-z0-9-]`
- **AND** 该 slug 可直接访问 `/b/<slug>`

#### Scenario: 编辑页仍可调整 slug

- **WHEN** 管理员打开已有 Book 的编辑页
- **THEN** 页面提供 slug 输入项，可改成新的可读短名
- **AND** 保存后旧链接失效、新链接立即可用
