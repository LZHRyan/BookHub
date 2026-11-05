# 部署与运维

面向部署 BookHub 的运维同事。所有行为都能在代码里找到依据，行内标注了对应文件；命令按「已实测」与「约定（未实测）」区分。

---

## 1. 部署前检查

| 检查项 | 要求 |
| --- | --- |
| Python | 3.12（`pyproject.toml` 的 `target-version = "py312"`；镜像基于 `python:3.12-slim`） |
| Docker（推荐路径） | Docker Engine/Desktop + **docker compose v2 插件**（`docker compose version` 能跑） |
| 依赖 | `requirements.txt`；迁移需要 `alembic`（已在其中） |
| 必填配置 | `SECRET_KEY`（≥16 字符，缺失或为占位值都会启动失败：`app/config.py` + `docker/entrypoint.sh`） |
| 数据卷 | 命名卷 `bookhub-data` → `/data`；用 bind mount 时宿主目录必须 `chown -R 10001:10001`（容器内 uid/gid） |
| 端口 | 宿主机端口由 `PORT` 控制（默认 `8000`），容器内固定 8000；建议只经反向代理对外 |
| 时区 | 数据库内所有时间按 **UTC** 存储（`app/models.py:utcnow`），页面按 UTC 展示，不做本地时区换算 |
| 时钟 | 增量同步依赖 `updated_at` 与 `server_time` 比较，宿主机时钟必须准确 |

---

## 2. 配置项总表

配置**只来自环境变量**（`app/config.py` 的 `Settings.from_env`，没有 `.env` 解析器；本地由 `docker compose`/shell 注入）。下表的默认值全部取自代码。

### 2.1 必填

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `SECRET_KEY` | 无（**必填**） | 会话 cookie、CSRF token 的签名密钥。少于 16 字符或为空都会抛 `ConfigError` 阻止启动。换掉它 = 所有已登录会话立即失效 |

### 2.2 数据与站点

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./data/bookhub.db` | SQLAlchemy URL。`sqlite` 前缀会额外打开 WAL/外键/`busy_timeout`（`app/db.py`）。容器里 compose 默认给 `sqlite:////data/bookhub.db`（**4 个斜杠**＝绝对路径） |
| `DATA_DIR` | `./data` | 应用侧**只记录进启动日志**，不参与应用内的路径计算（实际库位置由 `DATABASE_URL` 决定）；但 `docker/entrypoint.sh` 会用它做目录创建/可写探测，`docker/backup.sh` 也按 `/data` 打包 |
| `SITE_NAME` | `BookHub 知识库` | 站点名默认值；后台「站点设置」保存后会覆盖 |
| `SITE_FOOTER` | `内部技术文档` | 页脚默认值，同上 |
| `HOME_INTRO` | 空 | 首页说明默认值，同上 |
| `ROOT_PATH` | 空 | 反向代理子路径，如 `/kb`；`/`、尾部斜杠会被归一化掉（`_normalize_root_path`） |

### 2.3 会话与安全

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `SESSION_COOKIE_NAME` | `bookhub_session` | 会话 cookie 名 |
| `SESSION_MAX_AGE` | `28800`（8 小时） | 会话有效期（秒），下限 60；CSRF token 复用同一有效期 |
| `COOKIE_SECURE` | `false` | 置 `true` 时 cookie 带 `Secure`，**必须走 HTTPS**，否则登录后立刻失效 |
| `API_KEY` | 空 | 配置后 `/api/v1` 除 `/api/v1/site` 外都要 `X-API-Key` |
| `RATE_LIMIT_ENABLED` | `true` | 是否对 `/api/v1` 限流 |
| `RATE_LIMIT_PER_MINUTE` | `120` | 每 IP 每 60 秒窗口的 API 请求上限，下限 1 |
| `LOGIN_FAIL_LIMIT` | `5` | 同 IP+用户名在窗口内的登录失败上限 |
| `LOGIN_FAIL_WINDOW` | `300` | 登录失败统计窗口（秒），下限 10 |
| `TRUSTED_PROXIES` | 空 | 可信反向代理的 IP/CIDR 列表（逗号分隔）。**只有直连 peer 命中时才采信 `X-Forwarded-For` / `X-Real-IP`**；留空 = 谁都不信，一律用直连地址。填了非法条目直接启动失败 |
| `CORS_ORIGINS` | `*` | 逗号分隔；`*` 时 `allow_credentials=False`（`app/main.py`） |
| `API_DOCS_ENABLED` | `true` | 控制 `/docs` 与 `/openapi.json`；关闭后 `api.docs` 返回 `null` |
| `AUDIT_RETENTION_DAYS` | `180` | 审计保留天数：启动时与手动清理端点会删除超期记录；`0` 表示永久保留 |

### 2.4 内容限额

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `MAX_UPLOAD_BYTES` | `5242880`（5 MiB） | 单文件上传上限，超出 413 `file_too_large`；下限 1024 |
| `MAX_UPLOAD_FILES` | `50` | 单次批量上传的文件**个数**上限，超出 400；下限 1。网页端与 API multipart 一致生效 |
| `MAX_REQUEST_BYTES` | `文件个数 × 单文件上限 + 1 MiB`（默认约 251 MiB） | 单次**请求体**总量上限：`Content-Length` 超限直接在读正文前 413。反代的 `client_max_body_size` 要同时放得下合法上传 |
| `MAX_CONTENT_CHARS` | `500000` | 单章正文字符上限，超出 422 `content_too_long`；下限 1000。**粘贴正文与上传文件都受它约束** |
| `VERSION_RETENTION` | `50` | 每章保留的历史版本数，写入时裁剪，当前版本永不裁剪；下限 1 |

媒体资源（图片与附件）另有三项：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `MEDIA_MAX_BYTES` | `20971520`（20 MiB） | 单个图片/附件上限，超出 413 `file_too_large`；下限 1024 |
| `MEDIA_QUOTA_BYTES` | `524288000`（500 MiB） | 每个 Book 的媒体占用上限（软删除资源不计入），超出 413 `quota_exceeded` |
| `MEDIA_PURGE_GRACE_DAYS` | `7` | 已软删除资源多少天后允许物理回收；期间即使无引用也保留文件 |
| `MEDIA_ALLOWED_TYPES` | `png,jpg,jpeg,gif,webp,svg,avif,bmp,pdf,txt,md,csv,json,log,yaml,yml,zip` | 扩展名白名单，不在其中一律 415 `unsupported_media_type` |

> 媒体文件落在 `{DATA_DIR}/media/<book-slug>/`，与 SQLite 同一个卷。备份脚本备份整个 `/data` 时已经包含它们；只备份 `bookhub.db` 的话**图片会丢**。

### 2.5 引导与运行

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `BOOKHUB_INITIAL_ADMIN_USER` | 空 | 初始管理员用户名（会统一转小写）；为空则跳过创建 |
| `BOOKHUB_INITIAL_ADMIN_PASSWORD` | 空 | 初始管理员密码，需满足密码策略，否则 `bootstrap` 直接报错 |
| `SEED_DEMO` | `false` | 为真时在**库为空**的前提下写入两本演示 Book |
| `BUILTIN_GUIDE_ENABLED` | `true` | 启动时幂等创建内置《AI Agent 接入使用指南》（slug `ai-agent-guide`，不可删除、内容可编辑）。设 `false` 只跳过创建，不会删除已存在的书 |
| `WEB_CONCURRENCY` | `1` | uvicorn worker 数；由 `docker/entrypoint.sh` 传给 `--workers`（见第 10 节） |
| `LOG_LEVEL` | `INFO` | 仅接受 `DEBUG/INFO/WARNING/ERROR/CRITICAL`，其他值启动失败 |

### 2.6 容器/编排层变量（`app/config.py` 不读）

以下变量由 `Dockerfile` / `docker-compose.yml` / `docker/entrypoint.sh` 消费，`.env.example` 里也列了，别指望改它们会影响应用行为：

| 变量 | 默认 | 消费方 | 说明 |
| --- | --- | --- | --- |
| `PORT` | `8000` | compose `ports` + entrypoint | **两个用途耦合，别随便改**：`.env` 经 `env_file` 注入容器后，entrypoint 用它当 uvicorn 监听端口；而 `ports` 右侧写死 `:8000`。把 `PORT` 改成 8123 会导致"宿主 8123 → 容器 8000，但服务在容器 8123 上听"的错位。要换宿主端口请保持 `PORT=8000` 并改 `ports` 左侧（`"8123:8000"`） |
| `FORWARDED_ALLOW_IPS` | `*` | entrypoint → `uvicorn --forwarded-allow-ips` | 信任哪些代理的 `X-Forwarded-*`；直连公网时不要用 `*` |
| `PIP_INDEX_URL` | `https://pypi.org/simple` | Dockerfile builder | 构建期依赖源（国内可换镜像） |
| `BOOKHUB_TAG` | `latest` | compose `image:` | 镜像 tag，回滚时改它 |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | `bookhub` / `bookhub` / 占位密码 | compose `db` 服务 | 仅 `--profile postgres` 时生效 |

---

## 3. 首次启动会发生什么

### 3.1 真实流程（`docker/entrypoint.sh`）

容器入口按顺序做五件事，**能确定的错误尽早失败**：

```text
1) 校验 SECRET_KEY：缺失 → 退出；是占位值（please-change-me* / changeme* / change-me* / your-secret*）→ 退出；长度 <16 → 退出
2) 准备 DATA_DIR：mkdir → 写探测文件 .bookhub-write-test.<pid> → 删除；不可写则退出并提示命名卷 / bind mount 的 chown 10001:10001；DATA_DIR=/ 直接拒绝；顺带 mkdir $DATA_DIR/backups
2.5) 迁移前快照：alembic current ≠ heads 时，先用 sqlite3 backup() 把当前库做成 $DATA_DIR/backups/pre-upgrade-<UTC>.db（保留 PRE_UPGRADE_BACKUP_KEEP 份，默认 5）；失败只 WARN 不阻塞；非 SQLite 只提示手工 pg_dump
3) alembic upgrade head      # 失败 → 退出（带着不匹配的 schema 起来只会更难排查）
4) python -m app.bootstrap   # 失败 → 只打 WARN 继续（应用 lifespan 还会再尝试一次），保证已有实例不因它崩掉
5) exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port $PORT --workers $WEB_CONCURRENCY --proxy-headers --forwarded-allow-ips $FORWARDED_ALLOW_IPS
```

几个容易被忽略的细节：

- `.env` 是**必需**的：`docker-compose.yml` 用 `env_file: .env`，文件不存在时 compose 直接报错——这是有意设计，避免"忘了填 SECRET_KEY 也能起来"。
- 占位值检测意味着：`.env.example` 里那句 `SECRET_KEY=please-change-me-...` 留着不改，容器**起不来**（报错信息会直接告诉你要跑哪条命令生成）。
- 容器内用户是 `bookhub`，**uid/gid = 10001**。用 bind mount 时宿主目录必须 `chown -R 10001:10001`，否则第 2 步就会失败。
- 数据卷是命名卷 `bookhub-data` 挂到 `/data`；容器内默认 `DATABASE_URL=sqlite:////data/bookhub.db`（注意 **4 个斜杠**，第 3、4 个斜杠之间是空主机名）。
- entrypoint 会导出 `DATA_DIR=/data` 与 `DATABASE_URL=sqlite:///${DATA_DIR}/bookhub.db` 作为兜底，所以裸 `docker run -v data:/data <image>`（不经 compose）也能直接起来；compose 的 `environment` 覆盖这两个默认值。
- `WEB_CONCURRENCY > 1` 且数据库仍是 SQLite 时只打 WARN，不拒绝启动。
- 迁移与 `bootstrap` 也可以在宿主上手工执行，这两步**已实测**：

```bash
python -m alembic upgrade head
python -m app.bootstrap
uvicorn app.main:create_app --factory --port 8000
```

```powershell
python -m alembic upgrade head
python -m app.bootstrap
uvicorn app.main:create_app --factory --port 8000
```

- `python -m app.bootstrap` **必须在迁移之后**，否则会因为缺表报错退出。
- `app.main:create_app` 是工厂，必须带 `--factory`。
- 应用启动时**不会自动迁移**；`_startup_tasks` 里的异常只记录 `app.startup.error` 不抛出，所以「缺表」表现为请求 500 而不是启动失败。
- 用了 `--reload` 会让每个子进程各自执行一次启动钩子，只适合本地开发。

### 3.2 启动日志（JSON 一行一条，输出到 stdout）

| 事件 | 含义 |
| --- | --- |
| `app.start` | 启动完成，带脱敏后的配置快照（`public_dict()`，`secret_key` 固定 `***`） |
| `admin.bootstrap` | 本次真的创建了初始管理员 |
| `admin.bootstrap.skipped` | 未配置初始管理员变量，跳过 |
| `demo.seeded` | 写入了演示数据 |
| `app.startup.error` | 启动钩子抛错（不影响进程存活，需要关注） |
| `http.request` | 每请求一条（`/static/` 除外），带 `request_id`、状态码、耗时、客户端 IP |
| `auth.login_success` / `auth.login_failed` / `auth.rate_limited` | 登录相关 |
| `readyz.failed` | 就绪探针失败 |

`JsonFormatter` 会把 `password`、`password_hash`、`secret`、`secret_key`、`api_key`、`token`、`cookie` 这些键的值替换成 `***`（`app/logging_setup.py`）。

---

## 3.3 指标与站点地图

| 端点 | 用途 |
| --- | --- |
| /healthz | 存活探针（不查库） |
| /readyz | 就绪探针（写一次 _readyz_probe 验证库可写） |
| /metrics | Prometheus 文本：bookhub_books_total、bookhub_chapters_published_total、bookhub_media_bytes_total、bookhub_audit_rows_total、bookhub_tokens_active |
| /sitemap.xml | 公开内容地图（首页 + public Book + 已发布章页 + 多节章的节页），供搜索引擎/内部爬虫抓取 |

/metrics 不带鉴权（与 /healthz 一致，只有聚合数字），建议在反向代理层限制来源网段：

`
ginx
location = /metrics { allow 10.0.0.0/8; deny all; proxy_pass http://bookhub:8000; }
`

## 3.4 持续集成

仓库自带 .github/workflows/ci.yml：
uff check → pytest -q → docker build。工作流不需要任何密钥（测试用临时 SQLite）。本地等价命令见 README.md 的「测试」一节。

## 4. 健康探针

| 探针 | 语义 | 依赖 | 返回 |
| --- | --- | --- | --- |
| `GET /healthz` | **存活**：进程能响应 HTTP 即算好 | 无（schema 只读，失败降级为 null） | `200 {"status":"ok","version":"1.0.0","schema":"0013_webhooks"}` |
| `GET /readyz` | **就绪 + 数据库可写** | 数据库写权限 | `200 {"status":"ready","version":...,"schema":...}` / `503 {"status":"unavailable","reason":"database not writable"}` |

`version` 来自镜像（`app/__init__.py`），`schema` 来自库（`alembic_version`）——升级后两者都要看一眼，才能确认"镜像换了、迁移也真跑了"。数据库不可达时 `schema` 为 `null`，不会让 `/healthz` 失败。

`/readyz` 是**写探针**：它执行 `CREATE TABLE IF NOT EXISTS _readyz_probe`、插入一行、再删掉（`app/main.py:_register_health`）。因此：

- 它会在业务库里留下一个空表 `_readyz_probe`，这是预期行为。
- 只读数据库/只读副本会一直 503；磁盘满、权限错也会 503。
- 探针频率别设太密（每秒级没必要），它每次都是一次真实写事务。

两个探针都**不需要** API Key（`ApiKeyMiddleware` 只拦 `/api/v1`），也都在 OpenAPI 文档之外（`include_in_schema=False`）。

容器自带健康检查（`Dockerfile` 的 `HEALTHCHECK`，镜像里不装 curl/wget，用 `python -c "urllib.request.urlopen('http://127.0.0.1:'+PORT+'/healthz')"`）：

| 参数 | 值 |
| --- | --- |
| interval / timeout | 30s / 5s |
| start-period | 20s |
| retries | 3 |

- 它只打 `/healthz`（存活），**不打** `/readyz`：就绪检查留给外部编排或人工，避免每次探活都产生一次数据库写。
- `docker compose ps` 里的 `healthy` 状态就来自这条检查；`restart: unless-stopped` 不会因为不健康而重启容器（只有进程退出才重启）。

---

## 5. 升级流程

推荐用仓库自带的一键脚本（备份 → 镜像留档 → 构建 → 重建 → 等健康 → 打印版本）：

```bash
./scripts/upgrade.sh
# 输出最后会给出：/healthz -> {"status":"ok","version":"1.0.0","schema":"0013_webhooks", ...}
```

```powershell
# Windows 上通过 WSL 或 Git Bash 执行同一个 sh 脚本
wsl -d Ubuntu -e sh /mnt/d/Code/Other/BookHub/scripts/upgrade.sh
```

脚本做了四件手工容易漏的事：

1. **必定先备份**：调用 `docker/backup.sh`（在线一致性快照 + `/data` 打包）；只有显式 `SKIP_BACKUP=1` 才跳过。
2. **镜像留档**：把当前镜像额外打上 `bookhub:pre-upgrade-<UTC 时间>` 标签，回滚时 `BOOKHUB_TAG=<该标签>` 即可。
3. **等待 healthy**：以容器自带 HEALTHCHECK 为准，避免"容器起来了但迁移失败"的假成功。
4. **打印 `version` + `schema`**：确认镜像与库结构都到了新版本。

手工等价操作：

```bash
# 1) 先备份（见第 7 节），再升级
docker compose up -d --build
docker compose logs -f bookhub        # 服务名是 bookhub；观察迁移与启动日志
curl -fsS http://localhost:8000/healthz   # 看 version 与 schema
curl -fsS http://localhost:8000/readyz
```

```powershell
docker compose up -d --build
docker compose logs -f bookhub
curl.exe -fsS http://localhost:8000/healthz
curl.exe -fsS http://localhost:8000/readyz
```

- 迁移由 entrypoint 的 `alembic upgrade head` 幂等执行，重启一次即完成升级。
- **迁移前会自动快照**：`alembic current ≠ heads` 时，entrypoint 先做 `$DATA_DIR/backups/pre-upgrade-<UTC>.db`（保留最近 `PRE_UPGRADE_BACKUP_KEEP` 份，默认 5），再迁移。所以即使手工执行、忘了 `backup.sh`，也有启动瞬间的兜底副本。
- 迁移脚本遵循「只加不删」原则，为的是能回滚到上一个镜像。
- 无 Docker 的环境等价操作：停服务 → `pip install -r requirements.txt` → `python -m alembic upgrade head` → 起服务。
- 页面/模板/静态文件随镜像发布，不需要清缓存动作（静态资源无构建、无 hash 文件名）。

---

## 6. 回滚流程

```bash
# 1) 停服务，避免写入
docker compose down

# 2) 用升级前的备份覆盖数据（见第 7 节恢复步骤）

# 3) 用旧 tag 启动（compose 里的镜像是 bookhub:${BOOKHUB_TAG:-latest}）
BOOKHUB_TAG=<上一个可用版本> docker compose up -d
curl -fsS http://localhost:8000/readyz
```

```powershell
docker compose down
$env:BOOKHUB_TAG = "<上一个可用版本>"
docker compose up -d
curl.exe -fsS http://localhost:8000/readyz
```

**不会自动降级数据库**：`alembic downgrade` 需要人工判断，且旧版本代码面对新 schema 通常仍可运行（只加不删）。若新版本引入了破坏性迁移（删列/改类型），必须先恢复备份再启动旧镜像。

---

## 7. 备份与恢复

### 7.1 SQLite（默认形态）

数据库就是一个文件（容器内 `/data/bookhub.db`），**但开了 WAL**，同目录还会有 `bookhub.db-wal`、`bookhub.db-shm`；直接 `cp` 单个 `.db` 可能丢掉尚未 checkpoint 的事务。请用在线备份 API。

#### 用 `docker/backup.sh`（仓库自带，执行在宿主机）

```bash
./docker/backup.sh                 # 默认输出到 ./backups/<UTC时间戳>/
./docker/backup.sh /mnt/nas/bookhub-backups   # 或指定输出目录
```

```powershell
# 需要 bash（Git Bash / WSL / Linux 宿主）；脚本本身是 sh，不依赖 PowerShell
bash ./docker/backup.sh
bash ./docker/backup.sh /mnt/nas/bookhub-backups
```

它做四件事：

1. **在运行中的容器里**用 Python `sqlite3.backup()` 做在线一致快照（不停服、不依赖宿主装 sqlite3），并跑 `PRAGMA quick_check` 校验；
2. 把内容卷 `/data` 打成 `tar.gz`（排除 `backups/` 自身与 `-wal`/`-shm`）；
3. 用 `docker compose cp` 把产物取回宿主机，再删掉容器内临时目录；
4. 打印每个产物的 `sha256` 与大小。

产物形态：

```text
backups/20261021T052300Z/
├── bookhub-20261021T052300Z.db          # SQLite 在线快照
└── bookhub-data-20261021T052300Z.tar.gz # /data 内容卷
```

可覆盖的环境变量：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `SERVICE` | `bookhub` | compose 服务名 |
| `DB_NAME` | `bookhub.db` | **必须**与 `DATABASE_URL` 里的库文件名一致 |

前提：宿主机有 `docker` 与 `docker compose` v2 插件，且服务正在运行（脚本会先 `docker compose exec -T bookhub true` 探活）。

#### `docker/restore.sh`：从备份恢复

`backup.sh` 的输出提示会引用 `./docker/restore.sh <备份文件>`，该脚本就在 `docker/` 下：

```bash
./docker/restore.sh backups/20261021T052300Z/bookhub-20261021T052300Z.db          # 只换库
./docker/restore.sh backups/20261021T052300Z/bookhub-data-20261021T052300Z.tar.gz # 整个 /data
```

流程：预检备份文件 → **停服** → 现有库改名成 `bookhub.db.bak-<ts>`（不删，保留回退）→ 覆盖数据 → 起服 → 轮询 `/healthz`。破坏性操作，脚本会要求手工输入 `yes` 确认。

想手工做、或者脚本不适用（比如换机器、卷名不同）时，按下面的流程（**必须停服务**，SQLite 单写入者）：

```bash
docker compose down

# 方式一：只恢复数据库（最常用）
docker run --rm -v bookhub_bookhub-data:/data -v "$PWD/backups/20261021T052300Z:/backup" \
  alpine sh -c 'cp /backup/bookhub-20261021T052300Z.db /data/bookhub.db && rm -f /data/bookhub.db-wal /data/bookhub.db-shm'

# 方式二：恢复整个内容卷（会覆盖 /data 下所有内容）
docker run --rm -v bookhub_bookhub-data:/data -v "$PWD/backups/20261021T052300Z:/backup" \
  alpine sh -c 'rm -rf /data/* && tar xzf /backup/bookhub-data-20261021T052300Z.tar.gz -C /data'

docker compose up -d
curl -fsS http://127.0.0.1:8000/readyz
```

```powershell
docker compose down
docker run --rm -v bookhub_bookhub-data:/data -v "${PWD}\backups\20261021T052300Z:/backup" `
  alpine sh -c 'cp /backup/bookhub-20261021T052300Z.db /data/bookhub.db && rm -f /data/bookhub.db-wal /data/bookhub.db-shm'
docker compose up -d
curl.exe -fsS http://127.0.0.1:8000/readyz
```

要点：

- 卷名是 compose 项目名 + 卷名：`bookhub_bookhub-data`（`compose.yaml` 里 `name: bookhub`）。用 `docker volume ls` 确认。
- **必须删掉 `-wal`/`-shm`**，否则残留 WAL 会让恢复"看起来没生效"。
- 不用 Docker 的本地部署，等价做法是直接覆盖文件（备份文件里应当能看到 `alembic_version`、`books`、`chapters`、`chapter_sections`、`section_versions`、`users`、`audit_logs`、`site_settings`、`chapter_fts*` 这些表）：

```bash
cp backups/20261021T052300Z/bookhub-20261021T052300Z.db data/bookhub.db
rm -f data/bookhub.db-wal data/bookhub.db-shm
```

```powershell
Copy-Item backups\20261021T052300Z\bookhub-20261021T052300Z.db data\bookhub.db -Force
Remove-Item data\bookhub.db-wal, data\bookhub.db-shm -Force -ErrorAction SilentlyContinue
```

- 不想用脚本、也不想停服时，最小的在线备份就是一段 Python（**已实测**）：

```bash
python - <<'PY'
import sqlite3, pathlib, datetime

src = "data/bookhub.db"
dst = pathlib.Path("backups") / f"bookhub-{datetime.datetime.now():%Y%m%d-%H%M%S}.db"
dst.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
    s.backup(d)
print(dst, dst.stat().st_size)
PY
```

```powershell
@'
import sqlite3, pathlib, datetime

src = "data/bookhub.db"
dst = pathlib.Path("backups") / f"bookhub-{datetime.datetime.now():%Y%m%d-%H%M%S}.db"
dst.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
    s.backup(d)
print(dst, dst.stat().st_size)
'@ | python -
```

恢复后校验：`/readyz`、首页 Book 数量、随便点开一章看版本号是否与你备份时一致。

#### 迁移前自动快照（容器自带，防"忘备份就升级"）

当镜像里的 `alembic heads` 与库里的 `alembic current` 不一致时（也就是这次启动会真的改表结构），`docker/entrypoint.sh` 会在迁移**之前**调用 `app/dbbackup.py`：

```text
/data/backups/pre-upgrade-20261021T052300Z.db     # 保留最近 PRE_UPGRADE_BACKUP_KEEP 份，默认 5
```

- 用 `sqlite3.backup()` 做一致性副本，并跑 `PRAGMA quick_check`；WAL 里未提交的事务不会进快照；
- 只在新版本要迁移时触发，普通重启不产生垃圾文件；
- 非 SQLite 后端不做自动快照（打印提示让你自己 `pg_dump`）；
- 快照失败只告警、不阻塞启动——但日志里会出现 `WARN: 迁移前快照失败`。

手工也能用：`python -m app.dbbackup --database-url sqlite:////data/bookhub.db --data-dir /data`。

> 备份频率建议：每日一次 + 每次批量导入前一次。管理端没有"清空/重建"按钮，历史版本又被 `VERSION_RETENTION` 裁剪，所以**备份是唯一能救回被裁剪版本的手段**。

### 7.2 卷、配置与"升级会不会丢东西"

一份 BookHub 部署只有三类持久状态，升级镜像/重建容器不会碰它们：

| 状态 | 位置 | 升级后 | 说明 |
| --- | --- | --- | --- |
| 数据库（Book、章节、版本、账号、Token、Webhook、站点设置） | 命名卷 `bookhub_bookhub-data` → `/data/bookhub.db`（或 Postgres 卷 `bookhub_bookhub-pgdata`） | ✅ 保留 | 结构变更由启动时的 `alembic upgrade head` 迁移；迁移前还会自动快照 |
| 媒体库文件（封面、附件） | 同一卷 `/data/media/...` | ✅ 保留 | 与数据库同卷，`backup.sh` 的 tar 一起打包 |
| 运行配置 `.env`（SECRET_KEY、管理员初始密码、端口、ROOT_PATH…） | 宿主机上的项目目录，`env_file` 挂进容器 | ✅ 保留 | **不在镜像里**，换镜像不影响；换机器/换目录部署时要自己带走 |
| 站点设置（站名、页脚、首页文案） | 数据库 `site_settings` 表 | ✅ 保留 | 管理端修改的值优先于环境变量 |
| 应用代码、模板、静态资源 | 镜像只读层 | ❗随镜像更新 | 本来就该被替换，不是数据 |
| 容器可写层里的任何临时文件 | 容器 | ❌ 丢弃 | 应用不依赖它（`/data` 之外不写业务文件） |

会真正丢数据的只有两种情况，都发生在你显式执行破坏性命令时：

- `docker compose down -v`（或 `docker volume rm bookhub_bookhub-data`）——`-v` 会连命名卷一起删；
- 用空目录覆盖 `/data`，或用旧备份恢复后忘记删 `bookhub.db-wal` / `-shm`。

**Postgres 形态**：数据库在 `bookhub_bookhub-pgdata`，内容仍在 `bookhub_bookhub-data`。升级同样只重启容器，但自动快照只覆盖 SQLite，Postgres 需要在升级前自行 `pg_dump -Fc`（见第 8 节）。

`.env` 要一起备（或放进密钥管理系统）。`SECRET_KEY` 换了不影响数据，但会让所有会话失效；丢了 `API_KEY`/管理员密码属于配置问题，按 README 第 7.1 节处理。

---

## 8. 切换到 Postgres

代码层面已留好口子，但**不是零成本切换**，注意以下事实：

### 8.1 步骤

1. **先装驱动**（顺序很重要，否则容器启动就是 `No module named 'psycopg'`）：在 `requirements.txt` 里加一行，然后重新构建镜像——builder 阶段才会把它打成 wheel：

```text
psycopg[binary]>=3.2
```

2. 用 compose 的 `postgres` profile 起数据库（`docker-compose.yml` 里已定义 `db` 服务，只有 `--profile postgres` 时才创建）：

```bash
docker compose --profile postgres up -d --build
```

3. 改 `.env`：

```dotenv
DATABASE_URL=postgresql+psycopg://bookhub:<强密码>@db:5432/bookhub
POSTGRES_DB=bookhub
POSTGRES_USER=bookhub
POSTGRES_PASSWORD=<强密码>
```

   （`docker-compose.yml` 里那段被注释掉的 `depends_on` 只在切 Postgres 时才需要打开。）

4. 迁移在 entrypoint 里自动执行；宿主上手工等价命令是 `alembic upgrade head`（`app/db.py` 只在 `sqlite` 前缀时加 PRAGMA，Postgres 走默认引擎参数）。
5. 迁数据：从旧库 `/api/v1/books/{book}/export?format=zip` 导出，再在管理端重新上传；直接拷 `.db` 文件是不行的。OpenSpec 设计里提到的 `scripts/export_import.py` **尚未生成**。
6. 逐个验证 `/readyz`、`/api/v1/books`、`/search?q=部署`。

### 8.2 限制（`app/services/search.py` 里有明确分支）

| 差异 | 影响 |
| --- | --- |
| 没有 FTS5 | `_supports_fts()` 只对 `sqlite` 方言返回真，`index_chapter` / `remove_from_index` / `reindex_all` 直接跳过 |
| 检索退化为 `ILIKE` | 所有查询（含多字词）走 `c.title LIKE %q% OR c.content_raw LIKE %q%`，**全表扫描 + 按 `updated_at` 倒序**，没有相关度排序；数据量大时明显变慢 |
| 部分唯一索引 | `uq_books_slug_active` / `uq_chapters_book_slug_active` 用 `postgresql_where` 定义了，行为与 SQLite 一致（仅 `deleted_at IS NULL` 时唯一） |
| `/readyz` 写探针 | Postgres 上同样会建 `_readyz_probe` 表，需要写权限 |
| 备份方式 | 必须换成 `pg_dump -Fc bookhub > bookhub.dump`；恢复 `pg_restore -d bookhub bookhub.dump`。内容卷（若有）另行打包 |

结论：**除非确实需要多副本写或数据量很大，否则留在 SQLite**。切 Postgres 的收益主要在并发写，而本系统写操作只来自少数管理员。

---

## 9. 反向代理子路径（`ROOT_PATH`）

`ROOT_PATH=/kb` 会同时作用于两处，缺一不可：

1. **应用层**：`/api/v1/site` 里的 `api.docs`、payload 里的 `url`/`api_url`、会话 cookie 的 `path`、以及所有手写 `f"{root_path}/..."` 的跳转与链接。
2. **uvicorn 层**：`docker/entrypoint.sh` 在 `ROOT_PATH` 非空时会追加 `--root-path "${ROOT_PATH}"`。Starlette 的 `url_for()`（`/static/*`、首页、Book 链接）依据 ASGI scope 里的 `root_path` 生成地址，只有补上这个参数，这些链接才会带前缀。

实测（本地 `ROOT_PATH=/kb` + `uvicorn --root-path /kb` 启动，反代剥掉前缀后请求 `/`）：

```html
<link rel="stylesheet" href="http://host/kb/static/style.css">  <!-- 有前缀 -->
<a class="brand" href="http://host/kb/">                        <!-- 有前缀 -->
<a href="/kb/admin/login">                                      <!-- 有前缀 -->
```

注意 **必须由反代剥掉前缀**（`proxy_pass http://127.0.0.1:8000/;` 末尾带斜杠）：uvicorn 的 `--root-path` 语义是"外部路径比应用路径多这一段"，它会把收到的 prefix-free 路径补上 root_path 再交给应用；若反代保留前缀转发，实际路径会变成 `/kb/kb/...`，得到 404（已验证）。

推荐配置（剥前缀 + 补头）：

```nginx
location /kb/ {
    proxy_pass         http://127.0.0.1:8000/;      # 末尾斜杠 = 剥掉 /kb 前缀
    proxy_http_version 1.1;
    proxy_set_header   Host              $host;     # 必给：url_for 生成的是绝对 URL
    proxy_set_header   X-Real-IP         $remote_addr;
    proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
    client_max_body_size 8m;                        # 要大于 MAX_UPLOAD_BYTES(5 MiB)
    proxy_read_timeout 120s;
}
```

部署完按这三条自检：`curl -I http://host/kb/` 返回 200；页面里 CSS 地址带 `/kb/`；`:8000/healthz`（容器内直连）仍然 200。若只想用子域名（`docs.example.com`），把 `ROOT_PATH` 留空、`proxy_pass http://127.0.0.1:8000;` 即可，不需要 `--root-path`。

通用要点（与具体方案无关）：

- `X-Forwarded-For` / `X-Real-IP` 是应用取客户端 IP 的依据（`app/middleware.py:client_ip`，取 XFF 第一段）。**API 限流与登录限流都按这个 IP 计数**，不设就会把所有人算成代理 IP。
- 但应用**只在可信代理下才采信这两个头**：必须把反代地址/网段写进 `TRUSTED_PROXIES`（例如反代在 `10.0.0.0/8` 内就写 `TRUSTED_PROXIES=10.0.0.0/8`），否则一律用直连地址——这是为了防止客户端自己伪造 `X-Forwarded-For` 绕过登录失败限流。留空即"谁都不信"，直连公网部署应保持留空。
- 模板里的 `url_for` 生成的是**绝对 URL**（含 `http://host/kb/...`），所以 `Host` 必须原样传，且对外协议要与 `X-Forwarded-Proto` 一致（entrypoint 已开 `--proxy-headers`）。
- `FORWARDED_ALLOW_IPS` 决定 uvicorn 信任哪些来源的 `X-Forwarded-*`，默认 `*`；它和上面的 `TRUSTED_PROXIES` 是两层：前者给 uvicorn 改 `request.client`，后者决定应用是否再读原始转发头。两者都收紧到反代网段最稳妥。
- 走 HTTPS 时记得 `COOKIE_SECURE=true`。
- `client_max_body_size` 要大于 `MAX_UPLOAD_BYTES`，否则大文件在 nginx 层就被 413（而且没有应用的错误体）。

---

## 10. 资源与并发建议

| 项 | 建议 | 原因 |
| --- | --- | --- |
| uvicorn worker（`WEB_CONCURRENCY`） | **1** | SQLite 单写入者。写事务短但仍是全局串行；多 worker 只会把锁竞争挪到数据库层，还让进程内限流和登录失败计数各自为政。entrypoint 在 `WEB_CONCURRENCY>1` 且仍是 SQLite 时会打 WARN |
| 内存/CPU | 1 vCPU + 512 MiB 起步 | 读路径不渲染（`content_rendered` 落库缓存），主要开销是模板渲染与 JSON |
| 磁盘 | 库体积 ≈ 正文原文字节数 × (1 + 版本保留数) | 每版都存全文（`chapter_versions.content_raw`），`content_rendered` 只存当前版本；整个 `/data` 卷还要留出 `backups/` 中转空间 |
| 限流 | 进程内滑动窗口 | `RateLimiter` 存在 `app.state.limiter`，多副本时各算各的 |
| 静态文件 | 由应用自身提供 | 没有 CDN 前置需求；如需 nginx 直出 `/static/`，注意第 9 节的前缀问题 |
| 容器资源 | 镜像基于 `python:3.12-slim`，多阶段构建，运行镜像里**没有编译器**；以 uid 10001 非 root 运行 | builder 默认也不装 `build-essential`：本项目的依赖在 amd64/arm64 上都有预编译 wheel，装编译器只会拖慢构建。真遇到没有 wheel 的依赖时用 `docker build --build-arg WITH_BUILD_TOOLS=1 ...` 打开 |

关于多副本：`WEB_CONCURRENCY` 已被 entrypoint 透传给 `--workers`，所以技术上可以调大；但 SQLite 下这只会放大 `database is locked` 风险，而且限流/登录计数、`/data` 卷都必须共享或外置。真要横向扩展，属于「切 Postgres + 外部限流 + 共享存储」的组合工程，不在本期范围。

---

## 11. 排障速查

| 现象 | 原因与处理 |
| --- | --- |
| 启动即退出，日志有 `缺少必需配置 SECRET_KEY` | 补 `SECRET_KEY`（≥16 字符） |
| 启动即退出，提示 SECRET_KEY 是占位值 | `.env` 里还是 `.env.example` 的 `please-change-me-...`，换成本机生成的随机串 |
| 启动即退出，提示 `DATA_DIR=... 不可写` | 命名卷没挂上，或 bind mount 属主不是 10001:10001（`chown -R 10001:10001 <宿主目录>`） |
| `docker compose` 报 `.env` 相关错误 | 没 `cp .env.example .env`；这个文件是必需的 |
| 改了 `PORT` 后宿主访问被拒 | `PORT` 同时决定容器内监听端口，而 `ports` 右侧写死 8000 → 错位。改 `ports` 左侧，别改 `PORT`（见 2.6） |
| entrypoint 日志出现 `WARN: app.bootstrap 执行失败` | 容器仍在跑（有兜底），但要查上方 traceback：多为初始管理员密码不符合策略 |
| 启动即退出，`配置项 LOG_LEVEL 取值非法` | `LOG_LEVEL` 只接受五个大写枚举 |
| 页面能开，接口 500，日志 `no such table` | 没跑迁移 → `alembic upgrade head` |
| 登录成功但立刻跳回登录页 | `COOKIE_SECURE=true` 却在 HTTP 下访问；或子路径下 cookie `path` 与访问路径不一致 |
| 所有 IP 都被限流 | 反代没传 `X-Forwarded-For`/`X-Real-IP`，全站共用代理 IP；若已传仍共用，是反代地址没写进 `TRUSTED_PROXIES` |
| 每个 IP 都算成 127.0.0.1 / 登录失败次数怎么都不涨 | 直连部署下 `TRUSTED_PROXIES` 留空是对的（不采信转发头）；有反代时把反代网段加进去 |
| 管理 API 返回 403「admin 作用域与 Book 范围不能共存」 | 该 Token 是历史遗留的组合，吊销后重签；限定 Book 请只用 `read` / `write` |
| 上传被拒，提示「文件超过上限」 | 文件超 `MAX_UPLOAD_BYTES`（管理端表单渲染为 400，错误码 `file_too_large`）。若在 nginx 层就被 413 拦住，是 `client_max_body_size` 太小 |
| 上传被拒，提示「正文超过上限」 | 正文字符数超 `MAX_CONTENT_CHARS`（错误码 `content_too_long`） |
| 上传直接返回 413 `payload_too_large` | 请求体超过 `MAX_REQUEST_BYTES`（默认约 251 MiB）；批量很大时调大它，并同步调大反代的 `client_max_body_size` |
| 登录时提示「该来源登录尝试过于频繁」 | 同一 IP 在 `LOGIN_FAIL_WINDOW` 内的登录尝试总数超限（默认 `max(10, LOGIN_FAIL_LIMIT×6)`）；等窗口过去或换网络 |
| 搜索中文单字结果很杂 | 单字查询退化为 `LIKE`，见 [search.md](search.md) |
| `/readyz` 一直 503 | 库不可写：磁盘满、只读挂载、权限错误 |
| 时间显示比本地慢 8 小时 | 全站按 UTC 存储与展示，属预期 |
