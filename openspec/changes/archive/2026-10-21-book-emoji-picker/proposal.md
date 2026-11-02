# Proposal

## Why

新建 Book 时「图标」是一个空文本框，只写了"填一个 emoji"。多数同事并不知道有哪些 emoji 可用，也不想记输入法快捷键；结果就是要么留空（前台显示默认矢量图标，Book 之间毫无区分），要不到处都是同一个 📗。给一个**内置的可视化 emoji 面板**，点一下就能选，比让人手敲 emoji 快得多。

## What Changes

- 新增内置 emoji 清单（约 120 个，按「文档/技术/部署运维/数据/安全/协作/流程/其他」分组），随代码发布，不依赖网络与第三方库。
- Book 新建/编辑表单的「图标」字段改为：文本框 + 可展开的 emoji 面板 + 实时预览；点击面板里的 emoji 即写入文本框，仍允许手工输入任意字符。
- 清空按钮：一键回到"无图标"（前台回退为内置矢量图标）。
- 顺手把图标的 `maxlength` 从 8 提到 16，避免带变体选择符/组合序列的 emoji 被截断。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `book-catalog`: Book 的图标可以从预置集合中点选，选中结果与手工输入等价。

## Impact

- **代码**：新增 `app/services/emoji.py`（纯数据 + 少量辅助函数）；`app/web/admin.py` 两个 GET 表单处理器多传一个 `emoji_groups`；`book_form.html` 增加面板与预览；`app.js` 增加事件委托；`style.css` 增加面板样式。
- **接口/数据**：无 schema 变更，`icon` 仍是 `String(32)`、可为空。
- **测试**：新增面板存在性/数量、点选后提交、首页渲染三条用例。
