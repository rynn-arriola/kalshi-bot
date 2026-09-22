$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
& (Join-Path $projectPath '.venv\Scripts\python.exe') -B -m kalshi_bot.supervised_live status
exit $LASTEXITCODE
