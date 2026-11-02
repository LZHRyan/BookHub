# Spec Delta

## Purpose

为知识库提供图片与附件的托管能力：资源归属到 Book、以内容寻址方式落盘、按可见性受控读取，并在正文中以稳定的站内地址被引用，使文档不再依赖外部图床。

## ADDED Requirements

### Requirement: 媒体资源 MUST 归属单一 Book 并记录可核验元数据

每个上传资源 MUST 记录：归属 Book、原始文件名、存储文件名、MIME 类型、字节数、SHA-256 校验和、资源类别（`image` 或 `attachment`）、上传者与上传时间。资源 MUST 随所属 Book 一同进入回收站语义：Book 被软删除时其资源不可通过公开地址读取。

#### Scenario: 上传后元数据完整可查

- **WHEN** 管理员向某个 Book 上传一张 PNG 截图
- **THEN** 该资源的列表项包含原始文件名、MIME 类型、字节数、SHA-256 与资源类别 `image`
- **AND** 该资源只出现在这个 Book 的媒体列表里

#### Scenario: Book 被删除后资源不可公开读取

- **WHEN** 一个 Book 被软删除，访客请求它名下的媒体资源地址
- **THEN** 系统返回 404
- **AND** 恢复 Book 后同一地址重新可读，内容不变

### Requirement: 上传 MUST 通过类型白名单与内容校验

系统 MUST 以扩展名白名单与文件内容探测双重判定资源类型，两者不一致时 MUST 拒绝上传并返回可辨识的错误。可执行文件、脚本与未知类型 MUST 被拒绝；图片类别 MUST 只接受位图与矢量图扩展名。

#### Scenario: 伪装扩展名被拒绝

- **WHEN** 上传的文件名为 `logo.png`，但内容探测结果是可执行文件或纯文本脚本
- **THEN** 系统返回 4xx 并说明类型不匹配
- **AND** 磁盘上不留下任何文件，也不产生列表记录

#### Scenario: 白名单外扩展名被拒绝

- **WHEN** 上传的文件扩展名不在允许集合内
- **THEN** 系统返回 4xx 并列出允许的扩展名
- **AND** 该 Book 的媒体列表与配额统计保持提交前的状态

### Requirement: 单文件大小与每 Book 配额 MUST 有上限

系统 MUST 对单个文件字节数与单个 Book 的媒体总占用施加可配置上限。超限时 MUST 拒绝上传并返回与「类型非法」不同的错误标识，MUST NOT 写入部分内容。

#### Scenario: 单文件超限被拒绝

- **WHEN** 上传文件的字节数超过单文件上限
- **THEN** 系统返回 413 类错误并给出上限值
- **AND** 该 Book 的媒体列表不变

#### Scenario: 配额超限被拒绝

- **WHEN** 该 Book 已有资源占用加上新文件后超过每 Book 配额
- **THEN** 系统拒绝上传并说明配额与当前占用
- **AND** 清理未引用资源后同一请求可以成功

### Requirement: 内容相同的资源 MUST 只存一份

系统 MUST 以内容校验和作为存储标识：同一 Book 内重复上传内容完全相同的文件时 MUST 复用已有物理文件，并返回同一访问地址，而不是新增副本。

#### Scenario: 重复上传复用同一地址

- **WHEN** 同一张图片被连续上传两次
- **THEN** 两次响应返回的访问地址完全相同
- **AND** 该 Book 的媒体占用只增加一次

### Requirement: 写入路径 MUST 限制在媒体根目录内

存储路径 MUST 由系统生成，MUST NOT 直接采用客户端提供的文件名作为路径；原始文件名只作为元数据保存。任何解析出的目标路径 MUST 落在媒体根目录之下。

#### Scenario: 含路径分隔符的文件名被安全处理

- **WHEN** 上传文件名为 `../../etc/passwd` 或包含反斜杠、控制字符
- **THEN** 系统规范化后仍写入该 Book 的媒体目录内
- **AND** 元数据里的原始文件名被保留用于展示

### Requirement: 读取 MUST 遵守 Book 可见性与登录态

公开读取 MUST 校验 Book 存在且未删除；`unlisted` Book 的资源 MUST 仅在带有效会话或有效 Token 时返回；被删除资源的公开地址 MUST 返回 404。读取路径 MUST NOT 暴露目录列表。

#### Scenario: 未列出 Book 的资源需要身份

- **WHEN** 匿名访客请求 `unlisted` Book 的媒体地址
- **THEN** 系统返回 404 或 401 且不返回文件内容
- **AND** 携带有效管理会话或 Token 的同一请求返回文件

#### Scenario: 不存在的资源返回 404

- **WHEN** 请求的存储文件名不存在或属于其他 Book
- **THEN** 系统返回 404，且响应体不泄露其他 Book 的信息

### Requirement: 读取响应 MUST 可长期缓存且带安全头

命中资源的响应 MUST 携带 `Cache-Control` 长缓存与不可变语义、准确的 `Content-Type`、`X-Content-Type-Options: nosniff`，并对非图片资源给出下载文件名。HTML 原始文档模式的资源策略 MUST 允许加载同源媒体。

#### Scenario: 图片响应可被浏览器长期缓存

- **WHEN** 访客读取一个已存在的图片资源
- **THEN** 响应头包含 `Cache-Control: public, max-age=31536000, immutable`
- **AND** `Content-Type` 与上传时的探测结果一致

#### Scenario: 附件以原文件名下载

- **WHEN** 访客读取一个 `attachment` 类资源
- **THEN** 响应头 `Content-Disposition` 带原始文件名
- **AND** 浏览器按下载处理而不是内联渲染

### Requirement: 正文引用 MUST 使用稳定的站内地址

媒体在正文中的引用 MUST 采用形如 `/media/{book_slug}/{stored_name}` 的站内绝对路径，MUST NOT 依赖会话、查询参数或临时签名。Markdown Book 使用图片语法、HTML Book 使用 `<img>` 标签，两种格式的引用在导出与原文读取时保持原样。

#### Scenario: Markdown Book 插入图片语法

- **WHEN** 管理员在 Markdown Book 的编辑器里上传一张图片
- **THEN** 正文中插入 `![原始文件名](/media/<book-slug>/<stored-name>)`
- **AND** 渲染后的页面能直接显示该图片

#### Scenario: HTML Book 插入 img 标签

- **WHEN** 管理员在 HTML Book 的编辑器里上传一张图片
- **THEN** 正文中插入 `<img src="/media/<book-slug>/<stored-name>" alt="原始文件名">`
- **AND** 该标签在白名单净化后仍然保留

### Requirement: 编辑器 MUST 支持粘贴、拖拽与点选上传

章节编辑器 MUST 支持从剪贴板粘贴图片、把文件拖入正文区域、以及点选文件上传三种方式，并在上传成功后按当前光标位置插入引用。上传失败 MUST 就地提示原因，MUST NOT 破坏已输入的正文。

#### Scenario: 粘贴截图即插入

- **WHEN** 管理员在正文光标处粘贴一张剪贴板图片
- **THEN** 编辑器先上传该图片，成功后把引用插入到光标位置
- **AND** 原有正文内容保持不变

#### Scenario: 上传失败保留正文

- **WHEN** 粘贴的图片超过单文件上限
- **THEN** 编辑器显示失败原因
- **AND** 正文内容与光标位置不变

### Requirement: 删除 MUST 为软删除且不影响已发布正文

删除媒体 MUST 只标记删除并保留物理文件，使引用该资源的已发布章节仍可显示；删除后在管理端列表中标记为已删除，公开地址返回 404。重复删除 MUST 幂等。

#### Scenario: 删除后章节仍可显示

- **WHEN** 管理员删除一张仍被已发布章节引用的图片
- **THEN** 该章节页面上的图片仍正常显示
- **AND** 该资源的公开地址返回 404

#### Scenario: 重复删除幂等

- **WHEN** 对同一资源连续发起两次删除
- **THEN** 第二次返回成功且状态不变
- **AND** 审计中记录两次操作

### Requirement: 未引用资源 MUST 可被识别与清理

系统 MUST 能判定某资源是否被该 Book 的任意章节（含历史版本、草稿与已删除章节）的正文引用。清理操作 MUST 默认只返回将被删除的清单，仅在显式确认后才实际删除，且 MUST 只清理未被引用的资源。

#### Scenario: 预览清理不删文件

- **WHEN** 管理员发起未引用资源清理但没有显式确认
- **THEN** 响应列出未引用资源及其字节数合计
- **AND** 没有任何资源被删除

#### Scenario: 清理跳过被引用资源

- **WHEN** 管理员带确认执行清理，其中某资源仍被某个历史版本的正文引用
- **THEN** 该资源保留在媒体列表中
- **AND** 只有真正无引用的资源被删除

### Requirement: 媒体写入 MUST 记入审计

上传、删除与清理操作 MUST 写入审计日志，记录操作者、动作、目标 Book、资源标识与结果摘要；通过管理 API 发起的操作 MUST 归属为对应的 Token 身份。

#### Scenario: API 上传的审计归属到 Token

- **WHEN** 使用名为 `ai-writer` 的 Token 通过管理 API 上传资源
- **THEN** 审计日志出现该上传记录，操作者显示为 `api:ai-writer`
- **AND** 记录里带有 Book 与资源标识
