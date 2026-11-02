#
# BookHub 运行镜像（两阶段构建）
#
# 说明：刻意不写 `# syntax=docker/dockerfile:1`。那会让构建先联网解析 Docker Hub 上的
# 前端镜像，内网/受限网络下会卡在 "resolve image config for docker-image://..."。
# 本文件只用到标准 Dockerfile 指令，不需要该前端。
#   builder —— 用 `pip wheel` 把全部依赖预编译成 wheel，编译器只存在于本阶段
#   runtime —— 只安装 wheel + 源码，以非 root 用户 bookhub(10001) 运行
#
# 依赖源可覆盖（国内镜像示例）：
#   docker compose build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
# 或写进 .env：PIP_INDEX_URL=...（docker-compose.yml 已把它透传成构建参数）

ARG PYTHON_VERSION=3.12

# ------------------------------------------------------------------ builder
FROM python:${PYTHON_VERSION}-slim AS builder

ARG PIP_INDEX_URL=https://pypi.org/simple
# 默认不装编译器：所有依赖在 amd64/arm64 上都有预编译 wheel，装 build-essential 只会
# 让构建多花几分钟（还要拉 Debian 源）。只有遇到"某个依赖没有 wheel"时才需要打开。
ARG WITH_BUILD_TOOLS=0

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL}

RUN if [ "${WITH_BUILD_TOOLS}" = "1" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends build-essential \
        && rm -rf /var/lib/apt/lists/*; \
    fi

WORKDIR /build
COPY requirements.txt ./
RUN pip wheel --wheel-dir /wheels -r requirements.txt

# ------------------------------------------------------------------ runtime
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 非 root 用户：uid/gid 固定为 10001，便于挂载目录预先把属主设成 10001:10001。
# 只有 /data 归 bookhub，应用代码保持 root 所有且不可写（见文件末尾的 chmod）。
RUN groupadd --gid 10001 bookhub \
 && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin bookhub \
 && mkdir -p /data \
 && chown -R bookhub:bookhub /data

# 依赖只从 builder 产出的 wheel 安装：离线、可复现、不走网络
COPY --from=builder /wheels /wheels
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-index --find-links=/wheels -r /tmp/requirements.txt \
 && rm -rf /wheels /tmp/requirements.txt

WORKDIR /app

# app/ 之外的 alembic/ 与 alembic.ini 是启动时 `alembic upgrade head` 的依据
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY docker/entrypoint.sh ./docker/entrypoint.sh

# 硬性只读：镜像内代码归 root、去掉写位，运行用户 bookhub 只能读与执行。
# 这是必需的——从 Windows 工作区构建时 COPY 进来的文件会带着 777 权限，
# 不显式收权就等于运行用户可以改自己的代码。
RUN chmod 0755 ./docker/entrypoint.sh \
 && chown -R root:root app alembic alembic.ini docker \
 && chmod -R a-w app alembic alembic.ini docker

USER bookhub

EXPOSE 8000
VOLUME ["/data"]

# 用 python 标准库探活，镜像里不装 curl / wget。
# urlopen 在非 2xx 时抛异常 → 退出码非 0；PORT 与 entrypoint 的监听端口保持一致。
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,sys,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/healthz', timeout=3); sys.exit(0)"

ENTRYPOINT ["/app/docker/entrypoint.sh"]
