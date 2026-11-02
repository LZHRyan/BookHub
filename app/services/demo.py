"""演示数据：仅在 SEED_DEMO=true 时写入，便于本地预览。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import STATUS_PUBLISHED, Book
from app.services.books import create_book
from app.services.chapters import create_chapter
from app.services.sections import create_section

WELCOME_MD = """# 欢迎使用 BookHub

这是研发部技术文档知识库的演示章节。

| 能力 | 说明 |
| --- | --- |
| Book | 顶层单元，一个 Book 对应一套文档 |
| 章 | 目录里的一行，决定顺序与发布状态 |
| 节 | 一份 Markdown 或 HTML 文件 |

- [x] 支持 Markdown 与 HTML
- [ ] 待办：接入图片托管

```bash
curl http://localhost:8000/api/v1/books
```
"""

RELEASE_FLOW_MD = """# 发布流程

1. 在 `main` 上合并变更并通过 CI
2. 打 tag，触发镜像构建
3. 在测试环境 `docker compose up -d --build`
4. 验证 `/healthz` 与冒烟脚本后切生产

> 回滚：回退镜像 tag，数据卷保持不变。
"""

ENV_MD = """# 环境搭建

1. 安装 Python 3.12 与 Node 24
2. `python -m venv .venv` 并激活
3. `pip install -r requirements.txt`

遇到网络问题时先确认内部镜像可用。
"""

HTML_SAMPLE = """<h1>HTML 章节示例</h1>
<p>这份章节以 HTML 原文保存，渲染前会经过白名单净化。</p>
<h2>代码</h2>
<pre><code class="language-sql">select * from books;</code></pre>
<h2>表格</h2>
<table><thead><tr><th>列</th><th>含义</th></tr></thead>
<tbody><tr><td>slug</td><td>稳定 URL 标识</td></tr></tbody></table>
"""


def seed_demo_content(session: Session) -> bool:
    existing = session.execute(select(func.count()).select_from(Book)).scalar_one()
    if existing:
        return False
    handbook = create_book(
        session,
        title="研发手册",
        slug_raw="handbook",
        summary="新人入职、环境搭建与发布流程（Markdown 文档）。",
        icon="📘",
        fmt="markdown",
        visibility="public",
    )
    # 单节章：`/b/handbook/welcome` 直接显示这一节正文
    create_chapter(
        session,
        handbook,
        title="欢迎使用 BookHub",
        slug_raw="welcome",
        status=STATUS_PUBLISHED,
        note="演示数据",
        files=[{"title": "欢迎使用 BookHub", "raw": WELCOME_MD, "format": "markdown"}],
    )
    # 多节章：`/b/handbook/onboarding` 是节索引，`/b/handbook/onboarding/env` 才是正文
    onboarding = create_chapter(
        session,
        handbook,
        title="入职准备",
        slug_raw="onboarding",
        status=STATUS_PUBLISHED,
        note="演示数据",
    )
    create_section(
        session,
        onboarding,
        title="环境搭建",
        raw=ENV_MD,
        slug_raw="env",
        note="演示数据",
    )
    create_section(
        session,
        onboarding,
        title="发布流程",
        raw=RELEASE_FLOW_MD,
        slug_raw="release",
        note="演示数据",
    )
    html_book = create_book(
        session,
        title="HTML 文档示例",
        slug_raw="html-samples",
        summary="整本使用 HTML 编写、白名单净化后展示的示例。",
        icon="🧩",
        fmt="html",
        visibility="public",
    )
    create_chapter(
        session,
        html_book,
        title="HTML 章节示例",
        slug_raw="html-sample",
        status=STATUS_PUBLISHED,
        note="演示数据",
        files=[{"title": "HTML 章节示例", "raw": HTML_SAMPLE, "format": "html"}],
    )
    ops = create_book(
        session,
        title="运维笔记",
        slug_raw="ops-notes",
        summary="内部服务部署与排障记录（示例中设为 unlisted）。",
        icon="🛠",
        fmt="markdown",
        visibility="unlisted",
    )
    create_chapter(
        session,
        ops,
        title="备份与恢复",
        slug_raw="backup-restore",
        status=STATUS_PUBLISHED,
        note="演示数据",
        files=[
            {
                "title": "备份与恢复",
                "raw": "# 备份与恢复\n\n用 `docker/backup.sh` 产出备份。\n",
                "format": "markdown",
            }
        ],
    )
    session.flush()
    return True
