param([switch]$Live, [switch]$Initialize, [switch]$Foreground)
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$launchCommand = if ($Foreground) { 'start' } else { 'launch' }
$arguments = @('-B', '-m', 'kalshi_bot.supervised_live', $launchCommand)
if ($Live) { $arguments += '--live' }
if ($Initialize) { $arguments += '--initialize' }
Push-Location $projectPath
try {
    & (Join-Path $projectPath '.venv\Scripts\python.exe') @arguments
    $resultCode = $LASTEXITCODE
} finally { Pop-Location }
exit $resultCode
