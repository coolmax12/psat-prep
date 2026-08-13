[CmdletBinding()]
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$TaskName = "PSAT Prep Server Watchdog",
    [string]$BindHost = "0.0.0.0",
    [int]$Port = 8080,
    [string]$PythonPath = "",
    [string]$DatabasePath = "",
    [ValidateRange(1, 1440)]
    [int]$IntervalMinutes = 5,
    [switch]$RunNow
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path $RepoRoot).Path
$WatchdogScript = Join-Path $RepoRoot "scripts\ensure_server_running.ps1"

if (-not (Test-Path -LiteralPath $WatchdogScript)) {
    throw "Watchdog script was not found: $WatchdogScript"
}

function Quote-TaskArgument {
    param([string]$Value)

    return '"' + ($Value -replace '"', '\"') + '"'
}

$powerShellExe = (Get-Process -Id $PID).Path
if (-not $powerShellExe -or -not (Test-Path -LiteralPath $powerShellExe)) {
    $powerShellExe = (Get-Command powershell.exe -ErrorAction Stop).Source
}

$arguments = @(
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    (Quote-TaskArgument $WatchdogScript),
    "-RepoRoot",
    (Quote-TaskArgument $RepoRoot),
    "-BindHost",
    $BindHost,
    "-Port",
    [string]$Port
)

if ($PythonPath) {
    $arguments += @("-PythonPath", (Quote-TaskArgument $PythonPath))
}
if ($DatabasePath) {
    $arguments += @("-DatabasePath", (Quote-TaskArgument $DatabasePath))
}

$action = New-ScheduledTaskAction `
    -Execute $powerShellExe `
    -Argument ($arguments -join " ") `
    -WorkingDirectory $RepoRoot

$repeatingTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$logonTrigger = New-ScheduledTaskTrigger `
    -AtLogOn `
    -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)

$triggers = @($repeatingTrigger, $logonTrigger)

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Principal $principal `
    -Description "Checks the PSAT Prep server at user logon and every $IntervalMinutes minute(s), and starts it when it is not listening." `
    -Force | Out-Null

Write-Host "Installed scheduled task: $TaskName"
Write-Host "Runs at user logon and every $IntervalMinutes minute(s) while this Windows user is logged in."
Write-Host "Watchdog log: $(Join-Path $RepoRoot 'data\logs\update-and-restart.log')"

if ($RunNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Started scheduled task now."
}
