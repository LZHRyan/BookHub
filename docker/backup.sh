#!/usr/bin/env bash
# BookHub 在线备份（在宿主机执行，需要 docker + docker compose v2）
#
#   ./docker/backup.sh [输出目录]      # 默认 ./backups
#
# 做什么：
#   1) 在运行中的容器里用 Python sqlite3 的 backup() API 做「在线」一致快照
#      （不需要停服、不依赖宿主机装 sqlite3 命令行）
#   2) 把内容卷 /data 打成 tar.gz（排除 backups/ 自身与 -wal/-shm 边车文件）
#   3) 用 docker compose cp 取回宿主机，清理容器内临时文件
#   4) 打印产物路径与 sha256 校验和，供 restore.sh / 手工核对
#
# 注意：DB_NAME 必须与 DATABASE_URL 里的库文件名一致（SQLite 部署才会用它）。
set -euo pipefail

OUT_DIR="${1:-./backups}"
SERVICE="${SERVICE:-bookhub}"
DB_NAME="${DB_NAME:-bookhub.db}"
TS="$(date -u '+%Y%m%dT%H%M%SZ')"
REMOTE_DIR="/data/backups/${TS}"

log() { printf '[backup] %s\n' "$*"; }
die() { printf '[backup] ERROR: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "未找到 docker 命令。"
docker compose version >/dev/null 2>&1 || die "未找到 docker compose（需要 v2 插件）。"

# 在线备份的前提是服务在跑：exec 只是探一下，不产生副作用。
if ! docker compose exec -T "$SERVICE" true >/dev/null 2>&1; then
    die "服务 $SERVICE 未在运行，无法做在线备份。先执行：docker compose up -d"
fi

log "容器内临时目录：${REMOTE_DIR}"
docker compose exec -T "$SERVICE" sh -c "mkdir -p '${REMOTE_DIR}'" \
    || die "无法在容器内创建 ${REMOTE_DIR}（/data 是否可写？）"

# ---------------------------------------------------------------- 1. SQLite 在线快照 + 内容卷打包
# 单引号包裹整段 Python：宿主 shell 不做任何替换，时间戳等参数通过 -e 传入。
if ! docker compose exec -T -e BH_TS="$TS" -e BH_DB="$DB_NAME" -e BH_DIR="$REMOTE_DIR" \
        "$SERVICE" python -c '
import os
import pathlib
import sqlite3
import sys
import tarfile

ts = os.environ["BH_TS"]
db_name = os.environ["BH_DB"]
out_dir = pathlib.Path(os.environ["BH_DIR"])
data_dir = pathlib.Path("/data")

src = data_dir / db_name
if not src.exists():
    sys.exit("找不到数据库文件 %s —— 当前部署可能不是 SQLite（切了 Postgres 就该用 pg_dump -Fc）" % src)

dst = out_dir / ("bookhub-%s.db" % ts)
source_conn = sqlite3.connect("file:%s?mode=ro" % src, uri=True)
target_conn = sqlite3.connect(str(dst))
try:
    with target_conn:
        source_conn.backup(target_conn)
finally:
    target_conn.close()
    source_conn.close()

check_conn = sqlite3.connect(str(dst))
try:
    verdict = check_conn.execute("PRAGMA quick_check").fetchone()[0]
finally:
    check_conn.close()
if verdict != "ok":
    sys.exit("备份文件完整性检查失败：%s" % verdict)
print("db   %s  %d bytes  quick_check=ok" % (dst, dst.stat().st_size))

tarball = out_dir / ("bookhub-data-%s.tar.gz" % ts)
with tarfile.open(tarball, "w:gz") as tar:
    for path in sorted(data_dir.rglob("*")):
        rel = path.relative_to(data_dir)
        if rel.parts and rel.parts[0] == "backups":
            continue
        if rel.name.endswith(("-wal", "-shm")):
            continue
        if str(rel) == db_name:
            # 原始库文件在 WAL 模式下可能落后于已提交事务，跳过它，
            # 下面换成刚做出来的一致性快照，保证 tar 单独也能用。
            continue
        tar.add(str(path), arcname=str(rel), recursive=False)
    tar.add(str(dst), arcname=db_name, recursive=False)
print("tar  %s  %d bytes" % (tarball, tarball.stat().st_size))
' ; then
    docker compose exec -T "$SERVICE" sh -c "rm -rf '${REMOTE_DIR}'" >/dev/null 2>&1 || true
    die "容器内备份失败，已清理临时文件。详见上方输出。"
fi

# ---------------------------------------------------------------- 2. 取回宿主机
mkdir -p "${OUT_DIR}/${TS}"
docker compose cp "${SERVICE}:${REMOTE_DIR}/." "${OUT_DIR}/${TS}/" \
    || die "docker compose cp 失败（容器仍在运行？）"
# 备份里有用户口令哈希与全部正文：docker compose cp 会沿用它从容器里带出的 644，
# umask 管不到，这里显式收成 600（root 之外的账号不该能读备份）
chmod 700 "${OUT_DIR}/${TS}"
find "${OUT_DIR}/${TS}" -type f -exec chmod 600 {} +
log "已取回：${OUT_DIR}/${TS}/（权限 600）"

# ---------------------------------------------------------------- 3. 清理容器内临时文件
# 不清会撑爆命名卷；容器内 /data/backups 只是中转站。
docker compose exec -T "$SERVICE" sh -c "rm -rf '${REMOTE_DIR}'" >/dev/null 2>&1 \
    || log "WARN: 清理容器内 ${REMOTE_DIR} 失败，请手动删除"

# ---------------------------------------------------------------- 4. 校验和
checksum() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | cut -d' ' -f1
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | cut -d' ' -f1
    else
        for py in python3 python; do
            if command -v "$py" >/dev/null 2>&1; then
                "$py" -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],\"rb\").read()).hexdigest())" "$1" && return 0
            fi
        done
        printf '%s' "<无法计算：缺少 sha256sum/shasum/python>"
    fi
}

log "备份完成，产物如下（sha256  size  path）："
for f in "${OUT_DIR}/${TS}"/*; do
    [ -f "$f" ] || continue
    size="$(wc -c <"$f" | tr -d ' ')"
    printf '  %s  %10s  %s\n' "$(checksum "$f")" "$size" "$f"
done

log "恢复：./docker/restore.sh ${OUT_DIR}/${TS}/bookhub-${TS}.db"
log "       或 ./docker/restore.sh ${OUT_DIR}/${TS}/bookhub-data-${TS}.tar.gz"
