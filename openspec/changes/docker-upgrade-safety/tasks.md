# Tasks

## 1. 迁移前自动快照

- [x] 1.1 新增 `app/dbbackup.py`：SQLite URL 解析、`backup()` 一致性快照 + `quick_check`、按数量轮转、缺文件返回 `None`
- [x] 1.2 `docker/entrypoint.sh` 在 `alembic upgrade head` 前比较 `current` / `heads`，落后时调用快照并打印路径；非 SQLite 只提示 `pg_dump`
- [x] 1.3 快照失败只 WARN、不阻塞启动；`PRE_UPGRADE_BACKUP_KEEP` 控制保留份数

## 2. 可观测性

- [x] 2.1 `/healthz` 与 `/readyz` 增加 `schema`（`alembic_version`），数据库不可达时降级 `null`
- [x] 2.2 确认存活探针不因数据库故障改变状态码

## 3. 升级与回滚脚本

- [x] 3.1 新增 `scripts/upgrade.sh`：强制在线备份（可 `SKIP_BACKUP=1`）→ 当前镜像打 `bookhub:pre-upgrade-<UTC>` → build → up -d → 等 healthy → 打印 `version`/`schema`
- [x] 3.2 失败分支打印「回滚镜像 / 恢复备份 / 看日志」三条命令
- [x] 3.3 `docker-compose.yml` 顶部写明持久化契约与 `down -v` 风险；`.env.example` 增加 `PRE_UPGRADE_BACKUP_KEEP`、`BACKUP_DIR`

## 4. 测试

- [x] 4.1 `tests/test_dbbackup.py`：URL 解析（sqlite 绝对/相对、postgres、空值）、快照含已提交数据、WAL 未提交事务不进快照、轮转保留 N 份、库文件缺失返回 `None`
- [x] 4.2 `tests/test_deploy.py`：`/healthz`、`/readyz` 返回 `schema`；数据库不可用时 `schema` 为 `null` 且 `/healthz` 仍 200
- [x] 4.3 全量 `pytest` 与 `ruff` 通过
- [x] 4.4 容器内实测：`python -m app.dbbackup` 在有数据的卷上产出快照并通过 `quick_check`

## 5. 文档与规格

- [x] 5.1 `docs/deploy.md`：首次启动流程图加 2.5 步；升级流程改为推荐 `scripts/upgrade.sh` 并说明自动快照；探针表加 `schema`；7.1 增加快照小节；7.2 改为「升级会不会丢东西」表格 + `down -v` 警告
- [x] 5.2 `openspec validate docker-upgrade-safety --strict` 通过

## Workflow follow-up

- 归档本变更，使 `service-deployment` 主规格包含"迁移前自动快照 / 库结构可观测 / 一键升级"三条约束。
- Postgres 自动备份如确有需要，另起变更。
