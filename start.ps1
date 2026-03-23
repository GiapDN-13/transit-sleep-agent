# start.ps1 — Khoi dong Transit Sleep Agent
# Chay: powershell -ExecutionPolicy Bypass -File start.ps1

$PROJECT = "transit-sleep-agent"
$PORT    = 8001

Write-Host "=== Transit Sleep Agent ===" -ForegroundColor Cyan

# Buoc 1: Kill TAT CA python process lien quan den project nay
Write-Host "Cleaning up old processes..." -ForegroundColor Yellow
Get-WmiObject Win32_Process | Where-Object {
    $_.CommandLine -like "*$PROJECT*" -and (
        $_.CommandLine -like "*python*" -or
        $_.CommandLine -like "*uvicorn*"
    )
} | ForEach-Object {
    Write-Host "  Killing PID $($_.ProcessId)"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

# Buoc 2: Kill bat cu process nao van chiem port $PORT
$portPid = (Get-NetTCPConnection -LocalPort $PORT -ErrorAction SilentlyContinue).OwningProcess |
           Select-Object -Unique
if ($portPid) {
    foreach ($p in $portPid) {
        Write-Host "  Killing port $PORT owner PID $p"
        Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    }
}

Start-Sleep -Seconds 2

# Verify
$check = Get-NetTCPConnection -LocalPort $PORT -ErrorAction SilentlyContinue
if ($check) {
    Write-Host "WARNING: Port $PORT still in use! Try restarting your terminal." -ForegroundColor Red
    exit 1
}

Write-Host "Port $PORT is free. Starting server..." -ForegroundColor Green
Write-Host ""

# Buoc 3: Start uvicorn voi --reload
Write-Host "Tip: Run 'ngrok http $PORT' in another terminal if not already running." -ForegroundColor DarkGray
Write-Host ""
& "venv\Scripts\uvicorn.exe" backend.main:app --reload --port $PORT
