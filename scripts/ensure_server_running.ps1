[CmdletBinding()]
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$BindHost = "0.0.0.0",
    [int]$Port = 8080,
    [string]$PythonPath = "",
    [string]$DatabasePath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path $RepoRoot).Path
$UpdateScript = Join-Path $RepoRoot "scripts\update_and_restart.ps1"

if (-not (Test-Path -LiteralPath $UpdateScript)) {
    throw "Update script was not found: $UpdateScript"
}

$arguments = @{
    RepoRoot = $RepoRoot
    BindHost = $BindHost
    Port = $Port
    SkipGitCheck = $true
    NoDependencyInstall = $true
}

if ($PythonPath) {
    $arguments.PythonPath = $PythonPath
}
if ($DatabasePath) {
    $arguments.DatabasePath = $DatabasePath
}

& $UpdateScript @arguments
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
