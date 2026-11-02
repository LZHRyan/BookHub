# Spec Delta

## ADDED Requirements

### Requirement: 原始文档通道 MUST 原样输出且运行在沙箱中

对于 HTML 章节，系统 SHALL 提供独立的原始文档地址，MUST 原样返回管理员上传的内容，MUST NOT 经过白名单净化、MUST NOT 注入站点模板。该响应 MUST 通过内容安全策略的 `sandbox` 指令把文档降级为唯一源：MUST 允许文档自身的脚本与内联样式执行，MUST NOT 授予同源权限（即 MUST NOT 包含 `allow-same-origin`），从而使文档脚本无法读取本站 Cookie、本地存储，也读不到同源接口的响应。该响应 MUST 声明 `Referrer-Policy: no-referrer`、禁止搜索引擎收录，并且 MUST NOT 被浏览器缓存。Markdown 章节 MUST NOT 拥有该地址。

#### Scenario: 原样返回文档

- **WHEN** 访客请求某 HTML 章节的原始文档地址
- **THEN** 响应体的内容与该章节上传时的原文逐字一致
- **AND** 文档中的 `<style>`、内联样式、`<script>`、`data:` 内嵌图片全部保留

#### Scenario: 沙箱隔离

- **WHEN** 该原始文档包含脚本
- **THEN** 响应头声明的策略包含 `sandbox` 且包含允许脚本的标记
- **AND** 同一策略 MUST NOT 包含 `allow-same-origin`
- **AND** 文档脚本读取站点 Cookie 或同源接口响应的行为被浏览器拒绝

#### Scenario: 不污染站点来源

- **WHEN** 浏览器打开该原始文档
- **THEN** 响应头禁止搜索引擎收录、声明不发送 Referer 且不缓存
- **AND** 站点的阅读页内容安全策略不受该响应影响

#### Scenario: 草稿与格式限制

- **WHEN** 匿名访客请求一个草稿 HTML 章节、或请求任意 Markdown 章节的原始文档地址
- **THEN** 系统返回 404 且不泄露内容
- **AND** 已登录用户仍可预览草稿的原始文档
