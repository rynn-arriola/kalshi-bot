$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectPath '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Native Windows .venv is missing.' }
Push-Location $projectPath
try {
    & $pythonPath -B -m kalshi_bot preflight
    $preflightExitCode = $LASTEXITCODE
} finally { Pop-Location }
exit $preflightExitCode
