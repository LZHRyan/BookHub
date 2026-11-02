#!/usr/bin/env bash
# BookHub 一键升级（在宿主机执行，需要 docker + docker compose v2）
#
#   ./scripts/upgrade.sh                  # 备份 → 构建 → 重建容器 → 等待健康 → 打印版本
#   SKIP_BACKUP=1 ./scripts/upgrade.sh    # 跳过在线备份（只在"刚备份过"时用）
#
# 为什么值得用这个脚本而不是手敲 docker compose up -d --build：
#   1) 升级前必定先跑一次在线备份（docker/backup.sh）；
#   2) 会把当前镜像额外打上 bookhub:pre-upgrade-<UTC时间> 标签，回滚只需改 BOOKHUB_TAG；
#   3) 升级后必须等到容器 healthy，并打印 /healthz 里的 version + schema（库结构版本），
#      避免"镜像换了但迁移没跑"这种静默失败；
#   4) 任何一步失败都直接打印回滚命令。
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$PROJECT_DIR"

SERVICE="${SERVICE:-bookhub}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
SKIP_BACKUP="${SKIP_BACKUP:-0}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"
TS="$(date -u '+%Y%m%dT%H%M%SZ')"
PREV_TAG="pre-upgrade-${TS}"

log() { printf '[upgrade] %s\n' "$*"; }
warn() { printf '[upgrade] WARN: %s\n' "$*" >&2; }
die() { printf '[upgrade] ERROR: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "未找到 docker 命令。"
docker compose version >/dev/null 2>&1 || die "未找到 docker compose（需要 v2 插件）。"
[ -f .env ] || die "缺少 .env：升级前请先准备 SECRET_KEY 等配置（容器没有它不会启动）。"

# ---------------------------------------------------------------- 0. 现状
log "项目目录：${PROJECT_DIR}"
if CURRENT_CONTAINER="$(docker compose ps -q "$SERVICE" 2>/dev/null)" && [ -n "$CURRENT_CONTAINER" ]; then
    CURRENT_IMAGE="$(docker inspect -f '{{.Image}}' "$CURRENT_CONTAINER" 2>/dev/null || true)"
else
    CURRENT_CONTAINER=""
    CURRENT_IMAGE=""
fi

# ---------------------------------------------------------------- 1. 备份
if [ "$SKIP_BACKUP" = "1" ]; then
    warn "SKIP_BACKUP=1：跳过在线备份。请确认你已经手动执行过 ./docker/backup.sh"
elif [ -n "$CURRENT_CONTAINER" ]; then
    log "升级前备份到 ${BACKUP_DIR} …"
    sh ./docker/backup.sh "$BACKUP_DIR"
else
    warn "服务未在运行，无法做在线备份；升级完成后请立刻执行 ./docker/backup.sh"
fi

# ---------------------------------------------------------------- 2. 给当前镜像留退路
if [ -n "$CURRENT_IMAGE" ]; then
    if docker tag "$CURRENT_IMAGE" "bookhub:${PREV_TAG}" 2>/dev/null; then
        log "当前镜像已保留为 bookhub:${PREV_TAG}"
    else
        warn "给当前镜像打标签失败（继续升级；回滚时改用升级前的备份）"
    fi
else
    warn "没有正在运行的容器，跳过镜像留档（首次部署可忽略）"
fi

# ---------------------------------------------------------------- 3. 构建并重建
log "构建镜像并重建容器 …"
docker compose build || die "镜像构建失败，未做任何变更。"
docker compose up -d || die "容器启动失败。查看：docker compose logs --tail 100 ${SERVICE}"

# ---------------------------------------------------------------- 4. 等待健康
CONTAINER="$(docker compose ps -q "$SERVICE" 2>/dev/null || true)"
[ -n "$CONTAINER" ] || die "没有找到 ${SERVICE} 容器。查看：docker compose logs --tail 100 ${SERVICE}"

log "等待容器 healthy（最长 ${HEALTH_TIMEOUT}s）…"
HAS_HEALTH="$(docker inspect -f '{{if .State.Health}}yes{{else}}no{{end}}' "$CONTAINER" 2>/dev/null || echo no)"
if [ "$HAS_HEALTH" = "yes" ]; then
    OK_STATUS="healthy"
else
    OK_STATUS="running"
    warn "容器没有定义 healthcheck，只能以 running 作为就绪判断"
fi

waited=0
status="unknown"
while [ "$waited" -lt "$HEALTH_TIMEOUT" ]; do
    status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$CONTAINER" 2>/dev/null || echo unknown)"
    case "$status" in
        "$OK_STATUS") break ;;
        exited|dead) break ;;
    esac
    sleep 3
    waited=$((waited + 3))
done

if [ "$status" != "$OK_STATUS" ]; then
    printf '\n' >&2
    warn "升级后健康检查未通过（状态：${status}）。回滚方式："
    printf '  1) 回滚镜像：BOOKHUB_TAG=%s docker compose up -d\n' "$PREV_TAG" >&2
    printf '  2) 或恢复数据：./docker/restore.sh %s/<最近一次备份目录>/bookhub-*.db\n' "$BACKUP_DIR" >&2
    printf '  3) 看日志：docker compose logs --tail 200 %s\n' "$SERVICE" >&2
    exit 1
fi

# ---------------------------------------------------------------- 5. 版本与库结构
log "升级完成，当前状态："
docker compose exec -T "$SERVICE" python -c "
import json, os, urllib.request
port = os.environ.get('PORT', '8000')
body = urllib.request.urlopen('http://127.0.0.1:%s/healthz' % port, timeout=3).read().decode()
print('  /healthz ->', body.strip())
" || warn "无法读取 /healthz（容器刚起来时可能还在初始化，稍后再试）"

log "回滚命令（如需）：BOOKHUB_TAG=${PREV_TAG} docker compose up -d"
log "数据兜底（如需）：./docker/restore.sh ${BACKUP_DIR}/<时间戳>/bookhub-<时间戳>.db"
