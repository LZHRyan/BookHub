# Spec Delta

## Purpose

让 Book 与章节页面都有一条可一键复制的绝对地址，并带上 Open Graph 元数据，使链接在 IM、邮件与社交平台里能直接显示标题与摘要。

## ADDED Requirements

### Requirement: Book 与章节页 MUST 提供一键复制链接

Book 页与章节页 MUST 提供一个「复制链接」按钮，复制的内容 MUST 是**绝对地址**（含 scheme、host 与部署前缀 `ROOT_PATH`），MUST NOT 是相对路径。复制成功后按钮 MUST 立即给出可见反馈，并在数秒内恢复原样。

#### Scenario: 复制章节链接

- **WHEN** 读者在某章节页点击「复制链接」
- **THEN** 剪贴板里是该章节的绝对地址
- **AND** 按钮文案短暂变为「已复制」

#### Scenario: 子路径部署也带前缀

- **WHEN** 站点部署在 `ROOT_PATH=/kb`
- **THEN** 复制出来的是 `https://<host>/kb/b/<book>/<chapter>` 这类带前缀的地址

#### Scenario: 剪贴板不可用时给出手动复制

- **WHEN** 浏览器不支持剪贴板 API 或用户拒绝授权
- **THEN** 页面弹出可手动复制的地址输入框
- **AND** MUST NOT 静默失败

### Requirement: 页面 MUST 输出 Open Graph 元数据

Book 页与章节页 MUST 输出 `og:title`、`og:description`、`og:url`、`og:type`，Book 页与有封面的页面 MUST 输出 `og:image`（绝对地址）。`og:url` MUST 与「复制链接」给出的一致。

#### Scenario: IM 里贴链接有标题

- **WHEN** 抓取章节页的 HTML
- **THEN** `<meta property="og:title">` 是「章节标题 · Book 标题」
- **AND** `og:url` 是绝对地址

#### Scenario: 有封面时带图

- **WHEN** 某 Book 设置了封面
- **THEN** 其 Book 页输出 `og:image`，且是绝对地址
