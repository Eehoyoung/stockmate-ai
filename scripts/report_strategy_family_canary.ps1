param(
    [datetime]$SinceKst = [datetime]"2026-08-16T23:37:00+09:00",
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
$sinceIso = $SinceKst.ToString("yyyy-MM-dd HH:mm:sszzz")

function Query([string]$Sql) {
    $rows = docker exec stockmate-ai-postgres-1 psql -U postgres -d SMA -F '|' -Atc $Sql
    if ($LASTEXITCODE -ne 0) { throw "canary report query failed" }
    return @($rows)
}

function Cell([object]$Value) {
    if ($null -eq $Value -or [string]::IsNullOrWhiteSpace([string]$Value)) { return "INSUFFICIENT_SAMPLE" }
    return [string]$Value
}

$groupSql = @"
WITH base AS (
  SELECT s.id, s.strategy_family, s.strategy::text AS setup_id, s.market_type, s.market_flu_rt,
         o.realized_rr_net, o.realized_pnl,
         sh.max_favorable_excursion AS mfe, sh.max_adverse_excursion AS mae
  FROM trading_signals s
  LEFT JOIN LATERAL (
    SELECT realized_rr_net, realized_pnl FROM trade_outcomes
    WHERE signal_id=s.id ORDER BY exit_ts DESC NULLS LAST, id DESC LIMIT 1
  ) o ON true
  LEFT JOIN LATERAL (
    SELECT max_favorable_excursion, max_adverse_excursion FROM shadow_trades
    WHERE signal_id=s.id ORDER BY updated_at DESC NULLS LAST, id DESC LIMIT 1
  ) sh ON true
  WHERE s.created_at >= '$sinceIso'
)
SELECT COALESCE(strategy_family,'NULL'), setup_id, count(*),
       count(realized_rr_net),
       round(avg(realized_rr_net)::numeric,4),
       round((avg(realized_rr_net)-1.96*stddev_samp(realized_rr_net)/sqrt(count(realized_rr_net)))::numeric,4),
       round((avg(realized_rr_net)+1.96*stddev_samp(realized_rr_net)/sqrt(count(realized_rr_net)))::numeric,4),
       round((sum(realized_rr_net) FILTER (WHERE realized_rr_net>0) /
              NULLIF(abs(sum(realized_rr_net) FILTER (WHERE realized_rr_net<0)),0))::numeric,4),
       round(avg(mfe)::numeric,4), round(avg(mae)::numeric,4)
FROM base GROUP BY strategy_family, setup_id ORDER BY strategy_family, setup_id
"@

$drawdownSql = @"
WITH pnl AS (
  SELECT o.exit_ts, o.realized_rr_net,
         sum(o.realized_rr_net) OVER (ORDER BY o.exit_ts,o.id) AS equity
  FROM trade_outcomes o JOIN trading_signals s ON s.id=o.signal_id
  WHERE s.created_at >= '$sinceIso' AND o.realized_rr_net IS NOT NULL
), dd AS (
  SELECT equity-max(equity) OVER (ORDER BY exit_ts ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS drawdown
  FROM pnl
)
SELECT round(min(drawdown)::numeric,4) FROM dd
"@

$marketSql = @"
SELECT COALESCE(strategy_family,'NULL'), COALESCE(market_type,'UNKNOWN'),
       CASE WHEN market_flu_rt>=1 THEN 'BULL' WHEN market_flu_rt<=-1 THEN 'BEAR' ELSE 'SIDEWAYS_OR_UNKNOWN' END,
       count(*)
FROM trading_signals WHERE created_at >= '$sinceIso'
GROUP BY strategy_family,market_type,3 ORDER BY strategy_family,market_type,3
"@

$overlapSql = @"
SELECT count(*),
       count(*) FILTER (WHERE jsonb_array_length(matched_setup_ids)>1),
       round(100.0*count(*) FILTER (WHERE jsonb_array_length(matched_setup_ids)>1)/NULLIF(count(*),0),2)
FROM trading_signals WHERE created_at >= '$sinceIso'
"@

$tradingDays = (Query "select count(distinct date) from market_daily_context where date >= '$($SinceKst.ToString('yyyy-MM-dd'))'::date and source_complete=true and official_snapshot is not null")[0]
$groups = Query $groupSql
$markets = Query $marketSql
$overlap = (Query $overlapSql | Select-Object -First 1) -split '\|', -1
$maxDrawdown = Cell (Query $drawdownSql | Select-Object -First 1)
$guardJson = & "$PSScriptRoot\monitor_strategy_family_canary.ps1" -SinceKst $SinceKst | Out-String
$guard = $guardJson | ConvertFrom-Json

$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add("# Strategy Family Live Canary Report")
$lines.Add("")
$lines.Add("- Observation start: $sinceIso")
$lines.Add("- Generated at: $([datetimeoffset]::Now.ToString('o'))")
$lines.Add("- Observed signal dates: $(Cell $tradingDays) / 5")
$lines.Add("- Guard decision: $($guard.recommendation)")
$lines.Add("- Overall max drawdown (realized net RR): $maxDrawdown")
$lines.Add("")
$lines.Add("## Family / Setup Performance")
$lines.Add("")
$lines.Add("| Family | Setup | Signals | Evaluable | Net expectancy | 95pct CI low | 95pct CI high | PF | Mean MFE | Mean MAE |")
$lines.Add("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
if ($groups.Count -eq 0) {
    $lines.Add("| - | - | 0 | 0 | INSUFFICIENT_SAMPLE | INSUFFICIENT_SAMPLE | INSUFFICIENT_SAMPLE | INSUFFICIENT_SAMPLE | INSUFFICIENT_SAMPLE | INSUFFICIENT_SAMPLE |")
} else {
    foreach ($row in $groups) {
        $v = $row -split '\|', -1
        $lines.Add("| $($v[0]) | $($v[1]) | $($v[2]) | $($v[3]) | $(Cell $v[4]) | $(Cell $v[5]) | $(Cell $v[6]) | $(Cell $v[7]) | $(Cell $v[8]) | $(Cell $v[9]) |")
    }
}
$lines.Add("")
$lines.Add("## Market / Regime Breakdown")
$lines.Add("")
$lines.Add("| Family | Market | Regime proxy | Signals |")
$lines.Add("|---|---|---|---:|")
if ($markets.Count -eq 0) { $lines.Add("| - | - | - | 0 |") }
else { foreach ($row in $markets) { $v=$row -split '\|',-1; $lines.Add("| $($v[0]) | $($v[1]) | $($v[2]) | $($v[3]) |") } }
$lines.Add("")
$lines.Add("## Overlap / Safety")
$lines.Add("")
$lines.Add("- Total signals: $(Cell $overlap[0])")
$lines.Add("- Multi-setup confirmations: $(Cell $overlap[1])")
$overlapRate = Cell $overlap[2]
$lines.Add("- Overlap rate: $(if ($overlapRate -eq 'INSUFFICIENT_SAMPLE') { $overlapRate } else { $overlapRate + '%' })")
$lines.Add("- Missing lineage: $($guard.missing_family_lineage)")
$lines.Add("- Duplicate active stocks: $($guard.duplicate_active_stocks)")
$lines.Add("- stale/missing ENTER: $($guard.stale_or_missing_enter)")
$lines.Add("- ENTER missing source lineage: $($guard.enter_missing_source_lineage)")
$lines.Add("")
$lines.Add("Metrics below the sample floor are not approval evidence; their final classification is INSUFFICIENT_SAMPLE.")

$report = $lines -join [Environment]::NewLine
if ($OutputPath) {
    $resolved = if ([System.IO.Path]::IsPathRooted($OutputPath)) { $OutputPath } else { Join-Path $projectRoot $OutputPath }
    $parent = Split-Path -Parent $resolved
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    Set-Content -LiteralPath $resolved -Value $report -Encoding utf8
}
$report
