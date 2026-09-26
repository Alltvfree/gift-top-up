<#
.SYNOPSIS
    One-time setup for a shared Windows VPS that will host MULTIPLE
    clients' MT5 bridges side by side.

.DESCRIPTION
    Run this ONCE per VPS, as Administrator, before adding any clients.
    It installs Python and cloudflared — the shared infrastructure every
    client's bridge and tunnel will use — and nothing client-specific.

    After this finishes:
      1. Install each broker's MT5 terminal you'll need as a "master" copy
         (e.g. C:\MT5-Master-Exness\terminal64.exe) — just the broker's
         normal installer, logged into nothing.
      2. Run add-client.ps1 once per client account, pointing it at the
         matching master terminal to clone.

    Same caveat as the rest of this bridge: written and reviewed, not
    executed against a live Windows box — this sandbox has none to test
    against. Dry-run on a throwaway VPS first.

.EXAMPLE
    .\bootstrap-vps.ps1
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

Assert-Admin

Write-Host "== Tilly MT5 bridge — shared VPS bootstrap ==" -ForegroundColor Cyan

$pythonExe = Ensure-Python

Write-Host "Installing Python dependencies (shared by every client's bridge process)..."
$requirementsPath = Join-Path $PSScriptRoot "requirements.txt"
& $pythonExe -m pip install --upgrade pip --quiet
& $pythonExe -m pip install -r $requirementsPath --quiet
if ($LASTEXITCODE -ne 0) {
    throw "pip install failed — check the output above."
}

$cloudflaredExe = Ensure-Cloudflared

New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot "clients") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot "terminals") -Force | Out-Null

Write-Host ""
Write-Host "== VPS ready ==" -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "  1. Install each broker's MT5 terminal as a master copy, e.g."
Write-Host "     C:\MT5-Master-Exness\ (just the broker's installer, no login needed)."
Write-Host "  2. For each client account, run:"
Write-Host "     .\add-client.ps1 -ClientSlug ""acme"" -Mt5Login ""..."" -Mt5Password ""..."" -Mt5Server ""..."" -MasterTerminalDir ""C:\MT5-Master-Exness"""
