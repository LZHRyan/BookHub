## Why

巡检最后一批是"不好用/不一致"的问题，和权限、数据安全无关，但每天都会碰到：

- 网页端删除失败（例如内置指南不可删）直接甩一张 400 错误页，而分组删除走的是回列表页带提示——同一个后台两套失败体验；
- `PATCH /books/{ref}` 传空 `slug` 返回 200 却没改任何东西，用户以为改成功了；
- `POST /chapters` 的 JSON 请求允许空 `title`，会悄悄回落成「正文」并生成 `chapter-702239` 这种随机 slug（我巡检时就误建了一个），而规格写的是"章标题必填"；
- 文档里"首页说明原样输出 HTML、可注入脚本"的说法已过时（实际保存时 `sanitize_html`）；`search.html` 的 `snippet | safe` 缺一行约束注释；
- 三个部署脚本缺 `set -o pipefail`；`docs/api.md` 还留着 `uvicorn app.main:app`（与 README/部署文档推荐的 `--factory` 写法不一致）。

## What Changes

- **删除失败给提示**：网页端删除 Book 被拒绝时回列表页并显示提示条（`/admin?error=...`），不再渲染 400 错误页；列表页新增提示条区块。
- **空 slug 明确 400**：`update_book` 收到"显式但为空"的 slug 时返回 400「访问标识不能为空；不改请省略该字段」，不再静默忽略；省略字段的行为不变。
- **空章标题明确 400**：`POST /chapters` 的 JSON 请求要求非空 `title`；`multipart` 上传仍允许省略标题并回落为文件名（既有契约不变）。
- **文档与注释对齐现状**：`admin.md` 的首页说明风险描述改为"已净化，但仍可放外链/图片"；`search.html` 加"只放 make_snippet 产物"的注释；`api.md` 的两处启动命令改成 `create_app --factory`。
- **脚本健壮性**：`docker/backup.sh`、`docker/restore.sh`、`scripts/upgrade.sh` 改为 `set -euo pipefail`。

## Impact

- 代码：`app/services/books.py`、`app/api/admin.py`、`app/web/admin.py`、`app/templates/admin/dashboard.html`、`app/templates/search.html`。
- 行为变化（有意的收紧）：显式传空 slug → 400；JSON 建章缺标题 → 400。省略字段、multipart 上传不受影响。
- 规格：`book-catalog`（空 slug 拒绝 + 删除拒绝的提示方式）、`chapter-lifecycle`（JSON 建章标题必填、multipart 仍可回落）。
- 测试：新增 `tests/test_admin_validation.py`（7 条）；`tests/test_guide.py` 的网页删除用例改为断言 303 + 提示条。全量 454 passed。
