"""
ai-engine/strategy_runner.py
──────────────────────────────────────────────────────────────
StockMate AI – Python 전술 스캐너 (메인 실행자)

역할
  이 모듈은 Python 전술 파일(strategy_1~15.py)을 직접 실행하여
  telegram_queue 에 신호를 발행한다.
  신호는 반드시 telegram_queue → queue_worker → scorer → confirm_worker
  → ai_scored_queue → telegram-bot 경로를 통해 발송된다.
  (scorer MIN_SCORE 필터 및 Claude AI 2차 평가 포함)

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

# 키움 REST API 초당 약 5회 제한 → 루프 내 공통 대기 시간
_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))

logger = logging.getLogger(__name__)

REDIS_TOKEN_KEY   = "kiwoom:token"
SCAN_INTERVAL_SEC = float(os.getenv("STRATEGY_SCAN_INTERVAL_SEC", "60.0"))
QUEUE_TTL_SECONDS = 43200  # 12시간

# 동시 전술 실행 상한 – 60초 스캔 주기 내에 완료될 수 있도록 제한
MAX_CONCURRENT_STRATEGIES = int(os.getenv("MAX_CONCURRENT_STRATEGIES", "3"))
_semaphore: asyncio.Semaphore | None = None

# 스윙 전략은 하루 1회 dedup (86400s), 단기 전략은 1시간(3600s)
_SWING_STRATEGIES = {
    "S8_GOLDEN_CROSS", "S9_PULLBACK_SWING", "S10_NEW_HIGH",
    "S11_FRGN_CONT", "S12_CLOSING", "S13_BOX_BREAKOUT",
    "S14_OVERSOLD_BOUNCE", "S15_MOMENTUM_ALIGN",
}


def _get_semaphore() -> asyncio.Semaphore:
    """전술 실행 세마포어 싱글턴 반환 (이벤트 루프 내에서만 생성)"""
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENT_STRATEGIES)
    return _semaphore


async def _run_strategy_with_semaphore(name: str, coro):
    """세마포어를 획득한 후 전술 코루틴 실행. 대기 시 로그 출력."""
    sem = _get_semaphore()
    if sem.locked():
        logger.debug("[Runner] [%s] 세마포어 대기 중 (동시 실행 %d개 한도)", name, MAX_CONCURRENT_STRATEGIES)
    async with sem:
        return await coro


async def _load_token(rdb) -> str | None:
    """Redis 에서 Kiwoom 액세스 토큰 로드"""
    token = await rdb.get(REDIS_TOKEN_KEY)
    if not token:
        logger.warning("[Runner] kiwoom:token 없음 – Java api-orchestrator 기동 확인 필요")
    return token or None


async def _push_signals(rdb, signals: list, strategy_name: str):
    """신호 목록을 telegram_queue 에 LPUSH.

    모든 신호는 telegram_queue → queue_worker → scorer → confirm_worker
    → ai_scored_queue → telegram-bot 경로를 통해 발송된다.
    (scorer MIN_SCORE 필터 및 Claude AI 2차 평가 적용)

    dedup 키(scanner:dedup:{strategy}:{stk_cd}) TTL:
      스윙 전략(S8~S15): 86400s (하루 1회)
      단기 전략(S1~S7):  3600s  (1시간 1회)
    """
    for sig in signals:
        stk_cd = sig.get("stk_cd", "")

        # ── 중복 방지 ──────────────────────────────────────────────
        dedup_ttl = 86400 if strategy_name in _SWING_STRATEGIES else 3600
        dedup_key = f"scanner:dedup:{strategy_name}:{stk_cd}"
        try:
            is_new = await rdb.set(dedup_key, "1", nx=True, ex=dedup_ttl)
        except Exception as dedup_err:
            logger.debug("[Runner] dedup 확인 실패 (통과): %s", dedup_err)
            is_new = True
        if not is_new:
            logger.debug("[Runner] 중복 무시 [%s %s] (dedup TTL %ds)",
                         strategy_name, stk_cd, dedup_ttl)
            continue
        # ──────────────────────────────────────────────────────────

        # ── 종목명 보완 (stk_nm 없으면 Redis 캐시/API 조회) ────────
        if not sig.get("stk_nm"):
            try:
                from http_utils import fetch_stk_nm
                token = await rdb.get(REDIS_TOKEN_KEY)
                if token:
                    sig["stk_nm"] = await fetch_stk_nm(rdb, token, stk_cd)
            except Exception as nm_err:
                logger.debug("[Runner] stk_nm 조회 실패 [%s]: %s", stk_cd, nm_err)
        # ──────────────────────────────────────────────────────────

        try:
            payload = json.dumps(sig, ensure_ascii=False, default=str)
            await rdb.lpush("telegram_queue", payload)
            await rdb.expire("telegram_queue", QUEUE_TTL_SECONDS)
            logger.info("[Runner] 신호 발행 [%s] stk=%s score=%s",
                        strategy_name, sig.get("stk_cd"), sig.get("score", "N/A"))
        except Exception as e:
            logger.error("[Runner] 신호 발행 실패 [%s]: %s", strategy_name, e)


async def _run_once(rdb):
    """
    모든 전술 1회 스캔 실행.
    시간대별로 활성화된 전술들을 asyncio.gather + 세마포어로 병렬 실행 (최대 MAX_CONCURRENT_STRATEGIES).
    """
    token = await _load_token(rdb)
    if not token:
        return

    now = datetime.datetime.now().time()
    tasks = []

    # ── S7: 동시호가 (08:30 ~ 09:00) ──────────────────────────────
    if datetime.time(8, 30) <= now <= datetime.time(9, 0):
        async def _s7():
            try:
                from strategy_7_auction import scan_auction_signal
                for market in ("001", "101"):
                    signals = await scan_auction_signal(token, market, rdb=rdb)
                    await _push_signals(rdb, signals, "S7_AUCTION")
            except Exception as e:
                logger.error("[Runner] S7 스캔 오류: %s", e)
        tasks.append(_run_strategy_with_semaphore("S7", _s7()))

    # ── S1: 갭상승 시초가 (08:30 ~ 09:10) ─────────────────────────
    if datetime.time(8, 30) <= now <= datetime.time(9, 10):
        async def _s1():
            try:
                from strategy_1_gap_opening import scan_gap_opening
                kospi  = await rdb.lrange("candidates:s1:001", 0, 99)
                kosdaq = await rdb.lrange("candidates:s1:101", 0, 99)
                candidates = list(dict.fromkeys(kospi + kosdaq))
                if candidates:
                    signals = await scan_gap_opening(token, candidates, rdb=rdb)
                    await _push_signals(rdb, signals, "S1_GAP_OPEN")
            except Exception as e:
                logger.error("[Runner] S1 스캔 오류: %s", e)
        tasks.append(_run_strategy_with_semaphore("S1", _s1()))

    # ── S3: 외인+기관 동시 순매수 (09:30 ~ 14:30) ─────────────────
    if datetime.time(9, 30) <= now <= datetime.time(14, 30):
        async def _s3():
            try:
                from strategy_3_inst_foreign import scan_inst_foreign
                for market in ("001", "101"):
                    signals = await scan_inst_foreign(token, market, rdb=rdb)
                    await _push_signals(rdb, signals, "S3_INST_FRGN")
            except Exception as e:
                logger.error("[Runner] S3 스캔 오류: %s", e)
        tasks.append(_run_strategy_with_semaphore("S3", _s3()))

    # ── S4: 장대양봉 추격 (09:30 ~ 14:30) – 후보 종목 순차 스캔 ──
    if datetime.time(9, 30) <= now <= datetime.time(14, 30):
        async def _s4():
            try:
                from strategy_4_big_candle import check_big_candle
                kospi  = await rdb.lrange("candidates:s4:001", 0, 99)
                kosdaq = await rdb.lrange("candidates:s4:101", 0, 99)
                candidates = list(dict.fromkeys(kospi + kosdaq))[:30]  # 상위 30개만
                s4_signals = []
                for stk_cd in candidates:
                    await asyncio.sleep(_API_INTERVAL)   # Rate limit: ka10080 호출 전 대기
                    result = await check_big_candle(token, stk_cd, rdb=rdb)
                    if result:
                        s4_signals.append(result)
                        if len(s4_signals) >= 5:
                            break
                await _push_signals(rdb, s4_signals, "S4_BIG_CANDLE")
            except Exception as e:
                logger.error("[Runner] S4 스캔 오류: %s", e)
        tasks.append(_run_strategy_with_semaphore("S4", _s4()))

    # ── S5: 프로그램+외인 (10:00 ~ 14:00) ─────────────────────────
    if datetime.time(10, 0) <= now <= datetime.time(14, 0):
        async def _s5():
            try:
                from strategy_5_program_buy import scan_program_buy
                for market in ("001", "101"):
                    signals = await scan_program_buy(token, market, rdb=rdb)
                    await _push_signals(rdb, signals, "S5_PROG_FRGN")
            except Exception as e:
                logger.error("[Runner] S5 스캔 오류: %s", e)
        tasks.append(_run_strategy_with_semaphore("S5", _s5()))

    # ── S6: 테마 후발주 (09:30 ~ 13:00) ───────────────────────────
    if datetime.time(9, 30) <= now <= datetime.time(13, 0):
        async def _s6():
            try:
                from strategy_6_theme import scan_theme_laggard
                signals = await scan_theme_laggard(token, rdb=rdb)
                await _push_signals(rdb, signals, "S6_THEME_LAGGARD")
            except Exception as e:
                logger.error("[Runner] S6 스캔 오류: %s", e)
        tasks.append(_run_strategy_with_semaphore("S6", _s6()))

    # ── S10: 52주 신고가 돌파 스윙 (09:30 ~ 14:30) ────────────────
    if datetime.time(9, 30) <= now <= datetime.time(14, 30):
        async def _s10():
            try:
                from strategy_10_new_high import scan_new_high_swing
                for market in ("000",):  # 전체 시장
                    signals = await scan_new_high_swing(token, market, rdb=rdb)
                    await _push_signals(rdb, signals, "S10_NEW_HIGH")
            except Exception as e:
                logger.error("[Runner] S10 스캔 오류: %s", e)
        tasks.append(_run_strategy_with_semaphore("S10", _s10()))

    # ── S11: 외국인 연속 순매수 스윙 (09:30 ~ 14:30) ──────────────
    if datetime.time(9, 30) <= now <= datetime.time(14, 30):
        async def _s11():
            try:
                from strategy_11_frgn_cont import scan_frgn_cont_swing
                for market in ("001", "101"):
                    # Java가 candidates:s11:{market} 을 채워두면 pool-read 가능
                    # Java 미실행 시 scan_frgn_cont_swing 내부에서 ka10035 직접 호출
                    signals = await scan_frgn_cont_swing(token, market, rdb=rdb)
                    await _push_signals(rdb, signals, "S11_FRGN_CONT")
            except Exception as e:
                logger.error("[Runner] S11 스캔 오류: %s", e)
        tasks.append(_run_strategy_with_semaphore("S11", _s11()))

    # ── S8: 5일선 골든크로스 스윙 (10:00 ~ 14:30) ─────────────────
    if datetime.time(10, 0) <= now <= datetime.time(14, 30):
        async def _s8():
            try:
                from strategy_8_golden_cross import scan_golden_cross
                signals = await scan_golden_cross(token, rdb=rdb)
                await _push_signals(rdb, signals, "S8_GOLDEN_CROSS")
            except Exception as e:
                logger.error("[Runner] S8 스캔 오류: %s", e)
        tasks.append(_run_strategy_with_semaphore("S8", _s8()))

    # ── S9: 정배열 눌림목 스윙 (09:30 ~ 13:00) ────────────────────
    if datetime.time(9, 30) <= now <= datetime.time(13, 0):
        async def _s9():
            try:
                from strategy_9_pullback import scan_pullback_swing
                signals = await scan_pullback_swing(token, rdb=rdb)
                await _push_signals(rdb, signals, "S9_PULLBACK_SWING")
            except Exception as e:
                logger.error("[Runner] S9 스캔 오류: %s", e)
        tasks.append(_run_strategy_with_semaphore("S9", _s9()))

    # ── S13: 박스권 돌파 스윙 (09:30 ~ 14:00) ─────────────────────
    if datetime.time(9, 30) <= now <= datetime.time(14, 0):
        async def _s13():
            try:
                from strategy_13_box_breakout import scan_box_breakout
                signals = await scan_box_breakout(token, rdb=rdb)
                await _push_signals(rdb, signals, "S13_BOX_BREAKOUT")
            except Exception as e:
                logger.error("[Runner] S13 스캔 오류: %s", e)
        tasks.append(_run_strategy_with_semaphore("S13", _s13()))

    # ── S14: 과매도 오실레이터 수렴 반등 (09:30 ~ 14:00) ──────────
    if datetime.time(9, 30) <= now <= datetime.time(14, 0):
        async def _s14():
            try:
                from strategy_14_oversold_bounce import scan_oversold_bounce
                signals = await scan_oversold_bounce(token, rdb=rdb)
                await _push_signals(rdb, signals, "S14_OVERSOLD_BOUNCE")
            except Exception as e:
                logger.error("[Runner] S14 스캔 오류: %s", e)
        tasks.append(_run_strategy_with_semaphore("S14", _s14()))

    # ── S15: 다중지표 모멘텀 동조 스윙 (10:00 ~ 14:30) ────────────
    if datetime.time(10, 0) <= now <= datetime.time(14, 30):
        async def _s15():
            try:
                from strategy_15_momentum_align import scan_momentum_align
                signals = await scan_momentum_align(token, rdb=rdb)
                await _push_signals(rdb, signals, "S15_MOMENTUM_ALIGN")
            except Exception as e:
                logger.error("[Runner] S15 스캔 오류: %s", e)
        tasks.append(_run_strategy_with_semaphore("S15", _s15()))

    # ── S12: 종가 강도 확인 매수 (14:30 ~ 14:50) ──────────────────
    if datetime.time(14, 30) <= now <= datetime.time(14, 50):
        async def _s12():
            try:
                from strategy_12_closing import scan_closing_buy
                for market in ("001", "101"):
                    signals = await scan_closing_buy(token, market, rdb=rdb)
                    await _push_signals(rdb, signals, "S12_CLOSING")
            except Exception as e:
                logger.error("[Runner] S12 스캔 오류: %s", e)
        tasks.append(_run_strategy_with_semaphore("S12", _s12()))

    # 활성화된 전술들을 병렬 실행 (세마포어가 동시 실행 수 제한)
    if tasks:
        logger.debug("[Runner] 전술 %d개 병렬 실행 시작 (세마포어 한도: %d)",
                     len(tasks), MAX_CONCURRENT_STRATEGIES)
        await asyncio.gather(*tasks, return_exceptions=True)


async def run_strategy_scanner(rdb):
    """전술 스캐너 루프 – SCAN_INTERVAL_SEC 마다 전 전술 실행"""
    logger.info("[Runner] 전술 스캐너 시작 (interval=%.0fs, swing_dedup=86400s, intraday_dedup=3600s)",
                SCAN_INTERVAL_SEC)
    while True:
        try:
            await _run_once(rdb)
        except Exception as e:
            logger.error("[Runner] 스캔 루프 오류: %s", e)
        await asyncio.sleep(SCAN_INTERVAL_SEC)
