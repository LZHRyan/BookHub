# Spec Delta

## Purpose

把「章」定义为目录里的一个容器，把「节」定义为一份文件（以及它的正文与版本）。读者看到的是 章 → 节 两级结构，编辑看到的是「一章多文件」。分卷这一层随之消失。

## ADDED Requirements

### Requirement: 一章 MUST 可以包含多个节

每章 MUST 能容纳 0..N 个节；每个节 MUST 有自己的标题、slug、格式（`markdown` / `html`）、正文与序号。章 MUST 只保存目录级信息（标题、slug、序号、发布状态），MUST NOT 再保存正文与版本号。空章 MUST 允许存在（新建章后再加节）。

#### Scenario: 一章三节

- **WHEN** 管理员在「第 1 章」下依次添加三个文件
- **THEN** 该章下出现三节，序号为 1.1、1.2、1.3
- **AND** 三节各自有独立的标题与版本号

#### Scenario: 空章

- **WHEN** 新建章节但不添加任何节
- **THEN** 章仍然存在，管理端显示「还没有节」
- **AND** 读者端该章不出现在目录里（没有可见内容）

### Requirement: 节 MUST 有独立页面与稳定地址

节页 MUST 是 `/b/<book>/<chapter>/<section>`，其中 chapter / section 都是各自的 slug。章页 MUST 是 `/b/<book>/<chapter>`：该章**只有一节**时 MUST 直接渲染这一节的正文（兼容存量链接）；**多节**时 MUST 渲染该章的节索引（标题 + 序号 + 字数），MUST NOT 把多节正文拼在一页。

#### Scenario: 单节章兼容旧链接

- **WHEN** 迁移后打开一个原本就有的章节地址 `/b/ops/deploy`
- **THEN** 页面直接显示该章唯一一节的正文
- **AND** 侧栏高亮该节

#### Scenario: 多节章是索引页

- **WHEN** 打开一个有三节的章地址
- **THEN** 页面列出三节的标题与序号，点击进入各自的节页
- **AND** 不直接渲染正文

### Requirement: 节级序号 MUST 为「章号.节号」

目录与页面上的序号 MUST 是 `1`、`1.1`、`1.2`、`2`、`2.1` 这样的两级编号；节序号 MUST 只在其所属章内递增，MUST NOT 因为章的调整而重排跨章顺序。

#### Scenario: 章内节号独立

- **WHEN** 第 2 章有 3 节、第 3 章有 2 节
- **THEN** 第 3 章的节编号为 3.1、3.2
- **AND** 章的顺序变化不影响各章节的序号

### Requirement: 节 MUST 先于章校验 slug 唯一性

节 slug MUST 在同一章内唯一；章 slug MUST 在同一 Book 内唯一。两者冲突时 MUST 自动追加 `-2`、`-3`。节页地址中的章节段 MUST 与章的当前 slug 一致，章改 slug 后节页地址随之改变，旧地址 MUST 返回 404 而不是错误内容。

#### Scenario: 章内 slug 冲突自动去重

- **WHEN** 同一章内已有节 `overview`，再添加一个 slug 也为 `overview` 的节
- **THEN** 新节 slug 变成 `overview-2`
- **AND** 两节都能正常访问

### Requirement: 多文件上传 MUST 一次生成多节

编辑章节时 MUST 支持一次选择/拖入多个文件（`.md`/`.markdown`/`.txt`/`.html`/`.htm`），每个文件 MUST 生成一节，标题默认取文件名（去扩展名），格式按扩展名判定。单文件上传 MUST 仍然可用，且顺序按文件选择顺序。

#### Scenario: 拖入三个文件生成三节

- **WHEN** 管理员在一章里一次上传 `01-概述.md`、`02-架构.md`、`03-示例.html`
- **THEN** 生成三节，标题分别为「01-概述」「02-架构」「03-示例」
- **AND** 第三节格式为 HTML，前两节为 Markdown
