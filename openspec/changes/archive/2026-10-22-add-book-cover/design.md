# Design

## Context

媒体库（`add-media-library`）已经提供「按 Book 隔离的图片资源 + 受控读取地址 + 软删除」，封面本质上就是「Book 指向自己某张图片」。首页卡片是 `index.html` 里的 `book-grid`，详情页 hero 在 `book.html`；两者目前都用 `book.icon`（emoji）或内置矢量图。动机见 `proposal.md`。

## Goals / Non-Goals

**Goals:**

- 复用媒体库，不引入第二套文件存储或第二张资源表。
- 封面失效（资源被删）时页面自动降级，不出现破图。
- 首页卡片在有/无封面两种状态下高度与文字基线一致。

**Non-Goals:**

- 封面裁剪、自动缩略图、多尺寸输出（原图直接用，靠 CSS `object-fit` 裁切）。
- 从正文首图自动提取封面、封面轮播、Glossary 级别的品牌资产管理。
- 跨 Book 共享同一张封面（各 Book 独立引用自己的资源）。

## Decisions

### D1. 用 `media_assets` + `books.cover_media_id` 外键，而不是 `books.cover_url` 字符串

- **理由**：外键能保证「引用的资源存在且属于本 Book」，删除资源时能在服务层统一解绑；字符串 URL 无法阻止指向其他 Book 或已删资源，页面就得在渲染期兜错。
- 迁移 `0011_book_cover`：`ADD COLUMN cover_media_id INTEGER REFERENCES media_assets(id)`；SQLite 不支持 ALTER 加外键，用 `batch_alter_table` 且外键命名（与 0009 同样的坑）。

### D2. 校验集中在 `books.set_cover()`

规则：资源存在 → 属于该 Book → `kind == image` → 未软删。任何一条不满足抛 `ValidationFailed`，并在成功时写 `book.cover` 审计（含旧值与新值）。

- **理由**：网页端与管理 API 共用同一入口，避免两处校验漂移。

### D3. 删除资源时解绑封面

`media.delete_media()` 在软删后检查 `books.cover_media_id == asset.id`，是则置空并写一条 `book.cover` 审计（detail 标 `unbound: true`）。

- **理由**：软删除的地址会 404，如果留着外键，页面会拿到一个必然 404 的 URL；解绑后自然回退到图标。
- **备选**：渲染时判断资源是否已删——每次列表都要 join 一次媒体表，且产生「封面存在但不显示」的隐式状态；不如在删除时一次性修好。

### D4. 首页卡片：封面区固定 148px 高，无封面时同尺寸图标块

`.book-card` 改为纵向：`.book-cover`（图或图标）+ `.book-card-body`。摘要用 `-webkit-line-clamp: 3` 截断。

- **理由**：固定高度保证同一行卡片对齐；`object-fit: cover` 让任意比例的原图都不变形。

### D5. 媒体库页面负责「设为封面」，Book 编辑页只读展示 + 取消

- **理由**：媒体库已经有缩略图与图片清单，在那里选封面最自然；Book 编辑页只显示当前封面与「取消封面」，避免在表单里再造一个文件选择器。

## Risks / Trade-offs

- [原图很大，首页一次拉多张] → 媒体资源本身有 20 MiB 上限与 immutable 缓存；封面建议用不超过 300KB 的图（在文档里提示），不做自动压缩。
- [删除封面后旧地址仍被浏览器缓存] → 地址内容寻址 + immutable，读到的是缓存副本；页面已不再引用它，无副作用。
- [封面被引用于正文同时设为封面] → 允许；两者互不影响，删除时正文会裂图（既有语义），封面自动回退。
- [迁移加外键在 SQLite 上要重建表] → 用 batch 模式；books 表行数很小，重建开销可忽略，已在 0009 验证过同一手法。

## Migration Plan

1. `0011_book_cover`：batch 方式加列 + 命名外键 `fk_books_cover_media_id_media_assets`；downgrade 反向删列。
2. 存量 Book `cover_media_id` 为 NULL，页面行为与现在一致（图标块）。
3. 回滚：删列后封面信息丢失，图片资源仍在媒体库，可重新设置。
