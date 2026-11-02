#!/bin/sh
# 在 WSL 里启动容器。BUILD=1 时先重建镜像。
set -eu

PROJECT_DIR="${PROJECT_DIR:-/mnt/d/Code/Other/BookHub}"
cd "$PROJECT_DIR"

if [ "${BUILD:-0}" = "1" ]; then
    echo "[wsl] docker compose up -d --build"
    docker compose up -d --build
else
    echo "[wsl] docker compose up -d"
    docker compose up -d
fi
docker compose ps --format '{{.Name}} {{.Status}}'
