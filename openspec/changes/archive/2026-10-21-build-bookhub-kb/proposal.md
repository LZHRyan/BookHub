# Proposal

## Why

研发部的技术文档目前散落在 Confluence、共享盘、个人 Markdown 笔记和 Git 仓库里：找不到、不敢信、版本不可追溯，外部程序（CI 流水线、运维脚本、内部门户、AI 助手）更没有稳定的接口按需拉取"最新且已发布"的内容。需要一套自托管、可 Docker 一键部署、以 **Book 为单元、以 HTML/Markdown 文档为章节** 的知识库：少量管理员维护内容，访客无限只读浏览，同时对外提供只读 API 供程序取用。

## What Changes

一期交付一个完整可运行的服务 `BookHub`（后端 API + 服务端渲染 Web 界面 + 对外只读 API + Docker 部署资产），不改造任何既有系统（当前仓库为空，属全新项目）。

**内容组织**

- Book 作为顶层单元：标题、slug（用于稳定 URL）、简介、封面/图标（可选）、排序权重、可见性（`public` / `unlisted`）。
- Book 下以章节（Chapter）为文档：每个章节承载一份 HTML 或 Markdown 原文，拥有标题、slug、排序、草稿/已发布状态。
- 章节支持新建、上传文件新增、整体替换内容、删除（软删除 + 回收站式恢复）、拖拽/上移下移排序。

**内容与渲染**

- Markdown（GFM：表格、任务列表、删除线、围栏代码、脚注）+ 代码高亮 + 自动生成页内 TOC + 标题锚点。
- HTML 章节按安全白名单净化（脚本、内联事件、危险 URL 协议一律剔除），渲染时置于受沙箱约束的容器内，防止存储型 XSS 影响站内会话。
- 上传时自动检测编码（UTF-8 无 BOM / UTF-8 with BOM / GB18030），统一转存为 UTF-8，避免中文文档乱码。
- 章节内容变更保留历史版本，可查看、对比与回滚（回滚本身也产生一个新版本）。

**管理端**

- 少量管理员账号：用户名 + 密码（bcrypt 哈希）、会话登录、可禁用/重置密码/新增管理员、首次启动由环境变量注入初始管理员。
- 所有写操作记审计日志（操作者、动作、对象、时间、IP、前后版本号），可按 Book/章节筛选查看。
- 草稿预览：管理员可在发布前按访客视角预览未发布章节。

**访客端**

- Book 列表、Book 详情（目录 + 章节）、章节阅读页、全文搜索、面包屑与上一篇/下一篇导航。
- 不登录即可浏览全部 `public` 内容；`unlisted` 的 Book 不出现在列表与搜索中，只能通过直链访问。
- 站点级配置（站点名、页脚、默认首页说明）可在管理端修改。

**对外 API（供外部程序取用）**

- 只读 REST API `/api/v1`：Book 列表、Book 明细（含目录）、单章节原文（`text/markdown` / `text/html`）、单章节渲染后 HTML、全文搜索、整本导出（JSON manifest 或 ZIP）。
- 支持按 slug 或 ID 定位；只返回"已发布"内容；支持 `ETag` / `If-None-Match` 与 `updated_since` 增量拉取，便于外部同步。
- 可选 API Key（配置后要求 `X-API-Key`，未配置则完全公开）、按 IP 的限流、CORS 白名单、OpenAPI 文档页。
- 稳定兼容约定：`/api/v1` 内只做向后兼容的新增，破坏性改动走 `/api/v2`。

**部署与运维**

- 多阶段 `Dockerfile`（Python 3.12-slim，非 root 运行）+ `docker-compose.yml`（命名卷持久化；可选 Postgres profile）。
- 全部配置走环境变量（`.env.example` 齐全），启动即执行数据库迁移；`/healthz`、`/readyz` 探针。
- 镜像自带启动脚本：等待数据卷就绪、确保初始管理员、可选演示数据。
- 备份/恢复：SQLite 在线备份 + 内容卷打包脚本，README 给出具体命令。
- 结构化日志、可配 `root_path` 以适配反向代理子路径部署。

**明确不在本期范围**

- 多人实时协同编辑、评论/点赞、审批工作流、多租户隔离、SSO/OIDC/LDAP 登录（认证层留出 provider 接口）、文档附件二进制大文件管理（图片走后续变更）。

## Capabilities

### New Capabilities

- `book-catalog`: Book 的创建、元数据、slug 唯一性、排序与可见性，以及面向访客的 Book 列表/详情与目录导航。
- `chapter-content`: 章节内容模型（HTML/Markdown 双格式）、编码归一化、Markdown 渲染管线、HTML 白名单净化、页内锚点/TOC、内容大小限制。
- `chapter-lifecycle`: 章节的新增（表单/文件上传）、整体替换、排序、草稿/发布、软删除与恢复、历史版本与回滚。
- `admin-auth`: 管理员账号、登录会话、密码策略、初始管理员引导、账号管理与写操作审计日志。
- `public-reading`: 访客无登录浏览、搜索入口、直链章节访问、`unlisted` 可见性规则与隐藏草稿的保证。
- `content-search`: 跨 Book/章节的全文检索（中文按二元组切分 + 英文词干化）、结果高亮、只检索已发布内容。
- `content-api`: `/api/v1` 只读 API 的全部契约：资源表示、原文/渲染双通道、ETag 与增量同步、导出、限流与 CORS、OpenAPI 文档。
- `service-deployment`: Docker 镜像与编排、环境变量配置项、卷持久化、迁移与启动顺序、健康探针、备份恢复与升级路径。

### Modified Capabilities

（无。仓库为全新项目，`openspec/specs/` 当前为空。）

## Impact

- **代码**：新增 `app/`（FastAPI 应用：`api/`、`web/`、`services/`、`models/`、`templates/`、`static/`）、`tests/`、`scripts/`、`alembic/`。
- **对外接口**：新增 `/api/v1/*` 只读 API 与 `/openapi.json`、`/docs`；新增管理端 `/admin/*` 与访客端 `/`、`/b/<book-slug>`、`/b/<book-slug>/<chapter-slug>`。
- **数据**：新增 SQLite 数据库（WAL 模式，位于持久卷 `/data/bookhub.db`）与 FTS5 全文索引；可选 Postgres 通过同一 ORM 层切换。
- **依赖**：`fastapi`、`uvicorn`、`sqlalchemy`、`alembic`、`jinja2`、`markdown-it-py`、`mdit-py-plugins`、`nh3`（HTML 净化）、`pygments`、`python-multipart`、`bcrypt`、`itsdangerous`、`httpx`+`pytest`（测试）。
- **部署**：新增 `Dockerfile`、`docker-compose.yml`、`.env.example`、`deploy/`（备份恢复脚本），以及 `README.md` 部署与 API 使用说明。
- **风险**：管理员上传的 HTML 是不可信输入（净化 + 沙箱必须做对）；中文全文检索质量取决于切分策略；SQLite 单写入者模型要求写操作短事务。
