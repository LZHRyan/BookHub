# Spec Delta

## ADDED Requirements

### Requirement: 内容无变化的保存 MUST 幂等

保存章节时若标题、正文、格式与 slug 都没有变化，系统 MUST NOT 递增版本号、MUST NOT 写入新的版本记录、MUST NOT 记录 `chapter.replace` 审计、MUST NOT 触发 `chapter.updated` Webhook；页面 MUST 明确提示「内容没有变化，未生成新版本」。

#### Scenario: 连点两次保存只产生一个版本

- **WHEN** 管理员创建章节（v1）后在编辑页不做任何修改直接保存两次
- **THEN** 版本号始终是 v1
- **AND** 历史版本里只有 v1 一条
- **AND** 两次保存都提示「内容没有变化」

#### Scenario: 真的改了内容才产生新版本

- **WHEN** 管理员修改正文后保存
- **THEN** 版本号变为 v2，历史版本出现 v2
- **AND** 页面提示「已保存为 v2」

#### Scenario: 只改标题也算改动

- **WHEN** 正文不变但标题改了
- **THEN** 生成新版本（标题是内容的一部分）
