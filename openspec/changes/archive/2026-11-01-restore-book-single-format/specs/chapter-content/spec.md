## MODIFIED Requirements

### Requirement: 节正文双格式保存

每一个节 MUST 声明内容格式为 `markdown` 或 `html` 之一，且该格式 MUST 等于所属 Book 的文档类型（整本统一，不允许混排）。系统 SHALL 按上传或提交的原文原样保存正文，MUST NOT 在保存阶段改写语法结构；读取原文时 MUST 返回与保存时一致的内容（编码归一化除外）。格式仅决定展示与渲染路径，不影响原文的可取回性。

#### Scenario: Markdown 原文原样取回

- **WHEN** 管理员提交一份含表格与代码块的 Markdown 正文并保存
- **THEN** 按原文通道读取该节时，返回内容与提交内容逐字符一致
- **AND** 返回的格式标注为 `markdown`

#### Scenario: HTML 原文原样取回

- **WHEN** 管理员提交一份 HTML 正文并保存
- **THEN** 按原文通道读取该节时，返回内容与提交内容逐字符一致
- **AND** 返回的格式标注为 `html`

#### Scenario: 未指定格式时拒绝保存

- **WHEN** 提交的节声明的格式不属于 `markdown`、`html`
- **THEN** 系统拒绝保存并返回 4xx 状态码
- **AND** 错误信息指明格式取值非法

#### Scenario: 未指定格式时继承 Book 默认值

- **WHEN** 提交节时完全未声明格式
- **THEN** 系统按所属 Book 的文档类型保存该节
- **AND** 保存后的格式标注等于该 Book 的文档类型

#### Scenario: 格式与 Book 不一致时拒绝

- **WHEN** 向一本 Markdown 的 Book 提交声明为 `html` 的节
- **THEN** 系统拒绝保存并提示这本书是 Markdown 类型
- **AND** 该 Book 下不会出现 HTML 节
