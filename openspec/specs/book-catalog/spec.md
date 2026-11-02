# book-catalog Specification

## Purpose
定义 Book（内容顶层单元）的行为契约：元数据的创建、更新与校验，URL 标识的规范化与唯一性，排序与可见性语义，软删除与不可见性，以及面向访客的 Book 列表、详情与有序章节目录。

## Requirements

### Requirement: Book 创建与必填校验

系统 SHALL 允许管理员创建 Book 并保存标题、所属组、简介、图标与可见性等元数据。系统 MUST 拒绝标题缺失或仅含空白字符的创建请求，MUST 拒绝未指定组的创建请求，且校验失败时 MUST NOT 产生任何 Book 记录，并返回指明缺失字段的可读错误。

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

### Requirement: Book 元数据更新

Book 的标题、简介、图标、分组、可见性、置顶与封面 MUST 可随时更新，且更新 MUST 立即反映到列表、详情与只读 API。文档类型（`format`）在该 Book 已有章之后 MUST NOT 被修改。访问标识（`slug`）MUST 可改并 MUST 保持全站唯一。任一字段非法时整次更新 MUST NOT 生效。

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

Book 详情 SHALL 返回该 Book 的目录而不含任何正文，目录项 MUST 至少包含章的 id、标题、slug、状态、排序信息，以及它下面按顺序排列的节简要（节 id、slug、标题、格式、版本、访问路径）。目录 MUST 按章的展示顺序返回。访客视角的目录 MUST 只包含已发布且未删除的章与节；管理员视角的目录 MAY 包含草稿并须标明其状态。

#### Scenario: 访客目录只含已发布章节

- **WHEN** 访客请求某 Book 的详情
- **THEN** 返回的目录只包含已发布且未删除的章与节
- **AND** 草稿章、已删除章及其下节都不出现在目录中

#### Scenario: 目录顺序与排序一致

- **WHEN** 某 Book 依次有「章 A（2 节）」与「章 B（1 节）」
- **THEN** 详情返回的目录顺序为章 A、章 B，章 A 的两节按自身顺序排列
- **AND** 每一项都带标识与 slug，节条目还带 `format` 与 `version`

#### Scenario: 目录不携带正文

- **WHEN** 程序调用方请求 Book 详情
- **THEN** 目录项中不包含任何节的正文
- **AND** 响应体大小与节正文长度无关

#### Scenario: 管理员目录标注草稿

- **WHEN** 管理员查看含一个草稿章的 Book 详情
- **THEN** 目录中包含该草稿章及其节，并标明草稿状态

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

### Requirement: Book MUST 声明单一文档类型

每个 Book MUST 声明一个文档类型，取值为 `markdown` 或 `html`，且 MUST NOT 存在"混合"取值。创建 Book 时未指定类型或取值非法 MUST 被拒绝，且 MUST NOT 产生 Book 记录。该类型是整本书唯一的格式：其下所有节 MUST 使用同一格式；Book 的列表、详情与管理端展示 MUST 呈现该类型。

#### Scenario: 创建时必须选择类型

- **WHEN** 管理员提交创建 Book 的请求但没有指定文档类型
- **THEN** 系统拒绝创建并返回 4xx，错误信息指明「文档类型」必填
- **AND** 不产生任何 Book 记录

#### Scenario: 非法类型被拒绝

- **WHEN** 创建请求的文档类型取值为 `mixed` 或空字符串
- **THEN** 系统拒绝创建并明确指出取值只能是 `markdown` 或 `html`

#### Scenario: 类型在列表与详情中可见

- **WHEN** 创建了一个类型为 `html` 的 Book
- **THEN** 管理端列表与该 Book 的详情都显示 `html`
- **AND** 该 Book 的字段只保存一个类型值，其下所有节都是 HTML

### Requirement: Book 图标 MUST 可从预置集合中点选

新建或编辑 Book 时，系统 MUST 提供一个可展开的预置图标集合，至少包含 100 个图标并按类别分组。点击其中任一图标 MUST 把该图标写入图标字段，与手工输入等价；面板 MUST NOT 依赖任何外部网络资源。管理员 MUST 仍能手工输入任意字符作为图标，并能一键清空。

#### Scenario: 面板可用且数量充足

- **WHEN** 管理员打开新建 Book 表单并展开图标面板
- **THEN** 面板中至少有 100 个可点击图标，并按类别分组显示
- **AND** 面板不发出任何外部网络请求

#### Scenario: 点选后写入图标字段

- **WHEN** 管理员点击面板中的某个图标并提交创建
- **THEN** 保存后的 Book 图标即为该图标
- **AND** 首页卡片与 Book 页显示该图标

#### Scenario: 手工输入与清空仍然可用

- **WHEN** 管理员直接在图标输入框里粘贴一个不在面板中的字符，或点击「清空」
- **THEN** 前者按输入内容保存，后者保存为空
- **AND** 保存为空时前台回退为内置矢量图标，不出现空白方块

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

### Requirement: Book 表示 MUST 带所属组

Book 的对外表示（只读 API 与详细响应）MUST 包含 `group` 对象，至少含 `id`、`slug`、`title`；MUST NOT 只给一个裸 id。

#### Scenario: API 表示含组

- **WHEN** 请求 Book 列表或详情
- **THEN** 每项都带 `group.slug` 与 `group.title`
- **AND** 用 `?group=<slug>` 可以只列该组的 Book

### Requirement: Book 的文档类型在有章后 MUST 不可变更

当 Book 下存在任何未删除的章时，修改其文档类型 MUST 被拒绝，且 MUST NOT 影响任何字段。当 Book 下没有任何未删除的章时，允许修改类型。

#### Scenario: 有章时修改被拒绝

- **WHEN** 管理员对一个已有 3 个章的 Book 提交把 `markdown` 改成 `html` 的更新
- **THEN** 系统返回 4xx 并说明「已有章，不能修改文档类型」
- **AND** 该 Book 的类型、标题、简介等字段全部保持原值

#### Scenario: 空 Book 可以切换类型

- **WHEN** 管理员对一个没有任何章的 Book 把类型改为 `html`
- **THEN** 更新成功，随后可以在其中创建 HTML 节

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
