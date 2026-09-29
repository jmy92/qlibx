# ============================================================
# 彻底停止 Qlib 量化实验平台的前后端服务
# 用法: powershell -ExecutionPolicy Bypass -File stop.ps1
# 覆盖: 端口占用进程、后台隐藏进程、命令行窗口进程树
# ============================================================

$ErrorActionPreference = 'SilentlyContinue'
$Ports = @(8210, 5173)   # 8210=后端 FastAPI, 5173=前端 Vite

Write-Host "==> 开始停止服务..." -ForegroundColor Yellow

# ---------- 1. 按端口清理（含子进程树，可杀掉隐藏窗口进程） ----------
foreach ($port in $Ports) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($conn in $conns) {
        $procId = $conn.OwningProcess
        $name = (Get-Process -Id $procId -ErrorAction SilentlyContinue).ProcessName
        Write-Host "  端口 $port 由进程 $name (PID $procId) 占用，强制结束进程树"
        taskkill /PID $procId /T /F | Out-Null
    }
}

# ---------- 2. 按命令行特征清理（防止换端口/僵尸进程漏网） ----------
$patterns = @(
    'uvicorn\s+main:app',                                              # 后端 uvicorn（任意端口）
    'my_temp\\python\.exe.*uvicorn',                                   # 指定虚拟环境启动的 uvicorn
    'qlib\\ui-project\\frontend.*vite',                                # 本项目前端 vite
    'node(_\w+)?\.exe.*vite\.js'                                       # node 直启 vite
)
$procs = Get-CimInstance Win32_Process | Where-Object {
    $cl = $_.CommandLine
    if (-not $cl) { return $false }
    foreach ($p in $patterns) {
        if ($cl -match $p) { return $true }
    }
    return $false
}
foreach ($proc in $procs) {
    # 排除自身脚本所在进程树
    if ($proc.ProcessId -ne $PID) {
        Write-Host "  按特征结束进程: $($proc.Name) (PID $($proc.ProcessId))"
        taskkill /PID $proc.ProcessId /T /F | Out-Null
    }
}

Start-Sleep -Seconds 1

# ---------- 3. 复查端口，仍占用则再补一刀 ----------
$leftover = @()
foreach ($port in $Ports) {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($c) {
        $leftover += $port
        $c | ForEach-Object { taskkill /PID $_.OwningProcess /T /F | Out-Null }
    }
}
if ($leftover) {
    Write-Host "警告: 端口 $($leftover -join ', ') 仍未释放，请手动检查" -ForegroundColor Red
} else {
    Write-Host "==> 前后端服务已全部停止，端口 8210 / 5173 均已释放" -ForegroundColor Green
}
