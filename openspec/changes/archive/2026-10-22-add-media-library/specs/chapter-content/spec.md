# Spec Delta

## ADDED Requirements

### Requirement: 正文中的站内媒体引用 MUST 按部署前缀解析

正文里的站内媒体地址 MUST 以 `/media/` 开头的根相对路径表达，渲染输出时 MUST 按部署前缀（`ROOT_PATH`）补全为可访问地址；未配置前缀时 MUST 原样保留。净化流程 MUST 保留站内媒体引用，MUST NOT 因为 `src` 指向自身而丢弃标签。

#### Scenario: 根路径部署原样保留

- **WHEN** 未配置部署前缀，正文含 `![图](/media/demo/ab12-arch.png)`
- **THEN** 渲染结果中该图片的 `src` 仍为 `/media/demo/ab12-arch.png`

#### Scenario: 子路径部署自动补前缀

- **WHEN** 部署前缀为 `/kb`，同一正文被渲染
- **THEN** 渲染结果中该图片的 `src` 为 `/kb/media/demo/ab12-arch.png`

#### Scenario: 净化不丢弃站内图片

- **WHEN** 一份含站内媒体引用的 Markdown 正文经过白名单净化
- **THEN** `<img>` 标签与 `src`、`alt` 属性均被保留
- **AND** 渲染后的页面请求该地址返回 200
