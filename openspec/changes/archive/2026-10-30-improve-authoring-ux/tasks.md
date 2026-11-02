# Tasks

## 1. 幂等保存

- [x] 1.1 `chapters.replace_content()`：计算标题/正文/格式/slug 是否都未变，未变直接返回（不递增版本、不写版本记录、不写审计、不推 Webhook）
- [x] 1.2 单测：连存两次只产生一个版本；只改标题/只改正文/只改 slug 各自生成新版本；API 保存同样幂等

## 2. 保存反馈

- [x] 2.1 新增 `app/templates/admin/_notice.html`：把 `?notice=` code 映射成文案（含版本号、无改动用警告色）
- [x] 2.2 `chapter_new_submit` → `?notice=chapter-created`；`chapter_replace_submit` → `chapter-saved` / `chapter-unchanged`（按版本号有没有变判断）
- [x] 2.3 `book_new_submit` → `?notice=book-created`；`book_edit_submit` → `?notice=book-saved`
- [x] 2.4 `chapter_form.html`、`book_form.html`、`book_detail.html` 顶部渲染提示；编辑页保存按钮改为「保存为 v{{ chapter.current_version_no + 1 }}」
- [x] 2.5 页面测试：新建/保存后提示出现；无改动提示含「未生成新版本」；按钮含目标版本号

## 3. 防重复提交

- [x] 3.1 `app/static/app.js`：`submit` 后禁用 submitter 并改文案「处理中…」，取消确认时（`defaultPrevented`）不锁
- [x] 3.2 复制处理器补剪贴板不可用的 `prompt` 回退

## 4. 分享地址与 OG

- [x] 4.1 `public.py` 提供 `share_url(request, path)`；`book_detail` / `chapter_detail` 传入 `share_url`（章节页另传 `share_url` 给 OG）
- [x] 4.2 `book.html` / `chapter.html`：标题旁「复制链接」按钮（`data-copy`）、`{% block meta %}` 输出 `og:*`（有封面时带 `og:image`）
- [x] 4.3 `admin/book_detail.html` 加「复制分享链接」，与管理端现有按钮风格一致
- [x] 4.4 测试：`share_url` 绝对且含 `ROOT_PATH`；两页 HTML 含 `og:title` / `og:url` / 复制按钮；有封面时含 `og:image`
- [x] 4.5 修正 `absolute_url`：反代剥离前缀的部署下 `request.base_url` 不含 ROOT_PATH，需显式补；`sitemap` 复用同一助手

## 5. 文档

- [x] 5.1 `docs/authoring.md`：新增「保存与版本」小节（无改动不生成版本、按钮预告版本号、提示含义、如何真正打新版本）
- [x] 5.2 `docs/reading.md`：补「分享链接」与 OG 预览说明
- [x] 5.3 `README.md`：功能清单补一行

## Workflow follow-up

- `openspec validate improve-authoring-ux --strict` 通过后归档该变更，并把归档目录提交入库。
