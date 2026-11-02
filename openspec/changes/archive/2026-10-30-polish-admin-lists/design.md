# Design

## Context

`admin/dashboard.html` 的 Book 列表是 7 列表格（标题/分组/可见性/章节/访问/更新/操作），`admin/groups.html` 是 5 列表格。两者的共同特征：字段少、每个字段都很短、操作按钮多。表格的 `width: 100%` + `td.shrink` 组合把剩余宽度全给了「标题」列，于是内容集中在左侧、右侧零散，且 `.table .actions` 虽然是 `flex`，但在窄的 `shrink` 列里会换行成竖排，把行高撑到 ~100px。截图实测：分组页 4 行数据占满整屏，Book 页一屏 7 行。动机见 `proposal.md`。

## Goals / Non-Goals

**Goals:**

- 同屏信息量提升，同时让「标题 → 次要信息 → 操作」形成清晰三层。
- 保持既有交互与链接语义（分组筛选、编辑、查看、删除、上移下移）。
- 只改这两页的呈现，不动数据与 API。

**Non-Goals:**

- 章节表格（字段多、要批量勾选与拖拽，表格更合适）。
- 增加新的排序/筛选能力。
- 引入前端框架或组件库。

## Decisions

### D1. 复用 `book-grid` 的思路，新开 `.admin-card-grid` 而不是直接套首页卡片

首页 `.book-card` 是「封面 + 标题 + 摘要 + 元信息」的展示卡（整卡是链接）；管理卡需要多组独立操作（删除是表单 POST），整卡不能是 `<a>`。因此新建一套：

```css
.admin-card-grid { display: grid; gap: var(--space-4);
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); }
.admin-card { display: grid; gap: var(--space-3); padding: var(--space-4); }
.admin-card-head { display: flex; align-items: center; gap: var(--space-3); }
.admin-card-meta { display: flex; flex-wrap: wrap; gap: var(--space-2); align-items: center; }
.admin-card-foot { display: flex; align-items: center; gap: var(--space-2); margin-top: auto; }
```

- **理由**：`minmax(340px, 1fr)` 在 1440px 下得到 3 列、1200px 下 3 列、800px 下 2 列、600px 以下单列；不需要媒体查询就能自适应。
- 底部用 `margin-top: auto` 让同高度卡片的操作栏对齐。

### D2. Book 卡带封面缩略图，没有封面才回退图标

`dashboard()` 给每项补 `cover`（`media_service.cover_url(session, book, settings)`，单页 ≤20 本，逐条查询可接受）。缩略图 56×56、`object-fit: cover`、圆角。

- **理由**：封面是 Book 最强的识别信号，卡片布局正好能放；表格里放缩略图会让行更高。
- 备选：批量查一次 media 表——当前页 20 条，收益不明显，先用简单实现，必要时再优化。

### D3. 分组的上下移放在卡片右上角，两个图标并排

原表格里它们是两个独立的 `<form>` 竖排（每行 ~40px×2）。卡片里改成右上角 `flex` 的两个 `btn-icon btn-sm`。

- **理由**：保持"一次点击＝一次表单提交"的语义（不改成 fetch），只是布局改横排；禁用态（第一个不能上移）仍由后端静默忽略。

### D4. 分组筛选入口保留 `?group=<slug>` 的纯数字链接

卡片底部保留 `<a class="badge" href="…?group=slug">{{ book_count }}</a>` 再跟一个「本」字，既符合"点数量看该组 Book"的直觉，也保留既有测试对 `?group=infra-a">1</a>` 的断言。

### D5. 危险操作在卡片底部右侧

`改名/编辑/查看` 用次要样式，`删除` 用 `btn-danger` 并保持 `data-confirm`。卡片底部 `flex-wrap` 处理窄屏。

## Risks / Trade-offs

- [卡片比表格占更多纵向空间，单卡信息量下降] → 每卡只保留 4–6 个字段，实际高度约 150px，1440px 下 3 列 × 一屏 6–9 张，优于原 7 行。
- [长标题/长摘要撑破卡片] → 标题 `-webkit-line-clamp: 2`、摘要 `line-clamp: 2`，`min-width: 0` 防溢出。
- [删除按钮在卡片里容易被误点] → 保留二次确认，且卡片布局下按钮与「编辑」有间距。
- [分组卡片没有表格表头，用户可能不清楚「N 本」的含义] → 徽章后跟「本」字，且卡片标题区有 `分组` 上下文（页面标题已说明）。

## Migration Plan

纯前端模板与样式改动，无数据迁移。上线后：
1. 两页直接切换为卡片；
2. 既有书签/链接（`?group=`、分页）不受影响。
