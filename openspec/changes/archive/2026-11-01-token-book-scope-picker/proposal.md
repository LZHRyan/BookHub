## Why

`POST /admin/tokens` 的「可操作的 Book」原来把全部 Book 平铺成一列复选框。Book 一多（几十上百本）这一屏就没法用：找不到目标、看不出所属分组、页面被拉得很长，而且勾选状态没有跨页概念——因为根本没有分页。

## What Changes

- 选择器改成一块独立面板：**分组下拉 + 标题/访问标识搜索 + 分页**（每页 8 本，上一页/下一页），列表行显示 `图标 + 标题` 与右侧 `访问标识 · 分组`。
- 勾选状态由前端维护并跨页、跨筛选保留；当前页的复选框随表单提交，其它页的已选项用隐藏字段补齐。
- 服务端新增只读数据源 `GET /admin/tokens/books.json?group=&q=&page=`（管理员鉴权），页面首屏仍由服务端直出第一页，JS 只负责后续筛选/翻页。
- 作用域的三个复选框改成与站点其它表单一致的单选卡片样式（`fieldset` 默认边框重置），不再用裸 checkbox + 灰字。
- Token 列表的「范围」列最多显示 3 个 Book，其余折叠成「等 N 本」（悬停看全量）。

## Impact

- 受影响规格：`token-scoping`（「Token MUST 可限定到指定 Book」补充管理端选择器的可用性约束）。
- 代码：`app/web/tokens.py`、`app/templates/admin/tokens.html`、`app/static/app.js`、`app/static/style.css`。
- 测试：`tests/test_governance.py`（选择器控件存在、`books.json` 的分页/分组/搜索、首屏按 `bgroup` 过滤）。
- 接口契约不变：签发仍是 `book_ids` 多值表单字段，未选择仍表示全部 Book。
