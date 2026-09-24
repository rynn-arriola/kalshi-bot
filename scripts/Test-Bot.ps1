param(
    [switch]$Fast,
    [switch]$NativeSupervisor
)

$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectPath '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Create the native Windows .venv and install the project first.' }
Push-Location $projectPath
try {
    if ($Fast) {
        $patterns = @(
            'test_bot_live_runtime.py',
            'test_bot_dispatch_sources.py',
            'test_bot_reward_tracker.py',
            'test_bot_production_supervisor_repairs.py',
            'test_bot_supervision.py'
        )
        if ($NativeSupervisor) { $patterns += 'test_bot_supervisor_native.py' }
        $testExitCode = 0
        foreach ($pattern in $patterns) {
            & $pythonPath -B -m unittest discover -s tests -p $pattern
            if ($LASTEXITCODE -ne 0) {
                $testExitCode = $LASTEXITCODE
                break
            }
        }
    } else {
        if ($NativeSupervisor) { throw '-NativeSupervisor is only valid with -Fast.' }
        & $pythonPath -B -m unittest discover -s tests -v
        $testExitCode = $LASTEXITCODE
    }
} finally { Pop-Location }
exit $testExitCode
