# Spec Delta

## ADDED Requirements

### Requirement: Book MUST 记录 HTML 阅读方式

HTML 类型的 Book MUST 记录一个阅读方式，取值为 `inline`（站内净化渲染）或 `document`（原始文档通道），默认 `document`。存量的 HTML Book MUST 由一次性数据迁移统一回填为 `document`。创建与更新 Book 时提交非法取值 MUST 被拒绝且 MUST NOT 落库。Markdown 类型的 Book MUST 恒为 `inline`，提交其他取值 MUST 被忽略为 `inline`，而不是产生"Markdown + 原始文档"这种无意义组合。修改该字段 MUST 只影响渲染入口，MUST NOT 改动已上传的章节正文。

#### Scenario: 默认按原始文档打开

- **WHEN** 管理员创建一个 HTML 类型的 Book 且未指定阅读方式
- **THEN** 该 Book 的阅读方式为 `document`
- **AND** 其章节链接指向原始文档并在新标签页打开

#### Scenario: 存量 HTML Book 被回填

- **WHEN** 升级一个已经存在 HTML Book 的站点
- **THEN** 这些 Book 的阅读方式为 `document`
- **AND** 其章节正文与既有链接标识保持不变

#### Scenario: 切换为站内渲染

- **WHEN** 管理员把某 HTML Book 的阅读方式改为 `inline`
- **THEN** 保存成功，Book 详情页显示模式徽章
- **AND** Book 目录中的章节链接改回站内章节页
- **AND** 该 Book 已有章节的正文内容保持不变

#### Scenario: 非法取值被拒绝

- **WHEN** 创建或更新请求把阅读方式设为 `iframe` 或空串之外的任意非法值
- **THEN** 系统返回 4xx 并说明只允许 `inline` 或 `document`
- **AND** 该 Book 的阅读方式保持原值

#### Scenario: Markdown Book 忽略该字段

- **WHEN** 管理员对一个 Markdown 类型的 Book 提交阅读方式 `document`
- **THEN** 保存后的阅读方式仍为 `inline`
- **AND** 其章节始终按 Markdown 渲染管线输出
