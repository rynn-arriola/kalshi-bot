param([switch]$Live, [switch]$Initialize)
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$arguments = @('-B', '-m', 'kalshi_bot.supervised_live', 'start')
if ($Live) { $arguments += '--live' }
if ($Initialize) { $arguments += '--initialize' }
Push-Location $projectPath
try {
    & (Join-Path $projectPath '.venv\Scripts\python.exe') @arguments
    $resultCode = $LASTEXITCODE
} finally { Pop-Location }
exit $resultCode
