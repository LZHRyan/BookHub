# Tasks

## 1. 数据模型与迁移

- [x] 1.1 `app/models.py` 的 `Book` 增加 `format` 列（`String(16)`，默认 `markdown`，非空），`pytest tests/test_models.py` 覆盖默认值与非法值不落库
- [x] 1.2 新增 Alembic 迁移 `0002_book_format.py`：加列 + 按首章格式回填（无章节回填 `markdown`），验证 `alembic upgrade head` 在空库与已有数据的库上都成功
- [x] 1.3 验证 `alembic downgrade 0001` 可回退且不影响其它表

## 2. 服务层校验

- [x] 2.1 `books.create_book` 增加 `format` 参数并校验取值，非法值抛 `ValidationFailed` 且不写库（单测覆盖）
- [x] 2.2 `books.update_book` 在有未删除章节时拒绝修改格式，空 Book 允许（单测覆盖两种情况）
- [x] 2.3 `chapters.create_chapter` 强制 `fmt = book.format`，传入不同格式时抛 `ValidationFailed` 且不产生章节与版本（单测覆盖）
- [x] 2.4 `chapters.replace_content` 拒绝与 Book 类型不同的格式，且不递增版本号（单测覆盖）

## 3. 管理端与模板

- [x] 3.1 Book 表单新增「文档类型」选择（必填、无空选项、带说明），编辑有章节的 Book 时禁用并给出原因，验证空标题 + 未选类型的错误展示
- [x] 3.2 章节表单把格式选择改成只读展示（显示 Book 类型 + 说明），新建与编辑两条路径都正确
- [x] 3.3 Book 详情与章节表单页显示文档类型徽章，验证 HTML 类型 Book 显示 `HTML`
- [x] 3.4 上传入口按扩展名与 Book 类型比对，不一致时返回 4xx 并在表单上显示明确错误（单测覆盖 md/html 双向拒绝）
- [x] 3.5 对历史混排数据（Book 类型与章节格式不同）在 Book 详情显示黄色警示条，提示管理员统一

## 4. 对外 API 与导出

- [x] 4.1 `/api/v1/books` 与 `/api/v1/books/{ref}` 的 Book 表示增加 `format` 字段（单测断言字段存在且取值合法）
- [x] 4.2 章节表示的 `format` 恒等于 Book 的 `format`（单测覆盖新建的两种 Book）
- [x] 4.3 整本导出在同一 Book 内只产生一种扩展名（单测校验 ZIP 文件名集合）

## 5. 演示数据、脚本与文档

- [x] 5.1 `app/services/demo.py` 拆成「纯 Markdown 书」与「纯 HTML 书」，验证 `SEED_DEMO=true` 启动后两本书各含同格式章节
- [x] 5.2 `scripts/e2e_admin_flow.py` 改为两本书流程（Markdown 全流程 + HTML 章节净化），对运行中实例跑通
- [x] 5.3 更新 `docs/content-model.md`、`docs/authoring.md`、`docs/api.md`，说明 Book 级格式、不可变性、上传约束与 `format` 字段
- [x] 5.4 `openspec validate book-single-format --strict` 通过，`tasks.md` 全部勾选

## Workflow follow-up

- 归档本变更，使 `book-catalog`/`chapter-lifecycle`/`chapter-content`/`content-api` 的主规格合并新增需求。
