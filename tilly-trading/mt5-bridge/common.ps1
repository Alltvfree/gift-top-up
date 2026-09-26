<#
.SYNOPSIS
    Shared helper functions for the Tilly MT5 bridge setup scripts.
    Dot-source this from bootstrap-vps.ps1 / add-client.ps1 / setup-tunnel.ps1 —
    it does nothing on its own.
#>

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

function New-ApiKey {
    $bytes = [System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32)
    return [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

<#
.SYNOPSIS
    Picks the next free bridge port for a new client on a shared VPS.
    Reads port.txt out of every existing clients\<slug>\ folder so ports
    never collide, then returns the lowest unused integer at or above
    StartPort.
#>
function Find-FreePort {
    param(
        [int]$StartPort = 8787,
        [string]$ClientsDir
    )
    $used = @()
    if (Test-Path $ClientsDir) {
        Get-ChildItem -Path $ClientsDir -Directory | ForEach-Object {
            $portFile = Join-Path $_.FullName "port.txt"
            if (Test-Path $portFile) {
                $used += [int](Get-Content $portFile -Raw).Trim()
            }
        }
    }
    $port = $StartPort
    while ($used -contains $port) {
        $port++
    }
    return $port
}

<#
.SYNOPSIS
    Registers (or replaces) a Scheduled Task that runs a PowerShell script
    at logon, tied to the current interactive session.

.DESCRIPTION
    Every bridge and tunnel process needs this, not a true Windows service:
    MetaTrader5's IPC to the terminal only works inside a real desktop
    session — a Session-0 service breaks it. On a VPS this means: after
    setup, disconnect your RDP client, don't log off. Disconnecting keeps
    the session (and every task registered this way) alive; logging off
    ends it and kills all of them at once.
#>
function Register-InteractiveTask {
    param(
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][string]$Execute,
        [Parameter(Mandatory = $true)][string]$Argument
    )
    $action = New-ScheduledTaskAction -Execute $Execute -Argument $Argument
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
}
