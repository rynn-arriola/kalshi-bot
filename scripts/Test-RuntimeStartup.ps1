param(
    [Parameter(Mandatory=$true)][string[]]$Ticker,
    [int]$Seconds = 60
)
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectPath '.venv\Scripts\python.exe'
$keyIdPath = Join-Path $projectPath 'kalshi-bot.txt'
$privateKeyPath = Join-Path $projectPath 'Kalshi-Bot2.txt'
$outputRoot = Join-Path $projectPath 'data\runtime-startup'
$arguments = @('-B', '-m', 'kalshi_bot.startup', '--read-only-live-check',
    '--key-id-file', $keyIdPath, '--private-key-file', $privateKeyPath,
    '--output-root', $outputRoot, '--seconds', $Seconds)
foreach ($market in $Ticker) { $arguments += @('--ticker', $market) }
Push-Location $projectPath
try {
    & $pythonPath @arguments
    $resultCode = $LASTEXITCODE
} finally { Pop-Location }
exit $resultCode
