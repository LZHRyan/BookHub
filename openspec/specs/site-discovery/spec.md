# site-discovery Specification

## Purpose
提供让外部系统发现站点内容的两个机器可读入口：搜索引擎用的站点地图与内部监控用的指标端点。

## Requirements

### Requirement: sitemap.xml MUST 列出公开内容

`GET /sitemap.xml` MUST 返回符合 sitemap 协议的 XML（`<urlset>`），包含首页、所有 `public` 且未删除的 Book 页，以及这些 Book 下所有已发布且未删除的章页与节页（多节章的章页是节索引，与它所辖节页各自独立收录）。每项 MUST 带绝对 `loc` 与 `lastmod`（取该对象更新时间）。`unlisted` Book、草稿与已删除内容 MUST NOT 出现。

#### Scenario: 公开内容出现在地图里

- **WHEN** 请求 sitemap
- **THEN** 响应含首页、公开 Book 页、已发布章页与已发布节页的绝对地址
- **AND** `Content-Type` 为 `application/xml`

#### Scenario: 草稿与未列出内容不泄露

- **WHEN** 某 Book 是 `unlisted`，或某章是草稿
- **THEN** 该 Book 的地址、该章及其下节的地址都不出现在 sitemap 中

### Requirement: /metrics MUST 暴露最小指标集

`GET /metrics` MUST 返回 Prometheus 文本格式（`text/plain; version=0.0.4`），至少包含：Book 总数、已发布章节数、媒体资源字节总数、审计记录数、有效 Token 数。指标名 MUST 以 `bookhub_` 前缀且带 `# TYPE` 注释。

#### Scenario: 指标可被解析

- **WHEN** 抓取 `/metrics`
- **THEN** 每行符合 `name value` 形式
- **AND** 含 `bookhub_books_total`、`bookhub_chapters_published_total`、`bookhub_media_bytes_total`
