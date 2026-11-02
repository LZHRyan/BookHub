# Spec Delta

## ADDED Requirements

### Requirement: Book 更新 MUST 支持设置与清除封面

Book 的更新接口 MUST 接受 `cover_media_id`：传媒体资源 id 设为封面，传 `null` 清除封面。设置时必须复用与网页端相同的校验（本 Book、图片、未删除），失败 MUST 返回可辨识错误且不改动原封面。Book 表示 MUST 暴露 `cover` 字段（含 `id` 与可访问 `url`，无封面为 `null`）。

#### Scenario: 通过 API 设置封面

- **WHEN** 用 `PATCH /api/v1/admin/books/{ref}` 传 `{"cover_media_id": 12}`
- **THEN** 响应中的 `cover` 含该资源 id 与站内地址
- **AND** 只读 API 的 Book 表示同步带上 `cover`

#### Scenario: 清除封面

- **WHEN** 传 `{"cover_media_id": null}`
- **THEN** 响应中的 `cover` 为 `null`
- **AND** 首页与详情页回退到图标

#### Scenario: 非法封面被拒绝

- **WHEN** `cover_media_id` 指向其他 Book 的资源或一个附件
- **THEN** 返回 4xx 且错误信息说明原因
- **AND** 原封面保持不变
