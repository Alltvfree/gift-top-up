<#
.SYNOPSIS
    One-shot setup for the Tilly MT5 bridge on a fresh Windows VPS.

.DESCRIPTION
    Run this ONCE per client VPS, as Administrator, after MetaTrader 5 is
    installed on the box (this script does not install MT5 itself — the
    terminal has its own installer per broker). It installs Python if
    missing, installs the bridge's Python dependencies, generates an API
    key, writes a launcher script with the MT5 login baked in (so the
    terminal logs in automatically — no manual "log in and leave it open"
    step), and registers a Scheduled Task so the bridge survives reboots.

    Written for a Windows VPS the platform operator provisions and
    controls per client (client hands over MT5 login/password, never runs
    anything themselves) — not for a client's own PC. Same "written but
    not run against a live box" caveat as bridge.py itself: this was
    authored and reviewed, not executed, since this environment has no
    Windows machine to test against. Dry-run it on a throwaway VPS with a
    demo account before trusting it with a live one.

.PARAMETER Mt5Login
    The MT5 account number (login) to auto-connect on startup.

.PARAMETER Mt5Password
    The MT5 account's investor or master password.

.PARAMETER Mt5Server
    The broker's MT5 server name, e.g. "Exness-MT5Real8".

.PARAMETER Mt5Path
    Optional path to terminal64.exe, if it's not the default MT5 install
    location and isn't already on PATH.

.PARAMETER InstallDir
    Where to place run-bridge.ps1 and the generated env file. Defaults to
    this script's own folder (i.e. run it from inside mt5-bridge/).

.EXAMPLE
    .\install-windows.ps1 -Mt5Login 414312080 -Mt5Password "secret" -Mt5Server "Exness-MT5Real8"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Mt5Login,

    [Parameter(Mandatory = $true)]
    [string]$Mt5Password,

    [Parameter(Mandatory = $true)]
    [string]$Mt5Server,

    [string]$Mt5Path = "",

    [string]$InstallDir = $PSScriptRoot,

    [int]$Port = 8787,

    [string]$TaskName = "TillyMT5Bridge"
)

$ErrorActionPreference = "Stop"

function Assert-Admin {
    $current = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($current)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this script from an elevated (Administrator) PowerShell window."
    }
}

function Ensure-Python {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if ($py) {
        Write-Host "Python found: $($py.Source)"
        return $py.Source
    }

    Write-Host "Python not found — downloading the official installer..."
    $installerUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    $installerPath = Join-Path $env:TEMP "python-3.11.9-amd64.exe"
    Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing

    Write-Host "Installing Python 3.11 (silent, all users, added to PATH)..."
    $proc = Start-Process -FilePath $installerPath -ArgumentList @(
        "/quiet", "InstallAllUsers=1", "PrependPath=1", "Include_test=0"
    ) -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        throw "Python installer exited with code $($proc.ExitCode)."
    }

    # The installer updates the machine PATH, but this process's own PATH
    # snapshot is stale — reload it from the registry so `python` resolves
    # for the rest of this script without requiring a new shell.
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"

    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) {
        throw "Python installed but not resolvable on PATH — open a new PowerShell window and re-run this script."
    }
    Write-Host "Python installed: $($py.Source)"
    return $py.Source
}

function New-ApiKey {
    $bytes = [System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32)
    return [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

Assert-Admin

Write-Host "== Tilly MT5 bridge installer ==" -ForegroundColor Cyan

$pythonExe = Ensure-Python

Write-Host "Installing Python dependencies..."
$requirementsPath = Join-Path $PSScriptRoot "requirements.txt"
& $pythonExe -m pip install --upgrade pip --quiet
& $pythonExe -m pip install -r $requirementsPath --quiet
if ($LASTEXITCODE -ne 0) {
    throw "pip install failed — check the output above."
}

$apiKey = New-ApiKey
Write-Host "Generated bridge API key: $apiKey" -ForegroundColor Yellow
Write-Host "(save this — you'll paste it into Tilly's Account page + BRIDGE form)"

# A small PS1 launcher, not a plain .env file: the Scheduled Task action
# below invokes this directly, so the MT5 credentials never need to touch
# machine-wide environment variables (which require a logoff/login cycle
# to propagate) or get typed in twice.
$launcherPath = Join-Path $InstallDir "run-bridge.ps1"
$launcherContent = @"
# Generated by install-windows.ps1 — safe to re-run the installer to regenerate.
`$env:MT5_BRIDGE_API_KEY = "$apiKey"
`$env:MT5_LOGIN = "$Mt5Login"
`$env:MT5_PASSWORD = "$Mt5Password"
`$env:MT5_SERVER = "$Mt5Server"
$(if ($Mt5Path) { "`$env:MT5_PATH = `"$Mt5Path`"" })
Set-Location "$PSScriptRoot"
& "$pythonExe" -m uvicorn bridge:app --host 0.0.0.0 --port $Port
"@
Set-Content -Path $launcherPath -Value $launcherContent -Encoding UTF8
Write-Host "Wrote launcher: $launcherPath"

# --- Scheduled Task -------------------------------------------------------
# LogonType Interactive, not a true service: MetaTrader5.initialize() talks
# to the terminal over local IPC, which only works inside the same
# interactive desktop session (Session 0 isolation breaks it for a real
# Windows service — confirmed the hard way on the operator's own PC before
# this script existed). On a VPS: leave this account's session active by
# disconnecting your RDP client rather than logging off — logging off ends
# the session and kills the task with it.
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$launcherPath`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal | Out-Null
Write-Host "Registered Scheduled Task '$TaskName' (starts at logon, restarts on failure)."

Write-Host "Starting the bridge now..."
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 5

try {
    $health = Invoke-RestMethod -Uri "http://localhost:$Port/health" `
        -Headers @{ Authorization = "Bearer $apiKey" } -TimeoutSec 10
    Write-Host "Bridge is up: $($health | ConvertTo-Json -Compress)" -ForegroundColor Green
} catch {
    Write-Warning "Bridge did not respond on :$Port within 5s. Check Task Scheduler > $TaskName > History, and confirm MT5 is installed and 'Algo Trading' is enabled in the terminal."
}

Write-Host ""
Write-Host "== Next step ==" -ForegroundColor Cyan
Write-Host "Run setup-tunnel.ps1 to expose this bridge over a permanent HTTPS URL,"
Write-Host "then paste that URL + this API key into Tilly's Account page -> + BRIDGE."
Write-Host "API key (save it now): $apiKey" -ForegroundColor Yellow
