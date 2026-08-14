param(
    [string]$RepoRoot = "C:\Users\LeeHoYoung\IdeaProjects\t\stockmate-ai",
    [string]$OutputPath = "C:\Users\LeeHoYoung\IdeaProjects\t\stockmate-ai\logs\audit-monitor-20260723.jsonl"
)

$ErrorActionPreference = "Continue"
$deadline = [DateTimeOffset]::Parse("2026-07-23T22:00:00+09:00")
$outputDir = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

function Write-AuditRecord([string]$kind, $payload) {
    $record = [ordered]@{
        ts = [DateTimeOffset]::Now.ToString("o")
        kind = $kind
        payload = $payload
    }
    ($record | ConvertTo-Json -Compress -Depth 8) | Add-Content -LiteralPath $OutputPath -Encoding UTF8
}

Set-Location -LiteralPath $RepoRoot
$iteration = 0
while ([DateTimeOffset]::Now -lt $deadline) {
    $iteration++
    foreach ($endpoint in @(
        @{ name = "api"; url = "http://localhost:8080/actuator/health" },
        @{ name = "ws"; url = "http://localhost:8081/health" },
        @{ name = "ws_ready"; url = "http://localhost:8081/ready" },
        @{ name = "ai"; url = "http://localhost:8082/health" }
    )) {
        try {
            $body = Invoke-RestMethod -Uri $endpoint.url -TimeoutSec 5
            Write-AuditRecord "health:$($endpoint.name)" $body
        } catch {
            Write-AuditRecord "health_error:$($endpoint.name)" @{ error = $_.Exception.Message }
        }
    }

    $recent = docker compose logs --since 70s api-orchestrator ai-engine websocket-listener telegram-bot 2>&1 |
        Select-String -Pattern '"level":"(ERROR|FATAL)"|\bTraceback \(most recent call last\)|\bpanic\b|105110|105115|105118|rate[-_ ]limit(ed| code)|deadline (miss|exceeded)|ACK failed|summary refresh failed' |
        Where-Object { $_.Line -notmatch "Claude.*token|token.*Claude" } |
        Select-Object -ExpandProperty Line
    if ($recent) {
        Write-AuditRecord "log_alerts" @($recent)
    }

    if (($iteration % 5) -eq 0) {
        try {
            $sql = @"
SELECT json_build_object(
  'tick_rows_10m', (SELECT count(*) FROM ws_tick_data_partitioned WHERE created_at >= NOW() - INTERVAL '10 minutes'),
  'tick_parsed_10m', (SELECT count(*) FROM ws_tick_data_partitioned WHERE created_at >= NOW() - INTERVAL '10 minutes' AND source_time_parse_status='PARSED'),
  'tick_missing_10m', (SELECT count(*) FROM ws_tick_data_partitioned WHERE created_at >= NOW() - INTERVAL '10 minutes' AND source_time_parse_status='MISSING'),
  'max_tick_at', (SELECT max(created_at) FROM ws_tick_data_partitioned),
  'signals_10m', (SELECT count(*) FROM trading_signals WHERE created_at >= NOW() - INTERVAL '10 minutes'),
  'enter_10m', (SELECT count(*) FROM trading_signals WHERE created_at >= NOW() - INTERVAL '10 minutes' AND action='ENTER'),
  'non_live_mode_10m', (SELECT count(*) FROM trading_signals WHERE created_at >= NOW() - INTERVAL '10 minutes' AND upper(coalesce(extra_info,'')) LIKE '%SHADOW%'),
  'open_positions', (SELECT count(*) FROM open_positions WHERE status IN ('ACTIVE','PARTIAL_TP','OVERNIGHT')),
  'active_without_execution', (SELECT count(*) FROM trading_signals WHERE position_status IN ('ACTIVE','PARTIAL_TP','OVERNIGHT') AND executed_at IS NULL),
  'position_events_10m', (SELECT count(*) FROM position_state_events WHERE event_ts >= NOW() - INTERVAL '10 minutes'),
  'risk_events_10m', (SELECT count(*) FROM risk_events WHERE occurred_at >= NOW() - INTERVAL '10 minutes'),
  'orphan_score_components', (SELECT count(*) FROM signal_score_components c LEFT JOIN trading_signals s ON s.id=c.signal_id WHERE s.id IS NULL),
  'orphan_trade_plans', (SELECT count(*) FROM trade_plans p LEFT JOIN trading_signals s ON s.id=p.signal_id WHERE s.id IS NULL)
);
"@
            $db = docker compose exec -T postgres psql -U postgres -d SMA -Atc $sql
            Write-AuditRecord "db" ($db | ConvertFrom-Json)
        } catch {
            Write-AuditRecord "db_error" @{ error = $_.Exception.Message }
        }

        try {
            $queueJson = docker compose exec -T redis sh -lc 'printf "{\"telegram_queue\":"; redis-cli --no-auth-warning -a "$REDIS_PASSWORD" LLEN telegram_queue; printf ",\"ai_scored_queue\":"; redis-cli --no-auth-warning -a "$REDIS_PASSWORD" LLEN ai_scored_queue; printf ",\"signal_queue\":"; redis-cli --no-auth-warning -a "$REDIS_PASSWORD" LLEN signal_queue; printf ",\"vi_watch_queue\":"; redis-cli --no-auth-warning -a "$REDIS_PASSWORD" LLEN vi_watch_queue; printf "}"'
            Write-AuditRecord "queues" ($queueJson | ConvertFrom-Json)
        } catch {
            Write-AuditRecord "queue_error" @{ error = $_.Exception.Message }
        }

        try {
            $containerState = docker compose ps --format '{{.Service}}|{{.State}}|{{.Health}}'
            Write-AuditRecord "containers" @($containerState | ForEach-Object {
                $parts = $_ -split '\|', 3
                @{ service = $parts[0]; state = $parts[1]; health = $parts[2] }
            })
        } catch {
            Write-AuditRecord "container_error" @{ error = $_.Exception.Message }
        }
    }
    Start-Sleep -Seconds 60
}
Write-AuditRecord "monitor_complete" @{ deadline = $deadline.ToString("o") }
