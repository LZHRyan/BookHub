# 数据模型与内容规则

依据 `app/models.py`、`alembic/versions/0001_initial.py`、`alembic/versions/0015_chapter_sections.py`、`alembic/versions/0016_section_index.py`、`app/services/{books,chapters,sections,slug,render}.py`。字段名与类型逐字对应代码，可直接对照 ORM 定义。

---

## 1. 总览

```text
User ──(created_by/updated_by)── 挂在 Book / Chapter / ChapterSection / SectionVersion 上

BookGroup 1 ──── n Book 1 ──── n Chapter 1 ──── n ChapterSection 1 ──── n SectionVersion
                    │              │                    │
                    │              │                    ├─ content_raw / content_rendered / content_toc / content_checksum
                    │              │                    ├─ chapter_fts (FTS5 虚拟表，rowid = chapter_sections.id)
                    │              │                    └─ section_view_daily（访问计数，Book 热度按其各节之和）
                    │              └─ status / published_at（发布状态在章级）
                    └─ 目录字段：slug / title / sort_order

AuditLog（只追加，弱引用所有对象）
SiteSetting（key/value，只存 3 个键）
```

- 层级是 `BookGroup → Book → Chapter → ChapterSection`：**Book 必属于且只属于一个组**（`books.group_id` 非空），组只是首页分区，不带可见性、权限与页面。
- **章 = 容器，节 = 内容单元**：`chapters` 只有目录字段与发布状态；正文、格式、字数、版本都在 `chapter_sections`。
- 「分卷」已经彻底删除（迁移 `0015_chapter_sections`）：目录只剩两级，编号回到 `1.` / `1.1`。

- 所有时间列都是**不带时区的 UTC**（`utcnow()` 返回 `datetime.now(UTC)` 去掉 tzinfo）。
- 没有物理外键级联删除，唯一例外是 `chapter_sections.chapter_id` 与 `section_versions.section_id` 上的 `ON DELETE CASCADE`。
- `Book` / `Chapter` / `ChapterSection` 的删除都是**软删除**（`deleted_at` 打时间戳），从不出现在物理删除路径。

---

## 2. BookGroup（表 `book_groups`）

Book 的上一层：一个组就是首页上的一个分区，**每本 Book 必属于且只属于一个组**。组是薄实体——只有标题、slug、简介、图标与位置，不带可见性、权限与页面。

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `id` | Integer PK | 自增 | `books.group_id` 指向它 |
| `slug` | String(160) UNIQUE | — | **整表唯一**（组没有软删除，所以不是部分唯一索引）；只用于 API 的 `{ref}`、只读 API 的 `?group=<slug\|id>` 与首页的 `/?group=<slug>`，**不出现在读者地址栏** |
| `title` | String(120) | — | 必填，服务层限制 ≤120；首页分区标题 |
| `description` | Text | `""` | 分区说明，为空时首页不显示这一段 |
| `icon` | String(32) | `""` | 图标名（如 `folder-tree`），显示在分区标题与 Book 页的面包屑前 |
| `sort_order` | Integer | `0` | 组之间的先后顺序；新建取「当前最大值 + 10」，上移/下移后整体重写为 10/20/30… |
| `created_at` / `updated_at` | DateTime | `utcnow` | `updated_at` 只在改标题/slug/简介/图标时更新，调整顺序不动它 |

索引：

| 名称 | 定义 | 作用 |
| --- | --- | --- |
| `slug` UNIQUE | 列级唯一约束 | `book_groups.get_group()` 按 slug 或纯数字 id 解析 `{ref}` |
| `ix_book_groups_sort_order` | `(sort_order)` | 首页分区顺序、组列表、上移/下移 |

- 迁移 `0014_book_groups` 建表后立刻插入一行 slug `default`、标题「默认分组」、`sort_order = 10`，并把当时所有 Book 的 `group_id` 回填成它；运行时的 `book_groups.ensure_default()` 再兜一次底，保证任何 Book 都有组。
- 删除约束由**服务层**强制（外键上没有 `ON DELETE` 级联）：组下还有 Book（**含软删除的**）→ 拒绝；只剩一个组 → 拒绝。所以「回收站里的 Book」同样占着组。

---

## 3. Book（表 `books`）

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `id` | Integer PK | 自增 | |
| `group_id` | FK `book_groups.id` | — | **必填**（NOT NULL，索引 `ix_books_group_id`）：所属分组。存量 Book 由迁移 `0014_book_groups` 全部归入「默认分组」，之后新建/编辑都必须显式指定；换组只改这一列 |
| `slug` | String(160) | — | URL 标识，`[a-z0-9-]`；与 `deleted_at IS NULL` 组成部分唯一索引 |
| `title` | String(200) | — | 必填，服务层限制 ≤200 |
| `summary` | Text | `""` | 简介，首页卡片与 Book 页展示 |
| `icon` | String(32) | `""` | 内置图标名；空时页面回退为默认矢量图标 |
| `format` | String(16) | `markdown` | **文档类型（整本唯一）**：`markdown` \| `html`。所有节都必须用它；有章之后不可修改（`update_book` 会拒绝） |
| `html_view` | String(16) | `inline` | HTML Book 的阅读方式：`document`（默认，`/raw` 原样输出、新标签页打开）\| `inline`（站内净化渲染）。列默认值保留 `inline` 作安全兜底，HTML Book 由服务层默认写成 `document`；Markdown Book 恒为 `inline` |
| `visibility` | String(16) | `public` | `public` \| `unlisted` |
| `pinned` | Boolean | `false` | 置顶：置顶的 Book 排在列表最前，置顶内部仍按权重排序 |
| `cover_media_id` | FK `media_assets.id` | `NULL` | 封面：只能指向本 Book 名下、类别为 image、未软删的资源；资源被删时自动置空 |
| `created_at` / `updated_at` | DateTime | `utcnow` | 首页排序的新鲜度按 `created_at` 计算 |
| `created_by` | FK `users.id` | `NULL` | 创建人 |
| `deleted_at` | DateTime | `NULL` | 非空即已软删除 |

Book 没有"排序权重"字段：首页顺序完全由访问热度与创建时间在请求时算出，见第 4.1 节。Book 也**没有**手工组内序号：组内顺序沿用同一套权重，分组只决定它落在哪个分区。

索引：

| 名称 | 定义 | 作用 |
| --- | --- | --- |
| `uq_books_slug_active` | `slug` UNIQUE **WHERE `deleted_at IS NULL`** | slug 只对"活着的" Book 唯一，删掉后 slug 可被新 Book 复用 |
| `ix_books_listing` | `(deleted_at, visibility)` | 首页与 API 列表的过滤条件 |

---

## 4. SectionViewDaily（表 `section_view_daily`）

访问热度的唯一数据来源：按「**节** × UTC 日期」聚合的访问计数，不存访问明细。

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `section_id` | Integer，联合 PK，FK `chapter_sections.id` ON DELETE CASCADE | — | |
| `day` | Date，联合 PK | — | UTC 日期 |
| `views` | Integer | `0` | 当天这一节的累计访问次数 |
| `updated_at` | DateTime | `utcnow` | 最近一次累加时间 |

索引：

| 名称 | 定义 | 作用 |
| --- | --- | --- |
| PK | `(section_id, day)` | 单次累加按这两列定位，天然去重 |
| `ix_section_view_daily_day` | `(day)` | 清理历史数据、按天巡检 |

- **计数粒度到节**：Book 目录页不计热度，读到某一节才算；一次访问记在「当时读到的那一节」上。
- 一本书的热度 = 它各节访问数之和（`ranking.stats_for` 按 `section_view_daily → chapter_sections → chapters` 聚合）。
- 去重依旧是「同一 IP 对同一 Book 30 分钟内只计一次」（`visits.VisitDeduper`），避免刷新刷热度。
- 行数上限是「节数 × 有访问的天数」，与访问量无关；目前没有自动清理任务，需要时可手工删 90 天前的行（删掉只会让累计访问变小）。
- 迁移 `0016_section_index` 起，原来的 `book_view_daily`（Book 级计数）已删除。

### 4.1 排序权重怎么算

`app/services/ranking.py` 里每次列表请求实时计算，不落库：

```text
weight = 100 × ln(1 + 近 7 天访问数)
       +  25 × ln(1 + 累计访问数)
       +  60 × 2 ** (-创建天数 / 14)
```

- **热度越高 → 权重越大**：近 7 天访问是主信号（系数 100），累计访问打 1/4 折做长期加权。
- **创建越晚 → 权重越大**：新鲜度项让新书起点高（60 分），之后每 14 天减半，两个月后基本归零。
- **顺序稳定**：同一次请求里所有 Book 共用同一个"现在"，新鲜度项等于一个公共正因子乘 `2 ** (created_at/14)`，不影响相对大小；所以只要访问量不变，排序就不会因为刷新而抖动。
- 权重相同时按 `created_at` 倒序、`id` 倒序兜底。

---

## 5. Chapter（表 `chapters`）

**章只是容器**：只有目录字段与发布开关，没有正文、格式与版本（迁移 `0015_chapter_sections` 把这些列搬到了节上）。

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `id` | Integer PK | 自增 | |
| `book_id` | FK `books.id` | — | 必填，索引 |
| `slug` | String(160) | — | 与 `(book_id, deleted_at IS NULL)` 组成部分唯一索引 |
| `title` | String(200) | — | 必填 |
| `sort_order` | Integer | `0` | Book 内顺序，重排后为 10/20/30… |
| `status` | String(16) | `draft` | `draft` \| `published`。**发布状态只在章级**：章发布 → 它下面所有节可见；草稿 → 所有节 404 |
| `published_at` | DateTime | `NULL` | **首次**发布时间，撤回不清空 |
| `created_at` / `updated_at` | DateTime | `utcnow` | `updated_at` 也随其下节的写入刷新 |
| `created_by` / `updated_by` | FK `users.id` | `NULL` | |
| `deleted_at` | DateTime | `NULL` | 软删除标记（删除章会让它下面的节一起从访客视角消失） |

索引：

| 名称 | 定义 | 作用 |
| --- | --- | --- |
| `uq_chapters_book_slug_active` | `(book_id, slug)` UNIQUE **WHERE `deleted_at IS NULL`** | 同一 Book 内 slug 唯一；删除后可复用 |
| `ix_chapters_order` | `(book_id, deleted_at, sort_order)` | Book 目录与上一篇/下一篇 |
| `ix_chapters_changes` | `(updated_at)` | 增量同步扫描 |

---

## 6. ChapterSection（表 `chapter_sections`）

**节 = 一份文件**：标题、格式、正文、字数与版本都在这里。

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `id` | Integer PK | 自增 | 也是 `chapter_fts` 的 `rowid` |
| `chapter_id` | FK `chapters.id` **ON DELETE CASCADE** | — | 必填，索引 |
| `slug` | String(160) | — | 与 `(chapter_id, deleted_at IS NULL)` 组成部分唯一索引；留空时按节标题生成，中文标题回退成 `section-xxxxxx` |
| `title` | String(200) | — | 必填；节页标题、章索引页的列表标题 |
| `format` | String(16) | `markdown` | `markdown` \| `html`；**整本统一**，MUST 等于所属 Book 的 `format`（服务层校验） |
| `content_raw` | Text | `""` | 原文（Markdown 或 HTML），**是唯一真相**；HTML 节保留管理员上传的原始内容，仅供管理端查看 |
| `content_safe` | Text | `""` | 对外安全的"原文"：Markdown 与 `content_raw` 相同，HTML 为其白名单净化结果；API 的 `content_raw`、导出 ZIP 都取这一列 |
| `content_rendered` | Text | `""` | 净化+高亮+加锚点后的 HTML，读路径直接输出 |
| `content_toc` | Text | `"[]"` | JSON 数组字符串：`[{"level":2,"text":"...","anchor":"..."}]` |
| `content_checksum` | String(64) | `""` | `sha256(content_raw)` 的十六进制 |
| `word_count` | Integer | `0` | 中文字数 + 英文词数 |
| `sort_order` | Integer | `0` | **章内**顺序，重排后为 10/20/30…（展示编号 = 章号.节序，如 `1.1`） |
| `current_version_no` | Integer | `1` | 当前版本号，单调递增（每节各自一套） |
| `created_at` / `updated_at` | DateTime | `utcnow` | `updated_at` 也是增量同步的依据 |
| `created_by` / `updated_by` | FK `users.id` | `NULL` | |
| `deleted_at` | DateTime | `NULL` | 软删除标记 |

索引：

| 名称 | 定义 | 作用 |
| --- | --- | --- |
| `uq_chapter_sections_slug_active` | `(chapter_id, slug)` UNIQUE **WHERE `deleted_at IS NULL`** | 同一章内 slug 唯一；删除后可复用 |
| `ix_chapter_sections_order` | `(chapter_id, deleted_at, sort_order)` | 章索引页、上一篇/下一篇 |
| `ix_chapter_sections_chapter_id` | `(chapter_id)` | 按章取节 |

### 6.1 派生字段的算法

| 字段 | 何时重算 | 算法 |
| --- | --- | --- |
| `content_checksum` | 创建 / 替换 / 回滚 | `sha256(content_raw.encode()).hexdigest()`，64 字符 |
| `content_rendered` | 同上 | Markdown 走 CommonMark → 净化 → 锚点/TOC；HTML 走 净化 → 锚点/TOC |
| `content_toc` | 同上 | 从渲染结果里抽 `h1–h6`，`anchor` 去重 |
| `word_count` | 同上 | 渲染结果去标签后的文本：CJK 字符数 + `[A-Za-z0-9_]+` 词数 |

读路径**零渲染**：页面和 API 都直接输出 `content_rendered`。所以"渲染很慢"只影响写入，不影响浏览。

`content_checksum` 的用途：节 ETag（取前 8 位）、导出清单里的版本指纹、外部系统判断"这一节有没有变"。

### 6.2 幂等保存

`replace_content` 会比较「标题 + 格式 + 正文（CRLF 归一化后）+ slug」：**都没变就直接返回，不产生新版本**，也不写审计与 Webhook。这是"连点两次保存只多一个版本"的根因修复。

---

## 7. SectionVersion（表 `section_versions`）

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `id` | Integer PK | 自增 | |
| `section_id` | FK `chapter_sections.id` **ON DELETE CASCADE** | — | 索引 |
| `version_no` | Integer | — | 与 `section_id` 组成唯一约束 `uq_section_version` |
| `title` | String(200) | `""` | 该版本的标题（回滚时会一起恢复） |
| `format` | String(16) | `markdown` | 该版本的格式 |
| `content_raw` | Text | `""` | 该版本的原文快照（**只存原文，不存渲染结果**） |
| `note` | String(200) | `""` | 版本备注（默认「新建节」/「替换内容」/「回滚到版本 N」） |
| `created_by` | FK `users.id` | `NULL` | |
| `created_at` | DateTime | `utcnow` | |

### 7.1 版本生命周期（节级）

- 新建节 → 写入 `version_no = 1`，同时 `chapter_sections.current_version_no = 1`。
- 每次替换 / 回滚 → `current_version_no + 1`，并写入同号版本行。
- 保留策略：`VERSION_RETENTION`（默认 **50**）在写入后裁剪——按 `version_no` 倒序取前 N 个，之后的物理删除，但**当前版本永不删除**（即使它因异常落在第 N 名之后）。
- 回滚 **只作用于一个节**：把旧版本的 `title/format/content_raw` 取出来当一次新替换，所以是"新版本内容是旧的"，章的状态不变。回滚本身也可被回滚。
- 版本行不参与检索索引，也没有 `content_rendered`——版本页展示的是原文，diff 也是原文行级对比。
- 迁移 `0015_chapter_sections` 已删除旧的 `chapter_versions`（章不再有版本）。

---

## 8. User / AuditLog / SiteSetting

### 8.1 User（`users`）

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `id` | Integer PK | | |
| `username` | String(64) UNIQUE | — | 唯一索引 `ix_users_username`；存小写 |
| `display_name` | String(120) | `""` | 空时页面回退用户名 |
| `password_hash` | String(255) | — | bcrypt（rounds=12） |
| `role` | String(16) | `editor` | `admin` \| `editor` |
| `is_active` | Boolean | `True` | 停用即不能登录 |
| `session_epoch` | Integer | `1` | 改密码/停用时 +1，使旧会话立即失效 |
| `created_at` | DateTime | `utcnow` | |
| `last_login_at` | DateTime | `NULL` | 每次成功登录更新 |

### 8.2 AuditLog（`audit_logs`）

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `id` | Integer PK | | |
| `actor_id` | Integer | `NULL` | 无外键约束（账号删除/停用后仍要保留记录） |
| `actor_name` | String(120) | `""` | 冗余存显示名，系统动作为 `system` |
| `action` | String(64) | — | 如 `section.replace` / `chapter.publish` |
| `target_type` | String(32) | — | `book` / `chapter` / `section` / `group` / `user` / `settings` |
| `target_id` | Integer | `NULL` | |
| `target_label` | String(200) | `""` | 对象标题，截断到 200 |
| `book_id` | Integer | `NULL` | 索引，便于按 Book 过滤 |
| `detail` | Text | `"{}"` | JSON 字符串 |
| `ip` | String(64) | `""` | 截断到 64 |
| `created_at` | DateTime | `utcnow` | 索引 `ix_audit_created` |

只追加，没有任何更新/删除入口。

### 8.3 SiteSetting（`site_settings`）

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `key` | String(64) PK | — | 只允许 `site_name` / `site_footer` / `home_intro` |
| `value` | Text | `""` | |
| `updated_at` | DateTime | `utcnow` | |

有行就覆盖环境变量默认值；没有行就用 `SITE_NAME` / `SITE_FOOTER` / `HOME_INTRO`。

### 8.4 chapter_fts（FTS5 虚拟表）

不是 ORM 模型，由迁移创建（`0016_section_index` 重建过）：

```sql
CREATE VIRTUAL TABLE chapter_fts USING fts5(
  book_id UNINDEXED, chapter_id UNINDEXED, section_id UNINDEXED,
  title, body, tokenize='unicode61 remove_diacritics 2')
```

- `rowid` 对应 `chapter_sections.id`（**节**，不再是章）。
- `book_id` / `chapter_id` / `section_id` 是 `UNINDEXED` 列：只存不索引，MATCH 只命中 `title` 与 `body`。
- `title` / `body` 存的是**切分后的 token 串**（见 [search.md](search.md)）。备份时要连 `chapter_fts_*` 影子表一起带走。

---

## 9. slug 规则

`app/services/slug.py`：

| 环节 | 规则 |
| --- | --- |
| 派生 | NFKD 归一化 → 只保留 ASCII → 小写 → 非 `[a-z0-9]` 连续段压成 `-` → 去首尾 `-` → 截断到 **120** 字符 |
| 结果为空 | 回退 `book-<6 位十六进制>` / `chapter-<6 位十六进制>` / `section-<6 位十六进制>`（`token_hex(3)`），例如 `book-c1e1b9` |
| 冲突 | 依次尝试 `-2`、`-3`…… 到 `-9999`；仍冲突则追加 8 位随机十六进制 |
| 唯一范围 | Book 全局唯一；Chapter 在**同一 Book 内**唯一；Section 在**同一章内**唯一 |
| 软删除后 | 部分唯一索引只约束"活着的行"，所以删掉 `dev-handbook` 后可以再建一个同 slug 的 |
| 恢复时冲突 | 恢复 Book/Chapter/Section 时若 slug 已被占用，自动改名（追加 `-2`…），恢复不会失败 |
| 何时可改 | Book 可在编辑页改；**章的 slug 在章编辑器里改**；**节的 slug 在节编辑器里改**（改 slug 也会生成一个新版本） |
| 迁移生成 | 迁移不搬存量数据，新建的节按标题生成 slug（中文回退成 `section-xxxxxx`） |

标题锚点走另一套规则（`anchor_slug`）：**保留中文**，其余非 `\w`/空白/连字符的字符去掉，空格与连字符并成 `-`，重复时追加 `-2`。

---

## 10. 可见性、状态机与软删除

### 10.1 可见性（Book 级）

| 值 | 首页 | 目录页 | 搜索 | 直链 | API 列表 |
| --- | --- | --- | --- | --- | --- |
| `public` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `unlisted` | ❌ | ✅ | ❌ | ✅ | ❌（`visibility=unlisted/all` 需 API_KEY） |

### 10.2 章状态机（发布状态只在章级）

```text
        ┌──────── set_status(published) ────────┐
        │        （published_at 首次置位）        │
     draft ◄──── set_status(draft) ──────── published
        │                                      │
        └────────── soft delete ───────────────┘
                     deleted_at 非空（保留原 status，其下节一起对外消失）
                        └── restore ──► 回到删除前的 status
```

| 迁移 | 副作用 |
| --- | --- |
| `draft → published` | `status`、`published_at`（若为空才写）、`updated_at`、审计 `chapter.publish`、Webhook `chapter.published` + 每个节一条 `section.published` |
| `published → draft` | `status`、`updated_at`、审计 `chapter.unpublish`、Webhook `chapter.unpublished`；**`published_at` 不清空** |
| 同状态重复设置 | 服务层直接返回，不写库、不写审计 |
| 软删除章 | `deleted_at`、`updated_at`、把它所有节从 FTS 索引移除、审计 `chapter.delete`；节本身**不**软删 |
| 恢复章 | 清空 `deleted_at`、`updated_at`、按需改 slug、把它的节重新写回索引、审计 `chapter.restore` |
| 软删除节 | 只动那一节：`deleted_at`、从 FTS 移除、审计 `section.delete` |

节**没有**独立状态。可见条件是 **章 `status = published` 且章未删除且节未删除且 `book.deleted_at IS NULL`**（`find_section` / `sections_service.ordered_sections` / 搜索的基础条件）。

### 10.3 Book 软删除的特殊之处

- 删 Book **只标记 `books.deleted_at`**，章节与节的行完全不动（不级联）。
- 所有读路径都 `JOIN`/查询 `books.deleted_at IS NULL`，所以章页与节页对外一律 404。
- 恢复 = 清空 Book 的 `deleted_at` 即可整本回归；章与节的 `deleted_at` 保持原样（之前单独删过的仍是删除态）。
- 章 slug 的唯一性只在同一 `book_id` 内成立、节 slug 只在同一 `chapter_id` 内成立，因此删 Book 不会影响别的 Book。
- 回收站里的 Book **仍然占着它的分组**（`group_id` 没被清空），所以「非空分组不可删」的判断会把软删除的 Book 一起算进去。

---

## 11. 排序规则

| 对象 | 新建时 | 排序键 | 重排 |
| --- | --- | --- | --- |
| BookGroup | `sort_order = max(全部组) + 10` | `sort_order ASC, id ASC` | 上移/下移与**相邻的组**交换后，把全部组的序号整体重写为 10/20/30…；组不支持拖拽 |
| Book（组内） | 无排序字段，顺序由权重算出（见 4.1） | `pinned DESC, weight DESC, created_at DESC, id DESC` | 只有 `pinned` 开关可人工干预；置顶内部仍按权重。`group_id` 不参与排序，只在分桶时使用 |
| Chapter | `sort_order = max(同 Book 未删除章) + 10` | `(sort_order, created_at, id)` 升序 | 上移/下移相邻交换后把该 Book 的章整体重写为 10/20/30…；也支持拖拽整体重排 |
| ChapterSection | `sort_order = max(同章未删除节) + 10` | `(sort_order, created_at, id)` 升序 | 上移/下移相邻交换后把该章整体重写为 10/20/30…；**不做拖拽、不做跨章移动** |

- 组与 Book 是**两层顺序**：组之间按 `sort_order ASC` 决定首页分区的先后；每个组内部再按上表的权重规则排。首页由 `book_groups.overview()` 一次算出全部权重后按 `group_id` 分桶（保持组内顺序），组内最多展示 24 本，其余经「查看全部」进 `/?group=<slug>`。
- 没有可见 Book 的组不渲染分区；带 `?group=<slug>` 时只渲染这一个组。

- Book 列表的排序在 Python 里完成（`ranking.rank_books`）：先取符合条件的全部 Book，算权重再切片分页，因此分页的 `total` 与各页内容来自同一份集合，不会重复或漏项。
- 章的排序作用域是 Book；节的排序作用域是章（`next_sort_order(session, chapter_id)`），两者互不影响。
- 序号留 10 的间隔是为了将来"手工插一条"，但注意：**任何一次上移/下移都会把该作用域的序号压平成 10/20/30**，所以别指望手工插的空档能长期保留。
- 整体重排 API（`reorder_chapters`）要求传入的 id 集合与该 Book 当前未删除章完全一致，否则 400；节的 `reorder_sections` 同理。
- 目录里看到的编号（`1.`、`1.1`）是渲染序号（`tree()` + `section_numbers()` 计算），不是 `sort_order`。

---

## 12. 数据量估算

| 项 | 估算 |
| --- | --- |
| 单节存储 | `content_raw` + `content_rendered`（约 1.5–3 倍原文）+ 索引 |
| 版本开销 | 每版存一份 `content_raw`，最多 `VERSION_RETENTION`（50）份，之后滚掉 |
| FTS 索引 | 约为纯文本的 30%–60%（含影子表） |
| 1000 节 × 平均 20 KiB 原文 | 原文 20 MiB；渲染结果 ~40 MiB；版本最多 ~1000 MiB（若不常改会远低于此） |

这就是 `VERSION_RETENTION` 存在的意义：它是磁盘占用的主要放大器。

媒体资源（图片/附件）的体积往往比正文大一两个数量级，所以另有配额与清理机制，见下一节。

---

## 13. MediaAsset（表 `media_assets`）

一行 = 一个 Book 名下的一个图片或附件。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | int | 主键 |
| `book_id` | FK `books.id` | 归属 Book，**不跨 Book 复用** |
| `filename` | varchar(255) | 原始文件名，仅用于展示与下载，不参与路径 |
| `stored_name` | varchar(200) | `{sha256[:16]}-{安全文件名}`，全局唯一 |
| `mime` | varchar(100) | 由扩展名与内容嗅探共同确定的类型 |
| `byte_size` | int | 字节数，配额统计用 |
| `checksum` | varchar(64) | 完整 SHA-256，去重与幂等的依据 |
| `kind` | varchar(16) | `image`（正文内联）或 `attachment`（下载） |
| `created_by` / `created_at` | FK / datetime | 上传者与时间 |
| `deleted_at` | datetime | 软删除标记；软删除资源不计入配额，但仍可被已发布正文引用 |

物理布局：`{DATA_DIR}/media/{book_slug}/{stored_name}`。

- **内容寻址**：同一 Book 内同内容文件 `stored_name` 相同 → 天然去重、地址可 `immutable` 长缓存。
- **引用判定**：在 `chapter_sections.content_raw` 与 `section_versions.content_raw` 里做 `stored_name` 子串匹配（含草稿与已删除的章/节），误判方向偏向「保留文件」。
- **回收**：软删除 → 超过 `MEDIA_PURGE_GRACE_DAYS` 且仍无引用 → 清理接口物理删文件并删行。
- **孤儿文件**：手工删库或回滚迁移后 `data/media/` 可能留残留，直接删目录即可，不影响应用。
