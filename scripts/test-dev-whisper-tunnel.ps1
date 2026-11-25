<#
.SYNOPSIS
    Integration checks for the local Revora Whisper tunnel supervisor.

.DESCRIPTION
    Exercises the real detached supervisor: idempotent start, crash recovery,
    clean stop, and a second start. It leaves the managed tunnel running.
    Run from the repository root with Windows PowerShell.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ScriptPath = Join-Path $PSScriptRoot 'dev-whisper-tunnel.ps1'
if (-not (Test-Path -LiteralPath $ScriptPath)) { throw "Missing $ScriptPath" }

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "ASSERTION FAILED: $Message" }
    Write-Host "PASS: $Message"
}

function Invoke-TunnelAction {
    param([string]$Action)
    $outFile = Join-Path $env:TEMP ("revora-tunnel-test-{0}.out" -f [guid]::NewGuid().ToString('N'))
    $errFile = Join-Path $env:TEMP ("revora-tunnel-test-{0}.err" -f [guid]::NewGuid().ToString('N'))
    try {
        $process = Start-Process -FilePath 'powershell.exe' -ArgumentList ('-NoProfile -ExecutionPolicy Bypass -File "' + $ScriptPath + '" ' + $Action) -WindowStyle Hidden -PassThru -RedirectStandardOutput $outFile -RedirectStandardError $errFile
        for ($i = 0; $i -lt 120; $i++) {
            if ($process.HasExited) { break }
            Start-Sleep -Milliseconds 500
        }
        if (-not $process.HasExited) {
            try { & taskkill.exe /PID $process.Id /T /F 2>$null | Out-Null } catch { }
            throw "$Action timed out after 60 seconds"
        }
        $stdout = if (Test-Path -LiteralPath $outFile) { Get-Content -LiteralPath $outFile -Raw } else { '' }
        $stderr = if (Test-Path -LiteralPath $errFile) { Get-Content -LiteralPath $errFile -Raw } else { '' }
        $process.WaitForExit()
        $exitCode = $process.ExitCode
        if ($null -ne $exitCode -and $exitCode -ne 0) { throw "$Action failed (exit $exitCode): $stderr $stdout" }
        return $stdout
    } finally {
        Remove-Item -LiteralPath $outFile, $errFile -Force -ErrorAction SilentlyContinue
    }
}

function Get-TunnelStatus {
    $raw = Invoke-TunnelAction -Action 'status -Json'
    $json = $raw.Trim()
    if (-not $json.StartsWith('{')) {
        $start = $json.IndexOf('{')
        if ($start -lt 0) { throw "Status was not JSON: $json" }
        $json = $json.Substring($start)
    }
    return ($json | ConvertFrom-Json)
}

function Wait-ForRunning {
    param($DifferentTunnelPid = $null, [int]$TimeoutSeconds = 30)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $last = $null
    while ((Get-Date) -lt $deadline) {
        $last = Get-TunnelStatus
        if ($last.State -eq 'running' -and $last.HttpHealthy) {
            if ($null -eq $DifferentTunnelPid -or $last.TunnelPid -ne $DifferentTunnelPid) { return $last }
        }
        Start-Sleep -Milliseconds 500
    }
    throw ("Tunnel did not become healthy in time. Last status: " + ($last | ConvertTo-Json -Compress))
}

try {
    Write-Host '1. Start supervisor'
    Invoke-TunnelAction -Action 'start' | Out-Null
    $first = Wait-ForRunning
    Assert-True ($null -ne $first.SupervisorPid) 'supervisor PID is tracked'
    Assert-True ($null -ne $first.TunnelPid) 'tunnel PID is tracked'
    Assert-True ($first.Listener -and $first.HttpHealthy) 'listener and real HTTP path are healthy'

    Write-Host '2. Start again (must not duplicate)'
    Invoke-TunnelAction -Action 'start' | Out-Null
    $second = Get-TunnelStatus
    Assert-True ($second.SupervisorPid -eq $first.SupervisorPid) 'second start kept the same supervisor'
    Assert-True ($second.TunnelPid -eq $first.TunnelPid) 'second start kept the same tunnel process'

    Write-Host '3. Kill the tunnel process (supervisor must recover)'
    & taskkill.exe /PID $first.TunnelPid /T /F 2>$null | Out-Null
    $recovered = Wait-ForRunning -DifferentTunnelPid $first.TunnelPid -TimeoutSeconds 45
    Assert-True ($recovered.SupervisorPid -eq $first.SupervisorPid) 'same supervisor recovered the tunnel'
    Assert-True ($recovered.TunnelPid -ne $first.TunnelPid) 'a new tunnel process was started'
    Assert-True ($recovered.Restarts -ge 1) 'restart count increased'

    Write-Host '4. Kill only the tunnel parent (orphan child must be recovered)'
    Stop-Process -Id $recovered.TunnelPid -Force
    $orphanRecovered = Wait-ForRunning -DifferentTunnelPid $recovered.TunnelPid -TimeoutSeconds 60
    Assert-True ($orphanRecovered.SupervisorPid -eq $recovered.SupervisorPid) 'same supervisor recovered an orphaned tunnel'
    Assert-True ($orphanRecovered.TunnelPid -ne $recovered.TunnelPid) 'orphaned tunnel was replaced'
    Assert-True ($orphanRecovered.Restarts -ge 2) 'restart count increased again'
    Assert-True ($orphanRecovered.State -eq 'running') 'state is running after orphan recovery'

    Write-Host '5. Stop supervisor and tunnel'
    Invoke-TunnelAction -Action 'stop' | Out-Null
    $stopped = Get-TunnelStatus
    Assert-True ($stopped.State -eq 'stopped') 'status is stopped'
    Assert-True (-not $stopped.Listener) 'no listener remains'
    Assert-True ($null -eq $stopped.SupervisorPid) 'no supervisor remains'
    Assert-True ($null -eq $stopped.TunnelPid) 'no tracked tunnel remains'

    Write-Host '6. Start again after a clean stop'
    Invoke-TunnelAction -Action 'start' | Out-Null
    $final = Wait-ForRunning
    Assert-True ($final.State -eq 'running') 'tunnel is running again'
    Assert-True ($final.HttpHealthy) 'real HTTP path is healthy again'
    Write-Host ''
    Write-Host ('All tunnel supervisor checks passed. Supervisor PID ' + $final.SupervisorPid + ', tunnel PID ' + $final.TunnelPid + '.')
} catch {
    Write-Error $_.Exception.Message
    exit 1
}
