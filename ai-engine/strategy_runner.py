"""
ai-engine/strategy_runner.py
──────────────────────────────────────────────────────────────
StockMate AI – Python 전술 스캐너 (보완적 실행자)

역할
  Java api-orchestrator 가 메인 전술 스캔을 담당하지만,
  이 모듈은 Python 전술 파일(strategy_1~7.py)을 직접 실행하여
  telegram_queue 에 신호를 발행하는 보완 경로를 제공한다.

활성화
  환경변수: ENABLE_STRATEGY_SCANNER=true
  실행 주기: STRATEGY_SCAN_INTERVAL_SEC (기본 60초)

사전 조건
  Java api-orchestrator 가 먼저 기동되어
  Redis 에 kiwoom:token 과 candidates:{market} 이 저장되어야 한다.
"""

import asyncio
import datetime
import json
import logging
import os

logger = logging.getLogger(__name__)

REDIS_TOKEN_KEY      = "kiwoom:token"
SCAN_INTERVAL_SEC    = float(os.getenv("STRATEGY_SCAN_INTERVAL_SEC", "60.0"))
QUEUE_TTL_SECONDS    = 43200  # 12시간


async def _load_token(rdb) -> str | None:
    """Redis 에서 Kiwoom 액세스 토큰 로드"""
    token = await rdb.get(REDIS_TOKEN_KEY)
    if not token:
        logger.warning("[Runner] kiwoom:token 없음 – Java api-orchestrator 기동 확인 필요")
    return token or None


async def _push_signals(rdb, signals: list, strategy_name: str):
    """신호 목록을 telegram_queue 에 LPUSH"""
    for sig in signals:
        try:
            payload = json.dumps(sig, ensure_ascii=False, default=str)
            await rdb.lpush("telegram_queue", payload)
            await rdb.expire("telegram_queue", QUEUE_TTL_SECONDS)
            logger.info("[Runner] 신호 발행 [%s] stk=%s score=%s",
                        strategy_name, sig.get("stk_cd"), sig.get("score", "N/A"))
        except Exception as e:
            logger.error("[Runner] 신호 발행 실패 [%s]: %s", strategy_name, e)


async def _run_once(rdb):
    """모든 전술 1회 스캔 실행"""
    token = await _load_token(rdb)
    if not token:
        return

    now = datetime.datetime.now().time()

    # ── S7: 동시호가 (08:30 ~ 09:00) ──────────────────────────────
    if datetime.time(8, 30) <= now <= datetime.time(9, 0):
        try:
            from strategy_7_auction import scan_auction_signal
            for market in ("001", "101"):
                signals = await scan_auction_signal(token, market, rdb=rdb)
                await _push_signals(rdb, signals, "S7_AUCTION")
        except Exception as e:
            logger.error("[Runner] S7 스캔 오류: %s", e)

    # ── S1: 갭상승 시초가 (08:30 ~ 09:10) ─────────────────────────
    if datetime.time(8, 30) <= now <= datetime.time(9, 10):
        try:
            from strategy_1_gap_opening import scan_gap_opening
            kospi  = await rdb.lrange("candidates:001", 0, 199)
            kosdaq = await rdb.lrange("candidates:101", 0, 199)
            candidates = list(dict.fromkeys(kospi + kosdaq))
            if candidates:
                signals = await scan_gap_opening(token, candidates, rdb=rdb)
                await _push_signals(rdb, signals, "S1_GAP_OPEN")
        except Exception as e:
            logger.error("[Runner] S1 스캔 오류: %s", e)

    # ── S3: 외인+기관 동시 순매수 (09:30 ~ 14:30) ─────────────────
    if datetime.time(9, 30) <= now <= datetime.time(14, 30):
        try:
            from strategy_3_inst_foreign import scan_inst_foreign
            for market in ("001", "101"):
                signals = await scan_inst_foreign(token, market)
                await _push_signals(rdb, signals, "S3_INST_FRGN")
        except Exception as e:
            logger.error("[Runner] S3 스캔 오류: %s", e)

    # ── S4: 장대양봉 추격 (09:30 ~ 14:30) – 후보 종목 순차 스캔 ──
    if datetime.time(9, 30) <= now <= datetime.time(14, 30):
        try:
            from strategy_4_big_candle import check_big_candle
            kospi  = await rdb.lrange("candidates:001", 0, 99)
            kosdaq = await rdb.lrange("candidates:101", 0, 99)
            candidates = list(dict.fromkeys(kospi + kosdaq))[:30]  # 상위 30개만
            s4_signals = []
            for stk_cd in candidates:
                result = await check_big_candle(token, stk_cd, rdb=rdb)
                if result:
                    s4_signals.append(result)
                    if len(s4_signals) >= 5:
                        break
            await _push_signals(rdb, s4_signals, "S4_BIG_CANDLE")
        except Exception as e:
            logger.error("[Runner] S4 스캔 오류: %s", e)

    # ── S5: 프로그램+외인 (10:00 ~ 14:00) ─────────────────────────
    if datetime.time(10, 0) <= now <= datetime.time(14, 0):
        try:
            from strategy_5_program_buy import scan_program_buy
            for market in ("001", "101"):
                signals = await scan_program_buy(token, market)
                await _push_signals(rdb, signals, "S5_PROG_FRGN")
        except Exception as e:
            logger.error("[Runner] S5 스캔 오류: %s", e)

    # ── S6: 테마 후발주 (09:30 ~ 13:00) ───────────────────────────
    if datetime.time(9, 30) <= now <= datetime.time(13, 0):
        try:
            from strategy_6_theme import scan_theme_laggard
            signals = await scan_theme_laggard(token)
            await _push_signals(rdb, signals, "S6_THEME_LAGGARD")
        except Exception as e:
            logger.error("[Runner] S6 스캔 오류: %s", e)


async def run_strategy_scanner(rdb):
    """전술 스캐너 루프 – SCAN_INTERVAL_SEC 마다 전 전술 실행"""
    logger.info("[Runner] 전술 스캐너 시작 (interval=%.0fs)", SCAN_INTERVAL_SEC)
    while True:
        try:
            await _run_once(rdb)
        except Exception as e:
            logger.error("[Runner] 스캔 루프 오류: %s", e)
        await asyncio.sleep(SCAN_INTERVAL_SEC)
