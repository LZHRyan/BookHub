## Why

上一轮「章 → 节」重构把 `Book.format` 降级成「新建节时的默认格式」，允许同一章混排 Markdown 与 HTML（设计 D6）。实际使用中这条太自由：

- 一本手册里同时出现两种渲染管线，样式、锚点、代码高亮的行为不一致；
- 文件选择器只能同时接受两种扩展名，无法在录入时就挡住「把 .html 传进 Markdown 手册」；
- 管理端不再锁定类型，改一次默认值就会影响之后新建的节，容易产生难以解释的混合内容。

产品规则回到「一本 Book 只有一种格式」。

## What Changes

- `Book.format` 恢复为**整本唯一**的文档类型：所有 `ChapterSection.format` MUST 等于所属 Book 的类型。
- 服务层统一校验：`resolve_section_format()` 收到与 Book 不一致的格式直接 `ValidationFailed`；新建节、替换正文、API 写入都走同一处。
- 上传入口按 Book 类型过滤：网页端文件选择器 `accept` 只给对应扩展名，服务端在读文件时也拒绝不匹配的扩展名（整次请求不落库）；API 上传同样由服务层拒绝。
- 节编辑器不再提供格式单选，改为只读展示「整本统一：Markdown/HTML」，并提交隐藏字段。
- Book 编辑器在有章后重新锁定文档类型（radio 禁用 + hidden 保留原值 + 提示）；空 Book 仍可切换。
- 文档与规格同步（Book/节的格式语义、上传约束）。

## Impact

- 受影响规格：`book-catalog`（文档类型单一 + 有章不可改）、`chapter-content`（节格式由 Book 决定）、`chapter-lifecycle`（表单/上传新增时的格式校验）、`content-api`（Book 表示的 `format` 语义）。
- 代码：`app/services/{sections,books}.py`、`app/web/admin.py`、`app/api/admin.py`、`app/templates/admin/{book_form,chapter_form,section_form,book_detail}.html`。
- 测试：混排相关用例改为「拒绝」；新增上传扩展名不匹配、Book 类型锁定、节格式静态展示的断言。
- 数据：现有数据已是统一格式（迁移后重建），无需数据迁移。
