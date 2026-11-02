# book-cover Specification

## Purpose
定义 Book 封面的引用关系与表现：封面只能来自该 Book 自己的图片资源，可设置、可取消、资源删除时自动解绑，并在首页与详情页给出有封面 / 无封面两种稳定布局。

## Requirements

### Requirement: 封面 MUST 只引用本 Book 的图片资源

`cover_media_id` MUST 指向本 Book 名下、`kind = image`、未软删除的媒体资源。指向其他 Book 的资源、附件类型、已删除资源或不存在 id 时 MUST 拒绝并返回可辨识错误，且 MUST NOT 改动原封面。

#### Scenario: 设置为本 Book 的图片成功

- **WHEN** 管理员在媒体库里把一张本 Book 的图片设为封面
- **THEN** Book 详情与列表页都显示该图片
- **AND** 审计里出现一条封面变更记录

#### Scenario: 跨 Book 引用被拒绝

- **WHEN** 请求把另一 Book 的图片设为该 Book 的封面
- **THEN** 返回 4xx 并说明资源不属于该 Book
- **AND** 原封面保持不变

#### Scenario: 附件不能当封面

- **WHEN** 把一个 `attachment` 类资源设为封面
- **THEN** 返回 4xx 并说明封面必须是图片

### Requirement: 封面 MUST 可取消并回退到图标

封面 MUST 可以被清除（`cover_media_id = null`），清除后首页卡片与详情页 MUST 回退到 emoji 图标块，且 MUST NOT 留下破图或空白占位。

#### Scenario: 取消封面回到图标

- **WHEN** 管理员清除某本书的封面
- **THEN** 首页卡片显示该 Book 的 emoji 图标
- **AND** 详情页 hero 区不再出现封面图

### Requirement: 封面资源删除后 MUST 自动解绑

当被用作封面的资源被删除（软删除）时，系统 MUST 立即把该 Book 的 `cover_media_id` 置空，使页面回到图标回退，MUST NOT 让页面引用一个已失效的地址。

#### Scenario: 删除封面图片

- **WHEN** 管理员在媒体库删除当前被用作封面的图片
- **THEN** 该 Book 的封面被自动清除
- **AND** 首页卡片与详情页显示图标回退，而不是破图

### Requirement: 首页与详情页 MUST 在有封面时优先展示封面

首页卡片 MUST 在有封面时展示封面图（等比例裁切、固定高度），无封面时展示图标块；Book 详情 MUST 在 hero 区展示封面缩略图。两种状态在小屏下 MUST 保持文字可读、MUST NOT 出现横向滚动。

#### Scenario: 首页有封面与无封面共存

- **WHEN** 首页同时有一本有封面和一本无封面的 Book
- **THEN** 两张卡片高度与文字基线一致
- **AND** 有封面的显示图片，无封面的显示图标

#### Scenario: 小屏下不溢出

- **WHEN** 视口宽度为 375px 时浏览首页
- **THEN** 卡片单列显示，封面不撑破容器
- **AND** 标题与摘要正常换行或截断
