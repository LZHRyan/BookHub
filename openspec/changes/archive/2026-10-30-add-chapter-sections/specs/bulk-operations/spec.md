## ADDED Requirements

### Requirement: 拖拽排序 MUST 限定在同一 Book 内

管理端的章列表 MUST 支持拖动条目改变章的先后顺序；拖动 MUST NOT 改变条目所属的 Book。节在章编辑器内按自己的顺序维护（上移/下移），其顺序只影响该章。排序结果 MUST 只影响被拖动的那个容器，其它 Book 与其它章的顺序 MUST 保持不变。

#### Scenario: 章列表内拖动

- **WHEN** 管理员把某 Book 章列表里的第 3 行拖到第 1 行
- **THEN** 该 Book 的章顺序随之更新
- **AND** 其它 Book 的章顺序不受影响

#### Scenario: 节顺序只在章内变化

- **WHEN** 管理员在章编辑器里把第 2 节上移到第 1 位
- **THEN** 该章的节顺序更新
- **AND** 章在 Book 中的位置与其它章的内容不受影响

## MODIFIED Requirements

### Requirement: 排序提交 MUST 原子且校验完整

一次排序提交 MUST 携带目标容器（整本 Book 的章列表，或某章的节列表）与完整的有序 id 列表。若提交的 id 集合与该容器当前未删除条目不一致，系统 MUST 拒绝并返回 4xx，MUST NOT 改动任何条目的顺序。

#### Scenario: 缺项或多项被拒绝

- **WHEN** 提交的 id 列表比该容器实际条目少一个（或包含别的 Book 的章）
- **THEN** 系统返回 4xx 并说明排序列表不一致
- **AND** 目录顺序保持提交前的状态

#### Scenario: 提交成功后顺序持久

- **WHEN** 一次合法提交完成
- **THEN** 刷新页面后顺序与提交的一致
- **AND** 该容器的序号被重写为 10/20/30…

## REMOVED Requirements

### Requirement: 拖拽排序 MUST 限定在同一父级内

**Reason**: 「父级」概念随分卷删除而消失：章直接挂在 Book 下，只有一个拖拽容器；节顺序在章编辑器内维护。

**Migration**: 拖拽与提交规则见本能力新增的「拖拽排序 MUST 限定在同一 Book 内」与「排序提交 MUST 原子且校验完整」。
