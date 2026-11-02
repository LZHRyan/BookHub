## MODIFIED Requirements

### Requirement: Book 与章节页 MUST 提供一键复制链接

Book 页、章页与节页 MUST 提供一个「复制链接」按钮，复制的内容 MUST 是**绝对地址**（含 scheme、host 与部署前缀 `ROOT_PATH`），MUST NOT 是相对路径。单节章的章页 MUST 复制章地址（其正文就直出在该地址上）；多节章的节页 MUST 复制节地址。复制成功后按钮 MUST 立即给出可见反馈，并在数秒内恢复原样。

#### Scenario: 复制章节链接

- **WHEN** 读者在章页或节页点击「复制链接」
- **THEN** 剪贴板里是该页面的绝对地址（单节章的章页给出章地址，节页给出节地址）
- **AND** 按钮文案短暂变为「已复制」

#### Scenario: 子路径部署也带前缀

- **WHEN** 站点部署在 `ROOT_PATH=/kb`
- **THEN** 复制出来的是 `https://<host>/kb/b/<book>/<chapter>` 或 `https://<host>/kb/b/<book>/<chapter>/<section>` 这类带前缀的地址

#### Scenario: 剪贴板不可用时给出手动复制

- **WHEN** 浏览器不支持剪贴板 API 或用户拒绝授权
- **THEN** 页面弹出可手动复制的地址输入框
- **AND** MUST NOT 静默失败

### Requirement: 页面 MUST 输出 Open Graph 元数据

Book 页、章页与节页 MUST 输出 `og:title`、`og:description`、`og:url`、`og:type`，Book 页与有封面的页面 MUST 输出 `og:image`（绝对地址）。`og:url` MUST 与「复制链接」给出的一致，因此单节章的章页 `og:url` MUST 是章地址而不是重复内容的节地址。

#### Scenario: IM 里贴链接有标题

- **WHEN** 抓取节页（或单节章的章页）的 HTML
- **THEN** `<meta property="og:title">` 是「节标题 · 章标题」，两者同名时只保留一个
- **AND** `og:url` 是绝对地址且与复制链接一致

#### Scenario: 有封面时带图

- **WHEN** 某 Book 设置了封面
- **THEN** 其 Book 页输出 `og:image`，且是绝对地址
