# Tasks

## 1. 服务层

- [x] 1.1 `book_groups.is_default()`：以 `DEFAULT_SLUG` 为唯一判据，不新增列
- [x] 1.2 `delete()` 先判默认分组并抛 `ValidationFailed`，再走非空组 / 最后一个组
- [x] 1.3 `update()` 拒绝修改默认分组的 slug（标题/简介/图标仍可改）

## 2. 网页端

- [x] 2.1 分组列表：默认分组显示「系统内置」徽标、隐藏删除按钮、页脚说明规则
- [x] 2.2 分组编辑页：访问标识只读 + 说明；危险操作区不再给删除入口
- [x] 2.3 直接 POST 删除默认分组 → 303 回列表并带 `?error=`

## 3. 管理 API

- [x] 3.1 分组表示新增 `is_default`
- [x] 3.2 `DELETE /groups/{ref}` 对默认分组返回 400（message 指向默认分组）
- [x] 3.3 `PATCH /groups/{ref}` 改默认分组 slug 返回 400

## 4. 验证

- [x] 4.1 测试：服务层（删不掉 / 改标识被拒 / 可改名）、网页端（无删除入口 + 兜底拒绝）、API（`is_default` + DELETE/PATCH 拒绝）
- [x] 4.2 全量 `pytest` + `ruff` 通过
- [x] 4.3 文档：`docs/authoring.md` 6.3/6.4、`docs/ai.md`、`README.md`
