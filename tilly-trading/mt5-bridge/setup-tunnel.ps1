<#
.SYNOPSIS
    Give this client's bridge a permanent HTTPS URL via a named Cloudflare Tunnel.

.DESCRIPTION
    Run this AFTER install-windows.ps1 on the same VPS. A quick tunnel
    (`cloudflared tunnel --url ...`) gets a brand new random URL every
    time it restarts, which breaks a bridge_url already saved in Tilly's
    database — this script instead creates a NAMED tunnel bound to a
    subdomain you choose, so the URL never changes across reboots.

    Named tunnels are scoped to a Cloudflare account and need a one-time
    login (`cloudflared tunnel login`), which opens a browser — only
    possible if you're at this VPS over RDP with a browser available, or
    you've already logged in on another machine and copy that machine's
    cert.pem here (pass -CertPath to skip the interactive login).

    Requires: the chosen -Domain is already an active zone in the SAME
    Cloudflare account cloudflared logs into (Cloudflare dashboard -> Add a
    site). Use a domain/subdomain set aside for client bridges — not one
    already serving another site, to avoid DNS record collisions.

    Same caveat as install-windows.ps1: written and reviewed, not executed
    against a live Cloudflare account or VPS.

.PARAMETER ClientSlug
    Short, URL-safe identifier for this client, e.g. "acme" or "client07".
    Becomes both the tunnel name (tilly-<slug>) and the subdomain.

.PARAMETER Domain
    The Cloudflare-managed domain to publish under, e.g. "bridges.example.com".
    Final URL will be https://<ClientSlug>.<Domain>.

.PARAMETER CertPath
    Optional path to a cert.pem already issued by `cloudflared tunnel login`
    on another machine under the same Cloudflare account. Copy it here to
    skip the interactive browser login on a headless/RDP-less VPS.

.PARAMETER Port
    Local port the bridge listens on. Must match install-windows.ps1's -Port.

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

    [int]$Port = 8787,

    [string]$TaskName = "TillyMT5Tunnel"
)

$ErrorActionPreference = "Stop"

function Assert-Admin {
    $current = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($current)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this script from an elevated (Administrator) PowerShell window."
    }
}

function Ensure-Cloudflared {
    $cf = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cf) {
        Write-Host "cloudflared found: $($cf.Source)"
        return $cf.Source
    }

    Write-Host "cloudflared not found — downloading..."
    $installDir = "C:\Program Files\cloudflared"
    New-Item -ItemType Directory -Path $installDir -Force | Out-Null
    $exePath = Join-Path $installDir "cloudflared.exe"
    Invoke-WebRequest -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" `
        -OutFile $exePath -UseBasicParsing

    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    if ($machinePath -notlike "*$installDir*") {
        [Environment]::SetEnvironmentVariable("Path", "$machinePath;$installDir", "Machine")
    }
    $env:Path = "$env:Path;$installDir"

    Write-Host "cloudflared installed: $exePath"
    return $exePath
}

Assert-Admin

Write-Host "== Tilly MT5 bridge tunnel setup ==" -ForegroundColor Cyan

$cloudflaredExe = Ensure-Cloudflared
$cfDir = Join-Path $env:USERPROFILE ".cloudflared"
New-Item -ItemType Directory -Path $cfDir -Force | Out-Null

$certDest = Join-Path $cfDir "cert.pem"
if (-not (Test-Path $certDest)) {
    if ($CertPath -and (Test-Path $CertPath)) {
        Copy-Item -Path $CertPath -Destination $certDest
        Write-Host "Copied existing Cloudflare origin cert from $CertPath."
    } else {
        Write-Host "No cert.pem found — opening the interactive Cloudflare login."
        Write-Host "(If this VPS has no browser/RDP session, log in on another machine and re-run with -CertPath instead.)"
        & $cloudflaredExe tunnel login
        if (-not (Test-Path $certDest)) {
            throw "cloudflared login did not produce a cert.pem — aborting."
        }
    }
} else {
    Write-Host "Existing Cloudflare origin cert found — reusing it."
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

# Same interactive-session reasoning as install-windows.ps1's Scheduled
# Task: this must stay tied to a logged-on session, not a Session-0 service.
$action = New-ScheduledTaskAction -Execute $cloudflaredExe `
    -Argument "tunnel --config `"$configPath`" run $tunnelName"
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

Write-Host "Starting the tunnel now..."
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 5

Write-Host ""
Write-Host "== Done ==" -ForegroundColor Cyan
Write-Host "Bridge URL (permanent, survives reboots): https://$hostname" -ForegroundColor Green
Write-Host "DNS can take a minute or two to propagate. Once it resolves, paste this URL"
Write-Host "plus the API key from install-windows.ps1 into Tilly's Account page -> + BRIDGE."
