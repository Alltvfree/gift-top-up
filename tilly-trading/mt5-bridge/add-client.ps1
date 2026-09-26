<#
.SYNOPSIS
    Add one more client's MT5 account to a shared VPS's bridge fleet.

.DESCRIPTION
    Run this once per client, after bootstrap-vps.ps1 has already set up
    Python/cloudflared on this VPS. The MetaTrader5 Python package can only
    attach to ONE terminal per process, so running several clients on one
    box means giving each of them their own COPY of the MT5 terminal in
    its own folder — MetaTrader derives its per-install data directory
    (login, settings, cache) from the install path, so two copies in two
    different folders are fully isolated from each other automatically,
    with no special "portable" flag needed. This script clones a
    "master" terminal install you've already placed on the VPS into
    terminals\<ClientSlug>\, then starts a dedicated bridge.py process for
    it on its own port, registered as its own Scheduled Task.

    Same caveat as the rest of this bridge: written and reviewed (checked
    for balanced braces/parens, matches the Task Scheduler pattern already
    confirmed working on a real box earlier in this project), not executed
    against a live Windows machine — this sandbox has none. Dry-run with a
    demo account before trusting it with a live one.

.PARAMETER ClientSlug
    Short, URL-safe identifier for this client, e.g. "acme". Used as the
    folder name, Scheduled Task name suffix, and (later) the tunnel
    subdomain — keep it consistent with what you pass to setup-tunnel.ps1.

.PARAMETER Mt5Login
    This client's MT5 account number.

.PARAMETER Mt5Password
    This client's MT5 investor or master password.

.PARAMETER Mt5Server
    This client's broker MT5 server name, e.g. "Exness-MT5Real8".

.PARAMETER MasterTerminalDir
    Path to an already-installed MT5 terminal folder (containing
    terminal64.exe) matching this client's broker, e.g.
    "C:\MT5-Master-Exness". This script copies it — it never modifies the
    master, so the same master can seed any number of clients on the same
    broker.

.PARAMETER Port
    Local port for this client's bridge. Omit to auto-pick the next free
    port starting at 8787 (tracked via each client's port.txt).

.PARAMETER BridgeDir
    Folder containing bridge.py. Defaults to this script's own folder.

.EXAMPLE
    .\add-client.ps1 -ClientSlug "acme" -Mt5Login "12345678" -Mt5Password "secret" -Mt5Server "Exness-MT5Real8" -MasterTerminalDir "C:\MT5-Master-Exness"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ClientSlug,

    [Parameter(Mandatory = $true)]
    [string]$Mt5Login,

    [Parameter(Mandatory = $true)]
    [string]$Mt5Password,

    [Parameter(Mandatory = $true)]
    [string]$Mt5Server,

    [Parameter(Mandatory = $true)]
    [string]$MasterTerminalDir,

    [int]$Port = 0,

    [string]$BridgeDir = $PSScriptRoot
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

Assert-Admin

Write-Host "== Adding client '$ClientSlug' to this VPS's bridge fleet ==" -ForegroundColor Cyan

$pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pythonExe) {
    throw "Python not found — run bootstrap-vps.ps1 on this VPS first."
}

if (-not (Test-Path (Join-Path $MasterTerminalDir "terminal64.exe"))) {
    throw "No terminal64.exe found in $MasterTerminalDir — install that broker's MT5 terminal there first."
}

$clientsDir = Join-Path $BridgeDir "clients"
$terminalsDir = Join-Path $BridgeDir "terminals"
New-Item -ItemType Directory -Path $clientsDir -Force | Out-Null
New-Item -ItemType Directory -Path $terminalsDir -Force | Out-Null

$clientDir = Join-Path $clientsDir $ClientSlug
if (Test-Path $clientDir) {
    throw "clients\$ClientSlug already exists — pick a different -ClientSlug, or remove that folder and its Scheduled Task first if you're re-adding this client."
}

if ($Port -eq 0) {
    $Port = Find-FreePort -StartPort 8787 -ClientsDir $clientsDir
}
Write-Host "Assigned port: $Port"

$terminalDest = Join-Path $terminalsDir $ClientSlug
Write-Host "Cloning MT5 terminal into an isolated copy at $terminalDest ..."
Copy-Item -Path $MasterTerminalDir -Destination $terminalDest -Recurse
$terminalExe = Join-Path $terminalDest "terminal64.exe"
if (-not (Test-Path $terminalExe)) {
    throw "Copy succeeded but terminal64.exe is missing at $terminalExe — check $MasterTerminalDir."
}

$apiKey = New-ApiKey
Write-Host "Generated bridge API key: $apiKey" -ForegroundColor Yellow
Write-Host "(save this — you'll paste it into Tilly's Account page + BRIDGE form for this client)"

New-Item -ItemType Directory -Path $clientDir -Force | Out-Null
Set-Content -Path (Join-Path $clientDir "port.txt") -Value $Port -NoNewline

# A small PS1 launcher, not a plain .env file: the Scheduled Task action
# below invokes this directly, so per-client MT5 credentials and API keys
# never need to touch machine-wide environment variables (which several
# clients on one box would otherwise collide over).
$launcherPath = Join-Path $clientDir "run-bridge.ps1"
$launcherContent = @"
# Generated by add-client.ps1 for client '$ClientSlug' — safe to re-run add-client.ps1 to regenerate.
`$env:MT5_BRIDGE_API_KEY = "$apiKey"
`$env:MT5_LOGIN = "$Mt5Login"
`$env:MT5_PASSWORD = "$Mt5Password"
`$env:MT5_SERVER = "$Mt5Server"
`$env:MT5_PATH = "$terminalExe"
Set-Location "$BridgeDir"
& "$pythonExe" -m uvicorn bridge:app --host 0.0.0.0 --port $Port
"@
Set-Content -Path $launcherPath -Value $launcherContent -Encoding UTF8
Write-Host "Wrote launcher: $launcherPath"

$taskName = "TillyMT5Bridge-$ClientSlug"
Register-InteractiveTask -TaskName $taskName -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$launcherPath`""
Write-Host "Registered Scheduled Task '$taskName' (starts at logon, restarts on failure)."

Write-Host "Starting this client's bridge now..."
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 5

try {
    $health = Invoke-RestMethod -Uri "http://localhost:$Port/health" `
        -Headers @{ Authorization = "Bearer $apiKey" } -TimeoutSec 10
    Write-Host "Bridge is up: $($health | ConvertTo-Json -Compress)" -ForegroundColor Green
} catch {
    Write-Warning "Bridge did not respond on :$Port within 5s. Check Task Scheduler > $taskName > History, and confirm this client's MT5 login/password/server are correct and 'Algo Trading' would be enabled once logged in."
}

Write-Host ""
Write-Host "== Next step ==" -ForegroundColor Cyan
Write-Host "Give this client a permanent HTTPS URL:"
Write-Host "  .\setup-tunnel.ps1 -ClientSlug ""$ClientSlug"" -Domain ""bridges.yourdomain.com"" -Port $Port"
Write-Host "Then paste that URL + this API key into Tilly's Account page -> + BRIDGE."
Write-Host "API key (save it now): $apiKey" -ForegroundColor Yellow
