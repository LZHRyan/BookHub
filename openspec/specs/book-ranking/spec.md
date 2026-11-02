# book-ranking Specification

## Purpose
定义 Book 在访客端的展示顺序：权重由访问热度与创建时间自动计算、不可人工设置，并提供权重的可观测性，使排序结果可解释。

## Requirements

### Requirement: 访问热度采集

系统 SHALL 在访客打开 Book 详情页或该 Book 下任意已发布章节页时，为该 Book 记一次访问。计数 MUST 满足以下口径：同一访客（按客户端 IP 识别）对同一 Book 在 30 分钟窗口内只计一次；登录用户（`admin` / `editor`）的访问 MUST NOT 计入；只统计 `GET` 请求。计数 MUST 按 UTC 日期分桶存储，以便按时间窗口聚合。计数失败 MUST NOT 影响页面返回：写入异常被记录到日志后，阅读页仍正常渲染。

#### Scenario: 打开 Book 页计入一次

- **WHEN** 匿名访客打开某 Book 详情页
- **THEN** 该 Book 当天的访问计数 +1
- **AND** 管理端看到的累计与近 7 天访问数随之增加

#### Scenario: 刷新不刷热度

- **WHEN** 同一访客在 30 分钟内多次打开同一 Book 的页面或章节页
- **THEN** 该 Book 只被计一次

#### Scenario: 章节阅读计入所属 Book

- **WHEN** 匿名访客阅读某 Book 下的章节
- **THEN** 计入的是该章节所属的 Book，而不是章节自身

#### Scenario: 登录用户访问不计入

- **WHEN** 已登录的编辑或管理员打开 Book 页
- **THEN** 该 Book 的访问计数不变

#### Scenario: 统计失败不影响阅读

- **WHEN** 访问计数写入数据库时发生错误
- **THEN** 页面仍返回 200 并正常展示内容
- **AND** 错误被记录到日志，不向访客暴露

### Requirement: 自动权重计算

系统 SHALL 在每次列表请求时根据访问热度与创建时间计算每个 Book 的权重，权重越高排序越靠前。权重 MUST 同时满足：近 7 天访问次数增加时权重单调不减；累计访问次数增加时权重单调不减；在访问数据相同的前提下，创建时间越晚权重越大。权重 MUST NOT 存储在 Book 记录上，也 MUST NOT 由任何用户输入直接决定。

#### Scenario: 热度提升权重

- **WHEN** 两个 Book 的创建时间相同，其中一个近期访问次数更多
- **THEN** 访问更多的 Book 权重更大、排序更靠前

#### Scenario: 新建提升权重

- **WHEN** 两个 Book 的访问数据相同，其中一个创建时间更晚
- **THEN** 创建更晚的 Book 权重更大

#### Scenario: 长期冷却

- **WHEN** 一个 Book 长时间没有新访问
- **THEN** 它的权重只保留累计访问带来的部分，新鲜度加成随时间衰减且不会变成负值

#### Scenario: 权重不可人工设置

- **WHEN** 管理员尝试通过表单、接口参数或数据库以外的任何入口指定 Book 顺序
- **THEN** 系统没有这样的入口，顺序始终由自动权重决定

### Requirement: 权重可观测

系统 SHALL 让管理员与 API 调用方能看到权重及其输入，以便解释排序结果。管理端的 Book 详情 MUST 展示当前权重、近 7 天访问与累计访问；管理端 Book 列表 MUST 展示近期访问数；`/api/v1` 的 Book 表示 MUST 包含 `weight`、`view_count`、`recent_view_count` 且 MUST NOT 包含人工排序字段。

#### Scenario: 管理端能看到权重来源

- **WHEN** 管理员打开某 Book 的详情页
- **THEN** 页面显示该 Book 的权重、近 7 天访问数与累计访问数

#### Scenario: API 暴露权重

- **WHEN** 调用方请求 `/api/v1/books`
- **THEN** 每个元素包含 `weight`、`view_count`、`recent_view_count`
- **AND** 不包含 `sort_order` 之类的人工排序字段
