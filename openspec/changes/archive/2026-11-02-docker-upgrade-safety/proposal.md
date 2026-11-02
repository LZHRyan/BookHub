# Proposal

## Why

Docker 部署已经是默认形态，数据放在命名卷、配置放在宿主机 `.env`，但"升级不丢数据"目前只靠文档约定：容器启动即执行 `alembic upgrade head`，迁移前**没有任何自动兜底**。只要运维忘了先跑 `./docker/backup.sh`，一次有破坏性的迁移（删列、改类型）就没有可回退的副本；同样，升级后也没有一个地方能直接确认"镜像换了、迁移也真的跑完了"。

这次把"升级不丢数据/配置"从文档承诺变成启动路径上的硬保障。

## What Changes

- **迁移前自动快照**：entrypoint 发现 `alembic current ≠ heads` 时，先用 `app/dbbackup.py` 做一份 SQLite 一致性快照到 `$DATA_DIR/backups/pre-upgrade-<UTC>.db`，再执行迁移；按 `PRE_UPGRADE_BACKUP_KEEP`（默认 5）轮转。普通重启（无待执行迁移）不产生文件。
- **库结构可观测**：`/healthz` 与 `/readyz` 增加 `schema` 字段（`alembic_version`），与镜像里的 `version` 并排展示；数据库不可达时该字段为 `null`，不影响存活探针。
- **一键升级脚本**：新增 `scripts/upgrade.sh`，顺序固定为「在线备份 → 给当前镜像打 `bookhub:pre-upgrade-<UTC>` 保留退路 → 构建 → 重建容器 → 等 healthy → 打印 `version`/`schema`」，失败时直接打印回滚命令。
- **持久化契约显式化**：`docker-compose.yml` 顶部写明哪些状态在卷里、哪些在 `.env` 里、只有 `down -v` 才会删卷；`docs/deploy.md` 增加"升级会不会丢东西"表格与自动快照说明。
- `.env.example` 增加 `PRE_UPGRADE_BACKUP_KEEP`、`BACKUP_DIR`。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `service-deployment`: 升级路径增加"迁移前必须自动快照""库结构版本必须可观测""升级必须有一键脚本且默认先备份"三条约束；原有"数据持久化在挂载卷上""升级保持既有数据可用"不变。

## Impact

- **代码**：新增 `app/dbbackup.py`（纯标准库 + SQLAlchemy URL 解析）；`app/main.py` 两个探针增加 `schema`；`docker/entrypoint.sh` 增加迁移前快照步骤。
- **脚本/编排**：新增 `scripts/upgrade.sh`；`docker-compose.yml` 只加注释（不改变服务定义、卷名与端口）。
- **配置**：`.env.example` 新增两个非必需变量，均有默认值，旧 `.env` 不需要改。
- **测试**：新增 `tests/test_dbbackup.py`（URL 解析、快照内容、WAL 未提交隔离、轮转、缺文件降级）；`tests/test_deploy.py` 断言探针 `schema`。
- **兼容性**：非 SQLite（Postgres）部署不做自动快照，只打印提示；探针新增字段是增量，旧客户端不受影响。
- **非目标**：不做自动 `pg_dump`、不做跨机器配置同步、不做数据卷自动迁移到宿主目录。
