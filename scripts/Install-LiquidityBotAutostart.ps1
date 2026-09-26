# D-144: register (or remove with -Remove) the logon task that restarts the
# bot after a reboot or power loss. Run it yourself: it changes a Windows
# setting. The task runs as the current user, only after that user signs in.
param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$taskName = 'KalshiLiquidityBot-Autostart'
if ($Remove) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    "Removed scheduled task $taskName"
    return
}
$script = Join-Path $PSScriptRoot 'Start-LiquidityBotOnBoot.ps1'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$trigger.Delay = 'PT2M'
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description 'Restart the Kalshi liquidity bot after reboot if it was running (D-144).' -Force | Out-Null
"Registered scheduled task $taskName (runs 2 minutes after you sign in)."
