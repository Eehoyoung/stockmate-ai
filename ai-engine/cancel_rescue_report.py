from __future__ import annotations

import argparse
import asyncio
import csv
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import asyncpg

from config import PG_DB, PG_HOST, PG_PASSWORD, PG_PORT, PG_USER


TICK_UNION_LEGACY_SQL = """
    SELECT stk_cd, cur_prc, created_at
    FROM ws_tick_data
    WHERE cur_prc IS NOT NULL
"""

TICK_UNION_WITH_PARTITIONED_SQL = """
    SELECT stk_cd, cur_prc, created_at
    FROM ws_tick_data
    WHERE cur_prc IS NOT NULL
    UNION ALL
    SELECT stk_cd, cur_prc, created_at
    FROM ws_tick_data_partitioned
    WHERE cur_prc IS NOT NULL
"""


REPORT_SQL = """
WITH thresholds(strategy, threshold, rescue_floor, base_strength) AS (
    VALUES
    ('S1_GAP_OPEN',55.0,10.0,110.0),
    ('S7_ICHIMOKU_BREAKOUT',62.0,35.0,NULL),
    ('S8_GOLDEN_CROSS',50.0,45.0,NULL),
    ('S9_PULLBACK_SWING',55.0,40.0,NULL),
    ('S15_MOMENTUM_ALIGN',60.0,50.0,100.0)
), tick_union AS (
{tick_union_sql}
), cancelled AS (
    SELECT
        'RULE' AS cancel_source,
        r.signal_id,
        r.stk_cd,
        r.strategy,
        r.cancel_type,
        r.reason,
        r.created_at AS cancel_at,
        ts.stk_nm,
        COALESCE(ts.entry_price, ts.target_price, ts.tp1_price)::float8 AS entry_price,
        ts.tp1_price::float8 AS tp1_price,
        ts.sl_price::float8 AS sl_price,
        ts.rule_score::float8 AS rule_score,
        ts.effective_rr::float8 AS effective_rr,
        ts.cntr_strength::float8 AS cntr_strength,
        ts.bid_ratio::float8 AS bid_ratio,
        th.threshold,
        th.rescue_floor,
        th.base_strength
    FROM rule_cancel_signal r
    JOIN trading_signals ts ON ts.id = r.signal_id
    LEFT JOIN thresholds th ON th.strategy = r.strategy
    WHERE r.created_at >= $1 AND r.created_at < $2

    UNION ALL

    SELECT
        'AI',
        a.signal_id,
        a.stk_cd,
        a.strategy,
        COALESCE(a.cancel_reason, 'AI_CANCEL'),
        a.reason,
        a.created_at,
        ts.stk_nm,
        COALESCE(ts.entry_price, ts.target_price, ts.tp1_price)::float8,
        ts.tp1_price::float8,
        ts.sl_price::float8,
        ts.rule_score::float8,
        ts.effective_rr::float8,
        ts.cntr_strength::float8,
        ts.bid_ratio::float8,
        th.threshold,
        th.rescue_floor,
        th.base_strength
    FROM ai_cancel_signal a
    JOIN trading_signals ts ON ts.id = a.signal_id
    LEFT JOIN thresholds th ON th.strategy = a.strategy
    WHERE a.created_at >= $1 AND a.created_at < $2
), bucketed AS (
    SELECT *,
        CASE
            WHEN cancel_source = 'RULE'
             AND cancel_type = 'RULE_THRESHOLD'
             AND rescue_floor IS NOT NULL
             AND rule_score >= rescue_floor
             AND rule_score < threshold
             AND (
                (strategy = 'S7_ICHIMOKU_BREAKOUT' AND effective_rr >= 1.8 AND cntr_strength >= 115.0)
                OR (strategy = 'S1_GAP_OPEN' AND effective_rr >= 1.2 AND cntr_strength >= 140.0 AND COALESCE(bid_ratio, 0) >= 1.5)
                OR (strategy = 'S15_MOMENTUM_ALIGN' AND effective_rr >= 1.3 AND cntr_strength >= 90.0 AND COALESCE(bid_ratio, 0) >= 1.5)
                OR (strategy IN ('S8_GOLDEN_CROSS', 'S9_PULLBACK_SWING') AND effective_rr >= 1.5 AND cntr_strength >= 100.0)
             ) THEN 'RULE_RESCUE'
            WHEN cancel_source = 'RULE'
             AND cancel_type = 'HARD_GATE'
             AND strategy IN ('S1_GAP_OPEN', 'S15_MOMENTUM_ALIGN')
             AND cntr_strength >= COALESCE(base_strength, 999999.0)
             AND bid_ratio >= CASE strategy WHEN 'S1_GAP_OPEN' THEN 0.60 ELSE 0.50 END
             AND reason NOT ILIKE '%strength%' THEN 'BID_GATE_RESCUE'
            WHEN cancel_source = 'RULE'
             AND cancel_type = 'S8_BUY_ZONE'
             AND strategy = 'S8_GOLDEN_CROSS'
             AND (effective_rr >= 1.5 OR rule_score >= 75.0) THEN 'S8_ZONE_RESCUE'
            ELSE 'NON_RESCUE'
        END AS rescue_bucket
    FROM cancelled
    WHERE entry_price IS NOT NULL AND entry_price > 0
      AND tp1_price IS NOT NULL AND sl_price IS NOT NULL
), path AS (
    SELECT
        b.*,
        p.tp_at,
        p.sl_at,
        p.max_price,
        p.min_price,
        p.last_price
    FROM bucketed b
    LEFT JOIN LATERAL (
        SELECT
            MIN(created_at) FILTER (WHERE cur_prc >= b.tp1_price) AS tp_at,
            MIN(created_at) FILTER (WHERE cur_prc <= b.sl_price) AS sl_at,
            MAX(cur_prc) AS max_price,
            MIN(cur_prc) AS min_price,
            (ARRAY_AGG(cur_prc ORDER BY created_at DESC))[1] AS last_price
        FROM tick_union t
        WHERE t.stk_cd = b.stk_cd
          AND t.created_at >= b.cancel_at
          AND t.created_at < LEAST($2, b.cancel_at + ($3::int * INTERVAL '1 day'))
    ) p ON TRUE
)
SELECT
    signal_id,
    cancel_at,
    cancel_source,
    rescue_bucket,
    stk_cd,
    stk_nm,
    strategy,
    cancel_type,
    entry_price,
    tp1_price,
    sl_price,
    rule_score,
    effective_rr,
    cntr_strength,
    bid_ratio,
    CASE
        WHEN max_price IS NULL THEN 'NO_TICKS'
        WHEN tp_at IS NOT NULL AND (sl_at IS NULL OR tp_at <= sl_at) THEN 'TP1_FIRST'
        WHEN sl_at IS NOT NULL AND (tp_at IS NULL OR sl_at < tp_at) THEN 'SL_FIRST'
        ELSE 'TIMEOUT'
    END AS outcome,
    ROUND(((max_price - entry_price) / NULLIF(entry_price, 0) * 100)::numeric, 3) AS mfe_pct,
    ROUND(((min_price - entry_price) / NULLIF(entry_price, 0) * 100)::numeric, 3) AS mae_pct,
    CASE
        WHEN max_price IS NULL THEN NULL
        WHEN tp_at IS NOT NULL AND (sl_at IS NULL OR tp_at <= sl_at)
            THEN ROUND(((tp1_price - entry_price) / NULLIF(entry_price, 0) * 100)::numeric, 3)
        WHEN sl_at IS NOT NULL AND (tp_at IS NULL OR sl_at < tp_at)
            THEN ROUND(((sl_price - entry_price) / NULLIF(entry_price, 0) * 100)::numeric, 3)
        ELSE ROUND(((last_price - entry_price) / NULLIF(entry_price, 0) * 100)::numeric, 3)
    END AS sim_pnl_pct
FROM path
WHERE rescue_bucket <> 'NON_RESCUE'
ORDER BY cancel_at, rescue_bucket, strategy, stk_cd
"""


async def _has_table(conn: asyncpg.Connection, table_name: str) -> bool:
    return bool(await conn.fetchval("SELECT to_regclass($1::text) IS NOT NULL", f"public.{table_name}"))


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def resolve_window(args: argparse.Namespace) -> tuple[datetime, datetime]:
    if args.start or args.end:
        if not args.start or not args.end:
            raise SystemExit("--start and --end must be used together")
        start = _parse_date(args.start)
        end = _parse_date(args.end) + timedelta(days=1)
    elif args.date:
        start = _parse_date(args.date)
        end = start + timedelta(days=1)
    else:
        days = int(args.days or 1)
        end = date.today() + timedelta(days=1)
        start = end - timedelta(days=days)
    kst = timezone(timedelta(hours=9))
    return datetime.combine(start, datetime.min.time(), tzinfo=kst), datetime.combine(end, datetime.min.time(), tzinfo=kst)


def summarize(rows: list[asyncpg.Record]) -> list[dict]:
    groups: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row["rescue_bucket"], row["strategy"])
        group = groups.setdefault(
            key,
            {
                "rescue_bucket": row["rescue_bucket"],
                "strategy": row["strategy"],
                "n": 0,
                "tp1_first": 0,
                "sl_first": 0,
                "timeout": 0,
                "no_ticks": 0,
                "sum_sim_pnl_pct": 0.0,
                "sum_mfe_pct": 0.0,
                "sum_mae_pct": 0.0,
                "valid": 0,
            },
        )
        group["n"] += 1
        outcome = row["outcome"]
        if outcome == "TP1_FIRST":
            group["tp1_first"] += 1
        elif outcome == "SL_FIRST":
            group["sl_first"] += 1
        elif outcome == "TIMEOUT":
            group["timeout"] += 1
        else:
            group["no_ticks"] += 1

        if row["sim_pnl_pct"] is not None:
            group["valid"] += 1
            group["sum_sim_pnl_pct"] += float(row["sim_pnl_pct"])
        if row["mfe_pct"] is not None:
            group["sum_mfe_pct"] += float(row["mfe_pct"])
        if row["mae_pct"] is not None:
            group["sum_mae_pct"] += float(row["mae_pct"])

    summary = []
    for group in groups.values():
        valid = max(group["valid"], 1)
        total = max(group["n"] - group["no_ticks"], 1)
        summary.append({
            **group,
            "avg_sim_pnl_pct": round(group["sum_sim_pnl_pct"] / valid, 3),
            "avg_mfe_pct": round(group["sum_mfe_pct"] / total, 3),
            "avg_mae_pct": round(group["sum_mae_pct"] / total, 3),
            "tp1_first_rate": round(group["tp1_first"] / total * 100, 1),
            "false_cancel_rate": round((group["tp1_first"] + group["timeout"]) / total * 100, 1),
        })
    return sorted(summary, key=lambda r: (r["rescue_bucket"], r["strategy"]))


def write_csv(path: Path, rows: Iterable[dict]) -> None:
    rows = list(rows)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, *, start: datetime, end: datetime, summary: list[dict], rows: list[asyncpg.Record]) -> None:
    lines = [
        f"# CANCEL Rescue Daily Report - {start.date()} to {(end - timedelta(days=1)).date()}",
        "",
        f"- Rescue candidates: {len(rows)}",
        "",
        "## Summary",
        "",
        "| Bucket | Strategy | N | TP1 First | SL First | Timeout | No Ticks | Avg PnL | Avg MFE | Avg MAE | TP1 Rate | False Cancel Rate |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in summary:
        lines.append(
            f"| {r['rescue_bucket']} | {r['strategy']} | {r['n']} | {r['tp1_first']} | {r['sl_first']} | "
            f"{r['timeout']} | {r['no_ticks']} | {r['avg_sim_pnl_pct']:.3f}% | {r['avg_mfe_pct']:.3f}% | "
            f"{r['avg_mae_pct']:.3f}% | {r['tp1_first_rate']:.1f}% | {r['false_cancel_rate']:.1f}% |"
        )
    lines.extend([
        "",
        "## Top Simulated PnL",
        "",
        "| Time | Bucket | Stock | Strategy | Outcome | Sim PnL | MFE | MAE |",
        "|---|---|---|---|---|---:|---:|---:|",
    ])
    top_rows = sorted(
        [r for r in rows if r["sim_pnl_pct"] is not None],
        key=lambda r: float(r["sim_pnl_pct"]),
        reverse=True,
    )[:20]
    for r in top_rows:
        ts = r["cancel_at"].astimezone().strftime("%m-%d %H:%M")
        lines.append(
            f"| {ts} | {r['rescue_bucket']} | {r['stk_cd']} {r['stk_nm'] or ''} | {r['strategy']} | "
            f"{r['outcome']} | {float(r['sim_pnl_pct']):.3f}% | "
            f"{float(r['mfe_pct'] or 0):.3f}% | {float(r['mae_pct'] or 0):.3f}% |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def run(args: argparse.Namespace) -> None:
    start, end = resolve_window(args)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pool = await asyncpg.create_pool(
        host=PG_HOST,
        port=PG_PORT,
        database=PG_DB,
        user=PG_USER,
        password=PG_PASSWORD,
        min_size=1,
        max_size=2,
    )
    try:
        async with pool.acquire() as conn:
            tick_union_sql = TICK_UNION_LEGACY_SQL
            if await _has_table(conn, "ws_tick_data_partitioned"):
                tick_union_sql = TICK_UNION_WITH_PARTITIONED_SQL
            rows = await conn.fetch(
                REPORT_SQL.format(tick_union_sql=tick_union_sql),
                start,
                end,
                int(args.horizon_days),
            )
    finally:
        await pool.close()

    summary = summarize(rows)
    stem = f"cancel_rescue_daily_{start.date()}_{(end - timedelta(days=1)).date()}"
    formats = {fmt.strip().lower() for fmt in args.format.split(",") if fmt.strip()}
    if "csv" in formats:
        write_csv(out_dir / f"{stem}.csv", [dict(r) for r in rows])
        write_csv(out_dir / f"{stem}_summary.csv", summary)
    if "md" in formats:
        write_markdown(out_dir / f"{stem}.md", start=start, end=end, summary=summary, rows=rows)
    print(f"rows={len(rows)} summary_groups={len(summary)} output_dir={out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate CANCEL rescue backtest report.")
    parser.add_argument("--date", help="Single KST date, YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=None, help="Trailing days ending today")
    parser.add_argument("--start", help="Start KST date, YYYY-MM-DD")
    parser.add_argument("--end", help="End KST date, YYYY-MM-DD inclusive")
    parser.add_argument("--horizon-days", type=int, default=2)
    parser.add_argument("--format", default="md,csv", help="Comma-separated output formats: md,csv")
    parser.add_argument("--output-dir", default="../docs")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
