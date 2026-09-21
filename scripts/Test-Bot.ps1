$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectPath '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Create the native Windows .venv and install the project first.' }
Push-Location $projectPath
try {
    & $pythonPath -B -m unittest discover -s tests -v
    $testExitCode = $LASTEXITCODE
} finally { Pop-Location }
exit $testExitCode
