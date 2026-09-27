<#
.SYNOPSIS
    Set up Kronos on the same shared VPS as the MT5 bridge clients, using
    its own isolated MT5 terminal copy.

.DESCRIPTION
    Run once, after tilly-trading/mt5-bridge/bootstrap-vps.ps1 on this VPS.
    Same reasoning as add-client.ps1: MetaTrader5's Python package can only
    attach to ONE terminal per process. Kronos runs in its own process
    (separate from any client's bridge.py), so it needs its own terminal
    copy too — pointing it at a terminal another process already manages
    would reintroduce, across processes this time, the exact race that
    bridge.py's own in-process _mt5_lock exists to prevent (a lock inside
    one process can't protect against a second process calling into the
    same terminal's IPC channel at the same time).

    This script only sets up the machinery — it does NOT train a model or
    start live inference. Training is a one-off, interactive step you run
    yourself (see the printed next-steps at the end): it needs you to pick
    TP/SL parameters and read the printed test metrics before trusting the
    result, which isn't something to bake into an unattended script.

    Unlike a bridge or tunnel, Kronos never needs to be reached FROM the
    internet — it only makes outbound calls (to MT5 locally, to Supabase)
    — so there's no Cloudflare tunnel step here.

    Same caveat as every other script in this project: written and
    reviewed carefully, not executed against a live Windows box — this
    sandbox has none. Dry-run on a throwaway VPS first.

.PARAMETER Mt5Login
    MT5 login Kronos uses to read market data. This can be the SAME login
    as one of your clients' bridge accounts — Kronos only reads candle
    history, never places orders, and its own separate terminal copy means
    it never touches the same IPC channel that client's bridge.py uses,
    even with an identical login. If your broker caps concurrent sessions
    per account, use a second login on the same server instead.

.PARAMETER MasterTerminalDir
    Path to an already-installed MT5 terminal folder to clone from — same
    parameter as add-client.ps1.

.PARAMETER SupabaseUrl
    e.g. https://vvkddynlfgilymzvugfo.supabase.co

.PARAMETER SupabaseServiceRoleKey
    From Supabase dashboard -> Project Settings -> API -> service_role
    secret. Bypasses every RLS policy in the project — keep it on this VPS
    only, never commit it, never put it in the Tilly frontend or backend.

.PARAMETER KronosDir
    Folder containing kronos/'s Python files. Defaults to this script's
    own folder — the expected layout is running this from inside
    tilly-trading/kronos/ itself.

.EXAMPLE
    .\add-kronos.ps1 -Mt5Login "414312080" -Mt5Password "..." -Mt5Server "Exness-MT5Real8" -MasterTerminalDir "C:\MT5-Master-Exness" -SupabaseUrl "https://vvkddynlfgilymzvugfo.supabase.co" -SupabaseServiceRoleKey "..."
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Mt5Login,

    [Parameter(Mandatory = $true)]
    [string]$Mt5Password,

    [Parameter(Mandatory = $true)]
    [string]$Mt5Server,

    [Parameter(Mandatory = $true)]
    [string]$MasterTerminalDir,

    [Parameter(Mandatory = $true)]
    [string]$SupabaseUrl,

    [Parameter(Mandatory = $true)]
    [string]$SupabaseServiceRoleKey,

    [string]$KronosDir = $PSScriptRoot,

    [string]$Symbol = "XAUUSDm",

    [string]$Timeframe = "M5",

    [int]$PollSeconds = 60,

    [string]$TaskName = "TillyKronosInfer"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "..\mt5-bridge\common.ps1")

Assert-Admin

Write-Host "== Kronos setup on this VPS ==" -ForegroundColor Cyan

$pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pythonExe) {
    Write-Host "Python not found — installing (same as bootstrap-vps.ps1 would)..."
    $pythonExe = Ensure-Python
}

if (-not (Test-Path (Join-Path $MasterTerminalDir "terminal64.exe"))) {
    throw "No terminal64.exe found in $MasterTerminalDir — install that broker's MT5 terminal there first."
}

Write-Host "Installing Kronos's Python dependencies..."
$requirementsPath = Join-Path $KronosDir "requirements.txt"
& $pythonExe -m pip install --upgrade pip --quiet
& $pythonExe -m pip install -r $requirementsPath --quiet
if ($LASTEXITCODE -ne 0) {
    throw "pip install failed — check the output above."
}

$terminalDest = Join-Path $KronosDir "terminal"
if (-not (Test-Path $terminalDest)) {
    Write-Host "Cloning an isolated MT5 terminal copy for Kronos into $terminalDest ..."
    Copy-Item -Path $MasterTerminalDir -Destination $terminalDest -Recurse
} else {
    Write-Host "Terminal copy already exists at $terminalDest — reusing it."
}
$terminalExe = Join-Path $terminalDest "terminal64.exe"
if (-not (Test-Path $terminalExe)) {
    throw "Copy succeeded but terminal64.exe is missing at $terminalExe — check $MasterTerminalDir."
}

$modelPath = Join-Path $KronosDir "kronos_model.txt"

# A small PS1 launcher, not a plain .env file — same reasoning as
# mt5-bridge's launchers: the Scheduled Task action invokes this directly,
# so credentials never touch machine-wide environment variables.
$launcherPath = Join-Path $KronosDir "run-infer.ps1"
$launcherContent = @"
# Generated by add-kronos.ps1 — safe to re-run the setup to regenerate.
`$env:MT5_LOGIN = "$Mt5Login"
`$env:MT5_PASSWORD = "$Mt5Password"
`$env:MT5_SERVER = "$Mt5Server"
`$env:MT5_PATH = "$terminalExe"
`$env:SUPABASE_URL = "$SupabaseUrl"
`$env:SUPABASE_SERVICE_ROLE_KEY = "$SupabaseServiceRoleKey"
Set-Location "$KronosDir"
& "$pythonExe" infer.py --model "$modelPath" --symbol "$Symbol" --timeframe "$Timeframe" --poll-seconds $PollSeconds
"@
Set-Content -Path $launcherPath -Value $launcherContent -Encoding UTF8
Write-Host "Wrote launcher: $launcherPath"

# Same interactive-session reasoning as every Scheduled Task in this
# project: MT5's IPC only works inside a real desktop session.
Register-InteractiveTask -TaskName $TaskName -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$launcherPath`""
Write-Host "Registered Scheduled Task '$TaskName' (not started yet — see step 2 below)."

Write-Host ""
Write-Host "== Next steps (do these yourself, in order) ==" -ForegroundColor Cyan
Write-Host "1. Train a model first — a one-off, interactive step, not run by this script:"
Write-Host "   cd `"$KronosDir`""
Write-Host "   `$env:MT5_LOGIN=`"$Mt5Login`"; `$env:MT5_PASSWORD=`"$Mt5Password`"; `$env:MT5_SERVER=`"$Mt5Server`"; `$env:MT5_PATH=`"$terminalExe`""
Write-Host "   & `"$pythonExe`" train.py --symbol $Symbol --timeframe $Timeframe --bars 50000 --side BUY --tp 3.0 --sl 2.0 --out `"$modelPath`""
Write-Host "   Read the printed test AUC/accuracy before trusting it with anything."
Write-Host ""
Write-Host "2. Once $modelPath exists, start live inference:"
Write-Host "   Start-ScheduledTask -TaskName `"$TaskName`""
Write-Host ""
Write-Host "3. Same rule as every other Scheduled Task on this VPS: disconnect your RDP"
Write-Host "   client afterwards, don't log off — logging off ends the session every"
Write-Host "   task on this box (bridges, tunnels, and now Kronos) runs inside."
