[CmdletBinding()]
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$TaskName = "PSAT Prep Hourly Update",
    [string]$Remote = "origin",
    [string]$Branch = "main",
    [string]$BindHost = "0.0.0.0",
    [int]$Port = 8080,
    [string]$PythonPath = "",
    [string]$DatabasePath = "",
    [switch]$RunNow
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path $RepoRoot).Path
$UpdateScript = Join-Path $RepoRoot "scripts\update_and_restart.ps1"
$HiddenRunnerScript = Join-Path $RepoRoot "scripts\run_hidden.vbs"

if (-not (Test-Path -LiteralPath $UpdateScript)) {
    throw "Update script was not found: $UpdateScript"
}
if (-not (Test-Path -LiteralPath $HiddenRunnerScript)) {
    throw "Hidden runner script was not found: $HiddenRunnerScript"
}

function Quote-TaskArgument {
    param([string]$Value)

    return '"' + ($Value -replace '"', '\"') + '"'
}

$powerShellExe = (Get-Process -Id $PID).Path
if (-not $powerShellExe -or -not (Test-Path -LiteralPath $powerShellExe)) {
    $powerShellExe = (Get-Command powershell.exe -ErrorAction Stop).Source
}

$wscriptExe = Join-Path $env:WINDIR "System32\wscript.exe"
if (-not (Test-Path -LiteralPath $wscriptExe)) {
    $wscriptExe = (Get-Command wscript.exe -ErrorAction Stop).Source
}

$powerShellArguments = @(
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    $UpdateScript,
    "-RepoRoot",
    $RepoRoot,
    "-Remote",
    $Remote,
    "-Branch",
    $Branch,
    "-BindHost",
    $BindHost,
    "-Port",
    [string]$Port
)

if ($PythonPath) {
    $powerShellArguments += @("-PythonPath", $PythonPath)
}
if ($DatabasePath) {
    $powerShellArguments += @("-DatabasePath", $DatabasePath)
}

$hiddenArguments = @("//B", (Quote-TaskArgument $HiddenRunnerScript), (Quote-TaskArgument $powerShellExe))
foreach ($argument in $powerShellArguments) {
    $hiddenArguments += (Quote-TaskArgument $argument)
}

$action = New-ScheduledTaskAction `
    -Execute $wscriptExe `
    -Argument ($hiddenArguments -join " ") `
    -WorkingDirectory $RepoRoot

$hourlyTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(5) `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$logonTrigger = New-ScheduledTaskTrigger `
    -AtLogOn `
    -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)

$triggers = @($hourlyTrigger, $logonTrigger)

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
    -Description "Git fast-forward update and restart for PSAT Prep at user logon and hourly." `
    -Force | Out-Null

Write-Host "Installed scheduled task: $TaskName"
Write-Host "Runs at user logon and every hour while this Windows user is logged in."
Write-Host "Updater log: $(Join-Path $RepoRoot 'data\logs\update-and-restart.log')"

if ($RunNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Started scheduled task now."
}
