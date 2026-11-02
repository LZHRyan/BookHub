# book-groups Specification

## Purpose
在「知识库」和「Book」之间提供一层稳定的分类结构：组决定首页的分区与顺序，每本 Book 必须且只能属于一个组，删组前必须先腾空。

## Requirements

### Requirement: 组 MUST 有稳定的标识与位置

每个组 MUST 有标题（必填）、slug（站内唯一）、可选简介与图标、以及一个整数位置。组的位置 MUST 决定首页分区的先后，且 MUST 可通过上移/下移调整；调整 MUST 只重写组的位置序号，MUST NOT 影响任何 Book 的数据。

#### Scenario: 新建组排在最后

- **WHEN** 管理员新建一个组
- **THEN** 它出现在首页分区的最后
- **AND** 其他组的相对顺序不变

#### Scenario: 上移组只改顺序

- **WHEN** 管理员把第三个组上移一位
- **THEN** 首页分区顺序随之变化
- **AND** 各组下 Book 的归属与顺序都不变

#### Scenario: slug 冲突自动去重

- **WHEN** 新建组时填写的 slug 与已有组相同
- **THEN** 系统自动追加 `-2`、`-3` 等后缀
- **AND** 创建仍然成功

### Requirement: Book MUST 属于且只属于一个组

每本 Book MUST 有且只有一个组；创建 Book 时未指定组 MUST 被拒绝。修改归属 MUST 只改这一个字段，MUST NOT 影响章节、版本与媒体。

#### Scenario: 未指定组被拒绝

- **WHEN** 通过表单或 API 创建 Book 但没给组
- **THEN** 请求被拒绝并提示必须选择组
- **AND** 不产生 Book 记录

#### Scenario: 改归属不影响章节

- **WHEN** 把一本书从一个组移到另一个组
- **THEN** 该 Book 出现在新组的分区里
- **AND** 它的章节、版本与媒体资源都不变

### Requirement: 组内排序 MUST 沿用置顶与热度

同一组内 Book 的先后 MUST 沿用全局规则：置顶优先，其次按访问热度与创建时间；MUST NOT 为组内提供任意手工序号。

#### Scenario: 置顶在组内也生效

- **WHEN** 组内某本低热度 Book 被置顶
- **THEN** 它排在该组最前
- **AND** 其他组的排序不受影响

### Requirement: 删除组 MUST 先腾空且保留最后一个

默认分组 MUST NOT 被删除（见「默认分组 MUST 随系统存在且不可删除」）。其余分组：仍有 Book 的组 MUST 拒绝删除，错误信息 MUST 说明剩余 Book 数量；系统 MUST 至少保留一个组，最后一个组 MUST NOT 被删除（由于默认分组始终存在，实际的「最后一个组」就是它）。

#### Scenario: 非空组删不掉

- **WHEN** 管理员删除一个含 3 本书的组
- **THEN** 请求被拒绝并说明还剩 3 本 Book
- **AND** 组与 Book 都不变

#### Scenario: 空组可删除

- **WHEN** 删除一个没有 Book 且不是默认分组的组
- **THEN** 删除成功
- **AND** 首页不再出现该分区

#### Scenario: 最后一个组不能删

- **WHEN** 系统里只剩默认分组时尝试删除它
- **THEN** 请求被拒绝并说明默认分组不能删除
- **AND** 默认分组与其下 Book 都保持原状

### Requirement: 首页 MUST 按组分区并按位置排序

首页 MUST 按组的位置顺序渲染分区，每个分区 MUST 显示组标题与该组的 Book 卡片；MUST NOT 把不同组的 Book 混在同一份列表里。某组没有可见 Book 时 MUST NOT 渲染该分区（除非只有一个组）。

#### Scenario: 分区顺序与组顺序一致

- **WHEN** 首页有两个组，位置分别为 10 与 20
- **THEN** 位置 10 的分区在前
- **AND** 两个分区各自只包含自己组的 Book

#### Scenario: 空组不出现在首页

- **WHEN** 某组下的 Book 全被删除或都不可见
- **THEN** 该组的分区不渲染
- **AND** 其他分区正常显示

### Requirement: 存量数据 MUST 归入默认分组

迁移 MUST 创建一个「默认分组」并把所有存量 Book 归入其中，使 `books.group_id` 可以收紧为非空。MUST NOT 出现 group 为空的 Book。

#### Scenario: 迁移后无未分组 Book

- **WHEN** 在已有数据的库上执行迁移
- **THEN** 出现一个「默认分组」
- **AND** 所有原 Book 都指向它，首页仍能正常列出全部 Book

### Requirement: 默认分组 MUST 随系统存在且不可删除

系统 MUST 始终存在一个 `slug` 为 `default` 的「默认分组」：由迁移创建，运行时的缺省归属逻辑 MUST 在缺失时补建。它 MUST NOT 可删除——网页端与管理 API 一律拒绝并返回可读错误，MUST NOT 因为「组里没有 Book」而放行。它的 `slug` MUST NOT 可修改（系统按该标识识别默认分组）；标题、简介、图标 MAY 修改。未指定分组的 Book MUST 归入默认分组。

#### Scenario: 默认分组删不掉

- **WHEN** 管理员在分组列表或编辑器里删除默认分组
- **THEN** 请求被拒绝，提示默认分组由系统创建、不能删除
- **AND** 默认分组仍在列表里，其下 Book 的归属不变

#### Scenario: 有其它分组时默认分组仍不可删

- **WHEN** 系统里除默认分组外还有空的自建分组
- **THEN** 自建空分组可以删除
- **AND** 默认分组删除请求仍被拒绝

#### Scenario: 默认分组可改名但标识固定

- **WHEN** 管理员把默认分组的标题改为「未分组」并提交
- **THEN** 保存成功，首页分区显示新标题
- **AND** 它的 `slug` 仍是 `default`；尝试修改 `slug` 会被拒绝并说明原因

#### Scenario: 管理 API 暴露 is_default

- **WHEN** 调用方请求 `GET /api/v1/admin/groups`
- **THEN** 每个分组条目都带 `is_default` 布尔值，默认分组为 `true`
- **AND** 对 `is_default=true` 的组调用 `DELETE` 返回 400，`PATCH` 改 `slug` 返回 400
