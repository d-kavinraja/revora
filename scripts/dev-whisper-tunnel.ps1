<#
.SYNOPSIS
    Supervises the private Revora Whisper tunnel for local development.

.DESCRIPTION
    Local-development only. A detached supervisor keeps a tunnel forwarding
    127.0.0.1:18010 on this Windows machine to server-2's loopback-only
    Whisper service on port 8010.

    The supervisor starts the tunnel, checks the actual local HTTP path, and
    restarts it with bounded backoff after a crash or connectivity loss. It
    refuses to create duplicates or kill an unrelated listener, and it never
    reads or logs the speech token.

.PARAMETER Action
    start, stop, restart, status, or the internal supervise action.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev-whisper-tunnel.ps1 start

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev-whisper-tunnel.ps1 status
#>
[CmdletBinding()]
param(
    [ValidateSet('start', 'stop', 'restart', 'status', 'supervise')]
    [string]$Action = 'status',
    [switch]$Json
)

$ErrorActionPreference = 'Stop'

$LocalAddress = '127.0.0.1'
$LocalPort = 18010
$RemoteName = 'server-2'
$RemotePort = 8010
$Needle = "instabox port-forward $RemoteName $($LocalPort):$($RemotePort)"

$StateRoot = if ($env:LOCALAPPDATA) {
    Join-Path $env:LOCALAPPDATA 'Revora\dev'
} else {
    Join-Path $env:TEMP 'Revora-dev'
}
$PidFile = Join-Path $StateRoot 'whisper-tunnel.pid'
$SupervisorPidFile = Join-Path $StateRoot 'whisper-supervisor.pid'
$StopFile = Join-Path $StateRoot 'whisper-supervisor.stop'
$StateFile = Join-Path $StateRoot 'whisper-supervisor.state.json'
$SupervisorLog = Join-Path $StateRoot 'whisper-supervisor.log'
$SupervisorOut = Join-Path $StateRoot 'whisper-supervisor.out.log'
$SupervisorErr = Join-Path $StateRoot 'whisper-supervisor.err.log'
$OutLog = Join-Path $StateRoot 'whisper-tunnel.out.log'
$ErrLog = Join-Path $StateRoot 'whisper-tunnel.err.log'
$MutexName = 'Local\Revora.WhisperTunnel.Supervisor'

New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null

$script:RestartCount = 0
$script:StartedAt = (Get-Date).ToUniversalTime().ToString('o')
$script:LastError = $null

function Write-SupervisorLog {
    param([string]$Message)
    $line = '[' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + '] ' + $Message
    Add-Content -LiteralPath $SupervisorLog -Value $line -Encoding utf8
    try {
        $item = Get-Item -LiteralPath $SupervisorLog -ErrorAction Stop
        if ($item.Length -gt 1MB) {
            Move-Item -LiteralPath $SupervisorLog -Destination ($SupervisorLog + '.1') -Force
        }
    } catch { }
}

function Save-SupervisorState {
    param([string]$LastError)
    $state = [ordered]@{
        supervisor_pid = $PID
        started_at = $script:StartedAt
        restarts = $script:RestartCount
        last_error = $LastError
        updated_at = (Get-Date).ToUniversalTime().ToString('o')
    }
    try {
        Set-Content -LiteralPath $StateFile -Value ($state | ConvertTo-Json -Compress) -Encoding utf8
    } catch { }
}

function Get-CimProcess {
    param([int]$ProcessId)
    try {
        return Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    } catch {
        return $null
    }
}

function Get-TrackedSupervisor {
    if (-not (Test-Path -LiteralPath $SupervisorPidFile)) { return $null }
    $raw = Get-Content -LiteralPath $SupervisorPidFile -Raw -ErrorAction SilentlyContinue
    if ($null -eq $raw) { return $null }
    $pidValue = 0
    if (-not [int]::TryParse($raw.Trim(), [ref]$pidValue) -or $pidValue -le 0) { return $null }
    $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
    if ($null -eq $process) { return $null }
    $cim = Get-CimProcess -ProcessId $pidValue
    if ($null -eq $cim -or -not $cim.CommandLine) { return $null }
    if ($cim.CommandLine -notlike '*dev-whisper-tunnel.ps1*') { return $null }
    if ($cim.CommandLine -notlike '*supervise*') { return $null }
    return [pscustomobject]@{ ProcessId = $pidValue; CommandLine = $cim.CommandLine; Process = $process }
}

function Get-TrackedTunnel {
    if (-not (Test-Path -LiteralPath $PidFile)) { return $null }
    $raw = Get-Content -LiteralPath $PidFile -Raw -ErrorAction SilentlyContinue
    if ($null -eq $raw) { return $null }
    $pidValue = 0
    if (-not [int]::TryParse($raw.Trim(), [ref]$pidValue) -or $pidValue -le 0) { return $null }
    $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
    if ($null -eq $process) { return $null }
    $cim = Get-CimProcess -ProcessId $pidValue
    if ($null -eq $cim -or -not $cim.CommandLine) { return $null }
    if ($cim.CommandLine -notlike "*$Needle*") { return $null }
    return [pscustomobject]@{ ProcessId = $pidValue; CommandLine = $cim.CommandLine; Process = $process }
}

function Get-ListenerOwner {
    try {
        return (Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1 -ExpandProperty OwningProcess)
    } catch {
        return $null
    }
}

function Get-ListenerTunnelRoot {
    # If a tunnel parent was killed unexpectedly, its npx/instabox/ssh
    # descendants can keep listening. Walk the listener's parent chain and
    # return the highest ancestor whose command line is this exact forward.
    $owner = Get-ListenerOwner
    if ($null -eq $owner -or $owner -eq '') { return $null }
    $current = Get-CimProcess -ProcessId ([int]$owner)
    $candidate = $null
    $depth = 0
    while ($null -ne $current -and $depth -lt 12) {
        if ($current.CommandLine -and $current.CommandLine -like "*$Needle*") {
            $candidate = $current
        }
        $parentId = 0
        if (-not [int]::TryParse([string]$current.ParentProcessId, [ref]$parentId)) { break }
        if ($parentId -le 0 -or $parentId -eq [int]$current.ProcessId) { break }
        $current = Get-CimProcess -ProcessId $parentId
        $depth++
    }
    return $candidate
}

function Stop-OrphanedListener {
    # Stop only a listener whose ancestor chain proves it is this exact forward.
    $orphan = Get-ListenerTunnelRoot
    if ($null -eq $orphan) { return $false }
    & taskkill.exe /PID $orphan.ProcessId /T /F 2>$null | Out-Null
    for ($i = 0; $i -lt 10; $i++) {
        if (-not (Test-TunnelListener)) { break }
        Start-Sleep -Milliseconds 200
    }
    if (Test-Path -LiteralPath $PidFile) { Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue }
    return $true
}

function Test-TunnelListener {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync($LocalAddress, $LocalPort)
        if (-not $task.Wait(1500)) { return $false }
        return $client.Connected
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Get-TunnelHttpStatus {
    $url = "http://$($LocalAddress):$($LocalPort)/health"
    try {
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 4 -ErrorAction Stop
        return [int]$response.StatusCode
    } catch {
        $response = $_.Exception.Response
        if ($null -eq $response) { return $null }
        try { return [int]$response.StatusCode } catch { }
        try { return [int]$response.StatusCode.value__ } catch { }
        return $null
    }
}

function Test-TunnelRoundTrip {
    $status = Get-TunnelHttpStatus
    return ($status -eq 200 -or $status -eq 401)
}

function Test-TunnelHealthy {
    if (-not (Test-TunnelListener)) { return $false }
    return (Test-TunnelRoundTrip)
}

function Stop-TunnelProcess {
    param($Tracked)
    if ($null -eq $Tracked) { return }
    if (Get-Process -Id $Tracked.ProcessId -ErrorAction SilentlyContinue) {
        & taskkill.exe /PID $Tracked.ProcessId /T /F 2>$null | Out-Null
        Start-Sleep -Milliseconds 500
    }
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}

function Start-TunnelProcess {
    if (Test-TunnelListener) {
        throw "Port $LocalPort is already listening but no tunnel started by this supervisor owns it. Refusing to create a duplicate."
    }
    if (Test-Path -LiteralPath $PidFile) { Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue }
    $arguments = '/d /s /c "npx -y ' + $Needle + '"'
    $process = Start-Process -FilePath $env:ComSpec -ArgumentList $arguments -WindowStyle Hidden -PassThru -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog
    Set-Content -LiteralPath $PidFile -Value $process.Id -Encoding ascii
    for ($i = 0; $i -lt 40; $i++) {
        if (Test-TunnelHealthy) { return $process }
        if ($process.HasExited) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $process.HasExited) { & taskkill.exe /PID $process.Id /T /F 2>$null | Out-Null }
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    $detail = ''
    if (Test-Path -LiteralPath $ErrLog) {
        $detail = (Get-Content -LiteralPath $ErrLog -Tail 20 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
    }
    throw ("Tunnel did not become healthy. See $OutLog and $ErrLog." + [Environment]::NewLine + $detail)
}

function Invoke-Supervisor {
    $mutex = New-Object System.Threading.Mutex($false, $MutexName)
    $acquired = $false
    try {
        try { $acquired = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $acquired = $true }
        if (-not $acquired) { return }
        Set-Content -LiteralPath $SupervisorPidFile -Value $PID -Encoding ascii
        Remove-Item -LiteralPath $StopFile -Force -ErrorAction SilentlyContinue
        $script:StartedAt = (Get-Date).ToUniversalTime().ToString('o')
        $script:RestartCount = 0
        $script:LastError = $null
        Save-SupervisorState -LastError $null
        Write-SupervisorLog 'supervisor started'
        $failureCount = 0
        $connectivityFailures = 0
        $startedSuccessfully = $false
        while (-not (Test-Path -LiteralPath $StopFile)) {
            $tracked = Get-TrackedTunnel
            $listening = Test-TunnelListener
            if ($tracked -and $listening -and (Test-TunnelRoundTrip)) {
                if ($failureCount -gt 0 -or $connectivityFailures -gt 0) { Write-SupervisorLog 'tunnel healthy again' }
                $failureCount = 0
                $connectivityFailures = 0
                Start-Sleep -Seconds 5
                continue
            }
            if ($listening -and -not $tracked) {
                $orphan = Get-ListenerTunnelRoot
                if ($null -ne $orphan) {
                    Write-SupervisorLog ('orphaned tunnel tree found at PID ' + $orphan.ProcessId + '; stopping it before recovery')
                    Stop-OrphanedListener | Out-Null
                }
                if (Test-TunnelListener) {
                    $owner = Get-ListenerOwner
                    $script:LastError = "Port $LocalPort is owned by untracked PID $owner"
                    Save-SupervisorState -LastError $script:LastError
                    Write-SupervisorLog ($script:LastError + '; refusing to duplicate or kill it')
                    Start-Sleep -Seconds 15
                    continue
                }
            }
            if ($tracked) {
                if ($listening) {
                    $connectivityFailures++
                    if ($connectivityFailures -lt 2) {
                        Write-SupervisorLog 'tunnel HTTP probe failed once; retrying before recycling'
                        Start-Sleep -Seconds 2
                        continue
                    }
                    Write-SupervisorLog ('tunnel HTTP probe failed ' + $connectivityFailures + ' times; recycling')
                } else {
                    Write-SupervisorLog 'tunnel listener disappeared; recycling'
                }
                Stop-TunnelProcess -Tracked $tracked
            }
            $failureCount++
            try {
                Start-TunnelProcess | Out-Null
                if ($startedSuccessfully) { $script:RestartCount++ }
                $startedSuccessfully = $true
                $script:LastError = $null
                Save-SupervisorState -LastError $null
                Write-SupervisorLog ('tunnel started (pid ' + (Get-Content -LiteralPath $PidFile -Raw).Trim() + ')')
                $failureCount = 0
                $connectivityFailures = 0
            } catch {
                $script:LastError = $_.Exception.Message
                Save-SupervisorState -LastError $script:LastError
                Write-SupervisorLog ('tunnel start failed: ' + $script:LastError)
                $delay = [Math]::Min(60, [Math]::Pow(2, [Math]::Min($failureCount, 6)))
                Write-SupervisorLog ('retrying in ' + [int]$delay + ' seconds')
                Start-Sleep -Seconds ([int]$delay)
            }
        }
    } finally {
        Write-SupervisorLog 'supervisor stopping'
        $tracked = Get-TrackedTunnel
        Stop-TunnelProcess -Tracked $tracked
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $SupervisorPidFile -Force -ErrorAction SilentlyContinue
        if ($acquired) { try { $mutex.ReleaseMutex() } catch { } }
        $mutex.Dispose()
    }
}

function Start-Supervisor {
    $existing = Get-TrackedSupervisor
    if ($existing) {
        if (Test-TunnelHealthy) {
            Write-Host "Supervisor is already running (PID $($existing.ProcessId)); tunnel is healthy."
            return
        }
        Write-Host "Supervisor is running (PID $($existing.ProcessId)); waiting for recovery."
        for ($i = 0; $i -lt 40; $i++) {
            if (Test-TunnelHealthy) { return }
            Start-Sleep -Milliseconds 500
        }
        throw "Supervisor PID $($existing.ProcessId) is alive, but the tunnel did not become healthy."
    }
    Remove-Item -LiteralPath $StopFile -Force -ErrorAction SilentlyContinue
    $oldTunnel = Get-TrackedTunnel
    if ($oldTunnel) { Stop-TunnelProcess -Tracked $oldTunnel }
    if (Test-TunnelListener) {
        $orphan = Get-ListenerTunnelRoot
        if ($null -ne $orphan) {
            Write-Host "Stopping an orphaned tunnel tree (PID $($orphan.ProcessId)) left by a previous supervisor."
            Stop-OrphanedListener | Out-Null
        }
    }
    if (Test-TunnelListener) {
        $owner = Get-ListenerOwner
        throw "Port $LocalPort is already listening (PID $owner) but was not started by this supervisor. Refusing to create a duplicate."
    }
    Remove-Item -LiteralPath $SupervisorPidFile -Force -ErrorAction SilentlyContinue
    $arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" supervise'
    $supervisor = Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -WindowStyle Hidden -PassThru -RedirectStandardOutput $SupervisorOut -RedirectStandardError $SupervisorErr
    Set-Content -LiteralPath $SupervisorPidFile -Value $supervisor.Id -Encoding ascii
    for ($i = 0; $i -lt 60; $i++) {
        $trackedSupervisor = Get-TrackedSupervisor
        if ($trackedSupervisor -and (Test-TunnelHealthy)) {
            Write-Host "Supervisor started (PID $($supervisor.Id)); tunnel is healthy."
            return
        }
        if ($supervisor.HasExited) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $supervisor.HasExited) { & taskkill.exe /PID $supervisor.Id /T /F 2>$null | Out-Null }
    Remove-Item -LiteralPath $SupervisorPidFile -Force -ErrorAction SilentlyContinue
    $detail = ''
    if (Test-Path -LiteralPath $SupervisorLog) {
        $detail = (Get-Content -LiteralPath $SupervisorLog -Tail 20 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
    }
    throw ("Whisper tunnel supervisor did not start. See $SupervisorLog and $SupervisorErr." + [Environment]::NewLine + $detail)
}

function Stop-Supervisor {
    $supervisor = Get-TrackedSupervisor
    if ($supervisor) {
        Set-Content -LiteralPath $StopFile -Value ((Get-Date).ToUniversalTime().ToString('o')) -Encoding utf8
        for ($i = 0; $i -lt 40; $i++) {
            if (-not (Get-Process -Id $supervisor.ProcessId -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Milliseconds 250
        }
        if (Get-Process -Id $supervisor.ProcessId -ErrorAction SilentlyContinue) {
            Write-Warning "Supervisor PID $($supervisor.ProcessId) did not stop gracefully; terminating the verified supervisor tree."
            & taskkill.exe /PID $supervisor.ProcessId /T /F 2>$null | Out-Null
        }
        Remove-Item -LiteralPath $SupervisorPidFile -Force -ErrorAction SilentlyContinue
    } else {
        if (Test-Path -LiteralPath $SupervisorPidFile) { Remove-Item -LiteralPath $SupervisorPidFile -Force }
    }
    $tracked = Get-TrackedTunnel
    if ($tracked) { Stop-TunnelProcess -Tracked $tracked }
    if (Test-TunnelListener) { Stop-OrphanedListener | Out-Null }
    if (Test-TunnelListener) { Write-Warning "Port $LocalPort is still listening after stopping the managed tunnel." }
    else { Write-Host 'Whisper tunnel supervisor and tunnel are stopped.' }
}

function Show-Status {
    $supervisor = Get-TrackedSupervisor
    $tracked = Get-TrackedTunnel
    $listening = Test-TunnelListener
    $httpOk = Test-TunnelRoundTrip
    $owner = Get-ListenerOwner
    $state = 'stopped'
    if ($supervisor -and $tracked -and $listening -and $httpOk) { $state = 'running' }
    elseif ($supervisor) { $state = 'supervising/degraded' }
    elseif ($listening) { $state = 'listening, but not started by this supervisor' }
    $restarts = $null
    $lastError = $null
    if (Test-Path -LiteralPath $StateFile) {
        try {
            $saved = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
            $restarts = $saved.restarts
            $lastError = $saved.last_error
        } catch { }
    }
    $result = [pscustomobject]@{
        State = $state
        LocalEndpoint = "http://$($LocalAddress):$($LocalPort)"
        RemoteDestination = "$($RemoteName):$($RemotePort)"
        Listener = $listening
        HttpHealthy = $httpOk
        SupervisorPid = if ($supervisor) { $supervisor.ProcessId } else { $null }
        TunnelPid = if ($tracked) { $tracked.ProcessId } else { $null }
        ListenerOwnerPid = if ($null -ne $owner -and $owner -ne '') { [int]$owner } else { $null }
        Restarts = $restarts
        LastError = $lastError
        PidFile = $PidFile
        SupervisorPidFile = $SupervisorPidFile
        SupervisorLog = $SupervisorLog
        OutLog = $OutLog
        ErrorLog = $ErrLog
    }
    if ($Json) { $result | ConvertTo-Json -Depth 4 } else { $result | Format-List }
}

try {
    switch ($Action) {
        'start' { Start-Supervisor; if (-not $Json) { Show-Status } }
        'stop' { Stop-Supervisor; if ($Json) { Show-Status } }
        'restart' { Stop-Supervisor; Start-Sleep -Milliseconds 500; Start-Supervisor; if (-not $Json) { Show-Status } }
        'status' { Show-Status }
        'supervise' { Invoke-Supervisor }
    }
} catch {
    Write-Error $_.Exception.Message
    exit 1
}
