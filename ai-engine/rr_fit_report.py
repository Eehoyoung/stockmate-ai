"""
Strategy-level R:R fit report.

Usage:
    python rr_fit_report.py --days 5

The report compares:
  - stored_rr: rr_ratio saved by the signal pipeline
  - price_rr: R:R recomputed from saved entry/tp/sl prices
  - pass rates for service thresholds such as 1.0 and 1.2
"""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from statistics import mean
from typing import Any

import asyncpg

from config import PG_DB, PG_HOST, PG_PASSWORD, PG_PORT, PG_USER


async def _init_pg_conn(conn: asyncpg.Connection) -> None:
    await conn.execute("SET TIME ZONE 'Asia/Seoul'")


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def calc_price_rr(entry: Any, target: Any, stop: Any) -> float | None:
    entry_f = _f(entry)
    target_f = _f(target)
    stop_f = _f(stop)
    if not entry_f or not target_f or not stop_f:
        return None
    reward = target_f - entry_f
    risk = entry_f - stop_f
    if reward <= 0 or risk <= 0:
        return None
    return round(reward / risk, 3)


def pct_distance(entry: Any, price: Any) -> float | None:
    entry_f = _f(entry)
    price_f = _f(price)
    if not entry_f or not price_f:
        return None
    return round((price_f - entry_f) / entry_f * 100, 3)


def verdict(avg_rr: float | None, pass_10: float, pass_12: float, count: int) -> str:
    if count < 5:
        return "INSUFFICIENT"
    if avg_rr is not None and avg_rr >= 1.2 and pass_12 >= 0.55:
        return "FIT"
    if avg_rr is not None and avg_rr >= 1.0 and pass_10 >= 0.55:
        return "BORDERLINE"
    return "UNFIT"


async def fetch_rows(days: int) -> list[asyncpg.Record]:
    pool = await asyncpg.create_pool(
        host=PG_HOST,
        port=PG_PORT,
        database=PG_DB,
        user=PG_USER,
        password=PG_PASSWORD,
        min_size=1,
        max_size=2,
        init=_init_pg_conn,
    )
    try:
        return await pool.fetch(
            """
            SELECT
                id,
                strategy,
                action,
                signal_status,
                entry_price,
                COALESCE(target_price, tp1_price) AS target_price,
                COALESCE(stop_price, sl_price) AS stop_price,
                sl_price,
                tp1_price,
                tp2_price,
                rr_ratio,
                rule_score,
                ai_score,
                created_at
            FROM trading_signals
            WHERE created_at >= NOW() - ($1 || ' days')::INTERVAL
              AND entry_price IS NOT NULL
              AND COALESCE(target_price, tp1_price) IS NOT NULL
              AND COALESCE(stop_price, sl_price) IS NOT NULL
            ORDER BY created_at DESC
            """,
            str(days),
        )
    finally:
        await pool.close()


def summarize(rows: list[asyncpg.Record]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        entry = row["entry_price"]
        target = row["target_price"]
        stop = row["stop_price"] or row["sl_price"]
        price_rr = calc_price_rr(entry, target, stop)
        stored_rr = _f(row["rr_ratio"])
        grouped[row["strategy"] or "UNKNOWN"].append(
            {
                "stored_rr": stored_rr,
                "price_rr": price_rr,
                "target_pct": pct_distance(entry, target),
                "stop_pct": pct_distance(entry, stop),
                "is_cancel": row["action"] == "CANCEL" or row["signal_status"] == "CANCELLED",
            }
        )

    output = []
    for strategy, items in grouped.items():
        stored = [x["stored_rr"] for x in items if x["stored_rr"] is not None]
        price = [x["price_rr"] for x in items if x["price_rr"] is not None]
        target_pct = [x["target_pct"] for x in items if x["target_pct"] is not None]
        stop_pct = [abs(x["stop_pct"]) for x in items if x["stop_pct"] is not None]
        rr_for_verdict = price or stored
        avg_rr = round(mean(rr_for_verdict), 3) if rr_for_verdict else None
        pass_10 = sum(1 for v in rr_for_verdict if v >= 1.0) / len(rr_for_verdict) if rr_for_verdict else 0.0
        pass_12 = sum(1 for v in rr_for_verdict if v >= 1.2) / len(rr_for_verdict) if rr_for_verdict else 0.0
        output.append(
            {
                "strategy": strategy,
                "count": len(items),
                "cancel_rate": round(sum(1 for x in items if x["is_cancel"]) / len(items), 3),
                "avg_stored_rr": round(mean(stored), 3) if stored else None,
                "avg_price_rr": round(mean(price), 3) if price else None,
                "pass_rr_1_0": round(pass_10, 3),
                "pass_rr_1_2": round(pass_12, 3),
                "avg_target_pct": round(mean(target_pct), 3) if target_pct else None,
                "avg_stop_pct": round(mean(stop_pct), 3) if stop_pct else None,
                "verdict": verdict(avg_rr, pass_10, pass_12, len(items)),
            }
        )
    return sorted(output, key=lambda x: (x["verdict"], -x["count"], x["strategy"]))


def print_table(rows: list[dict[str, Any]]) -> None:
    headers = [
        "strategy",
        "count",
        "cancel",
        "stored_rr",
        "price_rr",
        "rr>=1.0",
        "rr>=1.2",
        "target%",
        "stop%",
        "verdict",
    ]
    print("\t".join(headers))
    for row in rows:
        print(
            "\t".join(
                str(x)
                for x in [
                    row["strategy"],
                    row["count"],
                    row["cancel_rate"],
                    row["avg_stored_rr"],
                    row["avg_price_rr"],
                    row["pass_rr_1_0"],
                    row["pass_rr_1_2"],
                    row["avg_target_pct"],
                    row["avg_stop_pct"],
                    row["verdict"],
                ]
            )
        )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=5)
    args = parser.parse_args()
    rows = await fetch_rows(args.days)
    print_table(summarize(rows))


if __name__ == "__main__":
    asyncio.run(main())
