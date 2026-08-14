<#
.SYNOPSIS
Registers weekly Docker/WSL storage compaction in Windows Task Scheduler.

.DESCRIPTION
The task runs every Sunday at 21:30 while the configured user is logged on.
It invokes compact_wsl_docker.ps1 with highest privileges. Running containers
are restored after compaction; containers that were stopped remain stopped.

This installer itself must be run once from an elevated PowerShell.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\scripts\register_storage_maintenance_task.ps1

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\scripts\register_storage_maintenance_task.ps1 -Unregister
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$TaskName = 'StockMate-Weekly-Docker-Storage-Reclaim',
    [string]$DayOfWeek = 'Sunday',
    [string]$At = '21:30',
    [switch]$Unregister
)

$ErrorActionPreference = 'Stop'

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdministrator)) {
    throw 'Run this installer once from an elevated (Administrator) PowerShell.'
}

if ($Unregister) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        if ($PSCmdlet.ShouldProcess($TaskName, 'unregister scheduled task')) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        }
    }
    return
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$compactScript = Join-Path $PSScriptRoot 'compact_wsl_docker.ps1'
$dataVhdx = Join-Path $env:LOCALAPPDATA 'Docker\wsl\disk\docker_data.vhdx'
$mainVhdx = Join-Path $env:LOCALAPPDATA 'Docker\wsl\main\ext4.vhdx'

if (-not (Test-Path -LiteralPath $compactScript)) {
    throw "Compaction script not found: $compactScript"
}
if (-not (Test-Path -LiteralPath $dataVhdx)) {
    throw "Docker data VHDX not found: $dataVhdx"
}

$vhdxArgs = @($dataVhdx)
if (Test-Path -LiteralPath $mainVhdx) {
    $vhdxArgs += $mainVhdx
}
$quotedVhdx = ($vhdxArgs | ForEach-Object { "'$_'" }) -join ','
$command = "& '$compactScript' -ProjectRoot '$projectRoot' -VhdxPath $quotedVhdx -Confirm:`$false"
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))

$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -EncodedCommand $encoded"
$trigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek $DayOfWeek -At $At
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$principal = New-ScheduledTaskPrincipal `
    -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Highest

if ($PSCmdlet.ShouldProcess($TaskName, "register weekly task $DayOfWeek $At")) {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description 'Prunes unused Docker cache and compacts Docker Desktop WSL VHDX files.' `
        -Force | Out-Null
    Get-ScheduledTask -TaskName $TaskName |
        Select-Object TaskName, State, @{Name='NextRunTime';Expression={(Get-ScheduledTaskInfo $_).NextRunTime}}
}
