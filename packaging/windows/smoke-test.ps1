<#
.SYNOPSIS
    Launches a built/installed CHIRP.exe, confirms it stays alive long
    enough to finish wxPython initialization, then closes it cleanly.
    Also runs the bundled CHIRP-driver-check.exe helper to confirm radio
    drivers registered correctly inside the frozen bundle.

.DESCRIPTION
    This is a STARTUP smoke test only -- it confirms the process launches,
    survives past the wx App/MainLoop initialization window, and exits
    cleanly. It does not exercise any interactive GUI functionality
    (opening files, talking to a radio, etc.); do not treat a pass here
    as proof the GUI works beyond "it starts."

    Used identically for the portable ZIP's extracted CHIRP.exe and for
    an Inno Setup-installed CHIRP.exe -- same script, same checks, so
    there is one implementation of "does CHIRP start" rather than two.

.PARAMETER ExeDir
    Directory containing CHIRP.exe (and, alongside it,
    CHIRP-driver-check.exe).

.PARAMETER ConfigDir
    Isolated --config-dir passed to CHIRP.exe, so the smoke test never
    touches a real user's ~\.chirp config, and reruns don't inherit state
    from a previous smoke test.

.PARAMETER TimeoutSeconds
    How long to wait after launch before checking the process is still
    alive (wxPython initialization + first-run config write takes a few
    seconds; this is not a fixed sleep before giving up, just before the
    first liveness check).

.EXAMPLE
    .\packaging\windows\smoke-test.ps1 -ExeDir dist\CHIRP -ConfigDir $env:TEMP\chirp-smoke-portable

.EXAMPLE
    .\packaging\windows\smoke-test.ps1 -ExeDir "$env:LOCALAPPDATA\Programs\CHIRP" -ConfigDir $env:TEMP\chirp-smoke-installed
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ExeDir,
    [Parameter(Mandatory = $true)][string]$ConfigDir,
    [int]$TimeoutSeconds = 20
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$exePath = Join-Path $ExeDir 'CHIRP.exe'
$driverCheckPath = Join-Path $ExeDir 'CHIRP-driver-check.exe'

if (-not (Test-Path $exePath)) {
    throw "CHIRP.exe not found at $exePath"
}

# --- Driver registry check (runs inside the frozen bundle) ---------------
if (-not (Test-Path $driverCheckPath)) {
    throw "CHIRP-driver-check.exe not found at $driverCheckPath -- " +
          "driver-discovery validation cannot run."
}
Write-Host "==> Running driver-registry check: $driverCheckPath"
$driverOutput = & $driverCheckPath 2>&1
$driverExit = $LASTEXITCODE
Write-Host $driverOutput
if ($driverExit -ne 0) {
    throw "CHIRP-driver-check.exe exited $driverExit -- radio driver discovery failed inside the frozen bundle."
}
if (-not ($driverOutput -match 'DRIVER_COUNT=(\d+)')) {
    throw "CHIRP-driver-check.exe did not print a DRIVER_COUNT line."
}
$driverCount = [int]$Matches[1]
if ($driverCount -le 0) {
    throw "Frozen bundle registered zero radio drivers."
}
Write-Host "Driver registry OK: $driverCount driver(s) registered." -ForegroundColor Green

# --- GUI launch smoke test -------------------------------------------------
if (Test-Path $ConfigDir) { Remove-Item -Recurse -Force $ConfigDir }
New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
$logPath = Join-Path $ConfigDir 'smoke-test-stderr.log'

Write-Host "==> Launching $exePath with isolated --config-dir $ConfigDir"
$proc = Start-Process -FilePath $exePath `
    -ArgumentList @('--config-dir', $ConfigDir) `
    -PassThru -RedirectStandardError $logPath

Start-Sleep -Seconds $TimeoutSeconds

if ($proc.HasExited) {
    $log = if (Test-Path $logPath) { Get-Content $logPath -Raw } else { '(no stderr captured)' }
    throw "CHIRP.exe exited on its own within $TimeoutSeconds seconds " +
          "(exit code $($proc.ExitCode)) -- treating this as a startup " +
          "failure (missing-DLL, import error, or immediate crash). " +
          "Captured stderr:`n$log"
}
Write-Host "CHIRP.exe is alive after $TimeoutSeconds seconds (PID $($proc.Id))." -ForegroundColor Green

Write-Host "==> Closing CHIRP.exe cleanly"
try {
    $proc.CloseMainWindow() | Out-Null
    if (-not $proc.WaitForExit(10000)) {
        Write-Warning "CloseMainWindow did not exit the process within 10s; force-stopping."
        Stop-Process -Id $proc.Id -Force
    }
}
catch {
    Write-Warning "CloseMainWindow failed ($_); force-stopping."
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
}

if (Test-Path $logPath) {
    $log = Get-Content $logPath -Raw
    if ($log -match 'Traceback|ImportError|ModuleNotFoundError|DLL load failed') {
        throw "CHIRP.exe stayed alive but logged an error signature during the smoke-test window:`n$log"
    }
}

Write-Host "Smoke test passed: $exePath" -ForegroundColor Green
exit 0
