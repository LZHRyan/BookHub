#!/usr/bin/env bash
# BookHub 恢复（在宿主机执行，需要 docker + docker compose v2，健康检查需要 curl）
#
#   ./docker/restore.sh backups/20240101T000000Z/bookhub-20240101T000000Z.db
#   ./docker/restore.sh backups/20240101T000000Z/bookhub-data-20240101T000000Z.tar.gz
#
# 流程：预检备份文件 → 停服 → 现有库改名成 bookhub.db.bak-<ts>（不删）→ 覆盖数据
#      → 启动 → 轮询 /healthz
#
# 破坏性操作，必须手工输入 yes 确认。旧库始终留档，确认数据无误后再自行清理。
set -euo pipefail

SERVICE="${SERVICE:-bookhub}"
HOST_PORT="${PORT:-8000}"
# 健康检查最长等待秒数（大库恢复 + 迁移可能更慢，可调）
HEALTH_WAIT="${HEALTH_WAIT_SECONDS:-120}"

log() { printf '[restore] %s\n' "$*"; }
die() { printf '[restore] ERROR: %s\n' "$*" >&2; exit 1; }

BACKUP="${1:-}"
[ -n "$BACKUP" ] || die "用法：./docker/restore.sh <备份文件 .db|.tar.gz>"
[ -f "$BACKUP" ] || die "备份文件不存在：$BACKUP"

TS="$(date -u '+%Y%m%dT%H%M%SZ')"

command -v docker >/dev/null 2>&1 || die "未找到 docker 命令。"
docker compose version >/dev/null 2>&1 || die "未找到 docker compose（需要 v2 插件）。"

# 宿主机映射端口 / 健康等待时长：环境变量优先，其次读 .env（与 docker-compose.yml 口径一致）。
if [ -f .env ]; then
    _port="$(sed -n 's/^[[:space:]]*PORT[[:space:]]*=[[:space:]]*\([0-9][0-9]*\).*/\1/p' .env | tail -n 1)"
    if [ -n "$_port" ]; then
        HOST_PORT="$_port"
    fi
    _wait="$(sed -n 's/^[[:space:]]*HEALTH_WAIT_SECONDS[[:space:]]*=[[:space:]]*\([0-9][0-9]*\).*/\1/p' .env | tail -n 1)"
    if [ -n "$_wait" ]; then
        HEALTH_WAIT="$_wait"
    fi
fi
HEALTH_URL="http://127.0.0.1:${HOST_PORT}/healthz"

case "$BACKUP" in
    *.db)          MODE=db  ;;
    *.tar.gz|*.tgz) MODE=tar ;;
    *) die "无法识别的备份文件（只支持 .db 与 .tar.gz）：$BACKUP" ;;
esac

# ---------------------------------------------------------------- 预检（在停服之前做）
if [ "$MODE" = "db" ]; then
    # SQLite 文件头是 15 字节的 "SQLite format 3"
    _magic="$(head -c 15 "$BACKUP")" || die "无法读取备份文件：$BACKUP"
    [ "$_magic" = "SQLite format 3" ] \
        || die "$BACKUP 不是合法的 SQLite 数据库文件（文件头不匹配）。"
    log "预检通过：SQLite 数据库文件"
else
    # 用一次性容器试着读目录，能列出来才敢覆盖 /data
    if ! docker compose run --rm -T --no-deps --entrypoint sh "$SERVICE" -c 'tar -tzf - > /dev/null' <"$BACKUP"; then
        die "$BACKUP 不是可解压的 tar.gz（预检失败，未做任何改动）。"
    fi
    log "预检通过：tar.gz 可解压"
fi

# ---------------------------------------------------------------- 确认
printf '\n'
log "即将执行（不可撤销，但旧库会留档）："
printf '  1) 停止容器           %s\n' "$SERVICE"
printf '  2) 现有库改名         /data/bookhub.db -> /data/bookhub.db.bak-%s\n' "$TS"
printf '  3) 覆盖数据来源       %s\n' "$BACKUP"
printf '  4) 启动并轮询         %s\n' "$HEALTH_URL"
printf '\n确认请输入 yes（其他任何输入都会取消）：'
answer=""
read -r answer || true
[ "$answer" = "yes" ] || die "已取消，未做任何改动。"

# ---------------------------------------------------------------- 停服
log "停止服务 ${SERVICE} …"
docker compose stop "$SERVICE" || die "停止服务失败。"

# ---------------------------------------------------------------- 旧库留档
# 迁移没做或数据库是 Postgres 时，/data 里可能根本没有 bookhub.db，用 if 兜住。
if ! docker compose run --rm -T --no-deps --entrypoint sh "$SERVICE" -s "$TS" <<'EOS'
set -eu
ts="$1"
cd /data
for f in bookhub.db bookhub.db-wal bookhub.db-shm; do
    if [ -e "$f" ]; then
        mv "$f" "$f.bak-$ts"
        echo "  renamed $f -> $f.bak-$ts"
    fi
done
EOS
then
    log "WARN: 旧库留档步骤失败，已中止恢复。请检查 /data 权限后重试。"
    docker compose start "$SERVICE" || true
    die "恢复中止，服务已尝试恢复启动。"
fi

# ---------------------------------------------------------------- 覆盖数据
# 用 stdin 把备份喂给容器，避免宿主/容器路径差异（Windows 下 docker cp 的路径转换坑）。
log "写入数据 …"
if [ "$MODE" = "db" ]; then
    docker compose run --rm -T --no-deps --entrypoint sh "$SERVICE" -c 'cat > /data/bookhub.db' <"$BACKUP" \
        || die "写入 /data/bookhub.db 失败。旧库仍以 bookhub.db.bak-${TS} 保留。"
else
    docker compose run --rm -T --no-deps --entrypoint sh "$SERVICE" -c 'tar -xzf - -C /data' <"$BACKUP" \
        || die "解包到 /data 失败。旧库仍以 bookhub.db.bak-${TS} 保留。"
fi

# ---------------------------------------------------------------- 启动
log "启动服务 ${SERVICE} …"
docker compose start "$SERVICE" || die "启动失败。查看日志：docker compose logs --tail 100 ${SERVICE}"

# ---------------------------------------------------------------- 健康检查
if command -v curl >/dev/null 2>&1; then
    log "等待 ${HEALTH_URL} 返回 200（最长 ${HEALTH_WAIT}s）…"
    tries=$((HEALTH_WAIT / 2))
    [ "$tries" -ge 1 ] || tries=1
    i=0
    while [ "$i" -lt "$tries" ]; do
        if curl -fsS -o /dev/null --max-time 3 "$HEALTH_URL" 2>/dev/null; then
            log "健康检查通过：${HEALTH_URL}"
            break
        fi
        i=$((i + 1))
        sleep 2
    done
    if [ "$i" -ge "$tries" ]; then
        die "等待 ${HEALTH_URL} 超时。排查：docker compose logs --tail 200 ${SERVICE}
  如需再次回滚：./docker/restore.sh <另一个备份文件>（旧库在 /data/bookhub.db.bak-${TS}）"
    fi
else
    log "WARN: 宿主机没有 curl，跳过健康检查。请手动确认："
    printf '  curl -fsS %s\n  docker compose logs --tail 100 %s\n' "$HEALTH_URL" "$SERVICE"
fi

log "恢复完成。旧库留档：/data/bookhub.db.bak-${TS}（确认无误后可删除）"
log "回退镜像版本：编辑 .env 的 BOOKHUB_TAG 后 docker compose up -d"
