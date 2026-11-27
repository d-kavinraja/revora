<#
.SYNOPSIS
    Starts (or restarts) the Revora FastAPI backend on 127.0.0.1:8000.

.DESCRIPTION
    Local-development launcher used by run.bat. It exists because uvicorn's
    --reload supervisor binds the listening socket before the application
    loads and, on Windows, a failed bind only prints a bare
    '[WinError 10013] An attempt was made to access a socket in a way
    forbidden by its access permissions' line.

    WinError 10013 is WSAEACCES: Windows is protecting the address, not a
    Revora bug. The usual causes are:
      * another process still owns 127.0.0.1:8000 with SO_EXCLUSIVEADDRUSE
        (Go-based tools set it, and Windows reports WSAEACCES instead of
        WSAEADDRINUSE);
      * a Windows NAT / portproxy mapping created by Docker Desktop, WSL or
        Hyper-V holds the port (these do not show up in netstat);
      * the port sits inside a WinNAT/Hyper-V excluded port range;
      * a security filter driver denies the bind.

    This script checks all four, stops a stale Revora backend from this
    repository when it is the owner, waits for the port to be released,
    and retries a transient bind failure instead of dying on the first try.

.PARAMETER ListenAddress
    Interface to bind. Default 127.0.0.1.

.PARAMETER Port
    TCP port to bind. Default 8000.

.PARAMETER NoReload
    Start uvicorn without --reload.

.PARAMETER CheckOnly
    Run the preflight checks and exit without starting the backend.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev-backend.ps1

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev-backend.ps1 -CheckOnly
#>
[CmdletBinding()]
param(
    [string]$ListenAddress = '127.0.0.1',
    [int]$Port = 8000,
    [switch]$NoReload,
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Backend  = Join-Path $RepoRoot 'backend'
$Python   = Join-Path $Backend 'venv\Scripts\python.exe'
$Alembic  = Join-Path $Backend 'venv\Scripts\alembic.exe'

function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Warn([string]$Message) { Write-Host "WARNING: $Message" -ForegroundColor Yellow }

function Get-PortOwners {
    Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
}

function Get-OwnerDescription([int]$OwnerPid) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$OwnerPid" -ErrorAction SilentlyContinue
    if (-not $proc) { return "PID $OwnerPid (process has exited; the TCP table still lists its socket - likely an orphaned uvicorn child)" }
    $path = $proc.ExecutablePath
    if (-not $path) { $path = $proc.Name }
    $cmd = $proc.CommandLine
    if ($cmd) {
        if ($cmd.Length -gt 180) { $cmd = $cmd.Substring(0, 180) + '...' }
        return "PID $OwnerPid  $path`n        $cmd"
    }
    return "PID $OwnerPid  $path"
}

function Get-RevoraBackendProcesses {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and
        $_.CommandLine -match 'uvicorn(\.exe)?"?\s+app\.main:app' -and
        ($_.CommandLine.IndexOf($Backend, [StringComparison]::OrdinalIgnoreCase) -ge 0)
    }
}

function Stop-ProcessTree([int]$ProcessId) {
    # taskkill /T also removes uvicorn's inherited-socket children. It writes to
    # stderr for processes that already exited, and native stderr would become a
    # terminating error under $ErrorActionPreference = 'Stop'.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'SilentlyContinue'
    try {
        if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
            & taskkill.exe /PID $ProcessId /T /F *> $null
        }
    }
    finally {
        $ErrorActionPreference = $previous
    }
}

function Invoke-Native([string]$FilePath, [string[]]$Arguments) {
    # uvicorn logs to stderr; with $ErrorActionPreference = 'Stop' and redirected
    # output PowerShell would turn that into a terminating NativeCommandError.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $FilePath @Arguments
    }
    finally {
        $ErrorActionPreference = $previous
    }
    # Do not return through the pipeline: uvicorn's stdout would be captured too.
    $script:LastExitCode = $LASTEXITCODE
}

function Invoke-NativeCaptured([string]$FilePath, [string[]]$Arguments) {
    # Same, plus re-print alembic's stderr as plain text instead of letting
    # PowerShell render each line as a red NativeCommandError block.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $FilePath @Arguments 2>&1
        $code = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previous
    }
    foreach ($item in $output) { Write-Host ([string]$item) }
    return $code
}

function Test-ExcludedRange {
    $lines = & netsh interface ipv4 show excludedportrange protocol=tcp 2>$null
    foreach ($line in $lines) {
        if ($line -match '^\s*(\d+)\s+(\d+)\s*$') {
            $start = [int]$Matches[1]
            $end   = [int]$Matches[2]
            if ($Port -ge $start -and $Port -le $end) { return "$start-$end" }
        }
    }
    return $null
}

function Test-NatMapping {
    try {
        $nat = Get-NetNatStaticMapping -ErrorAction SilentlyContinue | Where-Object {
            $_.Protocol -eq 'TCP' -and [int]$_.ExternalPort -eq $Port
        }
        if ($nat) { return 'a Windows NAT (WinNAT/HNS) static mapping' }
    } catch { }
    try {
        $proxy = & netsh interface portproxy show v4tov4 2>$null | Select-String -Pattern ":$Port\s"
        if ($proxy) { return 'a netsh interface portproxy v4tov4 rule' }
    } catch { }
    return $null
}

function Show-BindHelp {
    Write-Host ''
    Write-Warn "Port $Port is protected by Windows (WSAEACCES / WinError 10013)."
    Write-Host 'Common fixes, from least to most disruptive:'
    Write-Host "  1. If Docker Desktop or WSL is running, quit it (or run: wsl --shutdown), wait a few"
    Write-Host '     seconds, then start the backend again. Docker/WSL hold loopback ports through WinNAT'
    Write-Host '     and those reservations do not show up in netstat.'
    Write-Host '  2. Release Hyper-V/WinNAT reservations from an elevated PowerShell:'
    Write-Host '       net stop winnat'
    Write-Host '       net start winnat'
    Write-Host '     (this drops Docker/WSL networking until it reconnects)'
    Write-Host "  3. If the port is inside an excluded range, reserve it for this app from an elevated"
    Write-Host '     PowerShell, then start the backend again:'
    Write-Host '       net stop winnat'
    Write-Host "       netsh int ipv4 add excludedportrange protocol=tcp startport=$Port numberofports=1"
    Write-Host '       net start winnat'
    Write-Host "  4. If another application owns the port, stop it, or change the backend port in run.bat"
    Write-Host '     and the frontend API proxy target together.'
    Write-Host ''
}

Write-Step "Revora backend on ${ListenAddress}:$Port (repo: $RepoRoot)"

if (-not (Test-Path $Python))  { throw "Python venv not found: $Python" }
if (-not (Test-Path $Alembic)) { throw "Alembic not found: $Alembic" }

# --- Preflight 1: excluded/reserved range -------------------------------------
$excluded = Test-ExcludedRange
if ($excluded) {
    Write-Warn "Port $Port is inside the Windows excluded TCP range $excluded."
    Show-BindHelp
    exit 1
}

# --- Preflight 2: Windows NAT / portproxy reservations ------------------------
$nat = Test-NatMapping
if ($nat) {
    Write-Warn "Port $Port is reserved by $nat."
    Show-BindHelp
    exit 1
}

# --- Preflight 3: existing listener --------------------------------------------
$owners = @(Get-PortOwners)
if ($owners.Count -gt 0) {
    $ours = @(Get-RevoraBackendProcesses)
    $oursIds = @($ours | Select-Object -ExpandProperty ProcessId)
    $aliveOwnerIds = @()
    $deadOwnerIds = @()
    foreach ($ownerPid in $owners) {
        $alive = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerPid" -ErrorAction SilentlyContinue
        if ($alive) { $aliveOwnerIds += $ownerPid } else { $deadOwnerIds += $ownerPid }
    }
    $foreign = @($aliveOwnerIds | Where-Object { $oursIds -notcontains $_ })

    if ($foreign.Count -gt 0) {
        Write-Warn "Port $Port is already in use by another application:"
        foreach ($ownerPid in $foreign) { Write-Host ('  ' + (Get-OwnerDescription $ownerPid)) }
        Write-Host 'Revora did not start a second backend. Stop that process or free the port, then rerun.'
        Write-Host "If that application is Docker Desktop or WSL, quit it (or run 'wsl --shutdown') and rerun."
        exit 1
    }

    if ($CheckOnly) {
        if ($oursIds.Count -eq 0 -and $deadOwnerIds.Count -gt 0) {
            Write-Warn "Port $Port is held by an orphaned socket (dead PID $($deadOwnerIds -join ', '))."
            Write-Host 'Run this script without -CheckOnly to clean it up and start the backend.'
            exit 1
        }
        Write-Step "A Revora backend is already listening on $Port`:" 
        foreach ($ownerPid in $owners) { Write-Host ('  ' + (Get-OwnerDescription $ownerPid)) }
        exit 0
    }

    if ($oursIds.Count -gt 0) {
        Write-Step "An earlier Revora backend owns port $Port; stopping it for a clean restart."
    } else {
        Write-Step "An orphaned backend socket still owns port $Port; cleaning it up."
    }
    # /T matters: uvicorn --reload binds in the supervisor and the server child
    # inherits the socket. Killing only the supervisor would orphan the child and
    # leave the port bound (and a later bind can fail with WSAEACCES).
    foreach ($rootPid in $oursIds) { Stop-ProcessTree $rootPid }
    Start-Sleep -Milliseconds 800
    foreach ($proc in @(Get-RevoraBackendProcesses)) {
        Stop-ProcessTree $proc.ProcessId
    }

    # A previously killed supervisor leaves its multiprocessing child alive with the
    # inherited socket; Windows keeps attributing the listener to the dead PID.
    for ($sweep = 1; $sweep -le 2; $sweep++) {
        $busyOwners = @(Get-PortOwners)
        $orphans = @()
        foreach ($ownerPid in $busyOwners) {
            $alive = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerPid" -ErrorAction SilentlyContinue
            if (-not $alive) {
                $orphans += @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
                    Where-Object { $_.CommandLine -and $_.CommandLine -match "parent_pid=$ownerPid\b" })
            }
        }
        if ($orphans.Count -eq 0) { break }
        foreach ($orphan in $orphans) { Stop-ProcessTree $orphan.ProcessId }
        Start-Sleep -Milliseconds 800
    }

    $deadline = (Get-Date).AddSeconds(15)
    while ((Get-Date) -lt $deadline -and @(Get-PortOwners).Count -gt 0) { Start-Sleep -Milliseconds 300 }
    if (@(Get-PortOwners).Count -gt 0) {
        Write-Warn "Port $Port is still busy after stopping the old backend."
        foreach ($ownerPid in @(Get-PortOwners)) { Write-Host ('  ' + (Get-OwnerDescription $ownerPid)) }
        Show-BindHelp
        exit 1
    }
}

if ($CheckOnly) {
    Write-Step "Port $Port is free; preflight checks passed."
    exit 0
}

# --- Migrations ----------------------------------------------------------------
Write-Step 'Applying database migrations (alembic upgrade head)'
Push-Location $Backend
try {
    # run.bat used to export PYTHONPATH=.; alembic's env.py and uvicorn both
    # resolve 'app.*' from the backend root, so set it here instead.
    $env:PYTHONPATH = $Backend
    $alembicCode = Invoke-NativeCaptured $Alembic @('upgrade', 'head')
    if ($alembicCode -ne 0) { throw "alembic upgrade head failed with exit code $alembicCode" }

    $uvicornArgs = @('-m', 'uvicorn', 'app.main:app', '--host', $ListenAddress, '--port', "$Port")
    if (-not $NoReload) { $uvicornArgs += '--reload' }

    $attempts = 3
    for ($attempt = 1; $attempt -le $attempts; $attempt++) {
        Write-Step "Starting uvicorn (attempt $attempt/$attempts)"
        $startedAt = Get-Date
        Invoke-Native $Python $uvicornArgs
        $code = $script:LastExitCode
        $elapsed = ((Get-Date) - $startedAt).TotalSeconds
        if ($code -eq 0) { break }
        if ($elapsed -gt 20) {
            Write-Warn "Backend exited after $([int]$elapsed)s with code $code."
            break
        }
        if ($attempt -lt $attempts) {
            Write-Warn "Backend exited almost immediately (code $code); the port may still be releasing. Retrying in 2s..."
            Start-Sleep -Seconds 2
        }
    }

    if ($code -ne 0) {
        Write-Host ''
        $owners = @(Get-PortOwners)
        if ($owners.Count -gt 0) {
            Write-Host "Port $Port is currently owned by:"
            foreach ($ownerPid in $owners) { Write-Host ('  ' + (Get-OwnerDescription $ownerPid)) }
        } else {
            Write-Host "Port $Port is free now, so the failure above was transient. Run this script again."
        }
        Show-BindHelp
    }
}
finally {
    Pop-Location
}