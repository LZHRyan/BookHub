# Proposal

## Why

现在"文档类型"是**章节级**属性：同一个 Book 下可以既有 Markdown 章节又有 HTML 章节。实际使用中这会带来三个问题——(1) 一本书通常是同一套写作/发布规范（要么全用 Markdown 走 Git 化流程，要么全用 HTML 保留原排版），混在一起让读者和目录看起来风格割裂；(2) 导出整本（ZIP/JSON）时会得到 `.md` 与 `.html` 混杂的产物，下游脚本要按章分支处理；(3) 管理员上传时容易传错格式而毫无提示，直到读者看到渲染异常才发现。需要把文档类型上移到 Book 级并强制唯一。

## What Changes

- **BREAKING** `books` 表新增 `format` 列（`markdown` | `html`，非空）。已有 Book 按"第一章的格式"回填（无章节则回填 `markdown`），不丢数据。
- 新建 Book 时**必须显式选择**文档类型，不提供"混合"选项。
- Book 下已有章节时**不允许修改**文档类型；空 Book 仍可改。
- 章节的新建、上传、替换一律继承 Book 的类型：上传文件扩展名与 Book 类型不符、或表单提交了不同格式，一律拒绝并给出可读错误；`chapters.format` 仍然保留（用于渲染与 API），但被约束为等于所属 Book 的 `format`。
- Book 详情、管理端列表与 `/api/v1` 的 Book 表示都带上 `format` 字段。
- 演示数据与端到端脚本改为"Markdown 书 + HTML 书"两本，而不是一本书里混两种格式。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `book-catalog`: Book 必须声明单一文档类型；创建时强校验；有章节时不可变更。
- `chapter-lifecycle`: 章节创建/上传/替换必须与所属 Book 的文档类型一致，不一致一律拒绝且不落库、不产生版本。
- `content-api`: Book 表示新增 `format` 字段，供外部程序判断整本格式。
- `chapter-content`: 渲染与净化规则不变（Markdown 走渲染管线、HTML 走白名单净化），但章节格式来源改为继承 Book，不再由章节自行声明。

## Impact

- **数据**：新增 Alembic 迁移（加列 + 回填），SQLite/Postgres 均可执行；旧客户端不受影响（字段只增不改）。
- **服务层**：`books.create_book/update_book` 增加 `format` 参数与校验；`chapters.create_chapter/replace_content` 增加与 `book.format` 的一致性校验。
- **管理端**：Book 表单新增类型选择（编辑有章节时禁用并提示）；章节表单的格式选择改为只读展示。
- **对外 API**：`/api/v1/books` 与 `/api/v1/books/{ref}` 增加 `format`；章节 `format` 语义变为"恒等于 Book 类型"。
- **测试**：新增类型约束用例；调整既有用例（HTML 章节要在 HTML 类型的 Book 里创建）；`scripts/e2e_admin_flow.py` 改为两本书。
- **文档**：`docs/content-model.md`、`docs/authoring.md`、`docs/api.md` 同步说明。
