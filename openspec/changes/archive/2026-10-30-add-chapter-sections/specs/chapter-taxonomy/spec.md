## REMOVED Requirements

### Requirement: 分卷 MUST 只有标题与位置，不含正文

**Reason**: 分卷这一层已经删除（迁移 `0015_chapter_sections`）：Book 内部的结构变成「章 → 节」，章只承载目录与发布状态，正文与版本在节上。分卷的「只有标题与位置」语义没有承接对象。

**Migration**: 存量分卷与其下章节不再保留（本次迁移不搬运存量内容）。新建内容请用「一章多节」：章是目录行，节是一份 `.md` / `.html` 文件。目录层级与编号规则见 `chapter-sections` 能力。

### Requirement: 层级深度 MUST 限制为一层

**Reason**: 该要求约束的是「分卷 → 章节」的父子关系，`chapters.parent_id` / `kind` 已随迁移删除，系统里不再存在可嵌套的父子关系。

**Migration**: 目录固定两级（Book → 章 → 节），节不是可再嵌套的目录项。层级规则见 `chapter-sections` 的「节 MUST 有独立页面与稳定地址」。

### Requirement: 归属变更 MUST 保持排序稳定

**Reason**: 归属变更依赖 `chapters.parent`，该字段已删除；章直接挂在 Book 下，排序只在 Book 内一维进行。

**Migration**: 调整顺序改用 `chapter-lifecycle` 的「章节排序调整」与「排序 MUST 支持按有序 id 列表整体重排」（拖拽与上移/下移），没有跨父级的移动语义。

### Requirement: 删除分卷 MUST 要求先清空

**Reason**: 分卷表与相关外键已删除，不存在「非空分卷不能删」的规则。

**Migration**: 删除章时它的节一起软删除，可整章从回收站恢复（见 `chapter-lifecycle` 的「章节软删除与恢复」）。

### Requirement: 目录 MUST 按分卷分组并层级编号

**Reason**: 目录不再按分卷分组，改为「章 → 节」两级；编号规则随之改为 `1.` / `1.1`，由 `chapter-sections` 的「节级序号 MUST 为「章号.节号」」定义。

**Migration**: 目录与节页面包屑见 `public-reading`；分卷名不再出现在面包屑里。
