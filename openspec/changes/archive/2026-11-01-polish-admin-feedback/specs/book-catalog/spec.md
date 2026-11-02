## MODIFIED Requirements

### Requirement: slug 规范化与唯一性

系统 SHALL 接受调用方显式指定的 slug，并 MUST 将 slug 规范化为仅由小写字母、数字与连字符组成（`[a-z0-9-]`）：大写转小写，空白及不允许的字符替换为连字符，连续连字符合并为一个，并去除首尾连字符。slug 在全站 SHALL 唯一；发生冲突时系统 MUST 自动追加 `-2`、`-3` 等递增数字后缀直到可用，而不是拒绝创建。

「不传 slug」与「传了空 slug」MUST 区分对待：不传表示"不改"，MUST 保持原值；显式传了空字符串或纯空白 MUST 返回 400 并说明「访问标识不能为空；不改请省略该字段」，MUST NOT 静默忽略。

#### Scenario: 非法字符被规范化

- **WHEN** 管理员以 slug `Ops_Handbook 2024` 创建 Book
- **THEN** 系统保存的 slug 为 `ops-handbook-2024`
- **AND** 用该规范化后的 slug 访问 Book 详情成功

#### Scenario: slug 冲突时自动加后缀

- **WHEN** 已存在 slug 为 `guide` 的 Book，管理员再次创建会得到 slug `guide` 的 Book
- **THEN** 新 Book 保存为 `guide-2` 并创建成功
- **AND** 原 Book 的 slug 保持为 `guide` 不受影响
- **AND** 第三次同类创建得到 `guide-3`

#### Scenario: 派生结果为空时自动生成可用 slug

- **WHEN** 调用方未提供 slug，且按标题派生的 slug 规范化后为空字符串（例如标题为纯中文或纯符号）
- **THEN** 系统自动生成一个形如 `book-` 加 6 位十六进制字符的 slug 并创建成功
- **AND** 生成的 slug 满足 `[a-z0-9-]` 约束且全站唯一
- **AND** 管理员随后可显式修改该 slug，原直链失效但新直链立即可用

#### Scenario: 修改标题不改变已有 slug

- **WHEN** 管理员把已发布 Book 的标题由「运维手册」改为「运维手册（2025）」，且未显式修改 slug
- **THEN** 该 Book 的 slug 保持原值不变
- **AND** 原有直链继续可访问

#### Scenario: 显式空 slug 被拒绝

- **WHEN** 更新 Book 时把 `slug` 显式传成空字符串或纯空白
- **THEN** 返回 400 并提示「访问标识不能为空；不改请省略该字段」
- **AND** 该 Book 的 slug 与其它字段都没有被改动

### Requirement: 内置 Book MUST 不可删除

标记为 `is_builtin=true` 的 Book MUST NOT 被软删除：删除入口 MUST 返回 400 并说明它随系统生命周期存在。不需要读者看到时，MUST 通过改可见性（`unlisted`）或撤回章的发布状态来隐藏，而不是删除。该约束 MUST 在服务层强制，使网页端与 API 的行为一致。

网页端的删除操作被拒绝时 MUST NOT 只渲染一张错误页：MUST 回到列表页并展示一条可读的提示（说明为什么没删掉），且 MUST NOT 产生任何数据变更。

#### Scenario: API 删除被拒绝

- **WHEN** 调用 `POST /api/v1/admin/books/{内置书}/delete?confirm=true`
- **THEN** 返回 400 且 `error.message` 指出内置指南不能删除
- **AND** 回收站中不出现这本书

#### Scenario: 网页端不给按钮

- **WHEN** 管理员查看内容管理列表
- **THEN** 内置 Book 的卡片显示「内置 · 不可删除」而不是删除按钮
- **AND** 直接构造表单 POST 同样返回 400

#### Scenario: 网页端删除失败回到列表并提示

- **WHEN** 管理员对内置 Book 手工提交删除表单
- **THEN** 响应是 303 跳回内容管理列表，并带上 `error` 提示参数
- **AND** 列表页渲染出这条提示，书仍然可读、未被软删除
