# Tasks

## 1. 表单

- [x] 1.1 `book_form.html`：slug 字段只在 `mode == 'edit'` 时渲染；新建页副标题与提示中去掉 slug 相关文案
- [x] 1.2 编辑页 slug 说明补充"修改后旧链接失效"，验证两个模式分别渲染正确

## 2. 兼容与测试

- [x] 2.1 确认 `POST /admin/books/new` 不带 `slug` 时仍能创建（处理器 `Form(default="")` + 服务层自动生成），并保留显式传入 `slug` 的兼容路径
- [x] 2.2 新增用例：新建页不含 `name="slug"`；中文标题创建后 slug 以 `book-` 开头且可访问；编辑页仍含 slug 输入且改名后新链接可用
- [x] 2.3 全量 `pytest` 与 `ruff` 通过

## 3. 验证与文档

- [x] 3.1 重建镜像，用内置浏览器实测新建页无 slug、编辑页有 slug
- [x] 3.2 `docs/authoring.md` 更新：新建时不显示 slug、自动生成规则、编辑时可改
- [x] 3.3 `openspec validate auto-book-slug --strict` 通过，`tasks.md` 全部勾选

## Workflow follow-up

- 归档本变更，使 `book-catalog` 主规格包含"新建不展示 slug"这条需求。
