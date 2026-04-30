param(
    [string]$StartTime = "07:30",
    [string]$EndTime = "20:10",
    [int]$IntervalMinutes = 10,
    [string]$OutputPath = "",
    [switch]$RunOnce
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $RepoRoot ".env"

function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            return
        }
        $parts = $line.Split("=", 2)
        $name = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")
        if ($name -and -not [Environment]::GetEnvironmentVariable($name, "Process")) {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

function Get-KstNow {
    $tz = [TimeZoneInfo]::FindSystemTimeZoneById("Korea Standard Time")
    return [TimeZoneInfo]::ConvertTimeFromUtc((Get-Date).ToUniversalTime(), $tz)
}

function Test-TcpPort {
    param([string]$HostName, [int]$Port)
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $connect = $client.BeginConnect($HostName, $Port, $null, $null)
        $ok = $connect.AsyncWaitHandle.WaitOne(1500, $false)
        if ($ok) {
            $client.EndConnect($connect)
        }
        $client.Close()
        return $ok
    } catch {
        return $false
    }
}

function Invoke-HealthUrl {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
        $body = $response.Content
        $status = ""
        try {
            $json = $body | ConvertFrom-Json
            if ($json.status) {
                $status = [string]$json.status
            }
        } catch {
            $status = ""
        }

        if ($status) {
            return "HTTP $($response.StatusCode) $status"
        }
        return "HTTP $($response.StatusCode)"
    } catch {
        return "DOWN $($_.Exception.Message.Replace('|', '/'))"
    }
}

function Invoke-External {
    param([string[]]$Command)
    try {
        $output = & $Command[0] @($Command | Select-Object -Skip 1) 2>&1
        return @{
            Ok = $LASTEXITCODE -eq 0
            Text = ($output -join "`n").Trim()
        }
    } catch {
        return @{
            Ok = $false
            Text = $_.Exception.Message
        }
    }
}

function Get-ComposeStatuses {
    $containers = @{
        "redis" = "stockmate-ai-redis-1"
        "postgres" = "stockmate-ai-postgres-1"
        "api-orchestrator" = "stockmate-ai-api-orchestrator-1"
        "websocket-listener" = "stockmate-ai-websocket-listener-1"
        "ai-engine" = "stockmate-ai-ai-engine-1"
        "telegram-bot" = "stockmate-ai-telegram-bot-1"
    }

    $map = @{}
    foreach ($service in $containers.Keys) {
        $container = $containers[$service]
        $state = Invoke-External @("docker", "inspect", "-f", "{{.State.Status}}", $container)
        $health = Invoke-External @("docker", "inspect", "-f", "{{if .State.Health}}{{.State.Health.Status}}{{end}}", $container)
        if ($state.Ok) {
            $map[$service] = @{
                State = $state.Text
                Health = if ($health.Ok) { $health.Text } else { "" }
                Status = ""
            }
        }
    }
    return $map
}

function Format-ComposeStatus {
    param($Statuses, [string]$Service)
    if (-not $Statuses.ContainsKey($Service)) {
        return "not_found"
    }
    $s = $Statuses[$Service]
    $parts = @()
    if ($s.State) { $parts += $s.State }
    if ($s.Health) { $parts += $s.Health }
    if (-not $parts.Count -and $s.Status) { $parts += $s.Status }
    if (-not $parts.Count) { return "unknown" }
    return ($parts -join "/")
}

function Get-RedisStatus {
    param($ComposeStatuses)
    $compose = Format-ComposeStatus $ComposeStatuses "redis"
    $ping = Invoke-External @("docker", "exec", "stockmate-ai-redis-1", "sh", "-lc", 'redis-cli -a "$REDIS_PASSWORD" --no-auth-warning ping')
    if ($ping.Ok -and $ping.Text -match "PONG") {
        return "$compose; ping:PONG"
    }
    return "$compose; ping:fail"
}

function Get-PostgresStatus {
    param($ComposeStatuses)
    $compose = Format-ComposeStatus $ComposeStatuses "postgres"
    $ready = Invoke-External @("docker", "exec", "stockmate-ai-postgres-1", "sh", "-lc", 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"')
    if ($ready.Ok) {
        return "$compose; pg_isready:ok"
    }
    return "$compose; pg_isready:fail"
}

function Get-Snapshot {
    Import-DotEnv $EnvPath
    $compose = Get-ComposeStatuses

    $now = Get-KstNow
    $redis = Get-RedisStatus $compose
    $postgres = Get-PostgresStatus $compose
    $api = "$(Format-ComposeStatus $compose "api-orchestrator"); $(Invoke-HealthUrl "http://127.0.0.1:8080/actuator/health")"
    $ws = "$(Format-ComposeStatus $compose "websocket-listener"); $(Invoke-HealthUrl "http://127.0.0.1:8081/health")"
    $ai = "$(Format-ComposeStatus $compose "ai-engine"); $(Invoke-HealthUrl "http://127.0.0.1:8082/health")"
    $telegram = "$(Format-ComposeStatus $compose "telegram-bot"); container_health"

    return "| $($now.ToString("yyyy-MM-dd HH:mm:ss")) | $redis | $postgres | $api | $ws | $ai | $telegram |"
}

function Initialize-Report {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path) {
        return
    }

    $date = (Get-KstNow).ToString("yyyy-MM-dd")
    $content = @(
        "# System Status Monitor - $date KST",
        "",
        "- Window: $StartTime-$EndTime KST",
        "- Interval: $IntervalMinutes minutes",
        "- Scope: Redis, PostgreSQL, api-orchestrator, websocket-listener, ai-engine, telegram-bot",
        "- Primary source: Docker Compose health/status when available",
        "- Secondary source: localhost health URLs/TCP checks",
        "",
        "| KST | Redis | PostgreSQL | api-orchestrator | websocket-listener | ai-engine | telegram-bot |",
        "|---|---|---|---|---|---|---|"
    )
    Set-Content -LiteralPath $Path -Value $content -Encoding UTF8
}

if (-not $OutputPath) {
    $stamp = (Get-KstNow).ToString("yyyyMMdd")
    $OutputPath = Join-Path $RepoRoot "docs\system_status_monitor_$stamp.md"
} elseif (-not [System.IO.Path]::IsPathRooted($OutputPath)) {
    $OutputPath = Join-Path $RepoRoot $OutputPath
}

$outputDir = Split-Path -Parent $OutputPath
if (-not (Test-Path -LiteralPath $outputDir)) {
    New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
}
Initialize-Report $OutputPath

if ($RunOnce) {
    Add-Content -LiteralPath $OutputPath -Value (Get-Snapshot) -Encoding UTF8
    Write-Host "Recorded one snapshot to $OutputPath"
    exit 0
}

$today = (Get-KstNow).Date
$start = $today.Add([TimeSpan]::Parse($StartTime))
$end = $today.Add([TimeSpan]::Parse($EndTime))

while ($true) {
    $now = Get-KstNow
    if ($now -lt $start) {
        $sleepSeconds = [Math]::Min([int]($start - $now).TotalSeconds, 300)
        Start-Sleep -Seconds ([Math]::Max($sleepSeconds, 1))
        continue
    }
    if ($now -gt $end) {
        Write-Host "Monitor window finished. Report: $OutputPath"
        break
    }

    Add-Content -LiteralPath $OutputPath -Value (Get-Snapshot) -Encoding UTF8

    $next = $now.Date.AddMinutes(([Math]::Floor(($now.TimeOfDay.TotalMinutes / $IntervalMinutes)) + 1) * $IntervalMinutes)
    if ($next -le $now) {
        $next = $now.AddMinutes($IntervalMinutes)
    }
    if ($next -gt $end) {
        $next = $end
    }
    Start-Sleep -Seconds ([Math]::Max([int]($next - (Get-KstNow)).TotalSeconds, 1))
}
