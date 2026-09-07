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
from contextvars import ContextVar
import datetime
import json
import logging
import os
import time as _time
import uuid
from datetime import time, timedelta, timezone

from market_session import current_session, is_trading_active
from score_utils import normalize_runner_signal
from strategy_catalog import ALL_SETUP_IDS, family_lineage, family_lineage_enabled
from utils import normalize_stock_code

_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.8"))

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))

REDIS_TOKEN_KEY = "kiwoom:token"
_STRATEGY_TOKEN_CONTEXT: ContextVar[str | None] = ContextVar(
    "strategy_token_context", default=None
)
_SCAN_RUN_CONTEXT: ContextVar[str | None] = ContextVar("scan_run_context", default=None)
_SCAN_PUBLISHED_CONTEXT: ContextVar[dict | None] = ContextVar("scan_published_context", default=None)
STRATEGY_EXECUTION_OWNER = str(os.getenv("STRATEGY_EXECUTION_OWNER", "PYTHON")).strip().upper()
LIVE_ONLY_MODE = str(os.getenv("LIVE_ONLY_MODE", "true")).strip().lower() == "true"
SHADOW_MODE_FORBIDDEN = str(os.getenv("SHADOW_MODE_FORBIDDEN", "true")).strip().lower() == "true"
SCAN_INTERVAL_SEC = float(os.getenv("STRATEGY_SCAN_INTERVAL_SEC", "60.0"))
QUEUE_TTL_SECONDS = 43200
SWING_DEDUP_TTL_SEC = int(os.getenv("SWING_SIGNAL_DEDUP_SEC", "7200"))
INTRADAY_DEDUP_TTL_SEC = int(os.getenv("INTRADAY_SIGNAL_DEDUP_SEC", "1800"))
STATUS_SIGNAL_TTL_SEC = int(os.getenv("STATUS_SIGNAL_TTL_SEC", "600"))
MAX_CONCURRENT_STRATEGIES = int(os.getenv("MAX_CONCURRENT_STRATEGIES", "3"))
S1_MIN_READY_CANDIDATES = int(os.getenv("S1_MIN_READY_CANDIDATES", "3"))
S1_SCAN_START_HHMM = int(os.getenv("S1_SCAN_START_HHMM", "850"))
S1_SCAN_END_HHMM = int(os.getenv("S1_SCAN_END_HHMM", "903"))
_semaphore: asyncio.Semaphore | None = None
_pg_pool = None  # set by run_strategy_scanner; used by _push_signals for active-position dedup


def _env_flag(name: str, default: str = "false") -> bool:
    return str(os.getenv(name, default)).strip().lower() in {"1", "true", "yes", "on"}


def _python_owns_strategy_execution() -> bool:
    # Unknown/mistyped values fail closed so two runtimes cannot both publish.
    return STRATEGY_EXECUTION_OWNER == "PYTHON"


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(str(os.getenv(name, default)).strip()))
    except (TypeError, ValueError):
        return default


RUNNER_POOL_READ_LIMIT_S1 = _int_env("RUNNER_POOL_READ_LIMIT_S1", 100)
STRATEGY_SCAN_KIWOOM_CALL_BUDGET = _int_env("STRATEGY_SCAN_KIWOOM_CALL_BUDGET", 40)
_STRATEGY_CALL_BUDGET_DEFAULTS = {"S3": 20, "S7": 40, "S11": 30}
# S4 풀 읽기/스캔/시그널 제한값은 strategy_4_big_candle.scan_big_candle() 내부로 이관됨
# (동일한 RUNNER_POOL_READ_LIMIT_S4 / RUNNER_SCAN_LIMIT_S4 / RUNNER_SIGNAL_LIMIT_S4
#  env var 이름을 그대로 사용하므로 운영 설정은 변경할 필요 없음).


def _redis_text(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return str(value)


def _kst_hhmm() -> int:
    now = datetime.datetime.now(KST)
    return now.hour * 100 + now.minute


from strategy_meta import SWING_STRATEGIES as _SWING_STRATEGIES


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENT_STRATEGIES)
    return _semaphore


_DEFAULT_STRATEGY_TIMEOUT_SEC = int(os.getenv("STRATEGY_TIMEOUT_SEC", "300"))
_SLOW_STRATEGY_WARN_SEC = float(os.getenv("SLOW_STRATEGY_WARN_SEC", "90"))
ENABLE_STRATEGY_LATENCY_METRICS = _env_flag("ENABLE_STRATEGY_LATENCY_METRICS")
ENABLE_STRATEGY_SESSION_FILTER = _env_flag("ENABLE_STRATEGY_SESSION_FILTER")
STRATEGY_SESSION_DRY_RUN = _env_flag("STRATEGY_SESSION_DRY_RUN")
STRATEGY_SESSION_FAIL_OPEN = _env_flag("STRATEGY_SESSION_FAIL_OPEN", "false")
STRATEGY_LATENCY_STATUS_TTL_SEC = int(os.getenv("STRATEGY_LATENCY_STATUS_TTL_SEC", "1800"))
_STRATEGY_TIMEOUT_OVERRIDES = {
    "S3": int(os.getenv("STRATEGY_TIMEOUT_S3_SEC", str(_DEFAULT_STRATEGY_TIMEOUT_SEC))),
    "S5": int(os.getenv("STRATEGY_TIMEOUT_S5_SEC", str(_DEFAULT_STRATEGY_TIMEOUT_SEC))),
    "S11": int(os.getenv("STRATEGY_TIMEOUT_S11_SEC", str(_DEFAULT_STRATEGY_TIMEOUT_SEC))),
    "S16": int(os.getenv("STRATEGY_TIMEOUT_S16_SEC", str(_DEFAULT_STRATEGY_TIMEOUT_SEC))),
    # 2026-08-06: S8/S9 share the ka10081/ka10055 heavy-TR budget with every other
    # concurrently-scheduled strategy at ~1 req/s. With 5 strategies running at once
    # under that shared cap, 300s isn't enough to clear ~60 candidates' worth of
    # calls even with zero wasted requests (fetch coalescing landed the same day and
    # didn't fully fix it) -- S8 timed out 37/37 runs today, S9 4/14. Give them more
    # runway instead of racing the shared rate limiter.
    #
    # 2026-08-14 후속: 런웨이를 늘려도 다시 천장에 붙었다. S9 25회 전부 느린 실행
    # (평균 351s, 최대 441.9s / 450s — 8초 남김), S8 23회 중 22회 느림. 종목당
    # 순차 API 대기가 4회 x 0.8s라 60종목이면 대기만 192s다. 타임아웃을 또 올리는
    # 대신 S8/S9_SCAN_LIMIT을 60 -> 40으로 낮춰 호출량 자체를 줄였다(.env).
    # 후보 풀은 등락률 순위로 정렬돼 있어 꼬리 20종목의 신호 기여가 낮다
    # (S9는 하루 1270종목 평가에 신호 3건). 타임아웃 값은 안전 여유로 유지한다.
    "S8": int(os.getenv("STRATEGY_TIMEOUT_S8_SEC", "500")),
    "S9": int(os.getenv("STRATEGY_TIMEOUT_S9_SEC", "450")),
}


def _strategy_timeout_sec(name: str) -> int:
    return _STRATEGY_TIMEOUT_OVERRIDES.get(name, _DEFAULT_STRATEGY_TIMEOUT_SEC)


def _strategy_call_budget(name: str) -> int:
    default = _STRATEGY_CALL_BUDGET_DEFAULTS.get(name, STRATEGY_SCAN_KIWOOM_CALL_BUDGET)
    return _int_env(f"STRATEGY_SCAN_KIWOOM_CALL_BUDGET_{name}", default)


async def _incr_pipeline_daily(rdb, strategy: str, field: str) -> None:
    if not rdb or not strategy:
        return
    try:
        from datetime import datetime, timedelta, timezone as _tz

        today = datetime.now(_tz(timedelta(hours=9))).strftime("%Y-%m-%d")
        key = f"pipeline_daily:{today}:{strategy}"
        await rdb.hincrby(key, field, 1)
        await rdb.expire(key, 172800)
    except Exception:
        pass


async def _record_strategy_latency(rdb, name: str, elapsed_sec: float, state: str) -> None:
    if not ENABLE_STRATEGY_LATENCY_METRICS or not rdb:
        return
    try:
        key = f"status:strategy_latency:{name}"
        await rdb.hset(
            key,
            mapping={
                "strategy": name,
                "state": state,
                "latency_ms": str(int(elapsed_sec * 1000)),
                "slow_threshold_ms": str(int(_SLOW_STRATEGY_WARN_SEC * 1000)),
                "timeout_sec": str(_strategy_timeout_sec(name)),
                "updated_at": str(int(_time.time())),
            },
        )
        await rdb.expire(key, STRATEGY_LATENCY_STATUS_TTL_SEC)
        if state == "slow":
            await rdb.hincrby(key, "slow_count", 1)
            await _incr_pipeline_daily(rdb, name, "slow")
    except Exception as metric_err:
        logger.debug("[Runner] strategy latency metric failed [%s]: %s", name, metric_err)


async def _record_run_result(rdb, name: str, run_id: str, state: str, published: int, elapsed_sec: float) -> None:
    """Persist one explicit terminal result per scheduled strategy run."""
    if not rdb:
        return
    try:
        key = f"status:strategy_run:{name}"
        await rdb.hset(key, mapping={
            "scan_run_id": run_id,
            "state": state,
            "published": str(published),
            "elapsed_ms": str(int(elapsed_sec * 1000)),
            "completed_at": datetime.datetime.now(timezone.utc).isoformat(),
        })
        await rdb.expire(key, 172800)
        await _incr_pipeline_daily(rdb, name, f"run_{state.lower()}")
    except Exception as metric_err:
        logger.debug("[Runner] strategy run metric failed [%s]: %s", name, metric_err)


def _current_kst_time() -> time:
    return datetime.datetime.now(KST).time()


def _current_kst_datetime() -> datetime.datetime:
    return datetime.datetime.now(KST)


async def _session_filter_allows_run(rdb=None, now: datetime.datetime | None = None) -> bool:
    from redis_reader import get_runtime_flag

    filter_enabled = await get_runtime_flag(rdb, "strategy_session_filter", ENABLE_STRATEGY_SESSION_FILTER)
    if not filter_enabled:
        return True

    try:
        checked_at = now or _current_kst_datetime()
        session = current_session(checked_at)
        active = is_trading_active(checked_at)
    except Exception as exc:
        fail_open = await get_runtime_flag(rdb, "strategy_session_fail_open", STRATEGY_SESSION_FAIL_OPEN)
        if fail_open:
            logger.warning("[Runner] session filter failed open: %s", exc)
            return True
        logger.warning("[Runner] session filter failed closed: %s", exc)
        return False

    if active:
        logger.debug("[Runner] session filter allows scan (session=%s)", session.value)
        return True

    dry_run = await get_runtime_flag(rdb, "strategy_session_dry_run", STRATEGY_SESSION_DRY_RUN)
    if dry_run:
        logger.info("[Runner] session filter dry-run would skip scan (session=%s)", session.value)
        return True

    logger.info("[Runner] session filter skipped scan (session=%s)", session.value)
    return False


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
        run_id = str(uuid.uuid4())
        run_token = _SCAN_RUN_CONTEXT.set(run_id)
        published_state = {"count": 0}
        published_token = _SCAN_PUBLISHED_CONTEXT.set(published_state)
        from http_utils import begin_call_budget, end_call_budget
        budget_token = begin_call_budget(_strategy_call_budget(name))
        try:
            result = await asyncio.wait_for(coro, timeout=timeout_sec)
            elapsed_sec = _time.monotonic() - started_at
            published = published_state["count"]
            state = "COMPLETED_WITH_SIGNALS" if published else "SUCCESS_NO_MATCH"
            await _record_run_result(rdb, name, run_id, state, published, elapsed_sec)
            if elapsed_sec >= _SLOW_STRATEGY_WARN_SEC:
                logger.warning("[Runner] [%s] 느린 실행 감지 (%.1fs, timeout=%ds)", name, elapsed_sec, timeout_sec)
                await _record_strategy_latency(rdb, name, elapsed_sec, "slow")
            else:
                logger.info("[Runner] [%s] 실행 완료 (%.1fs)", name, elapsed_sec)
                await _record_strategy_latency(rdb, name, elapsed_sec, "ok")
            return result
        except asyncio.TimeoutError:
            elapsed_sec = _time.monotonic() - started_at
            logger.error("[Runner] [%s] 전략 실행 타임아웃 (%ds) - 강제 취소 elapsed=%.1fs", name, timeout_sec, elapsed_sec)
            await _incr_pipeline_daily(rdb, name, "timeout")
            await _record_strategy_latency(rdb, name, elapsed_sec, "timeout")
            await _record_run_result(rdb, name, run_id, "TIMEOUT", published_state["count"], elapsed_sec)
        except Exception:
            elapsed_sec = _time.monotonic() - started_at
            logger.exception("[Runner] [%s] 실행 실패 (%.1fs)", name, elapsed_sec)
            await _incr_pipeline_daily(rdb, name, "error")
            await _record_strategy_latency(rdb, name, elapsed_sec, "error")
            await _record_run_result(rdb, name, run_id, "API_ERROR", published_state["count"], elapsed_sec)
        finally:
            end_call_budget(budget_token)
            _SCAN_PUBLISHED_CONTEXT.reset(published_token)
            _SCAN_RUN_CONTEXT.reset(run_token)


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


async def _push_signals(rdb, signals: list, strategy_name: str) -> int:
    expected_token = _STRATEGY_TOKEN_CONTEXT.get()
    if expected_token:
        try:
            current_token = await rdb.get(REDIS_TOKEN_KEY)
        except Exception as exc:
            logger.warning(
                "[Runner] [%s] publish blocked: token generation check failed: %s",
                strategy_name,
                exc,
            )
            return 0
        if not current_token or current_token != expected_token:
            logger.warning(
                "[Runner] [%s] stale-token scan result discarded before publish",
                strategy_name,
            )
            return 0

    published = 0
    for sig in signals:
        if SHADOW_MODE_FORBIDDEN and str(sig.get("signal_mode", "")).upper() == "SHADOW":
            logger.warning(
                "[Runner] live-only policy rejected non-live candidate [%s %s]",
                strategy_name,
                sig.get("stk_cd", ""),
            )
            continue
        stk_cd = normalize_stock_code(sig.get("stk_cd", ""))
        sig["stk_cd"] = stk_cd
        sig.setdefault("scan_run_id", _SCAN_RUN_CONTEXT.get())
        normalize_runner_signal(sig, strategy_name)
        # Additive family lineage.  Keep ``strategy`` as the immutable legacy
        # setup id so existing DB constraints, prompts, reports and consumers
        # remain compatible during shadow migration.
        setup_id = str(sig.get("strategy") or strategy_name)
        if family_lineage_enabled() and setup_id in ALL_SETUP_IDS:
            for key, value in family_lineage(setup_id).items():
                sig.setdefault(key, value)

        dedup_ttl = SWING_DEDUP_TTL_SEC if strategy_name in _SWING_STRATEGIES else INTRADAY_DEDUP_TTL_SEC
        dedup_key = f"scanner:dedup:{strategy_name}:{stk_cd}"
        try:
            is_new = await rdb.set(dedup_key, "1", nx=True, ex=dedup_ttl)
        except Exception as dedup_err:
            logger.warning("[Runner] dedup 확인 1차 실패, 재시도 [%s %s]: %s", strategy_name, stk_cd, dedup_err)
            try:
                is_new = await rdb.set(dedup_key, "1", nx=True, ex=dedup_ttl)
            except Exception as dedup_err2:
                # 중복 발행(같은 종목·전략이 dedup TTL 내에 두 번 발행되는 문제)을 막기 위해
                # 재시도까지 실패하면 이번 사이클은 발행을 보류한다(다음 스캔 주기에 재평가).
                logger.warning(
                    "[Runner] dedup 확인 재시도 실패 — 이번 사이클 발행 보류 [%s %s]: %s",
                    strategy_name, stk_cd, dedup_err2,
                )
                continue
        if not is_new:
            logger.debug("[Runner] 중복 무시 [%s %s] (dedup TTL %ds)", strategy_name, stk_cd, dedup_ttl)
            continue

        if _pg_pool is not None:
            try:
                from db_reader import get_active_position
                existing = await get_active_position(_pg_pool, stk_cd)
                if existing is not None:
                    logger.info(
                        "[Runner] 활성 포지션 존재 — ENTER 발행 skip [%s %s]",
                        strategy_name, stk_cd,
                    )
                    continue
            except Exception as pos_err:
                logger.debug("[Runner] 활성 포지션 확인 실패 (통과): %s", pos_err)

        if not sig.get("stk_nm"):
            try:
                from http_utils import fetch_stk_nm

                token = await rdb.get(REDIS_TOKEN_KEY)
                if token:
                    sig["stk_nm"] = await fetch_stk_nm(rdb, token, stk_cd)
            except Exception as nm_err:
                logger.debug("[Runner] stk_nm 조회 실패 [%s]: %s", stk_cd, nm_err)

        try:
            # Additive payload metadata used by consumers to bound queue-value fallbacks.
            # Preserve an upstream timestamp when one already exists.
            sig.setdefault("enqueued_at", _time.time())
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
                        "runner_score_raw": str(sig.get("runner_score_raw", "")),
                        "score_scale": str(sig.get("score_scale", "")),
                        "updated_at": str(int(_time.time())),
                    },
                )
                await rdb.expire(f"status:last_signal:{strategy_name}", STATUS_SIGNAL_TTL_SEC)
            except Exception as status_err:
                logger.debug("[Runner] status signal metric failed [%s]: %s", strategy_name, status_err)
            logger.info("[Runner] 신호 발행 [%s] stk=%s score=%s", strategy_name, sig.get("stk_cd"), sig.get("score", "N/A"))
            published += 1
            published_state = _SCAN_PUBLISHED_CONTEXT.get()
            if published_state is not None:
                published_state["count"] += 1
        except Exception as exc:
            logger.error("[Runner] 신호 발행 실패 [%s]: %s", strategy_name, exc)

    return published


async def _run_with_token_context(coro, token: str):
    context_token = _STRATEGY_TOKEN_CONTEXT.set(token)
    try:
        return await coro
    finally:
        _STRATEGY_TOKEN_CONTEXT.reset(context_token)


async def _scan_s1(rdb, token):
    try:
        from strategy_1_gap_opening import scan_gap_opening

        pool_stop = RUNNER_POOL_READ_LIMIT_S1 - 1
        kospi = await rdb.lrange("candidates:s1:001", 0, pool_stop)
        kosdaq = await rdb.lrange("candidates:s1:101", 0, pool_stop)
        candidates = list(
            dict.fromkeys(
                code
                for code in (normalize_stock_code(_redis_text(raw)) for raw in kospi + kosdaq)
                if code
            )
        )

        now_hhmm = _kst_hhmm()
        if now_hhmm < S1_SCAN_START_HHMM and len(candidates) < S1_MIN_READY_CANDIDATES:
            meta = {}
            try:
                meta = {
                    "001": {_redis_text(k): _redis_text(v) for k, v in (await rdb.hgetall("candidate:quality:meta:s1:001") or {}).items()},
                    "101": {_redis_text(k): _redis_text(v) for k, v in (await rdb.hgetall("candidate:quality:meta:s1:101") or {}).items()},
                }
            except Exception as meta_err:
                logger.debug("[Runner] S1 readiness meta read failed: %s", meta_err)
            logger.info(
                "[Runner] S1 SKIP_NOT_READY hhmm=%04d candidates=%d min=%d meta=%s",
                now_hhmm,
                len(candidates),
                S1_MIN_READY_CANDIDATES,
                meta,
            )
            return

        if now_hhmm > S1_SCAN_END_HHMM:
            logger.info("[Runner] S1 SKIP_WINDOW_CLOSED hhmm=%04d candidates=%d", now_hhmm, len(candidates))
            return
        if not candidates:
            logger.warning("[Runner] S1 SKIP_EMPTY_POOL hhmm=%04d; fallback scan disabled", now_hhmm)
            await _incr_pipeline_daily(rdb, "S1_GAP_OPEN", "skip_empty_pool")
            return
        signals = await scan_gap_opening(token, candidates, rdb=rdb)
        try:
            fallback_markets = []
            for market in ("001", "101"):
                meta = {_redis_text(k): _redis_text(v) for k, v in (await rdb.hgetall(f"candidate:quality:meta:s1:{market}") or {}).items()}
                if meta.get("source_market") == "000":
                    fallback_markets.append(market)
            if fallback_markets:
                for sig in signals:
                    sig["candidate_source_status"] = "FALLBACK_ALL_MARKET"
                    sig["candidate_source_markets"] = ",".join(fallback_markets)
        except Exception as meta_err:
            logger.debug("[Runner] S1 fallback meta annotate failed: %s", meta_err)
        await _push_signals(rdb, signals, "S1_GAP_OPEN")
    except Exception as exc:
        logger.exception("[Runner] S1 스캔 오류")
        raise


async def _scan_s2(rdb, token):
    try:
        from strategy_2_vi_pullback import check_vi_pullback, is_publishable_signal

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
                if result and is_publishable_signal(result):
                    s2_signals.append(result)
                    if len(s2_signals) >= 3:
                        break
                elif result:
                    logger.debug("[Runner] S2 SHADOW rollback mode - 발행 제외 [%s]", item.get("stk_cd"))
                else:
                    await rdb.lpush("vi_watch_queue", item_raw)
            except Exception as ve:
                logger.debug("[Runner] S2 항목 처리 실패: %s", ve)
        await _push_signals(rdb, s2_signals, "S2_VI_PULLBACK")
    except Exception as exc:
        logger.exception("[Runner] S2 스캔 오류")
        raise


async def _scan_s3(rdb, token):
    try:
        from strategy_3_inst_foreign import scan_inst_foreign

        for market in ("001", "101"):
            signals = await scan_inst_foreign(token, market, rdb=rdb)
            await _push_signals(rdb, signals, "S3_INST_FRGN")
    except Exception as exc:
        logger.exception("[Runner] S3 스캔 오류")
        raise


async def _scan_s4(rdb, token):
    try:
        from strategy_4_big_candle import scan_big_candle

        s4_signals = await scan_big_candle(token, rdb=rdb)
        await _push_signals(rdb, s4_signals, "S4_BIG_CANDLE")
    except Exception as exc:
        logger.exception("[Runner] S4 스캔 오류")
        raise


async def _scan_s5(rdb, token):
    try:
        from strategy_5_program_buy import scan_program_buy

        for market in ("001", "101"):
            signals = await scan_program_buy(token, market, rdb=rdb)
            await _push_signals(rdb, signals, "S5_PROG_FRGN")
    except Exception as exc:
        logger.exception("[Runner] S5 스캔 오류")
        raise


async def _scan_s6(rdb, token):
    try:
        from strategy_6_theme import scan_theme_laggard

        signals = await scan_theme_laggard(token, rdb=rdb)
        await _push_signals(rdb, signals, "S6_THEME_LAGGARD")
    except Exception as exc:
        logger.exception("[Runner] S6 스캔 오류")
        raise


async def _scan_s7(rdb, token):
    try:
        from strategy_7_ichimoku_breakout import scan_ichimoku_breakout

        signals = await scan_ichimoku_breakout(token, rdb=rdb)
        await _push_signals(rdb, signals, "S7_ICHIMOKU_BREAKOUT")
    except Exception as exc:
        logger.exception("[Runner] S7 스캔 오류")
        raise


async def _scan_s8(rdb, token):
    try:
        from strategy_8_golden_cross import scan_golden_cross

        signals = await scan_golden_cross(token, rdb=rdb)
        return await _push_signals(rdb, signals, "S8_GOLDEN_CROSS")
    except Exception as exc:
        logger.exception("[Runner] S8 스캔 오류")
        raise


async def _scan_s9(rdb, token):
    try:
        from strategy_9_pullback import scan_pullback_swing

        signals = await scan_pullback_swing(token, rdb=rdb)
        return await _push_signals(rdb, signals, "S9_PULLBACK_SWING")
    except Exception as exc:
        logger.exception("[Runner] S9 스캔 오류")
        raise


async def _scan_s10(rdb, token):
    try:
        from strategy_10_new_high import scan_new_high_swing

        signals = await scan_new_high_swing(token, "000", rdb=rdb)
        await _push_signals(rdb, signals, "S10_NEW_HIGH")
    except Exception as exc:
        logger.exception("[Runner] S10 스캔 오류")
        raise


async def _scan_s11(rdb, token):
    published = 0
    try:
        from strategy_11_frgn_cont import scan_frgn_cont_swing

        for market in ("001", "101"):
            signals = await scan_frgn_cont_swing(token, market, rdb=rdb)
            published += await _push_signals(rdb, signals, "S11_FRGN_CONT")
    except Exception as exc:
        logger.exception("[Runner] S11 스캔 오류")
        raise
    return published


async def _scan_s12(rdb, token):
    try:
        from strategy_12_closing import scan_closing_buy

        for market in ("001", "101"):
            signals = await scan_closing_buy(token, market, rdb=rdb)
            await _push_signals(rdb, signals, "S12_CLOSING")
    except Exception as exc:
        logger.exception("[Runner] S12 스캔 오류")
        raise


async def _scan_s13(rdb, token):
    try:
        from strategy_13_box_breakout import scan_box_breakout

        signals = await scan_box_breakout(token, rdb=rdb)
        return await _push_signals(rdb, signals, "S13_BOX_BREAKOUT")
    except Exception as exc:
        logger.exception("[Runner] S13 스캔 오류")
        raise


async def _scan_s14(rdb, token):
    try:
        from strategy_14_oversold_bounce import scan_oversold_bounce

        signals = await scan_oversold_bounce(token, rdb=rdb)
        return await _push_signals(rdb, signals, "S14_OVERSOLD_BOUNCE")
    except Exception as exc:
        logger.exception("[Runner] S14 스캔 오류")
        raise


async def _scan_s15(rdb, token):
    try:
        from strategy_15_momentum_align import scan_momentum_align

        signals = await scan_momentum_align(token, rdb=rdb)
        return await _push_signals(rdb, signals, "S15_MOMENTUM_ALIGN")
    except Exception as exc:
        logger.exception("[Runner] S15 스캔 오류")
        raise


async def _scan_s16(rdb, token):
    try:
        from strategy_16_accumulation import scan_accumulation_shadow

        signals = await scan_accumulation_shadow(token, rdb=rdb)
        return await _push_signals(rdb, signals, "S16_ACCUMULATION_SHADOW")
    except Exception:
        logger.exception("[Runner] S16 스캔 오류")
        raise


_SCHEDULE: list[tuple[str, time, time, callable]] = [
    ("S7", time(10, 45), time(14, 0), _scan_s7),
    ("S1", time(8, 30), time(9, 10), _scan_s1),
    ("S3", time(10, 30), time(14, 0), _scan_s3),
    ("S4", time(10, 0), time(14, 30), _scan_s4),
    ("S5", time(10, 15), time(14, 0), _scan_s5),
    ("S6", time(9, 45), time(13, 0), _scan_s6),
    ("S10", time(10, 30), time(14, 30), _scan_s10),
    ("S11", time(10, 45), time(14, 0), _scan_s11),
    ("S8", time(11, 0), time(14, 0), _scan_s8),
    ("S9", time(10, 30), time(14, 0), _scan_s9),
    ("S13", time(11, 15), time(14, 30), _scan_s13),
    ("S14", time(10, 0), time(14, 0), _scan_s14),
    ("S15", time(10, 15), time(14, 30), _scan_s15),
    ("S16", time(11, 30), time(14, 30), _scan_s16),
    ("S12", time(14, 30), time(15, 10), _scan_s12),
]

# 대시보드 수동 실행("전략 수동 실행" 패널) 대상 — Java api-orchestrator에 대응 엔드포인트가
# 없는, Python 전용으로만 구현된 전략들. S1~S7/S10/S12는 이미 Java 쪽에 자체 /run 엔드포인트가
# 있으므로 여기 포함하지 않는다 (health_server.py의 /strategy/{code}/run 참고).
MANUAL_RUN_STRATEGIES: dict[str, tuple[str, callable]] = {
    "s8":  ("S8_GOLDEN_CROSS", _scan_s8),
    "s9":  ("S9_PULLBACK_SWING", _scan_s9),
    "s11": ("S11_FRGN_CONT", _scan_s11),
    "s13": ("S13_BOX_BREAKOUT", _scan_s13),
    "s14": ("S14_OVERSOLD_BOUNCE", _scan_s14),
    "s15": ("S15_MOMENTUM_ALIGN", _scan_s15),
    "s16": ("S16_ACCUMULATION_SHADOW", _scan_s16),
}


async def run_manual_scan(rdb, code: str) -> dict:
    """관리자 대시보드에서 개별 전략을 즉시 1회 실행한다. 자동 스케줄/오너십 게이트와 무관하게 동작."""
    entry = MANUAL_RUN_STRATEGIES.get(str(code or "").strip().lower())
    if entry is None:
        return {"error": f"unsupported strategy code: {code}"}
    strategy_name, fn = entry
    token = await _load_token(rdb)
    if not token:
        return {"strategy": strategy_name, "published": 0, "error": "kiwoom:token not available"}
    from http_utils import begin_call_budget, end_call_budget
    budget_token = begin_call_budget(_strategy_call_budget(strategy_name.split("_", 1)[0]))
    try:
        published = await fn(rdb, token)
    finally:
        end_call_budget(budget_token)
    return {"strategy": strategy_name, "published": int(published or 0)}


async def _run_once(rdb):
    if not _python_owns_strategy_execution():
        logger.debug("[Runner] strategy execution owner=%s; Python scan skipped", STRATEGY_EXECUTION_OWNER)
        return
    now = _current_kst_time()
    active_entries = _active_schedule_entries(now)
    if not await _session_filter_allows_run(rdb):
        return

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
        _run_strategy_with_semaphore(
            tag,
            _run_with_token_context(fn(rdb, token), token),
            rdb=rdb,
        )
        for tag, start, end, fn in active_entries
    ]

    dispatched_tags = ", ".join(tag for tag, _, _, _ in active_entries)
    logger.info(
        "[Runner] 전술 %d개 병렬 실행 시작 (세마포어 한도: %d): %s",
        len(tasks), MAX_CONCURRENT_STRATEGIES, dispatched_tags,
    )
    await asyncio.gather(*tasks, return_exceptions=True)


async def run_strategy_scanner(rdb, pg_pool=None):
    global _pg_pool
    _pg_pool = pg_pool
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
