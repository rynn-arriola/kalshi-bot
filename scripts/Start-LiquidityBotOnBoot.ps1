# D-144: run by the logon scheduled task. Waits for the network, then starts
# the bot only if it was running before the reboot/power loss (see
# kalshi_bot.supervised_live.boot_decision). A manual stop is never undone.
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectPath '.venv\Scripts\python.exe'
$logPath = Join-Path $projectPath 'data\trader\autostart.log'
function Write-Log($message) {
    Add-Content -Path $logPath -Value ("{0:o} {1}" -f (Get-Date).ToUniversalTime(), $message) -Encoding utf8
}
$deadline = (Get-Date).AddMinutes(15)
while ((Get-Date) -lt $deadline) {
    if (Test-NetConnection -ComputerName 'external-api.kalshi.com' -Port 443 -InformationLevel Quiet -WarningAction SilentlyContinue) { break }
    Start-Sleep -Seconds 20
}
Push-Location $projectPath
try {
    $output = & $pythonPath -B -m kalshi_bot.supervised_live boot --live 2>&1 | Out-String
    Write-Log ("boot exit={0} {1}" -f $LASTEXITCODE, ($output -replace '\s+', ' '))
} finally { Pop-Location }
