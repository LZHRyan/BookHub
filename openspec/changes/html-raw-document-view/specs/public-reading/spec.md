# Spec Delta

## ADDED Requirements

### Requirement: 章节页 MUST 提供原始排版入口

对于 HTML 类型的 Book，章节阅读页 MUST 显示一条说明当前阅读方式的提示，并 MUST 提供一个在新标签页打开该章节原始文档的入口（MUST 使用 `rel="noopener"`）。当 Book 的阅读方式为 `document` 时，Book 目录页的章节链接 MUST 直接指向原始文档并在新标签页打开，同时 MUST 说明该书按原始版式提供；此时章节阅读页 MUST 仍然可以正常访问，作为净化版兜底。

#### Scenario: 站内渲染模式下的入口

- **WHEN** 访客阅读 `inline` 模式 HTML Book 的章节
- **THEN** 页面提示当前是站内安全渲染版
- **AND** 页面提供在新标签页打开原始文档的入口

#### Scenario: 原始文档模式下的跳转

- **WHEN** 访客在 `document` 模式 Book 的目录页点击某章节
- **THEN** 链接在新标签页打开该章节的原始文档
- **AND** 目录页说明该书按原始版式提供

#### Scenario: 章节页作为兜底

- **WHEN** 访客直接访问 `document` 模式 Book 的章节页
- **THEN** 页面正常返回净化后的正文
- **AND** 页面提示本书按原始版式提供并给出原始文档入口
