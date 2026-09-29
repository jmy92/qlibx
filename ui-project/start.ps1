# ============================================================
# 一键启动 Qlib 量化实验平台的前后端服务
# 用法: powershell -ExecutionPolicy Bypass -File start.ps1
# 特性: 启动前先彻底停止旧服务（复用 stop.ps1 逻辑），
#       后端使用指定虚拟环境，前端依赖已装在项目目录
# ============================================================

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$BackendDir = Join-Path $Root 'backend'
$FrontendDir = Join-Path $Root 'frontend'
$PythonExe = 'D:\workspace_buddy\conda_envs\my_temp\python.exe'
$BackendPort = 8210
$FrontendPort = 5173

# ---------- 1. 先彻底停止旧服务 ----------
Write-Host "==> 步骤 1/4: 清理旧进程..." -ForegroundColor Yellow
& (Join-Path $Root 'stop.ps1')

# ---------- 2. 环境自检 ----------
Write-Host "==> 步骤 2/4: 检查环境..." -ForegroundColor Yellow
if (-not (Test-Path $PythonExe)) {
    Write-Host "错误: 未找到后端 Python: $PythonExe" -ForegroundColor Red
    Read-Host "按回车退出"; exit 1
}
if (-not (Test-Path (Join-Path $FrontendDir 'node_modules'))) {
    Write-Host "错误: 前端依赖未安装，请先在 $FrontendDir 执行 npm install" -ForegroundColor Red
    Read-Host "按回车退出"; exit 1
}

# ---------- 3. 启动后端（隐藏窗口，日志写文件） ----------
Write-Host "==> 步骤 3/4: 启动后端 (端口 $BackendPort)..." -ForegroundColor Yellow
$backendLog = Join-Path $BackendDir 'server.log'
$backendErr = Join-Path $BackendDir 'server.err.log'
Start-Process -FilePath $PythonExe `
    -ArgumentList '-m','uvicorn','main:app','--port',"$BackendPort" `
    -WorkingDirectory $BackendDir -WindowStyle Hidden `
    -RedirectStandardOutput $backendLog -RedirectStandardError $backendErr

# 等待后端就绪（最多 20 秒）
$backendOk = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 1
    $listening = Get-NetTCPConnection -LocalPort $BackendPort -State Listen -ErrorAction SilentlyContinue
    if ($listening) { $backendOk = $true; break }
}
if ($backendOk) {
    Write-Host "  后端已就绪: http://localhost:$BackendPort (日志: $backendLog)" -ForegroundColor Green
} else {
    Write-Host "警告: 后端 $BackendPort 端口未就绪，请查看 $backendErr" -ForegroundColor Red
}

# ---------- 4. 启动前端（隐藏窗口，日志写文件） ----------
Write-Host "==> 步骤 4/4: 启动前端 (端口 $FrontendPort)..." -ForegroundColor Yellow
$frontendLog = Join-Path $FrontendDir 'vite.log'
$frontendErr = Join-Path $FrontendDir 'vite.err.log'
Start-Process -FilePath 'node' `
    -ArgumentList 'node_modules/vite/bin/vite.js' `
    -WorkingDirectory $FrontendDir -WindowStyle Hidden `
    -RedirectStandardOutput $frontendLog -RedirectStandardError $frontendErr

$frontendOk = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 1
    $listening = Get-NetTCPConnection -LocalPort $FrontendPort -State Listen -ErrorAction SilentlyContinue
    if ($listening) { $frontendOk = $true; break }
}
if ($frontendOk) {
    Write-Host "  前端已就绪" -ForegroundColor Green
} else {
    Write-Host "警告: 前端 $FrontendPort 端口未就绪，请查看 $frontendErr" -ForegroundColor Red
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
if ($backendOk -and $frontendOk) {
    Write-Host "  启动完成！请在浏览器打开: http://localhost:$FrontendPort" -ForegroundColor Cyan
} else {
    Write-Host "  部分服务未就绪，请查看上方日志提示" -ForegroundColor Yellow
}
Write-Host "  停止服务请运行: stop.ps1" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Read-Host "按回车关闭本窗口（服务在后台继续运行）"
