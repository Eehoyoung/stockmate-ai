"""
verify_data_quality.py

2026-05-15 수정된 5개 구조적 결함이 다음 영업일에 올바르게 반영됐는지 검증.

실행:
    python verify_data_quality.py           # 오늘 데이터 기준
    python verify_data_quality.py 2026-05-16  # 특정 날짜 지정

각 항목마다 PASS / FAIL / SKIP(데이터 없음) 판정을 출력하고,
최종 요약 및 DB 원본 수치를 표로 보여준다.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any

import asyncpg
from dotenv import load_dotenv

load_dotenv()

# ── 연결 정보 ──────────────────────────────────────────────────────────────────
PG_DSN = (
    f"postgresql://{os.getenv('POSTGRES_USER','postgres')}"
    f":{os.getenv('POSTGRES_PASSWORD','')}"
    f"@{os.getenv('POSTGRES_HOST','localhost')}"
    f":{os.getenv('POSTGRES_PORT','5432')}"
    f"/{os.getenv('POSTGRES_DB','SMA')}"
)

KST = timezone(timedelta(hours=9))

# ── 검증 대상 전략 (지표 payload 추가된 전략) ──────────────────────────────────
MA_STRATEGIES    = {"S8_GOLDEN_CROSS", "S9_PULLBACK_SWING"}
ATR_STRATEGIES   = {"S13_BOX_BREAKOUT", "S14_OVERSOLD_BOUNCE"}
BB_STRATEGIES    = {"S14_OVERSOLD_BOUNCE"}
RSI_STRATEGIES   = {"S7_ICHIMOKU_BREAKOUT", "S8_GOLDEN_CROSS", "S9_PULLBACK_SWING",
                    "S14_OVERSOLD_BOUNCE", "S15_MOMENTUM_ALIGN"}
S9_STRATEGY      = "S9_PULLBACK_SWING"

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


def _fmt(label: str, result: str, detail: str = "") -> str:
    color = GREEN if result == "PASS" else (YELLOW if result == "SKIP" else RED)
    line = f"  {color}{BOLD}{result}{RESET}  {label}"
    if detail:
        line += f"  — {detail}"
    return line


async def run_checks(target_date: date) -> None:
    conn: asyncpg.Connection = await asyncpg.connect(PG_DSN)
    start_kst = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=KST)

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  데이터 품질 검증  ({target_date}){RESET}")
    print(f"{BOLD}{'='*60}{RESET}\n")

    results: list[tuple[str, str]] = []

    # ── 기본 신호 건수 ──────────────────────────────────────────────────────────
    total: int = await conn.fetchval(
        "SELECT COUNT(*) FROM trading_signals WHERE created_at >= $1", start_kst
    )
    print(f"  오늘 trading_signals 총 {total}건\n")

    if total == 0:
        print(f"  {YELLOW}데이터 없음 — 장중(09:00 이후)에 재실행하세요.{RESET}\n")
        await conn.close()
        return

    # ──────────────────────────────────────────────────────────────────────────
    # FIX-1  base_score (scorer.py 수정)
    # ──────────────────────────────────────────────────────────────────────────
    r = await conn.fetchrow("""
        SELECT COUNT(*) AS total,
               COUNT(ssc.base_score) AS filled,
               ROUND(AVG(ssc.base_score)::numeric, 1) AS avg_val
        FROM signal_score_components ssc
        JOIN trading_signals ts ON ts.id = ssc.signal_id
        WHERE ts.created_at >= $1
    """, start_kst)

    fix1_total, fix1_filled = r["total"], r["filled"]
    if fix1_total == 0:
        label, res, detail = "FIX-1  base_score", "SKIP", "signal_score_components 없음"
    elif fix1_filled == fix1_total:
        label, res, detail = "FIX-1  base_score", "PASS", \
            f"{fix1_filled}/{fix1_total}건 채움  avg={r['avg_val']}"
    elif fix1_filled > 0:
        label, res, detail = "FIX-1  base_score", "FAIL", \
            f"{fix1_filled}/{fix1_total}건만 채움 (일부 누락)"
    else:
        label, res, detail = "FIX-1  base_score", "FAIL", f"0/{fix1_total}건 — 여전히 전부 NULL"
    print(_fmt(label, res, detail))
    results.append((label, res))

    # ──────────────────────────────────────────────────────────────────────────
    # FIX-2  market_flu_rt (queue_worker 하드코딩 None 수정)
    # ──────────────────────────────────────────────────────────────────────────
    r = await conn.fetchrow("""
        SELECT COUNT(*) AS total,
               COUNT(market_flu_rt) AS filled,
               ROUND(MIN(market_flu_rt)::numeric, 2) AS min_val,
               ROUND(MAX(market_flu_rt)::numeric, 2) AS max_val
        FROM trading_signals
        WHERE created_at >= $1
    """, start_kst)

    fix2_filled = r["filled"]
    if fix2_filled == total:
        label, res, detail = "FIX-2  market_flu_rt", "PASS", \
            f"{fix2_filled}/{total}건  범위 [{r['min_val']} ~ {r['max_val']}]"
    elif fix2_filled > 0:
        label, res, detail = "FIX-2  market_flu_rt", "FAIL", \
            f"{fix2_filled}/{total}건만 채움"
    else:
        label, res, detail = "FIX-2  market_flu_rt", "FAIL", f"0/{total}건 — 여전히 전부 NULL"
    print(_fmt(label, res, detail))
    results.append((label, res))

    # ──────────────────────────────────────────────────────────────────────────
    # FIX-3  news_sentiment (하드코딩 None 수정 — 데이터 있을 때만 채움)
    # ──────────────────────────────────────────────────────────────────────────
    r = await conn.fetchrow("""
        SELECT COUNT(*) AS total, COUNT(news_sentiment) AS filled
        FROM trading_signals
        WHERE created_at >= $1
    """, start_kst)

    news_filled = r["filled"]
    if news_filled > 0:
        label, res, detail = "FIX-3  news_sentiment", "PASS", \
            f"{news_filled}/{total}건 채움 (payload에 뉴스 데이터 있는 건만)"
    else:
        label, res, detail = "FIX-3  news_sentiment", "SKIP", \
            "0건 — payload에 뉴스 없거나 정상 (뉴스 없는 날은 NULL이 맞음)"
    print(_fmt(label, res, detail))
    results.append((label, res))

    # ──────────────────────────────────────────────────────────────────────────
    # FIX-4  S9 flu_rt 시장지수 폴백 (strategy_9 수정)
    # ──────────────────────────────────────────────────────────────────────────
    s9_rows = await conn.fetch("""
        SELECT ts.stk_cd,
               ssc.strategy_components->>'flu_rt' AS flu_rt_raw
        FROM trading_signals ts
        JOIN signal_score_components ssc ON ssc.signal_id = ts.id
        WHERE ts.created_at >= $1
          AND ts.strategy = $2
    """, start_kst, S9_STRATEGY)

    if not s9_rows:
        label, res, detail = "FIX-4  S9 flu_rt 폴백", "SKIP", "오늘 S9 신호 없음"
    else:
        zero_count = sum(
            1 for row in s9_rows
            if row["flu_rt_raw"] in (None, "0", "0.0", "null")
        )
        non_zero = len(s9_rows) - zero_count
        if zero_count == 0:
            label, res, detail = "FIX-4  S9 flu_rt 폴백", "PASS", \
                f"전체 {len(s9_rows)}건 모두 비-0 flu_rt"
        elif non_zero > 0:
            label, res, detail = "FIX-4  S9 flu_rt 폴백", "FAIL", \
                f"{zero_count}/{len(s9_rows)}건 여전히 0.0 (WS 미구독 종목 폴백 미작동 가능성)"
        else:
            label, res, detail = "FIX-4  S9 flu_rt 폴백", "FAIL", \
                f"전체 {len(s9_rows)}건 flu_rt=0 — 폴백 미작동"
    print(_fmt(label, res, detail))
    results.append((label, res))

    # ──────────────────────────────────────────────────────────────────────────
    # FIX-5a  ma5_at_signal (S8/S9 수정)
    # ──────────────────────────────────────────────────────────────────────────
    strategies_list = list(MA_STRATEGIES)
    r = await conn.fetchrow("""
        SELECT COUNT(*) AS total, COUNT(ma5_at_signal) AS filled
        FROM trading_signals
        WHERE created_at >= $1
          AND strategy = ANY($2::text[])
    """, start_kst, strategies_list)

    ma_total, ma_filled = r["total"], r["filled"]
    if ma_total == 0:
        label, res, detail = "FIX-5a ma5_at_signal (S8/S9)", "SKIP", "S8/S9 신호 없음"
    elif ma_filled == ma_total:
        label, res, detail = "FIX-5a ma5_at_signal (S8/S9)", "PASS", \
            f"{ma_filled}/{ma_total}건 채움"
    elif ma_filled > 0:
        label, res, detail = "FIX-5a ma5_at_signal (S8/S9)", "FAIL", \
            f"{ma_filled}/{ma_total}건만 채움"
    else:
        label, res, detail = "FIX-5a ma5_at_signal (S8/S9)", "FAIL", \
            f"0/{ma_total}건 — payload 주입 미작동"
    print(_fmt(label, res, detail))
    results.append((label, res))

    # ──────────────────────────────────────────────────────────────────────────
    # FIX-5b  atr_at_signal (S13/S14 수정)
    # ──────────────────────────────────────────────────────────────────────────
    atr_list = list(ATR_STRATEGIES)
    r = await conn.fetchrow("""
        SELECT COUNT(*) AS total, COUNT(atr_at_signal) AS filled
        FROM trading_signals
        WHERE created_at >= $1
          AND strategy = ANY($2::text[])
    """, start_kst, atr_list)

    atr_total, atr_filled = r["total"], r["filled"]
    if atr_total == 0:
        label, res, detail = "FIX-5b atr_at_signal (S13/S14)", "SKIP", "S13/S14 신호 없음"
    elif atr_filled == atr_total:
        label, res, detail = "FIX-5b atr_at_signal (S13/S14)", "PASS", \
            f"{atr_filled}/{atr_total}건 채움"
    else:
        label, res, detail = "FIX-5b atr_at_signal (S13/S14)", "FAIL", \
            f"{atr_filled}/{atr_total}건만 채움"
    print(_fmt(label, res, detail))
    results.append((label, res))

    # ──────────────────────────────────────────────────────────────────────────
    # FIX-5c  bb_upper_at_sig (S14 수정)
    # ──────────────────────────────────────────────────────────────────────────
    r = await conn.fetchrow("""
        SELECT COUNT(*) AS total, COUNT(bb_upper_at_sig) AS filled
        FROM trading_signals
        WHERE created_at >= $1
          AND strategy = 'S14_OVERSOLD_BOUNCE'
    """, start_kst)

    bb_total, bb_filled = r["total"], r["filled"]
    if bb_total == 0:
        label, res, detail = "FIX-5c bb_upper_at_sig (S14)", "SKIP", "S14 신호 없음"
    elif bb_filled == bb_total:
        label, res, detail = "FIX-5c bb_upper_at_sig (S14)", "PASS", \
            f"{bb_filled}/{bb_total}건 채움"
    else:
        label, res, detail = "FIX-5c bb_upper_at_sig (S14)", "FAIL", \
            f"{bb_filled}/{bb_total}건만 채움"
    print(_fmt(label, res, detail))
    results.append((label, res))

    # ──────────────────────────────────────────────────────────────────────────
    # FIX-5d  rsi14_at_signal (S7/S8/S9/S14/S15)
    # ──────────────────────────────────────────────────────────────────────────
    rsi_list = list(RSI_STRATEGIES)
    r = await conn.fetchrow("""
        SELECT COUNT(*) AS total, COUNT(rsi14_at_signal) AS filled
        FROM trading_signals
        WHERE created_at >= $1
          AND strategy = ANY($2::text[])
    """, start_kst, rsi_list)

    rsi_total, rsi_filled = r["total"], r["filled"]
    if rsi_total == 0:
        label, res, detail = "FIX-5d rsi14_at_signal (S7/S8/S9/S14/S15)", "SKIP", "해당 전략 신호 없음"
    elif rsi_filled == rsi_total:
        label, res, detail = "FIX-5d rsi14_at_signal (S7/S8/S9/S14/S15)", "PASS", \
            f"{rsi_filled}/{rsi_total}건 채움"
    elif rsi_filled > 0:
        label, res, detail = "FIX-5d rsi14_at_signal (S7/S8/S9/S14/S15)", "FAIL", \
            f"{rsi_filled}/{rsi_total}건만 채움 — 일부 전략 미반영"
    else:
        label, res, detail = "FIX-5d rsi14_at_signal (S7/S8/S9/S14/S15)", "FAIL", \
            f"0/{rsi_total}건"
    print(_fmt(label, res, detail))
    results.append((label, res))

    # ──────────────────────────────────────────────────────────────────────────
    # 부록: 전략별 상세 수치 테이블
    # ──────────────────────────────────────────────────────────────────────────
    print(f"\n{BOLD}  전략별 지표 채움 현황{RESET}")
    rows = await conn.fetch("""
        SELECT
            ts.strategy,
            COUNT(*) AS total,
            COUNT(ts.market_flu_rt)   AS flu_rt,
            COUNT(ts.ma5_at_signal)   AS ma5,
            COUNT(ts.ma20_at_signal)  AS ma20,
            COUNT(ts.rsi14_at_signal) AS rsi,
            COUNT(ts.atr_at_signal)   AS atr,
            COUNT(ts.bb_upper_at_sig) AS bb,
            COUNT(ssc.base_score)     AS base
        FROM trading_signals ts
        LEFT JOIN signal_score_components ssc ON ssc.signal_id = ts.id
        WHERE ts.created_at >= $1
        GROUP BY ts.strategy
        ORDER BY ts.strategy
    """, start_kst)

    header = f"  {'전략':<24} {'총':<5} {'flu_rt':<8} {'ma5':<5} {'ma20':<5} {'rsi':<5} {'atr':<5} {'bb':<5} {'base':<5}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for row in rows:
        t = row["total"]
        def cell(v: int) -> str:
            if v == t:
                return f"{GREEN}{v}/{t}{RESET}"
            elif v > 0:
                return f"{YELLOW}{v}/{t}{RESET}"
            else:
                return f"{RED}0/{t}{RESET}"
        print(
            f"  {row['strategy']:<24} {t:<5}"
            f" {cell(row['flu_rt']):<17}"
            f" {cell(row['ma5']):<14}"
            f" {cell(row['ma20']):<14}"
            f" {cell(row['rsi']):<14}"
            f" {cell(row['atr']):<14}"
            f" {cell(row['bb']):<14}"
            f" {cell(row['base']):<14}"
        )

    # ──────────────────────────────────────────────────────────────────────────
    # 최종 요약
    # ──────────────────────────────────────────────────────────────────────────
    passed = sum(1 for _, r in results if r == "PASS")
    failed = sum(1 for _, r in results if r == "FAIL")
    skipped = sum(1 for _, r in results if r == "SKIP")

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  최종 결과: "
          f"{GREEN}PASS {passed}{RESET}  "
          f"{RED}FAIL {failed}{RESET}  "
          f"{YELLOW}SKIP {skipped}{RESET}")
    if failed:
        print(f"\n  {RED}FAIL 항목:{RESET}")
        for label, r in results:
            if r == "FAIL":
                print(f"    - {label}")
    print(f"{BOLD}{'='*60}{RESET}\n")

    await conn.close()


if __name__ == "__main__":
    target = date.today()
    if len(sys.argv) > 1:
        try:
            target = date.fromisoformat(sys.argv[1])
        except ValueError:
            print(f"날짜 형식 오류: {sys.argv[1]}  (예: 2026-05-19)")
            sys.exit(1)

    asyncio.run(run_checks(target))
