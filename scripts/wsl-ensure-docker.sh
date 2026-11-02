#!/bin/sh
# 在 WSL 里确保：常驻进程 + dockerd 就绪。
#
# WSL2 发行版在"没有活跃进程"时会被回收，dockerd 随之退出、容器跟着停；
# 这个常驻的 sleep 进程就是为了让发行版一直活着。
set -eu

PROJECT_DIR="${PROJECT_DIR:-/mnt/d/Code/Other/BookHub}"

if ! pgrep -f "sleep infinity" >/dev/null 2>&1; then
    setsid nohup sleep infinity >/dev/null 2>&1 &
    echo "[wsl] 已启动常驻进程（防止发行版被回收）"
else
    echo "[wsl] 常驻进程已在运行"
fi

if docker info >/dev/null 2>&1; then
    echo "[wsl] dockerd 已就绪"
else
    echo "[wsl] dockerd 未运行，尝试启动…"
    sudo service docker start >/dev/null 2>&1 || service docker start >/dev/null 2>&1 || true
    i=0
    while [ "$i" -lt 30 ]; do
        if docker info >/dev/null 2>&1; then
            echo "[wsl] dockerd 启动成功"
            break
        fi
        i=$((i + 1))
        sleep 1
    done
fi

docker info >/dev/null 2>&1 || { echo "[wsl] dockerd 仍不可用，请手动执行：sudo service docker start" >&2; exit 1; }
echo "[wsl] ready: $PROJECT_DIR"
