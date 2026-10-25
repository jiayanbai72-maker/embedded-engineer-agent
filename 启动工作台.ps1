param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$workspace = $PSScriptRoot
$endpoint = "http://127.0.0.1:$Port"
try {
    $health = Invoke-RestMethod "$endpoint/health" -TimeoutSec 2
    if ($health.status -eq 'ok' -and $health.mode -eq 'analyst_assisted') {
        Write-Output "工作台已经运行：$endpoint/"
        exit 0
    }
} catch {}
$runtimePython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $runtimePython)) {
    $runtimePython = (Get-Command python -ErrorAction Stop).Source
}
$env:PYTHONPATH = Join-Path $workspace 'src'
$armCompiler = 'C:\Keil_v5\ARM\ARMCC\bin\armcc.exe'
if (-not $env:EMBEDDED_AGENT_ARMCC -and (Test-Path -LiteralPath $armCompiler)) {
    $env:EMBEDDED_AGENT_ARMCC = $armCompiler
}
$logDirectory = Join-Path $workspace 'runtime'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$process = Start-Process -FilePath $runtimePython -ArgumentList @('-X','utf8','-m','embedded_agent.server','--port',"$Port") -WorkingDirectory $workspace -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory 'server.stdout.log') -RedirectStandardError (Join-Path $logDirectory 'server.stderr.log') -PassThru
for ($attempt = 0; $attempt -lt 15; $attempt++) {
    Start-Sleep -Milliseconds 300
    $process.Refresh()
    if ($process.HasExited) { throw '服务启动失败，请查看 runtime/server.stderr.log。' }
    try {
        $health = Invoke-RestMethod "$endpoint/health" -TimeoutSec 1
        if ($health.status -eq 'ok' -and $health.mode -eq 'analyst_assisted') {
            $process.Id | Set-Content -LiteralPath (Join-Path $logDirectory 'server.pid')
            Write-Output "工作台已启动：$endpoint/"
            Write-Output '服务独立运行，关闭聊天不会主动停止它。'
            exit 0
        }
    } catch {}
}
throw '未能确认服务启动，请查看 runtime/server.stderr.log。'
