param(
    [datetime]$SinceKst = [datetime]"2026-08-22T17:11:22+09:00"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

function Invoke-CanarySql([string]$Sql) {
    $output = docker exec stockmate-ai-postgres-1 psql -U postgres -d SMA -Atc $Sql
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL canary query failed"
    }
    return @($output)
}

function Invoke-CanaryCount([string]$Sql) {
    return [int]((Invoke-CanarySql $Sql | Select-Object -First 1))
}

$sinceIso = $SinceKst.ToString("yyyy-MM-dd HH:mm:sszzz")
$health = @{}
foreach ($service in @("api-orchestrator", "ai-engine", "telegram-bot", "websocket-listener", "postgres", "redis")) {
    $container = "stockmate-ai-$service-1"
    $health[$service] = docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $container
}

$metrics = [ordered]@{
    observed_from_kst = $sinceIso
    generated_at_kst = [datetimeoffset]::Now.ToString("o")
    service_health = $health
    signals = Invoke-CanaryCount "select count(*) from trading_signals where created_at >= '$sinceIso'"
    missing_family_lineage = Invoke-CanaryCount "select count(*) from trading_signals where created_at >= '$sinceIso' and strategy like 'S%' and (strategy_family is null or primary_setup_id is null or matched_setup_ids is null or setup_version is null or rule_score_version is null or prompt_version is null or confirmed_by_family_ids is null or data_source is null or source_timestamp is null or source_age_ms is null or fallback_reason is null)"
    duplicate_active_stocks = Invoke-CanaryCount "select count(*) from (select stk_cd from trading_signals where position_status in ('ACTIVE','PARTIAL_TP','OVERNIGHT') and coalesce(remaining_qty,entry_qty,0)>0 group by stk_cd having count(*)>1) q"
    stale_or_missing_enter = Invoke-CanaryCount "select count(*) from signal_data_freshness_log where created_at >= '$sinceIso' and action='ENTER' and freshness_status in ('STALE','MISSING','CANCEL')"
    enter_missing_source_lineage = Invoke-CanaryCount "select count(*) from trading_signals where created_at >= '$sinceIso' and execution_decision='ENTER' and (data_source='{}'::jsonb or source_timestamp='{}'::jsonb or source_age_ms='{}'::jsonb)"
    family_counts = @(Invoke-CanarySql "select coalesce(strategy_family,'NULL')||'='||count(*) from trading_signals where created_at >= '$sinceIso' group by strategy_family order by strategy_family")
}

$unhealthy = @($health.GetEnumerator() | Where-Object { $_.Value -ne "healthy" })
$violations = @()
if ($unhealthy.Count -gt 0) { $violations += "UNHEALTHY_SERVICE" }
if ($metrics.missing_family_lineage -gt 0) { $violations += "MISSING_FAMILY_LINEAGE" }
if ($metrics.duplicate_active_stocks -gt 0) { $violations += "DUPLICATE_ACTIVE_STOCK" }
if ($metrics.stale_or_missing_enter -gt 0) { $violations += "STALE_OR_MISSING_ENTER" }
if ($metrics.enter_missing_source_lineage -gt 0) { $violations += "ENTER_MISSING_SOURCE_LINEAGE" }
$metrics["violations"] = $violations
$metrics["recommendation"] = if ($violations.Count -eq 0) { "CONTINUE_CANARY" } else { "ROLLBACK_NOW" }

$metrics | ConvertTo-Json -Depth 5
if ($violations.Count -gt 0) { exit 2 }
