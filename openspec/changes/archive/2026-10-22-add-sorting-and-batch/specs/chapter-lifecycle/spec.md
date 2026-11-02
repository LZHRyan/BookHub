# Spec Delta

## ADDED Requirements

### Requirement: 排序 MUST 支持按有序 id 列表整体重排

系统 MUST 提供一次提交完整顺序的重排能力：给定目标父级与有序 id 列表，把该父级的 `sort_order` 重写为 10/20/30…。提交的 id 集合与该父级当前未删除条目不一致时 MUST 拒绝并返回 4xx，且不改动任何顺序。

#### Scenario: 合法提交重写序号

- **WHEN** 管理员提交某分卷内 3 个章节的新顺序
- **THEN** 该分卷内顺序与提交一致，序号为 10/20/30
- **AND** 其它父级的序号不变

#### Scenario: 集合不一致被拒绝

- **WHEN** 提交的 id 列表包含另一个分卷的章节
- **THEN** 返回 4xx 并说明排序列表不一致
- **AND** 顺序保持不变
