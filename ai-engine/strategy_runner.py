from __future__ import annotations
"""
ai-engine/strategy_runner.py
──────────────────────────────────────────────────────────────
StockMate AI - Python 전술 스캐너 (메인 실행자)

역할
  이 모듈은 Python 전술 파일(strategy_1~15.py)을 직접 실행하여
  telegram_queue 에 신호를 발행한다.
  신호는 반드시 telegram_queue -> queue_worker -> scorer -> confirm_worker
  -> ai_scored_queue -> telegram-bot 경로를 통해 발송된다.
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
import time as _time
from datetime import time, timedelta, timezone

from utils import normalize_stock_code

_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))

REDIS_TOKEN_KEY = "kiwoom:token"
SCAN_INTERVAL_SEC = float(os.getenv("STRATEGY_SCAN_INTERVAL_SEC", "60.0"))
QUEUE_TTL_SECONDS = 43200
SWING_DEDUP_TTL_SEC = int(os.getenv("SWING_SIGNAL_DEDUP_SEC", "7200"))
INTRADAY_DEDUP_TTL_SEC = int(os.getenv("INTRADAY_SIGNAL_DEDUP_SEC", "1800"))
STATUS_SIGNAL_TTL_SEC = int(os.getenv("STATUS_SIGNAL_TTL_SEC", "600"))
MAX_CONCURRENT_STRATEGIES = int(os.getenv("MAX_CONCURRENT_STRATEGIES", "3"))
_semaphore: asyncio.Semaphore | None = None

from strategy_meta import SWING_STRATEGIES as _SWING_STRATEGIES


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENT_STRATEGIES)
    return _semaphore


_DEFAULT_STRATEGY_TIMEOUT_SEC = int(os.getenv("STRATEGY_TIMEOUT_SEC", "300"))
_SLOW_STRATEGY_WARN_SEC = float(os.getenv("SLOW_STRATEGY_WARN_SEC", "30"))
_STRATEGY_TIMEOUT_OVERRIDES = {
    "S3": int(os.getenv("STRATEGY_TIMEOUT_S3_SEC", str(_DEFAULT_STRATEGY_TIMEOUT_SEC))),
    "S11": int(os.getenv("STRATEGY_TIMEOUT_S11_SEC", str(_DEFAULT_STRATEGY_TIMEOUT_SEC))),
}


def _strategy_timeout_sec(name: str) -> int:
    return _STRATEGY_TIMEOUT_OVERRIDES.get(name, _DEFAULT_STRATEGY_TIMEOUT_SEC)


def _current_kst_time() -> time:
    return datetime.datetime.now(KST).time()


def _active_schedule_entries(now: time | None = None):
    current_time = now or _current_kst_time()
    return [
        (tag, start, end, fn)
        for tag, start, end, fn in _SCHEDULE
        if start <= current_time <= end
    ]


async def _run_strategy_with_semaphore(name: str, coro, rdb=None):
    sem = _get_semaphore()
    timeout_sec = _strategy_timeout_sec(name)
    if sem.locked():
        logger.debug("[Runner] [%s] 세마포어 대기 중 (동시 실행 %d개 한도)", name, MAX_CONCURRENT_STRATEGIES)
    async with sem:
        started_at = _time.monotonic()
        try:
            result = await asyncio.wait_for(coro, timeout=timeout_sec)
            elapsed_sec = _time.monotonic() - started_at
            if elapsed_sec >= _SLOW_STRATEGY_WARN_SEC:
                logger.warning("[Runner] [%s] 느린 실행 감지 (%.1fs, timeout=%ds)", name, elapsed_sec, timeout_sec)
            else:
                logger.debug("[Runner] [%s] 실행 완료 (%.1fs)", name, elapsed_sec)
            return result
        except asyncio.TimeoutError:
            elapsed_sec = _time.monotonic() - started_at
            logger.error("[Runner] [%s] 전략 실행 타임아웃 (%ds) - 강제 취소 elapsed=%.1fs", name, timeout_sec, elapsed_sec)
            if rdb:
                try:
                    from datetime import datetime, timedelta, timezone as _tz

                    today = datetime.now(_tz(timedelta(hours=9))).strftime("%Y-%m-%d")
                    await rdb.hincrby(f"pipeline_daily:{today}:{name}", "timeout", 1)
                    await rdb.expire(f"pipeline_daily:{today}:{name}", 172800)
                except Exception:
                    pass
        except Exception:
            elapsed_sec = _time.monotonic() - started_at
            logger.exception("[Runner] [%s] 실행 실패 (%.1fs)", name, elapsed_sec)
            raise


async def _load_token(rdb) -> str | None:
    try:
        token = await rdb.get(REDIS_TOKEN_KEY)
    except Exception as exc:
        logger.exception("[Runner] kiwoom:token 조회 실패: %s", exc)
        return None
    if not token:
        logger.warning("[Runner] kiwoom:token 없음 - Java api-orchestrator 기동 확인 필요")
        return None
    return token


async def _push_signals(rdb, signals: list, strategy_name: str):
    for sig in signals:
        stk_cd = normalize_stock_code(sig.get("stk_cd", ""))
        sig["stk_cd"] = stk_cd

        dedup_ttl = SWING_DEDUP_TTL_SEC if strategy_name in _SWING_STRATEGIES else INTRADAY_DEDUP_TTL_SEC
        dedup_key = f"scanner:dedup:{strategy_name}:{stk_cd}"
        try:
            is_new = await rdb.set(dedup_key, "1", nx=True, ex=dedup_ttl)
        except Exception as dedup_err:
            logger.debug("[Runner] dedup 확인 실패 (통과): %s", dedup_err)
            is_new = True
        if not is_new:
            logger.debug("[Runner] 중복 무시 [%s %s] (dedup TTL %ds)", strategy_name, stk_cd, dedup_ttl)
            continue

        if not sig.get("stk_nm"):
            try:
                from http_utils import fetch_stk_nm

                token = await rdb.get(REDIS_TOKEN_KEY)
                if token:
                    sig["stk_nm"] = await fetch_stk_nm(rdb, token, stk_cd)
            except Exception as nm_err:
                logger.debug("[Runner] stk_nm 조회 실패 [%s]: %s", stk_cd, nm_err)

        try:
            payload = json.dumps(sig, ensure_ascii=False, default=str)
            await rdb.lpush("telegram_queue", payload)
            await rdb.expire("telegram_queue", QUEUE_TTL_SECONDS)
            try:
                status_key = f"status:signals_10m:{strategy_name}"
                await rdb.incr(status_key)
                await rdb.expire(status_key, STATUS_SIGNAL_TTL_SEC)
                await rdb.hset(
                    f"status:last_signal:{strategy_name}",
                    mapping={
                        "stk_cd": str(sig.get("stk_cd", "")),
                        "score": str(sig.get("score", "")),
                        "updated_at": str(int(_time.time())),
                    },
                )
                await rdb.expire(f"status:last_signal:{strategy_name}", STATUS_SIGNAL_TTL_SEC)
            except Exception as status_err:
                logger.debug("[Runner] status signal metric failed [%s]: %s", strategy_name, status_err)
            logger.info("[Runner] 신호 발행 [%s] stk=%s score=%s", strategy_name, sig.get("stk_cd"), sig.get("score", "N/A"))
        except Exception as exc:
            logger.error("[Runner] 신호 발행 실패 [%s]: %s", strategy_name, exc)


async def _scan_s1(rdb, token):
    try:
        from strategy_1_gap_opening import scan_gap_opening

        kospi = await rdb.lrange("candidates:s1:001", 0, 99)
        kosdaq = await rdb.lrange("candidates:s1:101", 0, 99)
        candidates = list(dict.fromkeys(kospi + kosdaq))
        if not candidates:
            logger.warning("[Runner] S1 후보풀이 비어 fallback 스캔을 사용합니다")
        signals = await scan_gap_opening(token, candidates, rdb=rdb)
        await _push_signals(rdb, signals, "S1_GAP_OPEN")
    except Exception as exc:
        logger.error("[Runner] S1 스캔 오류: %s", exc)


async def _scan_s2(rdb, token):
    try:
        from strategy_2_vi_pullback import check_vi_pullback

        s2_signals = []
        now_ms = int(_time.time() * 1000)
        for _ in range(20):
            item_raw = await rdb.rpop("vi_watch_queue")
            if not item_raw:
                break
            try:
                item = json.loads(item_raw)
                if item.get("watch_until", 0) < now_ms:
                    logger.debug("[Runner] S2 watch_until 만료 - 폐기 [%s]", item.get("stk_cd"))
                    continue
                result = await check_vi_pullback(token, item, rdb=rdb)
                if result:
                    s2_signals.append(result)
                    if len(s2_signals) >= 3:
                        break
                else:
                    await rdb.lpush("vi_watch_queue", item_raw)
            except Exception as ve:
                logger.debug("[Runner] S2 항목 처리 실패: %s", ve)
        await _push_signals(rdb, s2_signals, "S2_VI_PULLBACK")
    except Exception as exc:
        logger.error("[Runner] S2 스캔 오류: %s", exc)


async def _scan_s3(rdb, token):
    try:
        from strategy_3_inst_foreign import scan_inst_foreign

        for market in ("001", "101"):
            signals = await scan_inst_foreign(token, market, rdb=rdb)
            await _push_signals(rdb, signals, "S3_INST_FRGN")
    except Exception as exc:
        logger.error("[Runner] S3 스캔 오류: %s", exc)


async def _scan_s4(rdb, token):
    try:
        from strategy_4_big_candle import check_big_candle

        kospi = await rdb.lrange("candidates:s4:001", 0, 99)
        kosdaq = await rdb.lrange("candidates:s4:101", 0, 99)
        candidates = list(dict.fromkeys(kospi + kosdaq))[:30]
        s4_signals = []
        for stk_cd in candidates:
            await asyncio.sleep(_API_INTERVAL)
            result = await check_big_candle(token, stk_cd, rdb=rdb)
            if result:
                s4_signals.append(result)
                if len(s4_signals) >= 5:
                    break
        await _push_signals(rdb, s4_signals, "S4_BIG_CANDLE")
    except Exception as exc:
        logger.error("[Runner] S4 스캔 오류: %s", exc)


async def _scan_s5(rdb, token):
    try:
        from strategy_5_program_buy import scan_program_buy

        for market in ("001", "101"):
            signals = await scan_program_buy(token, market, rdb=rdb)
            await _push_signals(rdb, signals, "S5_PROG_FRGN")
    except Exception as exc:
        logger.error("[Runner] S5 스캔 오류: %s", exc)


async def _scan_s6(rdb, token):
    try:
        from strategy_6_theme import scan_theme_laggard

        signals = await scan_theme_laggard(token, rdb=rdb)
        await _push_signals(rdb, signals, "S6_THEME_LAGGARD")
    except Exception as exc:
        logger.error("[Runner] S6 스캔 오류: %s", exc)


async def _scan_s7(rdb, token):
    try:
        from strategy_7_ichimoku_breakout import scan_ichimoku_breakout

        signals = await scan_ichimoku_breakout(token, rdb=rdb)
        await _push_signals(rdb, signals, "S7_ICHIMOKU_BREAKOUT")
    except Exception as exc:
        logger.error("[Runner] S7 스캔 오류: %s", exc)


async def _scan_s8(rdb, token):
    try:
        from strategy_8_golden_cross import scan_golden_cross

        signals = await scan_golden_cross(token, rdb=rdb)
        await _push_signals(rdb, signals, "S8_GOLDEN_CROSS")
    except Exception as exc:
        logger.error("[Runner] S8 스캔 오류: %s", exc)


async def _scan_s9(rdb, token):
    try:
        from strategy_9_pullback import scan_pullback_swing

        signals = await scan_pullback_swing(token, rdb=rdb)
        await _push_signals(rdb, signals, "S9_PULLBACK_SWING")
    except Exception as exc:
        logger.error("[Runner] S9 스캔 오류: %s", exc)


async def _scan_s10(rdb, token):
    try:
        from strategy_10_new_high import scan_new_high_swing

        signals = await scan_new_high_swing(token, "000", rdb=rdb)
        await _push_signals(rdb, signals, "S10_NEW_HIGH")
    except Exception as exc:
        logger.error("[Runner] S10 스캔 오류: %s", exc)


async def _scan_s11(rdb, token):
    try:
        from strategy_11_frgn_cont import scan_frgn_cont_swing

        for market in ("001", "101"):
            signals = await scan_frgn_cont_swing(token, market, rdb=rdb)
            await _push_signals(rdb, signals, "S11_FRGN_CONT")
    except Exception as exc:
        logger.error("[Runner] S11 스캔 오류: %s", exc)


async def _scan_s12(rdb, token):
    try:
        from strategy_12_closing import scan_closing_buy

        for market in ("001", "101"):
            signals = await scan_closing_buy(token, market, rdb=rdb)
            await _push_signals(rdb, signals, "S12_CLOSING")
    except Exception as exc:
        logger.error("[Runner] S12 스캔 오류: %s", exc)


async def _scan_s13(rdb, token):
    try:
        from strategy_13_box_breakout import scan_box_breakout

        signals = await scan_box_breakout(token, rdb=rdb)
        await _push_signals(rdb, signals, "S13_BOX_BREAKOUT")
    except Exception as exc:
        logger.error("[Runner] S13 스캔 오류: %s", exc)


async def _scan_s14(rdb, token):
    try:
        from strategy_14_oversold_bounce import scan_oversold_bounce

        signals = await scan_oversold_bounce(token, rdb=rdb)
        await _push_signals(rdb, signals, "S14_OVERSOLD_BOUNCE")
    except Exception as exc:
        logger.error("[Runner] S14 스캔 오류: %s", exc)


async def _scan_s15(rdb, token):
    try:
        from strategy_15_momentum_align import scan_momentum_align

        signals = await scan_momentum_align(token, rdb=rdb)
        await _push_signals(rdb, signals, "S15_MOMENTUM_ALIGN")
    except Exception as exc:
        logger.error("[Runner] S15 스캔 오류: %s", exc)


_SCHEDULE: list[tuple[str, time, time, callable]] = [
    ("S7", time(10, 0), time(14, 30), _scan_s7),
    ("S1", time(8, 30), time(9, 10), _scan_s1),
    ("S3", time(9, 30), time(14, 30), _scan_s3),
    ("S4", time(10, 0), time(14, 30), _scan_s4),
    ("S5", time(10, 0), time(14, 0), _scan_s5),
    ("S6", time(9, 30), time(13, 0), _scan_s6),
    ("S10", time(10, 0), time(14, 0), _scan_s10),
    ("S11", time(10, 0), time(14, 30), _scan_s11),
    ("S8", time(10, 0), time(14, 30), _scan_s8),
    ("S9", time(9, 30), time(13, 0), _scan_s9),
    ("S13", time(10, 0), time(14, 0), _scan_s13),
    ("S14", time(9, 30), time(14, 0), _scan_s14),
    ("S15", time(10, 0), time(14, 30), _scan_s15),
    ("S12", time(14, 30), time(15, 10), _scan_s12),
]


async def _run_once(rdb):
    now = _current_kst_time()
    active_entries = _active_schedule_entries(now)
    token = await _load_token(rdb)
    if not token:
        if active_entries:
            active_tags = ", ".join(tag for tag, _, _, _ in active_entries)
            logger.warning("[Runner] token 없음 - 활성 전략 %d개를 실행하지 못합니다: %s", len(active_entries), active_tags)
        else:
            logger.warning("[Runner] token 없음 - 현재 시간대 활성 전략 없음")
        return

    if not active_entries:
        logger.debug("[Runner] 현재 시간대 활성 전략 없음 (%s)", now.strftime("%H:%M:%S"))
        return

    tasks = [
        _run_strategy_with_semaphore(tag, fn(rdb, token), rdb=rdb)
        for tag, start, end, fn in active_entries
    ]

    logger.debug("[Runner] 전술 %d개 병렬 실행 시작 (세마포어 한도: %d)", len(tasks), MAX_CONCURRENT_STRATEGIES)
    await asyncio.gather(*tasks, return_exceptions=True)


async def run_strategy_scanner(rdb):
    logger.info(
        "[Runner] 전술 스캐너 시작 (interval=%.0fs, swing_dedup=%ss, intraday_dedup=%ss)",
        SCAN_INTERVAL_SEC,
        SWING_DEDUP_TTL_SEC,
        INTRADAY_DEDUP_TTL_SEC,
    )
    while True:
        try:
            await _run_once(rdb)
        except Exception as exc:
            logger.error("[Runner] 스캔 루프 오류: %s", exc)
        await asyncio.sleep(SCAN_INTERVAL_SEC)
