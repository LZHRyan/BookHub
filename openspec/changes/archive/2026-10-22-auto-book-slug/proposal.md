# Proposal

## Why

新建 Book 时那个 `slug` 输入框对使用者是纯负担：多数人不知道该填什么，留空才是正确做法，而框里的说明（"纯中文标题会得到 `book-3f7a1c`"）反而让人怀疑是不是自己填错了。既然创建阶段的 slug 本来就是系统自动生成的，就不该把它摆在表单上让管理员做一次没有意义的选择。

## What Changes

- **新建 Book 表单不再显示 `slug` 字段**，也不提交它；slug 完全由标题自动生成（沿用现有规则：规范化后的 ASCII；纯中文标题回退 `book-<6 位十六进制>`；冲突自动追加 `-2`/`-3`）。
- 编辑页**仍然保留** `slug`：这是把 `book-xxxxxx` 改成可读 URL 的唯一入口。
- 服务层不变（`create_book` 已支持 `slug_raw` 为空时自动生成），HTTP 接口对旧客户端保持兼容（继续接受可选 `slug` 参数）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `book-catalog`: Book 创建流程中 slug 由系统生成，界面不要求也不展示该配置；编辑阶段仍允许调整。

## Impact

- **模板**：`app/templates/admin/book_form.html` 的 slug 段落只在编辑模式渲染。
- **接口/数据**：无 schema 变更；`POST /admin/books/new` 不再提交 `slug` 字段，处理器保留 `Form(default="")` 以兼容。
- **测试**：新增"新建页无 slug 输入、中文标题自动生成 `book-` 前缀、编辑页仍可改 slug"三条用例。
