[CmdletBinding()]
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$Remote = "origin",
    [string]$Branch = "main",
    [string]$BindHost = "0.0.0.0",
    [int]$Port = 8080,
    [string]$PythonPath = "",
    [string]$DatabasePath = "",
    [switch]$ForceRestart,
    [switch]$NoDependencyInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path $RepoRoot).Path
$DataDir = Join-Path $RepoRoot "data"
$LogDir = Join-Path $DataDir "logs"
$PidFile = Join-Path $DataDir "server.pid"
$UpdateLog = Join-Path $LogDir "update-and-restart.log"
$ServerOutLog = Join-Path $LogDir "server.out.log"
$ServerErrLog = Join-Path $LogDir "server.err.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-UpdateLog {
    param([string]$Message)

    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $UpdateLog -Value $line
    Write-Host $line
}

function Invoke-Git {
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$GitArgs
    )

    $output = & git @GitArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        $joined = ($output | Out-String).Trim()
        throw "git $($GitArgs -join ' ') failed. $joined"
    }
    return @($output)
}

function Resolve-PythonExe {
    if ($PythonPath) {
        if (-not (Test-Path -LiteralPath $PythonPath)) {
            throw "PythonPath was not found: $PythonPath"
        }
        return (Resolve-Path $PythonPath).Path
    }

    $venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) {
        return $venvPython
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        return $pythonCommand.Source
    }

    throw "Python was not found. Create .venv or pass -PythonPath."
}

function Get-ProcessInfo {
    param([int]$ProcessId)

    return Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
}

function Test-AppProcess {
    param([int]$ProcessId)

    $processInfo = Get-ProcessInfo -ProcessId $ProcessId
    if ($null -eq $processInfo) {
        return $false
    }

    $commandLine = [string]$processInfo.CommandLine
    return $commandLine -match "app\.py"
}

function Test-DescendantProcess {
    param(
        [int]$ProcessId,
        [int]$AncestorProcessId
    )

    $current = Get-ProcessInfo -ProcessId $ProcessId
    while ($null -ne $current) {
        if ([int]$current.ParentProcessId -eq $AncestorProcessId) {
            return $true
        }
        if ([int]$current.ParentProcessId -le 0 -or [int]$current.ParentProcessId -eq [int]$current.ProcessId) {
            return $false
        }
        $current = Get-ProcessInfo -ProcessId ([int]$current.ParentProcessId)
    }
    return $false
}

function Test-TcpPort {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $asyncResult = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $asyncResult.AsyncWaitHandle.WaitOne(500, $false)) {
            return $false
        }
        $client.EndConnect($asyncResult)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Get-PortOwnerProcessIds {
    $processIds = @()

    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    foreach ($listener in $listeners) {
        $ownerPid = [int]$listener.OwningProcess
        if ($ownerPid -gt 0) {
            $processIds += $ownerPid
        }
    }

    if ($processIds.Count -eq 0) {
        $netstatLines = & netstat.exe -ano -p tcp 2>$null
        foreach ($line in $netstatLines) {
            if ($line -match "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$") {
                $processIds += [int]$Matches[1]
            }
        }
    }

    return @($processIds | Where-Object { $_ -gt 0 } | Sort-Object -Unique)
}

function Get-ServerProcessIds {
    $processIds = @()

    if (Test-Path -LiteralPath $PidFile) {
        $rawPid = (Get-Content -LiteralPath $PidFile -Raw).Trim()
        $parsedPid = 0
        if ([int]::TryParse($rawPid, [ref]$parsedPid)) {
            $existing = Get-Process -Id $parsedPid -ErrorAction SilentlyContinue
            if ($existing -and $existing.ProcessName -match "python") {
                $processIds += $parsedPid
            }
        }
    }

    foreach ($ownerPid in (Get-PortOwnerProcessIds)) {
        if ($ownerPid -gt 0 -and (Test-AppProcess -ProcessId $ownerPid)) {
            $processIds += $ownerPid
        }
    }

    return @($processIds | Sort-Object -Unique)
}

function Test-ServerRunning {
    return (Test-TcpPort)
}

function Stop-Server {
    $processIds = @(Get-ServerProcessIds | Sort-Object -Unique)
    if ($processIds.Count -eq 0) {
        if (Test-TcpPort) {
            $owners = (Get-PortOwnerProcessIds) -join ", "
            Write-UpdateLog "Port $Port is listening, but no PSAT app process was identified. Owner process id(s): $owners."
        } else {
            Write-UpdateLog "No existing PSAT server process found."
        }
        return
    }

    foreach ($processId in $processIds) {
        Write-UpdateLog "Stopping PSAT server process $processId."
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }

    Start-Sleep -Seconds 2
}

function Start-Server {
    $pythonExe = Resolve-PythonExe
    $knownServerIds = @(Get-ServerProcessIds)
    if (Test-TcpPort) {
        if ($knownServerIds.Count -gt 0) {
            Write-UpdateLog "PSAT server is already listening on port $Port."
            return
        }

        $owners = (Get-PortOwnerProcessIds) -join ", "
        throw "Port $Port is already in use by process id(s): $owners. Stop that process or choose another port."
    }

    $env:PSAT_HOST = $BindHost
    $env:PSAT_PORT = [string]$Port
    $env:PYTHONUNBUFFERED = "1"
    if ($DatabasePath) {
        $env:PSAT_DB = $DatabasePath
    }

    Write-UpdateLog "Starting PSAT server with $pythonExe on ${BindHost}:$Port."
    $process = Start-Process `
        -FilePath $pythonExe `
        -ArgumentList "app.py" `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $ServerOutLog `
        -RedirectStandardError $ServerErrLog `
        -PassThru

    Set-Content -LiteralPath $PidFile -Value $process.Id

    $deadline = (Get-Date).AddSeconds(15)
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-Process -Id $process.Id -ErrorAction SilentlyContinue)) {
            throw "Server process $($process.Id) exited during startup. Check $ServerErrLog."
        }

        $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Where-Object {
                $_.OwningProcess -eq $process.Id -or
                (Test-AppProcess -ProcessId ([int]$_.OwningProcess)) -or
                (Test-DescendantProcess -ProcessId ([int]$_.OwningProcess) -AncestorProcessId $process.Id)
            } |
            Select-Object -First 1
        if ($listener) {
            Write-UpdateLog "PSAT server is listening on port $Port as process $($listener.OwningProcess)."
            return
        }

        Start-Sleep -Seconds 1
    }

    Write-UpdateLog "Started process $($process.Id), but port $Port was not confirmed within 15 seconds."
}

function Restart-Server {
    Stop-Server
    Start-Server
}

function Install-Dependencies {
    param([string]$PythonExe)

    if ($NoDependencyInstall) {
        Write-UpdateLog "Skipping dependency install because -NoDependencyInstall was supplied."
        return
    }

    $requirements = Join-Path $RepoRoot "requirements.txt"
    if (-not (Test-Path -LiteralPath $requirements)) {
        return
    }

    Write-UpdateLog "Installing Python dependencies from requirements.txt."
    $output = & $PythonExe -m pip install -r $requirements 2>&1
    foreach ($line in $output) {
        Write-UpdateLog ([string]$line)
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed."
    }
}

$mutex = [System.Threading.Mutex]::new($false, "Global\PsatPrepUpdateAndRestart")
$hasLock = $false

try {
    $hasLock = $mutex.WaitOne(0)
    if (-not $hasLock) {
        Write-UpdateLog "Another updater run is already active. Exiting."
        exit 0
    }

    Set-Location $RepoRoot
    Write-UpdateLog "Starting update check for $Remote/$Branch in $RepoRoot."

    if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot ".git"))) {
        throw "$RepoRoot is not a git repository."
    }

    $currentBranch = (Invoke-Git "branch" "--show-current" | Select-Object -First 1).Trim()
    if ($currentBranch -ne $Branch) {
        Write-UpdateLog "Current branch is '$currentBranch', not '$Branch'. Skipping pull."
        if ($ForceRestart -or -not (Test-ServerRunning)) {
            Restart-Server
        }
        exit 0
    }

    $dirtyTrackedChanges = @(Invoke-Git "status" "--porcelain" "--untracked-files=no")
    if ($dirtyTrackedChanges.Count -gt 0) {
        Write-UpdateLog "Tracked local changes are present. Skipping pull to avoid overwriting local work."
        foreach ($change in $dirtyTrackedChanges) {
            Write-UpdateLog "  $change"
        }
        if ($ForceRestart -or -not (Test-ServerRunning)) {
            Restart-Server
        }
        exit 0
    }

    Invoke-Git "fetch" "--prune" $Remote $Branch | Out-Null

    $remoteRef = "$Remote/$Branch"
    $localRev = (Invoke-Git "rev-parse" "HEAD" | Select-Object -First 1).Trim()
    $remoteRev = (Invoke-Git "rev-parse" $remoteRef | Select-Object -First 1).Trim()

    if ($localRev -eq $remoteRev) {
        Write-UpdateLog "Already up to date at $localRev."
        if ($ForceRestart) {
            Restart-Server
        } elseif (-not (Test-ServerRunning)) {
            Write-UpdateLog "Server is not running; starting it."
            Start-Server
        }
        exit 0
    }

    $baseRev = (Invoke-Git "merge-base" "HEAD" $remoteRef | Select-Object -First 1).Trim()
    if ($localRev -ne $baseRev) {
        Write-UpdateLog "Local branch has commits that are not in $remoteRef. Skipping pull; resolve manually."
        if ($ForceRestart -or -not (Test-ServerRunning)) {
            Restart-Server
        }
        exit 0
    }

    $changedFiles = @(Invoke-Git "diff" "--name-only" $localRev $remoteRev)
    Write-UpdateLog "Fast-forwarding from $localRev to $remoteRev."
    Invoke-Git "merge" "--ff-only" $remoteRef | Out-Null

    if ($changedFiles -contains "requirements.txt") {
        Install-Dependencies -PythonExe (Resolve-PythonExe)
    }

    Restart-Server
    Write-UpdateLog "Update and restart completed."
} catch {
    Write-UpdateLog "ERROR: $($_.Exception.Message)"
    exit 1
} finally {
    if ($hasLock) {
        [void]$mutex.ReleaseMutex()
    }
    $mutex.Dispose()
}
