# Tasks

## 1. 内置清单

- [x] 1.1 新增 `app/services/emoji.py`：8 个分组的 `EMOJI_GROUPS`，总数 ≥100 且无重复，提供 `total_emojis()` 与 `is_known_emoji()`
- [x] 1.2 单测断言分组数量、总数 ≥100、组内去重、全量去重（`tests/test_content.py` 或新文件）

## 2. 表单与交互

- [x] 2.1 `admin.py` 的新建/编辑 Book 表单处理器传入 `emoji_groups`，验证两个页面都能渲染出面板
- [x] 2.2 `book_form.html` 增加 `<details class="emoji-picker">` 面板（分组 + 按钮 + `title` 提示）、预览块与「清空」按钮，`maxlength` 提到 16
- [x] 2.3 `app.js` 用事件委托处理 `[data-emoji]` 与 `[data-emoji-clear]`，同步更新预览；`input` 事件也要更新预览
- [x] 2.4 `style.css` 增加 `.emoji-picker` / `.emoji-grid` / `.emoji-option` / `.emoji-preview` 样式，验证亮暗两套主题下可见

## 3. 验证与文档

- [x] 3.1 新增用例：表单含 ≥100 个 `data-emoji`、无内联脚本；提交 emoji 后首页与 API 都能读到该图标；提交空值前台回退矢量图标
- [x] 3.2 全量 `pytest` 与 `ruff` 通过
- [x] 3.3 重建镜像后用内置浏览器实测：展开面板、点选一个图标、保存、首页看到图标
- [x] 3.4 `docs/authoring.md` 补充"图标可从面板点选，也可手工输入/清空"
- [x] 3.5 `openspec validate book-emoji-picker --strict` 通过，`tasks.md` 全部勾选

## Workflow follow-up

- 归档本变更，使 `book-catalog` 主规格包含"图标可点选"这条需求。
