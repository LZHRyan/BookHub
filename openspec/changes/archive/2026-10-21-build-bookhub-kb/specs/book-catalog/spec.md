## Purpose

定义 Book（内容顶层单元）的行为契约：元数据的创建、更新与校验，URL 标识的规范化与唯一性，排序与可见性语义，软删除与不可见性，以及面向访客的 Book 列表、详情与有序章节目录。

## ADDED Requirements

### Requirement: Book 创建与必填校验

系统 SHALL 允许管理员创建 Book 并保存标题、简介、图标、排序权重与可见性等元数据。系统 MUST 拒绝标题缺失或仅含空白字符的创建请求，且校验失败时 MUST NOT 产生任何 Book 记录，并返回指明缺失字段的可读错误。

#### Scenario: 缺少标题时创建失败

- **WHEN** 管理员提交不含标题、或标题仅含空白字符的 Book 创建请求
- **THEN** 系统拒绝保存并返回 4xx 状态码
- **AND** 错误信息指明「标题」字段必填
- **AND** 访客端列表与管理端列表中都不出现新记录

#### Scenario: 必填项齐全时创建成功

- **WHEN** 管理员提交标题为「运维手册」的创建请求
- **THEN** 系统创建该 Book 并返回其标识与最终 slug
- **AND** 该 Book 立即出现在管理端列表；可见性为 `public` 时同时出现在访客端列表

#### Scenario: 可选元数据可省略

- **WHEN** 管理员只提交标题就创建 Book
- **THEN** 创建成功，简介与图标为空值
- **AND** 该 Book 在列表与详情中正常展示，不因缺少可选字段报错

### Requirement: slug 规范化与唯一性

系统 SHALL 接受调用方显式指定的 slug，并 MUST 将 slug 规范化为仅由小写字母、数字与连字符组成（`[a-z0-9-]`）：大写转小写，空白及不允许的字符替换为连字符，连续连字符合并为一个，并去除首尾连字符。slug 在全站 SHALL 唯一；发生冲突时系统 MUST 自动追加 `-2`、`-3` 等递增数字后缀直到可用，而不是拒绝创建。

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

### Requirement: Book 元数据更新

系统 SHALL 允许管理员更新 Book 的标题、简介、图标、排序权重与可见性，并 MUST 在更新成功后刷新该 Book 的更新时间。更新 MUST 为原子操作：若任一字段校验失败，则全部字段保持更新前的值。

#### Scenario: 更新成功后立即生效

- **WHEN** 管理员把某 Book 的简介改为新文本
- **THEN** 详情与列表中读到的简介为新文本
- **AND** 该 Book 的更新时间晚于更新前的值

#### Scenario: 部分字段非法时整体不生效

- **WHEN** 管理员同时提交新的合法简介与空的标题
- **THEN** 系统返回 4xx 状态码并指明标题字段错误
- **AND** 该 Book 的简介与标题都与更新前完全一致

### Requirement: Book 可见性语义

系统 SHALL 支持 `public` 与 `unlisted` 两种可见性。`public` 的 Book MUST 出现在访客端列表与全站搜索结果中；`unlisted` 的 Book MUST NOT 出现在访客端列表与全站搜索结果中，但 MUST 能通过直链正常访问。

#### Scenario: public Book 出现在列表与搜索

- **WHEN** 某 Book 可见性为 `public`
- **THEN** 它出现在访客端 Book 列表
- **AND** 用其标题中的词搜索时，该 Book 会出现在结果中

#### Scenario: unlisted Book 仅可直链访问

- **WHEN** 某 Book 可见性为 `unlisted`
- **THEN** 访客端 Book 列表中不出现该 Book
- **AND** 用其标题中的词搜索时不出现该 Book
- **AND** 直接访问该 Book 的详情直链返回正常页面

#### Scenario: 可见性变更为 unlisted 后立刻退出列表

- **WHEN** 管理员把某 Book 的可见性由 `public` 改为 `unlisted`
- **THEN** 后续的列表请求与搜索请求不再包含该 Book
- **AND** 其直链与章节直链仍然可以正常访问

### Requirement: Book 排序

系统 SHALL 按整数排序权重升序排列 Book。权重相同的 Book MUST 以稳定的次级规则（创建时间升序）排列，保证相同请求重复执行得到同一顺序。排序权重变更后，新顺序 MUST 在下一次列表请求中立即反映，无需任何额外刷新或重建步骤。

#### Scenario: 调整权重后顺序立即变化

- **WHEN** 管理员把原本排最后的 Book 的排序权重改为最小值
- **THEN** 下一次列表请求中该 Book 排在首位

#### Scenario: 权重相同时顺序稳定

- **WHEN** 两个 Book 的排序权重相同
- **THEN** 多次请求列表得到相同的相对顺序
- **AND** 该顺序与创建时间升序一致

#### Scenario: 分页遍历不重复不遗漏

- **WHEN** 访客按分页参数逐页拉取 Book 列表
- **THEN** 各页之间的 Book 不重复
- **AND** 全部页的并集等于当时的可见 Book 集合

### Requirement: Book 详情返回有序章节目录

Book 详情 SHALL 返回该 Book 的章节目录而不含章节正文，目录项 MUST 至少包含章节标题、slug 与排序信息。目录 MUST 按章节排序权重升序返回。访客视角的目录 MUST 只包含已发布且未删除的章节；管理员视角的目录 MAY 包含草稿并须标明其状态。

#### Scenario: 访客目录只含已发布章节

- **WHEN** 访客请求某 Book 的详情
- **THEN** 返回的目录只包含已发布且未删除的章节
- **AND** 草稿章节与已删除章节都不出现在目录中

#### Scenario: 目录顺序与排序一致

- **WHEN** 某 Book 下三个章节的排序权重依次为 30、10、20
- **THEN** 详情返回的目录顺序为权重 10、20、30 对应的章节

#### Scenario: 目录不携带正文

- **WHEN** 程序调用方请求 Book 详情
- **THEN** 目录项中不包含章节正文
- **AND** 响应体大小与章节正文长度无关

#### Scenario: 管理员目录标注草稿

- **WHEN** 管理员查看含一个草稿章节的 Book 详情
- **THEN** 目录中包含该草稿章节
- **AND** 该目录项标明其处于草稿状态

### Requirement: 空 Book 的表现

系统 SHALL 允许存在没有任何章节的 Book，且此类 Book MUST 仍可被正常访问与列出：列表与详情显示其章节数为 0，详情返回空目录，而不是错误或 404。

#### Scenario: 无章节的 public Book 正常展示

- **WHEN** 访客访问一个尚无章节的 `public` Book
- **THEN** 详情页正常返回并显示「暂无章节」类提示
- **AND** 该 Book 仍出现在 Book 列表中，章节数为 0

#### Scenario: 无章节的 unlisted Book 可直链访问

- **WHEN** 访客通过直链访问一个尚无章节的 `unlisted` Book
- **THEN** 详情正常返回，目录为空
- **AND** 响应中不出现错误码

### Requirement: Book 不存在时的 404 行为

当 Book 标识无法匹配任何未删除的 Book 时，系统 MUST 返回 404，且响应 MUST NOT 透露该标识是否曾经存在（区分「从未存在」「已删除」会泄露信息）。

#### Scenario: 未知 slug 返回 404

- **WHEN** 请求一个从未存在的 Book slug
- **THEN** 系统返回 404
- **AND** 响应中不包含任何该 slug 相关的内容片段

#### Scenario: 已软删除的 Book 返回 404

- **WHEN** 访客访问一个已被软删除的 Book 的列表页或详情直链
- **THEN** 系统返回 404
- **AND** 响应与「从未存在的 slug」在状态码与错误结构上完全一致
