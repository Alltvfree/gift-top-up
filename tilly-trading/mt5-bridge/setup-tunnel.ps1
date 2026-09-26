<#
.SYNOPSIS
    Give one client's bridge a permanent HTTPS URL via a named Cloudflare Tunnel.

.DESCRIPTION
    Run this AFTER add-client.ps1 for that same -ClientSlug. A quick tunnel
    (`cloudflared tunnel --url ...`) gets a brand new random URL every
    time it restarts, which breaks a bridge_url already saved in Tilly's
    database — this script instead creates a NAMED tunnel bound to a
    subdomain you choose, so the URL never changes across reboots.

    Each client gets their own tunnel process and Scheduled Task (not one
    shared tunnel for the whole VPS), so restarting or re-routing one
    client's tunnel never touches anyone else's — the only thing clients
    share on this box is the Cloudflare login (cert.pem) and the Python
    install from bootstrap-vps.ps1.

    Named tunnels are scoped to a Cloudflare account and need a one-time
    login (`cloudflared tunnel login`), which opens a browser — only
    possible if you're at this VPS over RDP with a browser available, or
    you've already logged in on another machine (or for an earlier client
    on this same VPS) and copy that cert.pem here (-CertPath). Once
    cert.pem exists on this VPS, every later client on it reuses it
    automatically — you only do the interactive login once per VPS.

    Requires: the chosen -Domain is already an active zone in the SAME
    Cloudflare account cloudflared logs into (Cloudflare dashboard -> Add a
    site). Use a domain/subdomain set aside for client bridges — not one
    already serving another site, to avoid DNS record collisions.

    Same caveat as the rest of this bridge: written and reviewed, not
    executed against a live Cloudflare account or VPS.

.PARAMETER ClientSlug
    Short, URL-safe identifier for this client, e.g. "acme". Must match
    what you passed to add-client.ps1. Becomes both the tunnel name
    (tilly-<slug>) and the subdomain.

.PARAMETER Domain
    The Cloudflare-managed domain to publish under, e.g. "bridges.example.com".
    Final URL will be https://<ClientSlug>.<Domain>.

.PARAMETER CertPath
    Optional path to a cert.pem already issued by `cloudflared tunnel login`
    on another machine under the same Cloudflare account. Copy it here to
    skip the interactive browser login on a headless/RDP-less VPS.

.PARAMETER Port
    Local port this client's bridge listens on. Omit to read it from
    clients\<ClientSlug>\port.txt, written by add-client.ps1.

.PARAMETER BridgeDir
    Folder containing the clients\ directory. Defaults to this script's
    own folder — only needed if you moved things around.

.EXAMPLE
    .\setup-tunnel.ps1 -ClientSlug "acme" -Domain "bridges.example.com"

.EXAMPLE
    .\setup-tunnel.ps1 -ClientSlug "acme" -Domain "bridges.example.com" -CertPath "C:\temp\cert.pem"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ClientSlug,

    [Parameter(Mandatory = $true)]
    [string]$Domain,

    [string]$CertPath = "",

    [int]$Port = 0,

    [string]$BridgeDir = $PSScriptRoot
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

Assert-Admin

if ($Port -eq 0) {
    $portFile = Join-Path $BridgeDir "clients\$ClientSlug\port.txt"
    if (-not (Test-Path $portFile)) {
        throw "No -Port given and $portFile doesn't exist — run add-client.ps1 for '$ClientSlug' first, or pass -Port explicitly."
    }
    $Port = [int](Get-Content $portFile -Raw).Trim()
}
Write-Host "== Tunnel setup for client '$ClientSlug' (port $Port) ==" -ForegroundColor Cyan

$cloudflaredExe = Ensure-Cloudflared
$cfDir = Join-Path $env:USERPROFILE ".cloudflared"
New-Item -ItemType Directory -Path $cfDir -Force | Out-Null

$certDest = Join-Path $cfDir "cert.pem"
if (-not (Test-Path $certDest)) {
    if ($CertPath -and (Test-Path $CertPath)) {
        Copy-Item -Path $CertPath -Destination $certDest
        Write-Host "Copied existing Cloudflare origin cert from $CertPath."
    } else {
        Write-Host "No cert.pem found on this VPS yet — opening the interactive Cloudflare login."
        Write-Host "(This only happens once per VPS. If this VPS has no browser/RDP session, log in on another machine and re-run with -CertPath instead.)"
        & $cloudflaredExe tunnel login
        if (-not (Test-Path $certDest)) {
            throw "cloudflared login did not produce a cert.pem — aborting."
        }
    }
} else {
    Write-Host "Existing Cloudflare origin cert found on this VPS — reusing it."
}

$tunnelName = "tilly-$ClientSlug"
$hostname = "$ClientSlug.$Domain"

# Idempotent: reuse an existing tunnel of this name instead of erroring out
# on a re-run (e.g. after changing -Port and wanting to redo the ingress).
$existing = & $cloudflaredExe tunnel list --output json 2>$null | ConvertFrom-Json
$tunnel = $existing | Where-Object { $_.name -eq $tunnelName } | Select-Object -First 1

if ($tunnel) {
    $tunnelId = $tunnel.id
    Write-Host "Reusing existing tunnel '$tunnelName' ($tunnelId)."
} else {
    Write-Host "Creating tunnel '$tunnelName'..."
    & $cloudflaredExe tunnel create $tunnelName
    if ($LASTEXITCODE -ne 0) {
        throw "cloudflared tunnel create failed — see output above."
    }
    $refreshed = & $cloudflaredExe tunnel list --output json | ConvertFrom-Json
    $tunnel = $refreshed | Where-Object { $_.name -eq $tunnelName } | Select-Object -First 1
    if (-not $tunnel) {
        throw "Tunnel '$tunnelName' was created but could not be found afterwards."
    }
    $tunnelId = $tunnel.id
}

$credsFile = Join-Path $cfDir "$tunnelId.json"
if (-not (Test-Path $credsFile)) {
    throw "Expected credentials file not found at $credsFile — tunnel create may have failed partway."
}

$configPath = Join-Path $cfDir "config-$ClientSlug.yml"
$configContent = @"
tunnel: $tunnelId
credentials-file: $credsFile

ingress:
  - hostname: $hostname
    service: http://localhost:$Port
  - service: http_status:404
"@
Set-Content -Path $configPath -Value $configContent -Encoding UTF8
Write-Host "Wrote tunnel config: $configPath"

Write-Host "Routing DNS: $hostname -> tunnel $tunnelName ..."
& $cloudflaredExe tunnel route dns $tunnelName $hostname
if ($LASTEXITCODE -ne 0) {
    Write-Warning "DNS route may already exist or failed — check the Cloudflare dashboard for $Domain if the URL doesn't resolve."
}

$taskName = "TillyMT5Tunnel-$ClientSlug"
Register-InteractiveTask -TaskName $taskName -Execute $cloudflaredExe `
    -Argument "tunnel --config `"$configPath`" run $tunnelName"
Write-Host "Registered Scheduled Task '$taskName' (starts at logon, restarts on failure)."

Write-Host "Starting the tunnel now..."
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 5

Write-Host ""
Write-Host "== Done ==" -ForegroundColor Cyan
Write-Host "Bridge URL (permanent, survives reboots): https://$hostname" -ForegroundColor Green
Write-Host "DNS can take a minute or two to propagate. Once it resolves, paste this URL"
Write-Host "plus the API key add-client.ps1 printed into Tilly's Account page -> + BRIDGE."
