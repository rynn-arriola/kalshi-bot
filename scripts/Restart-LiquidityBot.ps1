param([switch]$Flatten, [switch]$Live, [int]$TimeoutSeconds=180, [int]$StartupTimeoutSeconds=300)
$ErrorActionPreference = 'Stop'
if (-not $Flatten -or -not $Live) { throw 'Command 1 requires explicit -Flatten -Live; ordinary stop/start is unchanged.' }
$projectPath = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectPath '.venv\Scripts\python.exe'
Push-Location $projectPath
try {
    & $pythonPath -B -m kalshi_bot.emergency_restart --live --timeout $TimeoutSeconds --startup-timeout $StartupTimeoutSeconds
    $resultCode = $LASTEXITCODE
} finally { Pop-Location }
exit $resultCode
