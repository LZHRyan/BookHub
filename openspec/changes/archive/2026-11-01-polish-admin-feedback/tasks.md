# Tasks

- [x] 1.1 网页删除失败：`book_delete` 捕获 `AppError` → 回 `/admin?error=...`；列表页渲染提示条
- [x] 1.2 空 slug：`update_book` 显式空值 → 400（省略字段不变）
- [x] 1.3 空章标题：`POST /chapters` JSON 分支要求非空 title；multipart 保留文件名回落
- [x] 1.4 `docs/admin.md` 首页说明风险描述对齐（已净化）
- [x] 1.5 `search.html` 加 `snippet | safe` 约束注释
- [x] 1.6 `docs/api.md` 启动命令改 `create_app --factory`
- [x] 1.7 三个脚本改 `set -euo pipefail`
- [x] 1.8 测试：空 slug / 空标题 / multipart 回落 / 删除提示条 / 列表页提示条 / 编辑表单 400
- [x] 1.9 全量 `pytest`（454 passed）+ `ruff` 通过
