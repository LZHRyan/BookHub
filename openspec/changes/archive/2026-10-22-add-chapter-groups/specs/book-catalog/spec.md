# Spec Delta

## MODIFIED Requirements

### Requirement: Book 详情返回有序章节目录

Book 详情 SHALL 返回该 Book 的章节目录而不含章节正文，目录项 MUST 至少包含章节标题、slug、排序信息，以及归属信息（所属分卷的 slug/title，根层为 `null`）与条目类型（`doc` / `group`）。目录 MUST 先按根层顺序、再按分卷内顺序返回，使调用方能直接重建分组结构。访客视角的目录 MUST 只包含已发布且未删除的章节，分卷 MUST 一并返回；管理员视角的目录 MAY 包含草稿并须标明其状态。

#### Scenario: 访客目录只含已发布章节

- **WHEN** 访客请求某 Book 的详情
- **THEN** 返回的目录只包含已发布且未删除的章节与分卷
- **AND** 草稿章节与已删除章节都不出现在目录中

#### Scenario: 目录顺序与排序一致

- **WHEN** 某 Book 根层依次为分卷（其下两章）与一个独立章节
- **THEN** 详情返回的目录顺序为：分卷、该分卷下两章、独立章节
- **AND** 每一项都带 `kind` 与 `parent` 字段

#### Scenario: 目录不携带正文

- **WHEN** 程序调用方请求 Book 详情
- **THEN** 目录项中不包含章节正文
- **AND** 响应体大小与章节正文长度无关

#### Scenario: 管理员目录标注草稿

- **WHEN** 管理员查看含一个草稿章节的 Book 详情
- **THEN** 目录中包含该草稿章节
