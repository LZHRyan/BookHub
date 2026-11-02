# Design

## Context

- 现状：`docker-compose.yml` 用命名卷 `bookhub-data:/data`，镜像以 uid 10001 运行；`docker/entrypoint.sh` 在启动时依次做「校验 SECRET_KEY → 准备 /data → alembic upgrade head → bootstrap → uvicorn」。
- 备份能力已有 `docker/backup.sh`（sqlite3 backup API + /data 打包）与 `docker/restore.sh`，但**都靠人记得先跑**。
- 迁移历史里已经出现过破坏性变更（如 `0003` 删 `books.sort_order`），所以"启动即迁移"是有真实回退需求的。
- 探针 `/healthz` 只返回 `version`，无法区分"镜像新、库结构旧"。

## Goals / Non-Goals

**Goals:**

- 升级（换镜像 + 重建容器）后，数据库、媒体库、账号、站点设置、Token/Webhook 配置全部原样可用。
- 迁移前一定有一份**启动瞬间**的可回退副本，不依赖运维记性。
- 升级后一条命令就能确认"版本 + 库结构"两件事。
- 回滚路径明确：镜像标签留档 + 备份文件。

**Non-Goals:**

- 不做自动 `pg_dump`（Postgres 部署只提示，避免在容器里塞 pg 客户端）。
- 不做异地备份、备份加密、对象存储上传。
- 不做"零停机蓝绿/滚动升级"（单机 compose 场景）。
- 不改变服务定义、卷名、端口与既有迁移。

## Decisions

### D1. 快照放在 entrypoint，而不是应用启动钩子

`_startup_tasks` 在 uvicorn 起来之后才跑，那时迁移已经完成（entrypoint 里先迁移）；把快照放应用层等于"迁移后才备份"。放 entrypoint 还能复用 `alembic` 命令行判断是否需要迁移。

- 备选被否：单独一个 sidecar 容器做备份 → 需要额外编排与共享卷权限，单机部署收益低。
- 备选被否：在迁移脚本里调用 → 迁移可能由宿主手工执行，覆盖不全。

### D2. 只在"库结构落后于镜像"时快照

```sh
CUR_REV="$(alembic current …)"   # 例如 0012_x
HEAD_REV="$(alembic heads …)"    # 例如 0013_webhooks
[ "$CUR_REV" != "$HEAD_REV" ] && snapshot
```

这样普通重启、改 `.env` 后重建容器都不会产生垃圾文件；首次启动（空库）时 `alembic current` 为空、库文件还不在，快照函数返回 `None` 直接跳过。

- 备选被否：每次启动都快照 → 容器可能一天重启多次，`/data/backups` 会被无意义副本塞满。

### D3. 快照用 sqlite3 backup API，独立于在线备份脚本

`app/dbbackup.py` 复用与 `docker/backup.sh` 相同的机制（`source.backup(target)` + `PRAGMA quick_check`），但不打包 `/data`：迁移只需要数据库本身，媒体文件在迁移中不会被改。

- WAL 情况下 backup() 只读已提交事务，测试 `test_snapshot_excludes_uncommitted_wal_rows` 固定了这一点。
- 失败语义：模块返回非 0 → entrypoint 打 WARN 继续启动。理由：备份失败（如磁盘满）不应该让服务起不来，但要留下显眼日志。

### D4. 探针暴露 `schema`

`/healthz` 与 `/readyz` 都加 `schema: alembic_version`，读取失败降级 `null`。升级验证从"看日志有没有 ERROR"变成"curl 一下比对两个字段"。

- 频率：Docker HEALTHCHECK 每 30s 一次，多一条 `SELECT version_num FROM alembic_version` 可忽略。
- `/healthz` 保持"存活"语义：数据库挂了仍然 200（只是 `schema` 为 null），否则数据库抖动会引发重启风暴。

### D5. 一键脚本：备份 → 镜像留档 → 构建 → 重建 → 验证

`scripts/upgrade.sh` 的取舍：

- **默认强制备份**，`SKIP_BACKUP=1` 才能跳（用于"刚手工备份过"的场景）；
- 重建前把当前镜像打成 `bookhub:pre-upgrade-<UTC>`，比依赖版本号更容易回滚（本地 `build` 出来的镜像通常没有稳定 tag）；
- 就绪判断用容器自带 HEALTHCHECK（`docker inspect .State.Health.Status`），不依赖宿主机装 curl；镜像没有 healthcheck 时才退化为 `running`；
- 失败时打印三条命令：回滚镜像、恢复备份、看日志。

## Risks / Trade-offs

- **快照占用卷空间**：单库几十 MB × 5 份，可接受；`PRE_UPGRADE_BACKUP_KEEP=0` 可关闭轮转保留。
- **迁移前多一次全库复制**：SQLite 备份是页级复制，100MB 级库在秒级完成；大库（GB）会拖慢启动，可通过把 `PRE_UPGRADE_BACKUP_KEEP` 调小或改 bind mount 到大盘缓解。
- **探针多一次查询**：可忽略，但只读副本上 `alembic_version` 存在时也能读，不影响 503 语义。
- **脚本依赖 docker inspect 模板**：仅用 `State.Health.Status` / `State.Status` 两个稳定字段。
- **Postgres 用户没有自动兜底**：只能靠文档与脚本提示 `pg_dump`，这是有意不做（不往镜像里塞 pg 客户端）。

## Migration Plan

1. 部署新镜像：entrypoint 新增快照步骤，**不影响现有数据**；首次启动因 `current == heads` 直接跳过快照。
2. 下一次真正带迁移的升级会自动产生 `pre-upgrade-*.db`，无需改 `.env`。
3. 回滚：`BOOKHUB_TAG=pre-upgrade-<ts> docker compose up -d`（镜像）或 `./docker/restore.sh <备份>`（数据）。

## Open Questions

无。Postgres 自动备份如确有需要，另起变更（涉及镜像内引入 pg 客户端或外部 sidecar）。
