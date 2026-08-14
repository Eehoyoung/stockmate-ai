<#
.SYNOPSIS
Reclaims C-drive space held by Docker Desktop's WSL VHDX files.

.DESCRIPTION
Prunes unused build cache and dangling images, checkpoints StockMate PostgreSQL,
stops every currently running Docker container, shuts down WSL, compacts the
Docker VHDX files, then restores the containers that were running.

Run from an elevated (Administrator) PowerShell because diskpart is used when
the Hyper-V Optimize-VHD cmdlet is unavailable.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\scripts\compact_wsl_docker.ps1 -WhatIf

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\scripts\compact_wsl_docker.ps1 -Confirm:$false
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [string]$ProjectRoot,
    [string[]]$VhdxPath,
    [switch]$SkipDockerPrune,
    [switch]$SkipRestart,
    [int]$DockerReadyTimeoutSec = 180
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}

function Format-Bytes([long]$Bytes) {
    if ($Bytes -ge 1TB) { return ('{0:N2} TB' -f ($Bytes / 1TB)) }
    if ($Bytes -ge 1GB) { return ('{0:N2} GB' -f ($Bytes / 1GB)) }
    if ($Bytes -ge 1MB) { return ('{0:N2} MB' -f ($Bytes / 1MB)) }
    return ('{0:N0} bytes' -f $Bytes)
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-DockerVhdxPaths {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Docker\wsl\disk\docker_data.vhdx'),
        (Join-Path $env:LOCALAPPDATA 'Docker\wsl\data\ext4.vhdx'),
        (Join-Path $env:LOCALAPPDATA 'Docker\wsl\main\ext4.vhdx')
    )
    return @($candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -Unique)
}

function Invoke-DiskPartCompact([string]$Path) {
    $tempFile = New-TemporaryFile
    try {
        @(
            "select vdisk file=`"$Path`""
            'attach vdisk readonly'
            'compact vdisk'
            'detach vdisk'
            'exit'
        ) | Set-Content -LiteralPath $tempFile -Encoding ASCII
        & diskpart.exe /s $tempFile
        if ($LASTEXITCODE -ne 0) {
            throw "diskpart failed with exit code $LASTEXITCODE for $Path"
        }
    }
    finally {
        Remove-Item -LiteralPath $tempFile -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot 'docker-compose.yml'))) {
    throw "docker-compose.yml not found under ProjectRoot: $ProjectRoot"
}

if (-not $VhdxPath -or $VhdxPath.Count -eq 0) {
    $VhdxPath = Get-DockerVhdxPaths
}
if (-not $VhdxPath -or $VhdxPath.Count -eq 0) {
    throw 'No Docker Desktop WSL VHDX file was found.'
}

$resolvedVhdx = @($VhdxPath | ForEach-Object {
    if (-not (Test-Path -LiteralPath $_)) { throw "VHDX not found: $_" }
    (Resolve-Path -LiteralPath $_).Path
} | Select-Object -Unique)

$optimizer = Get-Command Optimize-VHD -ErrorAction SilentlyContinue
if (-not $optimizer -and -not (Test-IsAdministrator) -and -not $WhatIfPreference) {
    throw 'Run this script from an elevated (Administrator) PowerShell. diskpart is required because Optimize-VHD is unavailable.'
}

$before = @{}
foreach ($path in $resolvedVhdx) {
    $before[$path] = (Get-Item -LiteralPath $path).Length
    Write-Host "[WSL Compact] target=$path size=$(Format-Bytes $before[$path])"
}

Push-Location $ProjectRoot
try {
    $runningContainers = @(docker ps --format '{{.Names}}' | Where-Object { $_ })

    if (-not $SkipDockerPrune -and $PSCmdlet.ShouldProcess('Unused Docker build cache and dangling images', 'prune')) {
        docker builder prune --all --force | Out-Host
        docker image prune --force | Out-Host
    }

    if ($PSCmdlet.ShouldProcess('StockMate PostgreSQL', 'checkpoint before shutdown')) {
        docker compose exec -T postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CHECKPOINT"' | Out-Host
    }
    if ($runningContainers.Count -gt 0 -and
            $PSCmdlet.ShouldProcess(($runningContainers -join ', '), 'stop running Docker containers')) {
        docker stop --time 30 $runningContainers | Out-Host
    }

    if ($PSCmdlet.ShouldProcess('docker-desktop WSL filesystems', 'trim freed blocks')) {
        & wsl.exe -d docker-desktop -u root -- fstrim -av
        if ($LASTEXITCODE -ne 0) {
            Write-Warning 'fstrim was not available or returned an error; continuing with VHDX compaction.'
        }
    }

    if ($PSCmdlet.ShouldProcess('Docker Desktop and WSL', 'stop before VHDX compaction')) {
        Get-Process -Name 'Docker Desktop', 'com.docker.backend' -ErrorAction SilentlyContinue |
            Stop-Process -Force -ErrorAction SilentlyContinue
        wsl.exe --shutdown
        Start-Sleep -Seconds 3
    }

    foreach ($path in $resolvedVhdx) {
        if (-not $PSCmdlet.ShouldProcess($path, 'compact VHDX')) { continue }
        if ($optimizer) {
            Optimize-VHD -Path $path -Mode Full
        }
        else {
            Invoke-DiskPartCompact -Path $path
        }
    }

    foreach ($path in $resolvedVhdx) {
        $after = (Get-Item -LiteralPath $path).Length
        $saved = [Math]::Max(0, $before[$path] - $after)
        Write-Host "[WSL Compact] result=$path before=$(Format-Bytes $before[$path]) after=$(Format-Bytes $after) saved=$(Format-Bytes $saved)"
    }

    if (-not $SkipRestart -and $PSCmdlet.ShouldProcess('Docker Desktop and StockMate services', 'restart')) {
        $dockerDesktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
        if (-not (Test-Path -LiteralPath $dockerDesktop)) {
            throw "Docker Desktop executable not found: $dockerDesktop"
        }
        Start-Process -FilePath $dockerDesktop -WindowStyle Hidden

        $deadline = (Get-Date).AddSeconds($DockerReadyTimeoutSec)
        do {
            Start-Sleep -Seconds 3
            docker info *> $null
            if ($LASTEXITCODE -eq 0) { break }
        } while ((Get-Date) -lt $deadline)
        if ($LASTEXITCODE -ne 0) {
            throw "Docker Desktop did not become ready within $DockerReadyTimeoutSec seconds."
        }
        if ($runningContainers.Count -gt 0) {
            docker start $runningContainers | Out-Host
        }
    }
}
finally {
    Pop-Location
}
