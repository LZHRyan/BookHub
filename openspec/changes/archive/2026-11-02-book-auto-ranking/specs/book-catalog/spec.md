# Spec Delta

## MODIFIED Requirements

### Requirement: Book 创建与必填校验

系统 SHALL 允许管理员创建 Book 并保存标题、所属组、简介、图标与可见性等元数据。系统 MUST NOT 提供任何人工填写排序权重的字段；Book 的展示顺序由系统自动计算（见 `book-ranking`）。系统 MUST 拒绝标题缺失或仅含空白字符的创建请求，MUST 拒绝未指定组的创建请求，且校验失败时 MUST NOT 产生任何 Book 记录，并返回指明缺失字段的可读错误。

#### Scenario: 缺少标题时创建失败

- **WHEN** 管理员提交不含标题、或标题仅含空白字符的 Book 创建请求
- **THEN** 系统拒绝保存并返回 4xx 状态码
- **AND** 错误信息指明「标题」字段必填
- **AND** 访客端列表与管理端列表中都不出现新记录

#### Scenario: 缺少组时创建失败

- **WHEN** 管理员提交了标题但没有指定组
- **THEN** 系统返回 4xx 并提示必须选择组
- **AND** 不产生 Book 记录

#### Scenario: 必填项齐全时创建成功

- **WHEN** 管理员提交标题为「运维手册」并选择了一个组
- **THEN** 系统创建该 Book 并返回其标识与最终 slug
- **AND** 该 Book 出现在所选组的分区里

#### Scenario: 可选元数据可省略

- **WHEN** 管理员只提交标题与组就创建 Book
- **THEN** 创建成功，简介与图标为空值

#### Scenario: 创建请求不接受排序权重

- **WHEN** 创建请求里附带任意「排序权重」参数
- **THEN** 该参数被忽略，不写入任何字段
- **AND** 创建后的 Book 顺序完全由系统按热度与创建时间决定

### Requirement: Book 元数据更新

Book 的标题、简介、图标、分组、可见性、置顶与封面 MUST 可随时更新，且更新 MUST 立即反映到列表、详情与只读 API。文档类型（`format`）在该 Book 已有章之后 MUST NOT 被修改。访问标识（`slug`）MUST 可改并 MUST 保持全站唯一。任一字段非法时整次更新 MUST NOT 生效。系统 MUST NOT 接受任何修改排序权重的请求。

内置指南 Book（`is_builtin=true`）的 `slug` 与 `format` MUST NOT 被修改：前者是外部集成（链接、MCP 配置、脚本）的锚点，后者决定其 Markdown 正文的渲染方式。其余字段（标题、简介、图标、可见性、置顶、封面）MUST 仍可更新。

#### Scenario: 更新成功后立即生效

- **WHEN** 修改某 Book 的标题或可见性并保存
- **THEN** 列表中立即显示新值
- **AND** `GET /api/v1/books` 的对应条目也带新值

#### Scenario: 部分字段非法时整体不生效

- **WHEN** 同时提交合法标题与非法的可见性取值
- **THEN** 返回 400
- **AND** 标题也没有被改动

#### Scenario: 内置指南只锁定身份字段

- **WHEN** 对 `ai-agent-guide` 提交新的标题与简介
- **THEN** 更新成功并立即生效
- **AND** 同时提交新 slug 或 `format=html` 时返回 400，其余字段不落库

#### Scenario: 表单里的排序权重被忽略

- **WHEN** 编辑请求里附带「排序权重」参数并保存成功
- **THEN** 标题、简介等合法字段照常生效
- **AND** 该 Book 在列表中的位置仍只由自动权重决定

### Requirement: Book 排序

系统 SHALL 按自动计算的热度权重**降序**排列 Book。权重 MUST 由系统根据访问热度与创建时间计算得出，MUST NOT 提供任何人工设置排序权重的入口、字段或接口。权重相同的 Book MUST 以稳定的次级规则（创建时间降序，再回退到 id 降序）排列，保证相同数据下重复请求得到同一顺序。访问热度或新建 Book 引起的顺序变化 MUST 在下一次列表请求中立即反映，无需任何额外刷新或重建步骤。

#### Scenario: 热门 Book 排到最前

- **WHEN** 某 Book 近期访问量明显高于其他 Book
- **THEN** 下一次列表请求中该 Book 排在最前
- **AND** 无需管理员做任何设置

#### Scenario: 新建 Book 默认靠前

- **WHEN** 两本 Book 都没有任何访问记录
- **THEN** 创建时间较晚的那本排在前面
- **AND** 该顺序随创建时间衰减而逐渐回落，不需要人工干预

#### Scenario: 调整权重后顺序立即变化

- **WHEN** 某 Book 因近期被频繁访问而权重升到最高
- **THEN** 下一次列表请求中该 Book 排在首位
- **AND** 无需任何额外刷新或重建步骤

#### Scenario: 权重相同时顺序稳定

- **WHEN** 两本 Book 的访问数据与创建时间完全一致
- **THEN** 多次请求列表得到相同的相对顺序
- **AND** 该顺序按 id 降序兜底

#### Scenario: 分页遍历不重复不遗漏

- **WHEN** 访客按分页参数逐页拉取 Book 列表
- **THEN** 各页之间的 Book 不重复
- **AND** 全部页的并集等于当时的可见 Book 集合

#### Scenario: 顺序不随请求时刻抖动

- **WHEN** 两次列表请求之间没有任何新的访问与创建
- **THEN** 即使相隔数天，两次请求得到的相对顺序也完全一致
