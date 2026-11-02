# Proposal

## Why

首页现在每个 Book 只有一个 emoji 图标，卡片靠文字撑场面：文档一多，读者只能逐行读标题才能在「部署手册」「接口规范」「事故复盘」之间找到目标，视觉上也没有任何可辨识的锚点。技术文档封面往往是架构图、系统截图或一张品牌图，比 emoji 有信息量得多。

## What Changes

- Book 新增封面：`books.cover_media_id` 指向该 Book 媒体库里的一张图片（复用已有的 `media_assets`，不另造存储），置空表示回退到 emoji 图标。
- 设置入口：媒体库页面每张图片卡片加「设为封面」；Book 编辑页显示当前封面与「取消封面」。
- 封面校验：只能指向**本 Book 名下、类别为 image、未软删**的资源，任何越权或类型不符 MUST 被拒绝。
- 删除封面资源时 MUST 自动解除封面绑定（不留悬空引用）。
- 展示：首页卡片改为「封面图 + 标题/摘要/章节数」的图文布局，无封面时回退 emoji 图标块；Book 页 hero 区在标题右侧显示封面缩略图。
- 对外 API：Book 表示新增 `cover`（`{id, url}` 或 `null`），`PATCH /api/v1/admin/books/{ref}` 接受 `cover_media_id`。
- 顺带把首页卡片的信息层次理顺：标题、摘要两行截断、底部元信息，空态与分页不变。

## Capabilities

### New Capabilities

- `book-cover`: 封面的所有权与校验（只能引用本 Book 的未删除图片）、设置与取消、被删资源自动解绑，以及首页/详情页在有无封面时的回退表现。

### Modified Capabilities

- `management-api`: Book 更新 MUST 支持设置/清除封面，Book 表示 MUST 暴露 `cover`。
- `web-presentation`: 首页卡片 MUST 支持封面图布局并在无封面时回退图标块，且在小屏下仍可读。

## Impact

- **数据**：迁移 `0011_book_cover`（`books.cover_media_id` FK `media_assets.id`，可空；SQLite 用 batch 模式加外键），有 downgrade。
- **服务层**：`books.set_cover()`（校验 + 审计）、`media.delete_media()` 解绑封面、`_book_payload` / `_book_json` 输出 `cover`。
- **Web**：`POST /admin/books/{id}/cover`（设置/清除）、媒体库页面按钮、Book 编辑页显示当前封面。
- **模板/样式**：`index.html` 卡片、`book.html` hero、`admin/book_form.html`、`admin/media.html`、`style.css`。
- **测试**：新增 `tests/test_cover.py`（校验、越权、解绑、API 字段、页面渲染）。
- **非目标**：不做封面裁剪/自动缩略图、不做多封面与封面轮播、不做从正文首图自动提取封面。
