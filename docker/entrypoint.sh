#!/bin/sh
# BookHub 容器启动入口：校验配置 → 准备 /data → 迁移 → 初始管理员 → 前台起 uvicorn。
# 原则：能确定的错误尽早失败（让容器直接崩掉），可容忍的问题只告警（让服务尽量起来）。
set -eu

# DATA_DIR 必须 export：应用（app/config.py）按环境变量读它；只赋 shell 变量会让
# 应用回退到默认的 ./data，在只读的 /app 下直接 PermissionError。
export DATA_DIR="${DATA_DIR:-/data}"
PORT="${PORT:-8000}"
WEB_CONCURRENCY="${WEB_CONCURRENCY:-1}"

log() {
    printf '%s [entrypoint] %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"
}

die() {
    printf '%s [entrypoint] ERROR: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >&2
    exit 1
}

# ---------------------------------------------------------------- 1. 必需配置
# SECRET_KEY 是唯一会阻止启动的配置（会话签名依赖它，缺失或占位值等于没有安全边界）。
if [ -z "${SECRET_KEY:-}" ]; then
    die "缺少必需环境变量 SECRET_KEY。
  生成一个随机值后写入 .env：SECRET_KEY=\$(python -c \"import secrets;print(secrets.token_urlsafe(48))\")
  或直接执行：python -c \"import secrets;print(secrets.token_urlsafe(48))\" >> .env"
fi

case "${SECRET_KEY}" in
    please-change-me*|changeme*|CHANGEME*|change-me*|your-secret*)
        die "SECRET_KEY 仍是 .env.example 里的占位值，请替换为随机字符串。
  执行：python -c \"import secrets;print(secrets.token_urlsafe(48))\"
  把输出填进 .env 的 SECRET_KEY 后重新启动。"
        ;;
esac

if [ "${#SECRET_KEY}" -lt 16 ]; then
    die "SECRET_KEY 过短（${#SECRET_KEY} 个字符，至少 16 个）。请使用 secrets.token_urlsafe(48) 生成的值。"
fi

# ---------------------------------------------------------------- 2. 数据目录
# 挂载的卷（含 bind mount）如果属主不是 bookhub(10001)，这里会直接暴露问题，而不是等写库时报错。
mkdir -p "${DATA_DIR}" 2>/dev/null || die "无法创建 DATA_DIR=${DATA_DIR}，请检查卷挂载与权限。"
_probe="${DATA_DIR}/.bookhub-write-test.$$"
( : > "${_probe}" ) 2>/dev/null || die "DATA_DIR=${DATA_DIR} 不可写。
  命名卷：确认 docker-compose.yml 的 bookhub-data 已挂到 ${DATA_DIR}。
  bind mount：在宿主执行 chown -R 10001:10001 <宿主目录>（容器内用户 uid/gid=10001）。"
rm -f "${_probe}"

case "${DATA_DIR}" in
    /) die "DATA_DIR 不能是根目录 /，请指向独立的数据目录（默认 /data）。" ;;
esac

# 备份脚本把中间产物放在 <DATA_DIR>/backups，这里先建好，省得首次备份因权限失败。
mkdir -p "${DATA_DIR}/backups" 2>/dev/null || log "WARN: 无法创建 ${DATA_DIR}/backups（备份脚本将无法写入）"

# 没显式给 DATABASE_URL 时把它指到数据卷里：这样 `docker run -v data:/data <image>`
# 这种不经 compose 的启动也能用，且不会因为相对路径落到只读的 /app 下而报错。
export DATABASE_URL="${DATABASE_URL:-sqlite:///${DATA_DIR}/bookhub.db}"

log "config: DATA_DIR=${DATA_DIR} DATABASE_URL=${DATABASE_URL} PORT=${PORT} WEB_CONCURRENCY=${WEB_CONCURRENCY}"

# SQLite 单写入者模型：多 worker 会放大写锁竞争，提醒而不是直接拒绝（用户可能已切 Postgres）。
if [ "${WEB_CONCURRENCY}" -gt 1 ] 2>/dev/null; then
    case "${DATABASE_URL:-sqlite}" in
        sqlite*) log "WARN: WEB_CONCURRENCY=${WEB_CONCURRENCY} 但数据库仍是 SQLite；写并发下易出现 database is locked，建议保持 1 或切换 Postgres。" ;;
    esac
fi

# ---------------------------------------------------------------- 2.5 迁移前快照
# 启动即迁移是设计选择，但迁移前必须留一份可回退的一致副本：只在「库结构落后于镜像」
# 时做，避免每次普通重启都产生垃圾文件；SQLite 以外的后端不做自动快照。
CUR_REV="$(alembic current 2>/dev/null | sed -n 's/^\([0-9A-Za-z_]\{1,\}\).*/\1/p' | tail -n 1 || true)"
HEAD_REV="$(alembic heads 2>/dev/null | sed -n 's/^\([0-9A-Za-z_]\{1,\}\).*/\1/p' | head -n 1 || true)"
if [ -n "${HEAD_REV}" ] && [ "${CUR_REV}" != "${HEAD_REV}" ]; then
    case "${DATABASE_URL:-sqlite}" in
        sqlite*)
            log "检测到待执行迁移（${CUR_REV:-空库} -> ${HEAD_REV}），先做迁移前快照 …"
            if python -m app.dbbackup \
                --database-url "${DATABASE_URL:-sqlite:////data/bookhub.db}" \
                --data-dir "${DATA_DIR}" \
                --keep "${PRE_UPGRADE_BACKUP_KEEP:-5}"; then
                log "迁移前快照步骤结束（上一行为 snapshot: 或 skip:；目录 ${DATA_DIR}/backups，保留 ${PRE_UPGRADE_BACKUP_KEEP:-5} 份）"
            else
                log "WARN: 迁移前快照失败，继续启动；如需可回退请先手工执行 ./docker/backup.sh"
            fi
            ;;
        *)
            log "WARN: 非 SQLite 数据库，本次不做自动快照；升级前请自行 pg_dump -Fc 备份"
            ;;
    esac
else
    log "库结构已是最新（${HEAD_REV:-unknown}），跳过迁移前快照"
fi

# ---------------------------------------------------------------- 3. 数据库迁移
# 迁移失败必须退出：带着不匹配的表结构启动只会产生更难排查的运行时错误。
log "alembic upgrade head …"
if ! alembic upgrade head; then
    die "alembic upgrade head 失败。请检查 DATABASE_URL 指向的库是否可写、迁移脚本是否完整。"
fi
log "数据库迁移完成"

# ---------------------------------------------------------------- 4. 初始管理员
# 占位值告警：.env.example 里密码是 <CHANGE_ME_...>，忘了改就会创建出一个弱口令管理员。
case "${BOOKHUB_INITIAL_ADMIN_PASSWORD:-}" in
    *CHANGE_ME*|*change_me*)
        log "WARN: BOOKHUB_INITIAL_ADMIN_PASSWORD 仍是占位值（含 CHANGE_ME），请立刻修改 .env 并重建管理员密码。" ;;
esac

# app.bootstrap 负责幂等创建 BOOKHUB_INITIAL_ADMIN_USER/PASSWORD 指定的管理员。
# 说明：该模块尚未实现时不能让容器起不来（已有实例续跑不应因它崩溃），故用 `|| true` 语义兜底；
#       同时 app.main 的 lifespan 启动钩子也会再尝试一次 ensure_initial_admin。
if python -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('app.bootstrap') else 1)" 2>/dev/null; then
    log "初始化管理员（幂等）…"
    python -m app.bootstrap || log "WARN: app.bootstrap 执行失败，已忽略并继续启动（详见上方 traceback）"
else
    log "WARN: 未找到 app.bootstrap 模块，跳过独立的初始管理员步骤（启动后由应用 lifespan 兜底创建）"
fi

# ---------------------------------------------------------------- 5. 启动服务
# ROOT_PATH 必须同时交给 uvicorn：Starlette 的 url_for 依据 ASGI scope 里的 root_path
# 生成带前缀的链接，只设应用层 ROOT_PATH 会让 /static、站内链接丢掉子路径。
ROOT_PATH="${ROOT_PATH:-}"
set -- uvicorn app.main:create_app \
    --factory \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --proxy-headers \
    --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" \
    --workers "${WEB_CONCURRENCY}"
if [ -n "${ROOT_PATH}" ]; then
    set -- "$@" --root-path "${ROOT_PATH}"
    log "子路径部署：ROOT_PATH=${ROOT_PATH}（反代需同时剥掉该前缀，nginx 示例见 docs/deploy.md）"
fi
log "启动 uvicorn：0.0.0.0:${PORT} workers=${WEB_CONCURRENCY} root_path=${ROOT_PATH:-/} forwarded_allow_ips=${FORWARDED_ALLOW_IPS:-*}"
exec "$@"
