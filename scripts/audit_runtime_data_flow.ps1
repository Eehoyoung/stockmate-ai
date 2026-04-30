param(
    [string]$StartTime = "07:30",
    [string]$EndTime = "20:10",
    [int]$IntervalMinutes = 10,
    [string]$OutputPath = "",
    [switch]$RunOnce
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$RedisContainer = "stockmate-ai-redis-1"
$PostgresContainer = "stockmate-ai-postgres-1"

function Get-KstNow {
    $tz = [TimeZoneInfo]::FindSystemTimeZoneById("Korea Standard Time")
    return [TimeZoneInfo]::ConvertTimeFromUtc((Get-Date).ToUniversalTime(), $tz)
}

function Invoke-Text {
    param([scriptblock]$Block)
    try {
        return ((& $Block 2>&1) -join "`n").Trim()
    } catch {
        return "COMMAND_FAILED: $($_.Exception.Message)"
    }
}

function Invoke-Redis {
    param([string]$Command)
    return Invoke-Text { docker exec $RedisContainer sh -lc "redis-cli -a `"`$REDIS_PASSWORD`" --no-auth-warning $Command" }
}

function Invoke-Psql {
    param([string]$Sql)
    return Invoke-Text { docker exec $PostgresContainer psql -U postgres -d SMA -c $Sql }
}

function Invoke-PsqlAt {
    param([string]$Sql)
    return Invoke-Text { docker exec $PostgresContainer psql -U postgres -d SMA -Atc $Sql }
}

function Get-LogIssues {
    $issuePattern = '("level"\s*:\s*"(WARN|WARNING|ERROR|CRITICAL)")|(\[(WARN|WARNING|ERROR|CRITICAL)\])|(Traceback)|(Exception)|(ConnectionClosed)|(disconnect)|(failed)'
    $benignPattern = 'spring\.jpa\.open-in-view|BYPASS_MARKET_HOURS=true|Human Confirm Gate 비활성화'
    Push-Location $RepoRoot
    try {
        $lines = docker compose logs --since 15m --no-color api-orchestrator ai-engine websocket-listener telegram-bot 2>&1 |
            Select-String -Pattern $issuePattern -CaseSensitive:$false |
            Where-Object { $_.Line -notmatch $benignPattern } |
            Select-Object -Last 30
        if (-not $lines) {
            return "No operational WARN/ERROR issues in last 15m."
        }
        return (($lines | ForEach-Object { $_.Line }) -join "`n")
    } catch {
        return "COMMAND_FAILED: $($_.Exception.Message)"
    } finally {
        Pop-Location
    }
}

function Get-RedisPrefixSummary {
    try {
        $keys = docker exec $RedisContainer sh -lc "redis-cli -a `"`$REDIS_PASSWORD`" --no-auth-warning KEYS '*'" 2>&1
        if (-not $keys) {
            return "No Redis keys returned."
        }
        return (($keys |
            Where-Object { $_ -and $_ -notmatch "^Warning:" } |
            ForEach-Object {
                if ($_ -match "^([^:]+)") { $Matches[1] } else { $_ }
            } |
            Group-Object |
            Sort-Object Count -Descending |
            ForEach-Object { "$($_.Name)=$($_.Count)" }) -join ", ")
    } catch {
        return "COMMAND_FAILED: $($_.Exception.Message)"
    }
}

function Get-RedisQueueSummary {
    $queues = @("telegram_queue", "ai_scored_queue", "error_queue", "vi_watch_queue", "confirmed_queue", "human_confirm_queue")
    $parts = foreach ($q in $queues) {
        $len = Invoke-Redis "LLEN $q"
        "$q=$len"
    }
    return ($parts -join ", ")
}

function Write-Snapshot {
    param([string]$Path)

    $now = (Get-KstNow).ToString("yyyy-MM-dd HH:mm:ss")
    $flyway = Invoke-PsqlAt "select count(*) || ' migrations, failed=' || count(*) filter (where not success) || ', latest_rank=' || max(installed_rank) from flyway_schema_history;"
    $tableSummary = Invoke-Psql "select 'stock_master' as table_name, count(*) as rows, max(updated_at) as latest_ts from stock_master union all select 'ws_tick_data', count(*), max(created_at) from ws_tick_data union all select 'vi_events', count(*), max(created_at) from vi_events union all select 'trading_signals', count(*), max(created_at) from trading_signals union all select 'signal_score_components', count(*), max(computed_at) from signal_score_components union all select 'candidate_pool_history', count(*), max(last_seen) from candidate_pool_history union all select 'daily_indicators', count(*), max(computed_at) from daily_indicators union all select 'open_positions', count(*), max(entry_at) from open_positions;"
    $signalQuality = Invoke-Psql "select count(*) total, count(*) filter (where stk_nm is null or trim(stk_nm)='') empty_stk_nm, count(*) filter (where entry_price is null) null_entry_price, count(*) filter (where signal_score is null) null_signal_score from trading_signals; select count(*) as stock_master_empty_names from stock_master where stk_nm is null or trim(stk_nm)=''; select count(*) as recent_0b_null_price from ws_tick_data where created_at >= current_date - interval '1 day' and tick_type='0B' and cur_prc is null;"
    $recentSignals = Invoke-Psql "select ts.stk_cd, ts.stk_nm as signal_name, sm.stk_nm as master_name, ts.strategy, ts.entry_price, ts.signal_score, ts.signal_status, ts.created_at from trading_signals ts left join stock_master sm on sm.stk_cd=ts.stk_cd order by ts.created_at desc limit 10;"
    $recentTicks = Invoke-Psql "select stk_cd, cur_prc, flu_rt, cntr_str, tick_type, created_at from ws_tick_data order by created_at desc limit 10;"
    $redisDbSize = Invoke-Redis "DBSIZE"
    $redisInfo = Invoke-Redis "INFO keyspace"
    $redisPrefixes = Get-RedisPrefixSummary
    $redisQueues = Get-RedisQueueSummary
    $heartbeat = Invoke-Redis "HGETALL ws:py_heartbeat"
    $schedulerStatus = Invoke-Redis "MGET ops:scheduler:news_scheduler:last_status ops:scheduler:status_report:last_status news:market_sentiment"
    $logIssues = Get-LogIssues

    $section = @(
        "",
        "## $now KST",
        "",
        "### Log Issues",
        '```text',
        $logIssues,
        '```',
        "",
        "### Redis",
        "- dbsize: $redisDbSize",
        "- keyspace: $($redisInfo -replace "`r?`n", '; ')",
        "- prefixes: $redisPrefixes",
        "- queues: $redisQueues",
        "- scheduler/news status: $($schedulerStatus -replace "`r?`n", ', ')",
        "- ws heartbeat:",
        '```text',
        $heartbeat,
        '```',
        "",
        "### PostgreSQL",
        "- flyway: $flyway",
        "",
        "Table freshness:",
        '```text',
        $tableSummary,
        '```',
        "",
        "Data quality:",
        '```text',
        $signalQuality,
        '```',
        "",
        "Recent signals:",
        '```text',
        $recentSignals,
        '```',
        "",
        "Recent ticks:",
        '```text',
        $recentTicks,
        '```'
    )
    Add-Content -LiteralPath $Path -Value $section -Encoding UTF8
}

if (-not $OutputPath) {
    $stamp = (Get-KstNow).ToString("yyyyMMdd")
    $OutputPath = Join-Path $RepoRoot "docs\runtime_data_audit_$stamp.md"
} elseif (-not [System.IO.Path]::IsPathRooted($OutputPath)) {
    $OutputPath = Join-Path $RepoRoot $OutputPath
}

$outputDir = Split-Path -Parent $OutputPath
if (-not (Test-Path -LiteralPath $outputDir)) {
    New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
}
if (-not (Test-Path -LiteralPath $OutputPath)) {
    $date = (Get-KstNow).ToString("yyyy-MM-dd")
    Set-Content -LiteralPath $OutputPath -Encoding UTF8 -Value @(
        "# Runtime Data Audit - $date KST",
        "",
        "- Window: $StartTime-$EndTime KST",
        "- Interval: $IntervalMinutes minutes",
        "- Scope: console warnings/errors, Redis keys/queues, PostgreSQL table freshness and data quality"
    )
}

if ($RunOnce) {
    Write-Snapshot $OutputPath
    Write-Host "Recorded one runtime audit snapshot to $OutputPath"
    exit 0
}

$today = (Get-KstNow).Date
$start = $today.Add([TimeSpan]::Parse($StartTime))
$end = $today.Add([TimeSpan]::Parse($EndTime))

while ($true) {
    $now = Get-KstNow
    if ($now -lt $start) {
        Start-Sleep -Seconds ([Math]::Max([Math]::Min([int]($start - $now).TotalSeconds, 300), 1))
        continue
    }
    if ($now -gt $end) {
        Write-Host "Audit window finished. Report: $OutputPath"
        break
    }

    Write-Snapshot $OutputPath

    $next = $now.Date.AddMinutes(([Math]::Floor(($now.TimeOfDay.TotalMinutes / $IntervalMinutes)) + 1) * $IntervalMinutes)
    if ($next -le $now) {
        $next = $now.AddMinutes($IntervalMinutes)
    }
    if ($next -gt $end) {
        $next = $end
    }
    Start-Sleep -Seconds ([Math]::Max([int]($next - (Get-KstNow)).TotalSeconds, 1))
}
