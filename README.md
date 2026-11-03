# BookHub

技术文档知识库：把散落的 Markdown / HTML 文档按 **Book → 章 → 节** 组织起来，网页上只读浏览，同时对外提供一套稳定的只读 JSON / 原文 / 导出 API，方便脚本、CI 和其他系统消费。

一句话定位：**一个容器、一个数据库文件、零前端构建** 的自建知识库，主打「上传即用」和「对外可编程」。

---

## 1. 功能清单

| 能力 | 说明 |
| --- | --- |
| Book 管理 | 顶层单元，一套文档一个 Book；有标题、slug、摘要、图标、可见性，首页顺序由访问热度与创建时间自动计算 |
| 分组（Book 归组） | Book 的上一层分类，每本 Book 必属于且只属于一个分组；首页按分组分区渲染，组内沿用「置顶 + 访问热度」排序，组间用上移 / 下移调整；默认分组由系统创建、不可删除且标识固定，其余非空分组（**含回收站里的 Book**）与最后一个分组不可删 |
| 章节管理 | **章 = 容器，节 = 一份文件**：一章可包含多个 Markdown / HTML 节，新建/加节时可以**一次选多个文件**（一个文件生成一节），也可以直接粘贴正文 |
| 节级内容 | 一章可包含多个节，每个节一份文件、各自版本；**整本统一格式**由 Book 的文档类型决定，上传只接受对应扩展名 |
| 节页 URL | 目录两级：`/b/<book>` → `/b/<book>/<chapter>`（单节章直出正文、多节章是节索引）→ `/b/<book>/<chapter>/<section>`（唯一正文出口） |
| 拖拽与批量 | 章可拖拽排序；勾选多行可批量发布 / 撤回 / 删除，结果逐条回显；节在章内用上移/下移 |
| Book 置顶 | 「置顶到首页」把重点文档钉在最前，置顶内部仍按访问热度排序 |
| Book 封面 | 从媒体库选一张图设为封面，首页卡片与 Book 页优先显示；删除该图自动解绑回退图标 |
| 图片与附件 | 编辑器内**粘贴截图 / 拖拽 / 点选**上传，自动插入引用；按 Book 隔离、内容寻址去重、配额与未引用清理、软删除可恢复 |
| HTML 原始排版 | HTML 节按原始文档提供：在新标签页原样运行上传文档的 CSS / JS / base64 图片与自带导航，隔离靠 CSP `sandbox`（`/sections/<section>/raw` 下沉到节） |
| 版本与回滚 | **节级版本**：每节各自 v1/v2，可查看历史、做行级 diff、一键回滚（回滚也生成新版本） |
| 草稿 / 发布 | 发布状态在**章级**：新建默认草稿，其下所有节访客一律 404；发布后整章的节一起可见 |
| 软删除 / 回收站 | Book、章、节都是软删除，删除后 slug 可被新文档复用，回收站里可恢复 |
| 全文检索 | SQLite FTS5 + 中文二元组切分，索引与结果都到**节**；两字词（如「部署」）能命中，单字查询退化为模糊匹配 |
| 只读 API | `/api/v1` 下提供 Book 列表、章（带 `sections[]`）/ 节 JSON、原文、渲染 HTML、整本导出（JSON / ZIP）、增量同步 |
| Webhook | `chapter.*` 只在这些字段变化时发；新增 `section.published` / `section.updated` 到节粒度 |
| 发现与监控 | `/sitemap.xml` 列出全部公开内容（章页 + 多节章的节页；单节章只收章地址）；`/metrics` 暴露 Prometheus 指标（含节数） |
| CI | GitHub Actions：ruff + pytest + 镜像构建，推送即校验 |
| 条件请求 | 节与 Book 详情带 `ETag` / `Last-Modified`，支持 `If-None-Match` 拿 304 |
| 一键分享 | Book 页与节页「复制链接」给绝对地址，附 Open Graph 元数据（IM 里有标题/摘要/封面预览） |
| 幂等保存 | 节内容没改动时保存不产生新版本，并在页面上明确提示「已保存为 vN / 未生成新版本」 |
| 权限 | `admin`（含账号、站点设置、审计）与 `editor`（只维护内容）两级角色 |
| 审计日志 | 谁、什么时候、把哪个对象从第几版改到第几版、来源 IP，只追加不可改；支持按条件导出 CSV 与按保留期自动清理 |
| Token 范围 | 签发时可按 Book 限定 Token 的可操作范围，越界请求返回 403；过期与长期未用会在列表里提示 |
| HTML 安全 | 管理员上传的 HTML 按白名单净化（去 `script` / `on*` / `javascript:` / `iframe` / `form`），页面另加 CSP |
| 编码识别 | 上传文件按 UTF-8 BOM → UTF-8 → GB18030 顺序自动识别，可手动指定编码 |
| 站点设置 | 站点名、页脚、首页说明可在后台改，无需重启 |

---

## 2. 五分钟启动（Docker，推荐）

前置：Docker Engine/Desktop + docker compose v2。

```bash
cp .env.example .env
```

编辑 `.env`，至少改这三项（其余保持默认即可）：

```dotenv
SECRET_KEY=<用下面的命令生成>
BOOKHUB_INITIAL_ADMIN_USER=admin
BOOKHUB_INITIAL_ADMIN_PASSWORD=<一个符合策略的密码，≥10 位且含两类字符>
```

生成 `SECRET_KEY`：

```bash
python -c "import secrets;print(secrets.token_urlsafe(48))"
```

```powershell
python -c "import secrets;print(secrets.token_urlsafe(48))"
```

> `.env.example` 里的 `SECRET_KEY=please-change-me-...` 是占位值，**留着不改容器会直接退出**（entrypoint 会识别占位前缀并报错），这是有意的防呆。

启动：

```bash
docker compose up -d --build
docker compose ps                     # 等 STATUS 变成 healthy
curl -fsS http://127.0.0.1:8000/healthz
```

```powershell
docker compose up -d --build
docker compose ps
curl.exe -fsS http://127.0.0.1:8000/healthz
```

访问：

| 入口 | 地址 | 说明 |
| --- | --- | --- |
| 访客门户 | <http://localhost:8000> | 首页 → Book 目录（章 → 节）→ 节阅读 |
| 管理后台 | <http://localhost:8000/admin> | 用 `.env` 里的初始管理员登录 |
| API 文档 | <http://localhost:8000/docs> | OpenAPI（`API_DOCS_ENABLED=false` 可关闭） |
| 能力发现 | <http://localhost:8000/api/v1/site> | 免鉴权的站点元信息 |
| 健康探针 | <http://localhost:8000/healthz> · <http://localhost:8000/readyz> | 见 [docs/deploy.md](docs/deploy.md) |

改宿主机端口：**不要改 `.env` 的 `PORT`**——`env_file` 会把它注入容器，entrypoint 又用它作为 uvicorn 监听端口，而 `ports` 右侧写死 8000，改了会变成"宿主 8123 → 容器 8000，但服务在 8123 上听"的错位。正确做法是保持 `PORT=8000`，改 `docker-compose.yml` 的映射左侧：

```yaml
ports:
  - "8123:8000"
```

首次启动容器内按顺序执行：**环境自检 → 目录准备 → 数据库迁移（`alembic upgrade head`）→ 初始管理员（`python -m app.bootstrap`）→ 启动 uvicorn**。初始管理员只在账号不存在时创建，改了环境变量重启**不会**覆盖已有密码（原因见第 7 节）。

常用运维命令：

```bash
docker compose logs -f bookhub        # 服务名是 bookhub
docker compose exec bookhub python -m app.bootstrap   # 手动补建初始管理员（幂等）
./docker/backup.sh                    # 在线备份到 ./backups/<时间戳>/
docker compose down                   # 停服（加 -v 会连数据卷一起删，慎用）
```

```powershell
docker compose logs -f bookhub
docker compose exec bookhub python -m app.bootstrap
bash ./docker/backup.sh
docker compose down
```

---

## 3. 本地启动（不用 Docker）

前置：Python 3.12。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

应用**只从环境变量读配置**（没有 `.env` 解析器），本地开发请先在当前 shell 里导出：

```bash
export SECRET_KEY="local-dev-secret-key-please-change"
export DATABASE_URL="sqlite:///./data/bookhub.db"
export BOOKHUB_INITIAL_ADMIN_USER="admin"
export BOOKHUB_INITIAL_ADMIN_PASSWORD="AdminPass123"
export SEED_DEMO="true"          # 可选：写入两本演示 Book，方便看效果
```

```powershell
$env:SECRET_KEY = "local-dev-secret-key-please-change"
$env:DATABASE_URL = "sqlite:///./data/bookhub.db"
$env:BOOKHUB_INITIAL_ADMIN_USER = "admin"
$env:BOOKHUB_INITIAL_ADMIN_PASSWORD = "AdminPass123"
$env:SEED_DEMO = "true"          # 可选：写入两本演示 Book，方便看效果
```

然后三步（顺序不能换，`bootstrap` 依赖已经建好的表）：

```bash
python -m alembic upgrade head
python -m app.bootstrap
uvicorn app.main:create_app --factory --reload --port 8000
```

```powershell
python -m alembic upgrade head
python -m app.bootstrap
uvicorn app.main:create_app --factory --reload --port 8000
```

注意 `--factory`：应用的入口是**工厂函数** `app.main:create_app`，不是模块级 `app` 对象（`app.main` 里的 `app` 只在环境里已经有 `SECRET_KEY` 时才非空）。

访问 <http://localhost:8000>，用上面设置的账号进 `/admin`。

`DATA_DIR` 只用于日志展示，**实际数据位置由 `DATABASE_URL` 决定**；SQLite 相对路径相对于启动时的工作目录。

---

## 4. API 快速上手

三个最常用的调用（`curl` 在 Windows PowerShell 里是 `Invoke-WebRequest` 的别名且会按 ISO-8859-1 解码，中文会乱码，**请用 `curl.exe`**）：

```bash
# 1) 列出公开 Book
curl "http://localhost:8000/api/v1/books"

# 2) 取某节原文（Markdown 节返回 text/markdown，HTML 节返回 text/html；
#    单节章可以省略 ?section=）
curl "http://localhost:8000/api/v1/books/<book_slug>/chapters/<chapter_slug>?section=<section_slug>" \
     -H "Accept: text/markdown"

# 3) 全文搜索（结果为节，链接指向节页）
curl "http://localhost:8000/api/v1/search?q=部署&page_size=5"
```

```powershell
# 1) 列出公开 Book
curl.exe "http://localhost:8000/api/v1/books"

# 2) 取某节原文
curl.exe "http://localhost:8000/api/v1/books/<book_slug>/chapters/<chapter_slug>?section=<section_slug>" `
         -H "Accept: text/markdown"

# 3) 全文搜索（中文参数建议先 URL 编码）
curl.exe "http://localhost:8000/api/v1/search?q=%E9%83%A8%E7%BD%B2&page_size=5"
```

`/api/v1/books` 的响应形如：

```json
{
  "items": [
    {
      "id": 1,
      "slug": "book-c1e1b9",
      "title": "研发手册",
      "summary": "新人入职、环境搭建与发布流程。",
      "icon": "📘",
      "visibility": "public",
      "weight": 58.11,
      "view_count": 0,
      "recent_view_count": 0,
      "chapter_count": 2,
      "created_at": "2026-10-21T05:48:42.926592Z",
      "updated_at": "2026-10-21T05:48:42.926592Z",
      "url": "/b/book-c1e1b9",
      "api_url": "/api/v1/books/book-c1e1b9"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

> 上面这个 `book-c1e1b9` 是真实行为：纯中文标题经 slug 化后为空，会自动回退成 `book-<6 位十六进制>`；章节标题「欢迎使用 BookHub」能抽出 ASCII 部分，slug 为 `bookhub`。

完整端点、字段、错误码、ETag 与增量同步用法见 [docs/api.md](docs/api.md)。

---

## 5. 目录结构

```text
BookHub/
├── app/
│   ├── main.py               # 应用工厂 create_app()、错误处理、健康探针
│   ├── config.py             # 全部环境变量与默认值（Settings.from_env）
│   ├── db.py                 # 引擎/会话；SQLite 打开 WAL、外键、busy_timeout
│   ├── models.py             # ORM：User/Book/Chapter/ChapterVersion/AuditLog/SiteSetting
│   ├── security.py           # bcrypt 密码、签名会话、CSRF token
│   ├── middleware.py         # request_id、安全响应头、API Key、限流
│   ├── errors.py             # 统一异常与错误响应体
│   ├── bootstrap.py          # `python -m app.bootstrap`：幂等创建初始管理员
│   ├── api/v1.py             # 只读 API /api/v1
│   ├── web/                  # 页面路由：public.py / auth.py / admin.py / common.py
│   ├── services/             # 业务逻辑：books/book_groups/chapters/search/render/encoding/slug/users/audit/settings
│   ├── templates/            # Jinja2 模板（base + admin/*）
│   └── static/               # style.css / app.js / pygments.css（无构建步骤）
├── alembic/
│   ├── env.py                # 迁移环境，读取 DATABASE_URL
│   └── versions/0001_initial.py
├── tests/                    # pytest：api/auth/content/render/search/web/deploy/config
├── data/                     # 默认 SQLite 数据目录（已 gitignore）
├── scripts/                  # 运维脚本（如 gen_pygments.py）
├── docker/
│   ├── entrypoint.sh         # 容器入口：配置自检 → 目录准备 → 迁移 → 初始管理员 → uvicorn
│   └── backup.sh             # SQLite 在线备份 + 内容卷打包（restore.sh 尚未生成）
├── docs/                     # 交付文档（本目录）
├── openspec/                 # 规格与变更记录
├── Dockerfile                # 两阶段构建，运行镜像以 uid 10001 非 root
├── docker-compose.yml        # 单服务 + 命名卷；postgres 走 --profile
├── .env.example              # 全部配置项样例（cp 成 .env 后按注释改）
├── .dockerignore
├── requirements.txt          # 运行时依赖
├── requirements-dev.txt      # + pytest / httpx / ruff
├── alembic.ini · pytest.ini · pyproject.toml
```

---

## 6. 测试

```bash
pytest
```

```powershell
pytest
```

- 只装了运行时依赖时需要先装测试依赖：`pip install -r requirements-dev.txt`。
- 每个用例使用独立临时 SQLite 库并跑真实迁移（`tests/conftest.py`），不会碰 `data/`。
- 代码风格：`ruff check .`、`ruff format .`（配置在 `pyproject.toml`，行宽 110）。

### 6.1 实机冒烟（CI 也跑这套）

`pytest` 用的是进程内 TestClient，覆盖不到「`alembic upgrade` → `bootstrap` → uvicorn → 真实 HTTP」这条启动链路，所以仓库另带三个只依赖标准库的冒烟脚本，对着**已经跑起来的实例**验：

```bash
python scripts/smoke.py                                                   # 访客侧只读端点
python scripts/e2e_admin_flow.py --username admin --password '<密码>'      # 网页端完整生命周期
python scripts/api_smoke.py --token "bh_xxx"                              # 管理 API 生命周期
```

- 三者都以退出码表示结果（0 通过 / 1 失败），可直接放进部署流水线。
- `e2e_admin_flow.py` 与 `api_smoke.py` 会写入带时间戳的测试 Book，**生产环境不要跑**。
- 管理 API 冒烟需要一个 `write` 以上作用域的 Token：可在后台「API Token」页签发，或设 `ADMIN_API_TOKEN` 让应用启动时幂等落库一个。
- CI 的 `smoke` job 就是按上面顺序跑的（含 60s 内等 `/healthz` 就绪，失败时上传 `uvicorn.log`）。

---

## 7. 常见问题

### 7.1 忘记管理员密码，改 `BOOKHUB_INITIAL_ADMIN_*` 重启为什么没用？

`ensure_initial_admin()` 的逻辑是「**账号不存在才创建**」，已存在则直接返回（不算错误）。所以改环境变量不会重置已有账号的密码。

三条出路，按推荐顺序：

1. 还有另一个 `admin` 账号 → 登录后到 `/admin/users` 给目标账号「重置密码」。
2. 进容器/在宿主用脚本直接改密码（`DATABASE_URL` 与 `SECRET_KEY` 需和运行环境一致）：

```bash
python - <<'PY'
from sqlalchemy import select
from app.config import Settings
from app.db import build_engine, build_sessionmaker
from app.models import User
from app.services.users import set_password

settings = Settings.from_env()
engine = build_engine(settings.database_url)
factory = build_sessionmaker(engine)
with factory() as session:
    user = session.execute(select(User).where(User.username == "admin")).scalar_one()
    set_password(user, "NewPass12345")     # 会同时让该账号所有旧会话失效
    session.commit()
    print("password updated:", user.username)
engine.dispose()
PY
```

```powershell
@'
from sqlalchemy import select
from app.config import Settings
from app.db import build_engine, build_sessionmaker
from app.models import User
from app.services.users import set_password

settings = Settings.from_env()
engine = build_engine(settings.database_url)
factory = build_sessionmaker(engine)
with factory() as session:
    user = session.execute(select(User).where(User.username == "admin")).scalar_one()
    set_password(user, "NewPass12345")
    session.commit()
    print("password updated:", user.username)
engine.dispose()
'@ | python -
```

3. 实在进不去也没有别的账号：删掉/改名数据库文件重建（**会丢全部内容**，先备份）。

密码策略：至少 10 个字符，不能与用户名相同，不能是纯数字或纯字母（需两类以上字符），且不超过 72 字节。

### 7.2 上传后中文乱码

- 代码按 **UTF-8 BOM → 严格 UTF-8 → GB18030** 顺序自动识别，并统一把 CRLF 归一化成 LF。GB18030 几乎能解码任意字节，所以含 NUL 字节的文件会被直接判为「疑似二进制」拒绝，而不是静默变乱码。
- 仍然乱码时，在上传表单的「文件编码」下拉里**显式指定** `GB18030 / GBK` 或 `UTF-8` 再提交。
- 用外部工具另存为 UTF-8 是最省事的做法。
- 另一种「乱码」不是服务端问题：Windows PowerShell 5.1 的 `Invoke-WebRequest` / `Invoke-RestMethod` 会把 UTF-8 响应按 ISO-8859-1 解码。用 `curl.exe`，或 `[Console]::OutputEncoding = [Text.Encoding]::UTF8` 后再读。

### 7.3 数据在哪、怎么备份

- 默认 `DATABASE_URL=sqlite:///./data/bookhub.db`，即启动工作目录下的 `data/bookhub.db`。
- SQLite 开了 WAL，同目录还会出现 `bookhub.db-wal` 与 `bookhub.db-shm`；**直接拷贝单个 `.db` 文件可能丢掉尚未 checkpoint 的写入**，务必停服务或用 SQLite 在线备份（`sqlite3 db ".backup out.db"`）。
- 容器部署：`./docker/backup.sh` 会做在线快照 + 内容卷打包 + sha256 校验（不停服），用法见 [docs/deploy.md](docs/deploy.md) 第 7 节。
- `docker/restore.sh` **尚未生成**；恢复目前按 deploy.md 里的手工流程（停服 → 覆盖库文件 → 删掉 `-wal`/`-shm` → 起服）。
- 换成 Postgres 时备份方式完全不同（`pg_dump -Fc`），见同一篇文档。

### 7.4 启动报「缺少必需配置 SECRET_KEY」

`SECRET_KEY` 是唯一会**阻止启动**的配置（且不能短于 16 字符）。初始管理员变量缺失只会跳过创建并打一条 `admin.bootstrap.skipped` 日志。

### 7.5 页面能开但接口 500、日志里有「no such table」

说明迁移没跑。执行 `python -m alembic upgrade head`（容器里由 entrypoint 负责）。应用启动时**不会**自动建表，`_startup_tasks` 里的异常只记录不抛出，所以缺表时表现为请求报错而不是启动失败。

### 7.6 `/readyz` 会不会往数据库写东西？

会。它是一个**写探针**：建/写/删 `_readyz_probe` 表里的一行，用来确认数据库可写（只读副本会返回 503 `database not writable`）。纯存活检查用 `/healthz`。

### 7.7 Windows + WSL2：过一会儿就打不开、登录到一半变 chrome-error

这是 **WSL 发行版被回收**，不是应用的问题：WSL2 在"没有活跃进程"时会关掉发行版，`dockerd` 跟着退出，容器随之停止（Docker 的 `restart: unless-stopped` 只能在 daemon 活着时生效）。现象是：刚启动时一切正常，闲置一两分钟后页面打不开、登录 POST 直接连接失败。

三种处理方式：

1. **用启动脚本**（最简单）：`./scripts/run-docker.ps1` —— 它会在 WSL 里挂一个常驻进程（`sleep infinity`）让发行版不被回收，确保 `dockerd` 就绪，再 `docker compose up -d` 并等到 `/healthz` 通过。
2. **开一个 WSL 终端别关**：`wsl` 进去停在那儿，同样能撑住发行版。
3. **不用 WSL**：按第 3 节在 Windows 原生跑 `uvicorn`，进程随宿主走，不受 WSL 回收影响（代价是没有容器隔离）。

自检命令：`wsl -e bash -lc "docker compose ps"`。如果容器 `Up` 但 Windows 侧连不上，通常是 WSL 刚开始重启、端口转发还没就绪，等 10~20 秒即可。

---

## 8. 界面与主题

界面是一套自建的轻量设计系统（`app/static/style.css`，无 CSS 框架、无构建步骤、无 CDN），颜色/字号/圆角/阴影全部走 CSS 变量。

- **三态主题**：顶栏右侧切换「跟随系统 / 亮色 / 暗色」，选择存在 `localStorage["bookhub-theme"]`；首屏由 `<head>` 里的 `app/static/theme.js` 同步设置 `data-theme`，不会闪白。禁用 JS 时自动退化为跟随系统。
- **换主色**：只改 `style.css` 里 `:root` 的 `--accent` / `--accent-hover` / `--accent-soft` / `--accent-border`（暗色同名变量在 `:root[data-theme="dark"]` 里），全站按钮、链接、焦点环、选中态一起变。
- **站点图标**：`app/static/favicon.svg`（矢量，跟随主题色 `theme-color`）。想换 logo 直接替换这个文件，模板里通过 `<link rel="icon">` 引用。
- **代码高亮**：`app/static/pygments.css` 由 `scripts/gen_pygments.py` 生成，亮色用 `default`、暗色用 `github-dark`，跟随 `data-theme`。
- **排版**：正文行宽上限 `--measure: 72ch`，阅读页宽屏显示右侧页内目录、窄屏折叠为可展开的「本页目录」，打印时自动隐藏导航与侧栏。

改完样式后重建镜像即可（静态文件在镜像里）：`docker compose up -d --build`；本地调试直接刷新，浏览器强刷 `Ctrl+F5` 可绕过缓存。

---

## 9. 文档索引

| 文档 | 内容 |
| --- | --- |
| [docs/deploy.md](docs/deploy.md) | 部署、配置项、healthcheck、升级回滚、备份恢复、Postgres 切换、反代子路径 |
| [docs/api.md](docs/api.md) | `/api/v1` 完整参考、ETag、导出、增量同步、限流 |
| [docs/authoring.md](docs/authoring.md) | 建 Book → 传章节 → 替换 → 发布 → 回滚 → 删除/恢复 的操作路径 |
| [docs/reading.md](docs/reading.md) | 访客侧 URL、可见性语义、面包屑、TOC、打印 |
| [docs/admin.md](docs/admin.md) | 角色权限矩阵、账号、审计、CSRF、安全建议 |
| [docs/search.md](docs/search.md) | 中文二元组切分、单字回退、已知限制 |
| [docs/content-model.md](docs/content-model.md) | 数据模型字段表、slug 规则、状态机、排序、版本保留 |
