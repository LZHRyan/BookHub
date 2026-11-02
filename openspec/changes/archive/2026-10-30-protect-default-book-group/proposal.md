## Why

「默认分组」是 `books.group_id` 非空契约与「新建 Book 未指定分组」时的兜底，由迁移 `0014_book_groups` 建出来、运行时 `book_groups.ensure_default()` 再补一次。现在的删除规则只看「组里有没有 Book」和「是不是最后一个」，于是：

- 只剩默认分组时，会提示「至少要保留一个分组」，看起来像临时限制，管理员容易误以为把 Book 挪走后就能删；
- 默认分组一旦被删（在已经有别的组时就会被放行），下一个未指定分组的 Book 会触发 `ensure_default()` 重新造一个 `default` 组，分组 id 与排序位置全变；
- 允许改默认分组的 slug 同样致命：`ensure_default()` 按 `slug = default` 查找，改了标识之后它会再造一个同名组，出现两个「默认」语义的组。

## What Changes

- 代码里把默认分组定义为**系统内置对象**：`book_groups.is_default()` 以 `DEFAULT_SLUG = "default"` 为唯一判据（不新增数据库列，跟随系统生命周期）。
- 删除默认分组一律拒绝：服务层抛 `ValidationFailed`，网页端与管理 API 都返回可读错误，不再落到「最后一个组」的分支。
- 默认分组的 `slug` 不可修改（标题、简介、图标仍可改）。
- 网页端分组列表对默认分组显示「系统内置」徽标并隐藏删除按钮；编辑页把访问标识改成只读并说明原因，危险操作区不再给删除入口。
- 管理 API 的分组表示新增 `is_default` 字段，方便调用方自己禁用删除入口。

## Impact

- 受影响规格：`book-groups`（新增「默认分组 MUST 随系统存在且不可删除」，修订删除规则）。
- 代码：`app/services/book_groups.py`、`app/web/admin.py`、`app/api/admin.py`、`app/templates/admin/groups.html`、`app/templates/admin/book_group_form.html`。
- 测试：`tests/test_book_groups.py`（服务层 / 网页端 / 管理 API 三处）。
- 不变：数据库结构、`ensure_default()` 的兜底逻辑、Book 必须选分组的创建契约。
