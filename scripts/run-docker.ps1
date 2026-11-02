# BookHub 一键启动（Windows + WSL2 + Docker）
#
# 背景：WSL2 发行版在"没有活跃进程"时会被回收，dockerd 随之退出，容器也会停掉
# （Docker 的 restart policy 只能在 daemon 活着时生效）。表现就是：过一会儿再访问，
# 页面打不开、登录提交到一半变成 chrome-error。
#
# 这个脚本：
#   1) 调 scripts/wsl-ensure-docker.sh：挂常驻进程 + 确保 dockerd 就绪；
#   2) 调 scripts/wsl-compose-up.sh：启动容器（-Build 时重建镜像）；
#   3) 等 /healthz 通过并打印访问地址。
#
# 用法（PowerShell，在项目根目录）：
#   ./scripts/run-docker.ps1
#   ./scripts/run-docker.ps1 -Port 18000 -Build

[CmdletBinding()]
param(
    [int]$Port = 18000,
    [switch]$Build,
    [string]$Distro = "Ubuntu"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

function Write-Step([string]$message) {
    Write-Host "[bookhub] $message" -ForegroundColor Cyan
}

if (-not (Test-Path (Join-Path $root ".env"))) {
    Write-Host "[bookhub] 缺少 .env：先 cp .env.example .env，并填好 SECRET_KEY 与初始管理员" -ForegroundColor Yellow
    exit 1
}

Write-Step "准备 WSL 与 Docker"
wsl -d $Distro -e sh /mnt/d/Code/Other/BookHub/scripts/wsl-ensure-docker.sh | Out-Host

if ($Build) {
    Write-Step "构建并启动容器"
    $env:BUILD = "1"
} else {
    Write-Step "启动容器"
    $env:BUILD = "0"
}
wsl -d $Distro -e sh /mnt/d/Code/Other/BookHub/scripts/wsl-compose-up.sh | Out-Host

Write-Step "等待就绪"
$ready = $false
for ($i = 1; $i -le 60; $i++) {
    Start-Sleep -Seconds 2
    try {
        $response = Invoke-WebRequest "http://127.0.0.1:$Port/healthz" -UseBasicParsing -TimeoutSec 3
        if ($response.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
}

if (-not $ready) {
    Write-Host "[bookhub] 启动超时。查看日志：docker compose logs --tail 100 bookhub" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "[bookhub] 已就绪" -ForegroundColor Green
Write-Host "  站点首页   http://localhost:$Port"
Write-Host "  管理后台   http://localhost:$Port/admin"
Write-Host "  API 文档   http://localhost:$Port/docs"
Write-Host "  管理员账号见 .env 的 BOOKHUB_INITIAL_ADMIN_USER / BOOKHUB_INITIAL_ADMIN_PASSWORD"
Write-Host ""
Write-Host "提示：WSL 被回收时容器会跟着停，保持一个 wsl 会话开着，或重跑本脚本。"
