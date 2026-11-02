# Tasks

## 1. 项目骨架与依赖

- [x] 1.1 初始化 git 仓库与 `.gitignore`（忽略 `.env`、`/data`、`__pycache__`、`.venv`、`*.db`），`git status` 干净可提交
- [x] 1.2 建立目录结构 `app/{api,web,services,models,templates,static}`、`tests/`、`alembic/`、`docker/`、`scripts/`、`docs/`，验证 `python -c "import app"` 无报错
- [x] 1.3 写 `requirements.txt`（运行）与 `requirements-dev.txt`（pytest/httpx/ruff），在 venv 内 `pip install -r requirements-dev.txt` 全部成功
- [x] 1.4 实现 `app/config.py`（环境变量 → Settings，缺 `SECRET_KEY` 时启动即失败并给出明确报错），单测覆盖默认值与必填校验
- [x] 1.5 实现 `app/main.py` 应用工厂 + 静态文件挂载 + 中间件骨架，验证 `uvicorn app.main:app` 可启动且 `/healthz` 返回 200

## 2. 数据模型与迁移

- [x] 2.1 用 SQLAlchemy 2.0 定义 `users/books/chapters/chapter_versions/audit_logs/site_settings` 模型与索引，`pytest tests/test_models.py` 覆盖唯一约束与默认值
- [x] 2.2 配置 Alembic（`alembic.ini` + `env.py` 读 `DATABASE_URL`），生成初始迁移并在空库上 `alembic upgrade head` 成功
- [x] 2.3 初始化 SQLite 连接参数（WAL、`busy_timeout`、`foreign_keys=ON`），验证 `PRAGMA journal_mode` 返回 `wal`
- [x] 2.4 建 `chapter_fts`（FTS5）虚拟表与同步写入/删除逻辑，单测验证插入章节后 FTS 行数一致
- [x] 2.5 写 `tests/conftest.py`（临时 SQLite + 迁移 + TestClient 工厂 + 登录夹具），`pytest -q` 全绿

## 3. 认证与账号（admin-auth）

- [x] 3.1 实现密码哈希与校验（bcrypt，含 72 字节边界处理），单测覆盖正确/错误/超长密码
- [x] 3.2 实现签名 Cookie 会话（登录、登出、过期、`session_epoch` 失效），单测覆盖改密后旧会话 401
- [x] 3.3 实现角色与权限依赖（`admin` / `editor` / 未登录），单测覆盖 editor 访问账号管理返回 403
- [x] 3.4 实现 CSRF token 签发与校验，单测覆盖缺 token / 错误 token 的表单提交被拒绝（400/403）
- [x] 3.5 实现初始管理员引导（`BOOKHUB_INITIAL_ADMIN_USER/PASSWORD`，幂等、弱密码拒绝），单测覆盖重复启动不重建
- [x] 3.6 实现账号管理页（列表、新增、禁用/启用、重置密码），并写 `docs/admin.md` 对应操作说明，手动走通一遍
- [x] 3.7 实现登录失败限速（同 IP/账号滑动窗口），单测覆盖超过阈值返回 429 或锁定提示

## 4. Book 管理（book-catalog）

- [x] 4.1 实现 slug 规范化与唯一化工具（`[a-z0-9-]`、冲突追加 `-2`），单测覆盖中文标题、空格、重复、纯符号标题
- [x] 4.2 实现 Book 服务层（创建、更新、软删除、排序、可见性），单测覆盖软删除后不出现在查询结果
- [x] 4.3 实现管理端 Book 列表/新建/编辑表单（含校验错误回显），手动验证标题为空时给出字段级错误
- [x] 4.4 实现 Book 详情目录查询（有序章节、空 Book 表现），单测覆盖排序与空目录
- [x] 4.5 写 `docs/content-model.md` 说明 Book/章节/可见性语义，并核对文中示例与实现一致

## 5. 章节内容与渲染（chapter-content）

- [x] 5.1 实现编码检测与归一化（UTF-8 BOM → UTF-8 → GB18030，失败报错），单测覆盖三种编码与不可解码输入
- [x] 5.2 实现上传校验（扩展名白名单、单文件大小上限、空文件），单测覆盖超限返回 413/422 且不落库
- [x] 5.3 实现 Markdown 渲染管线（GFM 表格/任务列表/删除线/脚注/围栏代码 + Pygments 高亮 + 标题锚点 + TOC 提取），单测断言表格、高亮 class 与锚点 id
- [x] 5.4 实现 HTML 白名单净化（去 `script`/`iframe`/`form`/`on*`/`javascript:`，保留表格与代码），单测用 XSS payload 集逐一断言被剔除
- [x] 5.5 实现渲染结果缓存（`content_rendered` + `content_checksum` 失效），单测覆盖"内容变更后立即读到新渲染结果且只渲染一次"
- [x] 5.6 实现页面 CSP 与安全响应头中间件，单测断言公开页不含内联脚本且 CSP 头存在

## 6. 章节生命周期（chapter-lifecycle）

- [x] 6.1 实现章节创建（表单标题/格式/正文 + 文件上传，slug 由标题或文件名推导），单测覆盖两种入口
- [x] 6.2 实现章节内容整体替换（新版本号、旧内容进 `chapter_versions`、校验和更新），单测覆盖版本号递增与历史内容可读
- [x] 6.3 实现排序（上移/下移/指定位置，单事务重写 `sort_order`），单测覆盖边界位置与并发安全的乐观校验
- [x] 6.4 实现草稿/发布流转（`published_at` 首次发布时间不被覆盖），单测覆盖草稿对外 404、发布后可见
- [x] 6.5 实现软删除、回收站列表与恢复，单测覆盖删除后 slug 可复用与恢复后顺序正确
- [x] 6.6 实现历史版本查看、对比与回滚（回滚生成新版本），单测覆盖回滚后当前内容等于目标版本
- [x] 6.7 实现版本保留策略（`VERSION_RETENTION` 裁剪，永不删当前版本），单测覆盖超限裁剪
- [x] 6.8 写 `docs/authoring.md` 说明上传/替换/回滚流程与大小限制，按文档手动操作一遍

## 7. 访客阅读端（public-reading）

- [x] 7.1 实现首页 Book 列表（仅 `public`、分页、空态），单测断言 `unlisted` 不出现
- [x] 7.2 实现 Book 目录页与章节阅读页（面包屑、上下篇、TOC 侧栏、打印样式），手动验证深链接与锚点跳转
- [x] 7.3 实现阅读端只暴露已发布内容（草稿/已删除 404，`unlisted` 可直链），单测覆盖三种情况
- [x] 7.4 实现站点设置读取（站点名、页脚、首页说明）并在模板生效，单测覆盖设置变更后页面标题变化
- [x] 7.5 写 `docs/reading.md` 记录 URL 规则与可见性行为，并核对实现

## 8. 全文检索（content-search）

- [x] 8.1 实现中文二元组 + ASCII 词切分工具与查询构造，单测覆盖 2 字中文、英文大小写、混合串
- [x] 8.2 实现检索服务（仅已发布未删除、按 Book 过滤、分页、片段高亮），单测覆盖草稿不可命中与替换后旧内容不再命中
- [x] 8.3 实现站内搜索页与空查询/超长查询处理，手动验证高亮与结果跳转
- [x] 8.4 写 `docs/search.md` 说明切分与召回限制，并给出可复现的示例查询

## 9. 对外 API（content-api）

- [x] 9.1 实现 `/api/v1/books` 与 `/api/v1/books/{slug_or_id}`（含目录、分页），单测覆盖按 slug/ID 定位与 404
- [x] 9.2 实现单章节三通道（默认 JSON、`?format=raw`、`Accept: text/markdown`、`Accept: text/html`），单测断言原文与库内字节一致
- [x] 9.3 实现整本导出（`format=json` 与 `format=zip`），单测解压校验 `book.json` 与章节文件数量/编码
- [x] 9.4 实现 `ETag`/`If-None-Match`/`Last-Modified`（304 路径），单测覆盖内容变更后 ETag 必变
- [x] 9.5 实现 `/api/v1/changes?since=` 增量同步（含删除墓碑、时间边界），单测覆盖 since 边界与墓碑
- [x] 9.6 实现统一错误体与状态码（404 不泄露未发布、400 参数错误、405 写方法、429 限流+`Retry-After`），单测逐条覆盖
- [x] 9.7 实现可选 `API_KEY` 校验、CORS 白名单、限流中间件，单测覆盖开启/关闭两种配置
- [x] 9.8 实现 OpenAPI 文档开关（`/docs`、`/openapi.json`），验证文档中列出全部 `/api/v1` 路径
- [x] 9.9 写 `docs/api.md`（端点、参数、响应示例、ETag 与增量同步用法），并用文档里的 curl 示例对运行中实例验证一遍

## 10. 审计与站点设置

- [x] 10.1 实现审计日志写入（动作、对象、操作者、IP、版本号），单测覆盖新建/替换/删除/回滚四类动作
- [x] 10.2 实现审计日志查询页（按 Book/章节/操作者筛选、分页），手动验证筛选结果
- [x] 10.3 实现站点设置管理页（站点名、页脚、首页说明、`API_KEY` 提示），单测覆盖保存与读取

## 11. Docker 部署与运维（service-deployment）

- [x] 11.1 编写多阶段 `Dockerfile`（非 root、healthcheck、`/data` 卷、`PYTHONUNBUFFERED`），`docker build` 成功
- [x] 11.2 编写 `docker/entrypoint.sh`（迁移 → 初始管理员 → 启动）与 `docker-compose.yml`（命名卷、env_file、postgres profile），`docker compose config` 校验通过
- [x] 11.3 编写 `.env.example`（每项带注释与默认值），核对 `app/config.py` 中所有变量都在其中出现（脚本比对）
- [x] 11.4 实现 `/healthz` 与 `/readyz`（就绪含 DB 写探测），单测覆盖 DB 不可写时 `/readyz` 返回 503
- [x] 11.5 实现结构化 stdout 日志与 `request_id` 关联，手动验证一次请求的日志可串起来
- [x] 11.6 实现 `ROOT_PATH` 子路径部署（模板内链接与静态资源使用 `url_for`），单测覆盖 `ROOT_PATH=/kb` 下渲染链接带前缀
- [x] 11.7 编写 `docker/backup.sh` 与 `docker/restore.sh`（在线备份 + 恢复校验），本地演练一次"备份→删库→恢复→数据完整"
- [x] 11.8 编写 `scripts/smoke.py`（对运行实例跑 API 主流程），对本地启动实例执行通过
- [x] 11.9 写 `docs/deploy.md`（部署、升级、回滚、备份、Postgres 切换、反代示例），按文档在干净环境走一遍

## 12. 集成验证

- [x] 12.1 跑完整测试套件 `pytest -q` 全绿，并记录覆盖率（核心服务层 ≥80%）
- [x] 12.2 端到端演练：建 Book → 上传 Markdown → 上传 HTML（含 XSS payload）→ 替换 → 回滚 → 删除 → 恢复，并用 API 逐项验证结果
- [x] 12.3 写 `README.md`（功能概览、5 分钟 Docker 启动、API 快速上手、目录结构、测试命令），按 README 从零启动验证
- [x] 12.4 `openspec validate build-bookhub-kb --strict` 通过，且 `tasks.md` 全部勾选

## Workflow follow-up

- 实现完成后运行 `openspec archive build-bookhub-kb --yes`，确认 `openspec/specs/` 生成 8 个能力的主规格。
