from __future__ import annotations
"""
http_utils.py
공통 Kiwoom API HTTP 유틸리티 – 전술 파일 간 코드 중복 제거용.
"""

import asyncio
import json
import logging
import os
import time as _time
from datetime import datetime, timedelta, timezone

import httpx
import redis.asyncio as redis_async

from config import KIWOOM_BASE_URL, REDIS_HOST, REDIS_PASSWORD, REDIS_PORT
from utils import safe_float as _sf_global, normalize_stock_code

logger = logging.getLogger(__name__)
_DEFAULT_TIMEOUT = 10.0
_KST = timezone(timedelta(hours=9))
KIWOOM_RATE_LIMIT_CODES = {"1700", "1687"}
KIWOOM_AUTH_ERROR_CODES = {"8005", "8050", "8103"}


def classify_kiwoom_return_code(return_code) -> str:
    """Classify Kiwoom body-level return_code for observability and callers."""
    if return_code is None or str(return_code) == "0":
        return "ok"
    code = str(return_code)
    if code in KIWOOM_RATE_LIMIT_CODES:
        return "rate_limit"
    if code in KIWOOM_AUTH_ERROR_CODES:
        return "auth"
    return "business_error"


def kiwoom_error_meta(data: dict, api_id: str) -> dict:
    """Return normalized error metadata for a Kiwoom response body."""
    if "error" in data:
        return {
            "api_id": api_id,
            "error_type": "wrapped_server_error",
            "return_code": data.get("return_code"),
            "return_msg": data.get("message") or data.get("return_msg") or "",
        }
    rc = data.get("return_code")
    error_type = classify_kiwoom_return_code(rc)
    return {
        "api_id": api_id,
        "error_type": error_type,
        "return_code": rc,
        "return_msg": data.get("return_msg", ""),
    }


class _KiwoomRateLimiter:
    """asyncio 토큰 버킷 – Java KiwoomRateLimiter와 동일한 3 req/s.

    candidates_builder, strategy_runner, http_utils 모두 이 싱글턴을 공유하여
    Python ai-engine 내 전체 Kiwoom API 호출 속도를 제한한다.
    """

    def __init__(self, rate: float = 3.0):
        self._interval = 1.0 / rate  # seconds per request
        self._lock = asyncio.Lock()
        self._last = 0.0
        self._global_enabled = os.getenv("KIWOOM_GLOBAL_RATE_LIMIT_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
        self._global_interval_ms = int(os.getenv("KIWOOM_GLOBAL_RATE_LIMIT_INTERVAL_MS", "333"))
        self._global_key = os.getenv("KIWOOM_GLOBAL_RATE_LIMIT_KEY", "kiwoom:global_rate_limit:lock")
        self._global_wait_ms = int(os.getenv("KIWOOM_GLOBAL_RATE_LIMIT_WAIT_MS", "5000"))
        self._fallback_interval_ms = int(os.getenv("KIWOOM_GLOBAL_RATE_LIMIT_FALLBACK_INTERVAL_MS", "1000"))
        self._unavailable_backoff_ms = int(os.getenv("KIWOOM_GLOBAL_RATE_LIMIT_UNAVAILABLE_BACKOFF_MS", "30000"))
        self._fallback_lock = asyncio.Lock()
        self._fallback_last = 0.0
        self._redis = None
        self._global_disabled_until = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = _time.monotonic()
            wait = self._interval - (now - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = _time.monotonic()
        await self._acquire_global()

    def _redis_client(self):
        if self._redis is None:
            self._redis = redis_async.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                password=REDIS_PASSWORD,
                decode_responses=True,
                socket_connect_timeout=0.2,
                socket_timeout=0.2,
            )
        return self._redis

    async def _acquire_global(self) -> None:
        if not self._global_enabled:
            return
        now = _time.monotonic()
        if now < self._global_disabled_until:
            await self._acquire_global_fallback("global limiter unavailable")
            return
        deadline = now + max(self._global_wait_ms, 0) / 1000.0
        client = self._redis_client()
        while True:
            try:
                ok = await client.set(self._global_key, "python", nx=True, px=max(self._global_interval_ms, 1))
                if ok:
                    return
            except Exception as exc:
                self._global_disabled_until = _time.monotonic() + max(self._unavailable_backoff_ms, 0) / 1000.0
                logger.warning(
                    "[http_utils] global Kiwoom rate limiter unavailable; local fallback %.0fms for %.0fms: %s",
                    self._fallback_interval_ms,
                    self._unavailable_backoff_ms,
                    exc,
                )
                await self._acquire_global_fallback("global limiter unavailable")
                return
            if _time.monotonic() >= deadline:
                logger.warning(
                    "[http_utils] global Kiwoom rate limiter wait exceeded %.0fms; local fallback %.0fms",
                    self._global_wait_ms,
                    self._fallback_interval_ms,
                )
                await self._acquire_global_fallback("global limiter wait exceeded")
                return
            await asyncio.sleep(0.025)

    async def _acquire_global_fallback(self, reason: str) -> None:
        """Slow local progress instead of fail-opening when Redis coordination is unavailable."""
        async with self._fallback_lock:
            interval = max(self._fallback_interval_ms, self._global_interval_ms, 1) / 1000.0
            now = _time.monotonic()
            wait = interval - (now - self._fallback_last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._fallback_last = _time.monotonic()


# 전역 싱글턴 – 모든 Kiwoom API 호출에서 공유
kiwoom_rate_limiter = _KiwoomRateLimiter(rate=3.0)


def kiwoom_client(timeout: float = _DEFAULT_TIMEOUT) -> httpx.AsyncClient:
    """Rate Limiter가 내장된 Kiwoom API 전용 httpx AsyncClient 팩토리.

    Usage:
        async with kiwoom_client() as client:
            resp = await client.post(url, headers=..., json=...)
    """
    async def _rate_hook(request: httpx.Request) -> None:
        await kiwoom_rate_limiter.acquire()

    return httpx.AsyncClient(
        timeout=timeout,
        event_hooks={"request": [_rate_hook]},
    )


async def kiwoom_post(
    url: str,
    headers: dict,
    json_body: dict,
    api_id: str,
    max_retries: int = 2,
    backoff_base: float = 60.0,
) -> "httpx.Response | None":
    """Rate-limited Kiwoom API POST with 429 exponential-backoff retry.

    Replaces the private ``_post_with_retry()`` helper that was duplicated in
    ``candidates_builder.py``.  Each call opens its own ``kiwoom_client()``
    context so the rate-limiter singleton is always respected.

    Returns the ``httpx.Response`` on success, or ``None`` when all retries are
    exhausted or a non-retriable error occurs.
    """
    for attempt in range(max_retries + 1):
        try:
            async with kiwoom_client() as client:
                resp = await client.post(url, headers=headers, json=json_body)
            if resp.status_code == 429:
                wait = backoff_base * (2 ** attempt)
                logger.warning(
                    "[http_utils] %s 429 Too Many Requests – %.0fs 대기 (attempt %d/%d)",
                    api_id, wait, attempt + 1, max_retries + 1,
                )
                if attempt < max_retries:
                    await asyncio.sleep(wait)
                    continue
                return None
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as e:
            if attempt < max_retries:
                logger.warning(
                    "[http_utils] %s HTTP 오류 %s – 재시도",
                    api_id, e.response.status_code,
                )
                await asyncio.sleep(0.5)
                continue
            logger.error("[http_utils] %s HTTP 오류 최종 실패: %s", api_id, e)
            return None
        except Exception as e:
            logger.error("[http_utils] %s 요청 오류: %s", api_id, e)
            return None
    return None


def validate_kiwoom_response(data: dict, api_id: str, log=None) -> bool:
    """
    Kiwoom API가 HTTP 200이지만 에러 바디를 반환하는 경우를 감지한다.

    - 'error' 키 존재 → Spring Boot 서버 내부 오류 바디 (HTTP 200 wrapping 500)
    - return_code 가 '0'이 아닌 값 → API 레벨 비즈니스 오류

    반환: True(정상), False(오류) — False 시 호출부는 빈 값을 반환해야 한다.
    """
    _log = log or logger
    if "error" in data:
        _log.warning("[%s] Kiwoom 서버 오류 바디 수신 (HTTP 200 wrapping error): %s",
                     api_id, data.get("message", ""))
        return False
    rc = data.get("return_code")
    if rc is not None and str(rc) != "0":
        error_type = classify_kiwoom_return_code(rc)
        _log.warning("[%s] Kiwoom %s return_code=%s msg=%s", api_id, error_type, rc, data.get("return_msg", ""))
        return False
    return True


async def fetch_stk_nm(rdb, token: str, stk_cd: str) -> str:
    """
    종목명 조회. Redis 캐시(stk_nm:{stk_cd}, TTL 1일) 우선.
    캐시 미스 시 ka10001 주식기본정보로 조회 후 캐시 저장.
    rdb=None 이면 항상 REST API 직접 호출.
    """
    stk_cd = normalize_stock_code(stk_cd)
    if not stk_cd:
        return ""
    if rdb:
        try:
            cached = await rdb.get(f"stk_nm:{stk_cd}")
            if cached:
                return cached
        except Exception:
            pass

    try:
        async with kiwoom_client() as client:
            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/stkinfo",
                headers={
                    "api-id": "ka10001",
                    "authorization": f"Bearer {token}",
                    "Content-Type": "application/json;charset=UTF-8",
                },
                json={
                    "stk_cd": stk_cd
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if not validate_kiwoom_response(data, "ka10001", logger):
                return ""
            items = data.get("stk_info", [])
            stk_nm = str(data.get("stk_nm", "")).strip()
            if not stk_nm and items:
                stk_nm = str(items[0].get("stk_nm", "")).strip()
    except Exception as e:
        logger.debug("[http_utils] fetch_stk_nm [%s] 실패: %s", stk_cd, e)
        return ""

    if rdb and stk_nm:
        try:
            await rdb.set(f"stk_nm:{stk_cd}", stk_nm, ex=86400)
        except Exception:
            pass

    return stk_nm


async def fetch_hoga(token: str, stk_cd: str, rdb=None) -> float | None:
    """
    매수/매도 호가 총잔량 비율(bid_ratio) 조회.

    우선순위:
      1. Redis ws:hoga:{stk_cd} — WS 0D 구독 종목 (total_buy_bid_req / total_sel_bid_req)
      2. ka10004 주식호가요청 REST — WS 미구독 스윙 종목 (tot_buy_req / tot_sel_req)

    반환: bid_ratio (float, ≥ 0) | None (조회 실패 또는 데이터 없음)
    캐시 TTL: REST 조회 결과를 Redis hoga:{stk_cd}:rest 에 30초 캐싱.
    """
    _sf = _sf_global
    stk_cd = normalize_stock_code(stk_cd)
    if not stk_cd:
        return None

    # 1. WS Redis 캐시 우선
    if rdb:
        try:
            ws_hoga = await rdb.hgetall(f"ws:hoga:{stk_cd}")
            if ws_hoga:
                bid = _sf(ws_hoga.get("total_buy_bid_req", 0))
                ask = _sf(ws_hoga.get("total_sel_bid_req", 0))
                return bid / ask if ask > 0 else None
        except Exception:
            pass

        # REST 결과 단기 캐시 확인 (30초)
        try:
            cached = await rdb.get(f"hoga:{stk_cd}:rest")
            if cached is not None:
                return float(cached) if cached != "None" else None
        except Exception:
            pass

    # 2. ka10004 REST 조회
    try:
        async with kiwoom_client() as client:
            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/mrkcond",
                headers={
                    "api-id": "ka10004",
                    "authorization": f"Bearer {token}",
                    "Content-Type": "application/json;charset=UTF-8",
                },
                json={"stk_cd": stk_cd},
            )
            resp.raise_for_status()
            data = resp.json()
            if not validate_kiwoom_response(data, "ka10004", logger):
                return None

        tot_buy = _sf(data.get("tot_buy_req", 0))
        tot_sel = _sf(data.get("tot_sel_req", 0))
        ratio = (tot_buy / tot_sel) if tot_sel > 0 else None

        # 30초 캐싱
        if rdb:
            try:
                await rdb.set(f"hoga:{stk_cd}:rest", str(ratio), ex=30)
            except Exception:
                pass

        return ratio

    except Exception as e:
        logger.debug("[http_utils] fetch_hoga [%s] 실패: %s", stk_cd, e)
        return None


async def fetch_hoga_rest(
    token: str,
    stk_cd: str,
    *,
    timeout: float = 3.0,
) -> tuple[float | None, dict]:
    """
    Redis를 읽지 않고 ka10004 REST API로 직접 bid_ratio를 조회한다.
    stale Redis 우회 전용 — rdb 파라미터 없음.
    반환: (bid_ratio | None, meta)
    meta = {"source": "rest", "api_id": "ka10004",
            "retry_count": int, "latency_ms": int, "error": str | None}
    """
    _sf = _sf_global
    stk_cd = normalize_stock_code(stk_cd)
    meta: dict = {
        "source": "rest",
        "api_id": "ka10004",
        "retry_count": 0,
        "latency_ms": 0,
        "error": None,
    }
    if not stk_cd:
        meta["error"] = "invalid stk_cd"
        return None, meta

    url = f"{KIWOOM_BASE_URL}/api/dostk/mrkcond"
    headers = {
        "api-id": "ka10004",
        "authorization": f"Bearer {token}",
        "Content-Type": "application/json;charset=UTF-8",
    }
    json_body = {"stk_cd": stk_cd}

    t0 = _time.monotonic()
    try:
        resp = await kiwoom_post(url, headers, json_body, "ka10004", max_retries=2)
        meta["latency_ms"] = int((_time.monotonic() - t0) * 1000)
        # kiwoom_post 내부에서 최대 2회 재시도하므로 retry_count는 최대 2
        if resp is None:
            meta["error"] = "kiwoom_post returned None"
            return None, meta

        data = resp.json()
        if not validate_kiwoom_response(data, "ka10004", logger):
            rc = data.get("return_code", "?")
            msg = data.get("return_msg", "")
            meta["error"] = f"return_code={rc} msg={msg}"
            return None, meta

        # output1 리스트 형식과 최상위 필드 형식 모두 지원
        output1 = data.get("output1", [])
        if output1 and isinstance(output1, list):
            row = output1[0]
            bid = _sf(row.get("total_buy_bid_req", row.get("tot_buy_req", 0)))
            ask = _sf(row.get("total_sel_bid_req", row.get("tot_sel_req", 0)))
        else:
            bid = _sf(data.get("total_buy_bid_req", data.get("tot_buy_req", 0)))
            ask = _sf(data.get("total_sel_bid_req", data.get("tot_sel_req", 0)))

        if ask <= 0:
            meta["error"] = "ask=0 or missing"
            return None, meta

        return bid / ask, meta

    except Exception as e:
        meta["latency_ms"] = int((_time.monotonic() - t0) * 1000)
        meta["error"] = str(e)
        logger.debug("[http_utils] fetch_hoga_rest [%s] 실패: %s", stk_cd, e)
        return None, meta


async def fetch_tick_snapshot(
    token: str,
    stk_cd: str,
    *,
    timeout: float = 3.0,
) -> tuple[dict, dict]:
    """
    REST로 현재 tick(현재가/등락률) 스냅샷을 조회한다.
    tick이 missing이고 signal에 cur_prc도 없을 때 사용하는 REST direct 조회 함수.

    반환: (tick_dict, meta)
    tick_dict = {"cur_prc": str, "flu_rt": str}  # 빈 dict이면 조회 실패
    meta = {"source": "rest", "api_id": "ka10001",
            "retry_count": int, "latency_ms": int, "error": str | None}
    """
    stk_cd = normalize_stock_code(stk_cd)
    meta: dict = {
        "source": "rest",
        "api_id": "ka10001",
        "retry_count": 0,
        "latency_ms": 0,
        "error": None,
    }
    if not stk_cd:
        meta["error"] = "invalid stk_cd"
        return {}, meta

    url = f"{KIWOOM_BASE_URL}/api/dostk/stkinfo"
    headers = {
        "api-id": "ka10001",
        "authorization": f"Bearer {token}",
        "Content-Type": "application/json;charset=UTF-8",
    }
    json_body = {"stk_cd": stk_cd}

    t0 = _time.monotonic()
    try:
        resp = await kiwoom_post(url, headers, json_body, "ka10001", max_retries=2)
        meta["latency_ms"] = int((_time.monotonic() - t0) * 1000)
        if resp is None:
            meta["error"] = "kiwoom_post returned None"
            return {}, meta

        data = resp.json()
        if not validate_kiwoom_response(data, "ka10001", logger):
            rc = data.get("return_code", "?")
            msg = data.get("return_msg", "")
            meta["error"] = f"return_code={rc} msg={msg}"
            return {}, meta

        # 최상위 필드 우선, 없으면 stk_info[0] 서브배열에서 추출
        cur_prc = str(data.get("cur_prc", "")).strip()
        flu_rt = str(data.get("flu_rt", "")).strip()

        if not cur_prc:
            items = data.get("stk_info", [])
            if items and isinstance(items, list):
                row = items[0]
                cur_prc = str(row.get("cur_prc", "")).strip()
                flu_rt = str(row.get("flu_rt", "")).strip()

        if not cur_prc:
            meta["error"] = "cur_prc missing in response"
            return {}, meta

        return {"cur_prc": cur_prc, "flu_rt": flu_rt}, meta

    except Exception as e:
        meta["latency_ms"] = int((_time.monotonic() - t0) * 1000)
        meta["error"] = str(e)
        logger.debug("[http_utils] fetch_tick_snapshot [%s] 실패: %s", stk_cd, e)
        return {}, meta


async def fetch_cntr_strength(token: str, stk_cd: str) -> float:
    """
    체결강도 조회 (ka10046 체결강도추이시간별요청).
    최근 5개 cntr_str 평균을 반환. 데이터 없거나 오류 시 100.0 반환.
    """
    stk_cd = normalize_stock_code(stk_cd)
    if not stk_cd:
        return 100.0

    try:
        async with kiwoom_client() as client:
            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/mrkcond",
                headers={
                    "api-id": "ka10046",
                    "authorization": f"Bearer {token}",
                    "Content-Type": "application/json;charset=UTF-8",
                },
                # Kiwoom ka10046 PDF request body only requires stk_cd.
                json={"stk_cd": stk_cd},
            )
            resp.raise_for_status()
            data = resp.json()
            if not validate_kiwoom_response(data, "ka10046", logger):
                return 100.0

        records = data.get("cntr_str_tm", [])
        if not records:
            return 100.0

        values = []
        for rec in records[:5]:
            raw = rec.get("cntr_str", "")
            try:
                values.append(float(str(raw).replace("+", "").replace(",", "")))
            except (ValueError, TypeError):
                continue

        if not values:
            return 100.0

        return sum(values) / len(values)

    except Exception as e:
        logger.debug("[http_utils] fetch_cntr_strength [%s] 실패: %s", stk_cd, e)
        return 100.0


async def fetch_cntr_strength_cached(token: str, stk_cd: str, rdb=None, count: int = 5) -> tuple[float, str]:
    """Return execution strength from Redis/tick cache first, then REST fallback."""
    stk_cd = normalize_stock_code(stk_cd)
    if not stk_cd:
        return 100.0, "invalid"

    if rdb:
        try:
            strength_data = await rdb.lrange(f"ws:strength:{stk_cd}", 0, max(count - 1, 0))
            values = []
            for raw in strength_data:
                try:
                    values.append(float(str(raw).replace("+", "").replace(",", "")))
                except (TypeError, ValueError):
                    continue
            if values:
                return sum(values) / len(values), "redis"
        except Exception as e:
            logger.debug("[http_utils] fetch_cntr_strength_cached redis [%s] failed: %s", stk_cd, e)

        try:
            tick = await rdb.hgetall(f"ws:tick:{stk_cd}")
            raw = tick.get("cntr_str") if tick else None
            if raw not in (None, ""):
                return float(str(raw).replace("+", "").replace(",", "")), "tick"
        except Exception as e:
            logger.debug("[http_utils] fetch_cntr_strength_cached tick [%s] failed: %s", stk_cd, e)

    return await fetch_cntr_strength(token, stk_cd), "rest"


def _safe_number(value, default: float = 0.0) -> float:
    try:
        text = str(value).replace(",", "").replace("+", "").strip()
        if not text or text == "--":
            return default
        if text.startswith("--"):
            text = "-" + text[2:]
        return float(text)
    except (TypeError, ValueError):
        return default


def _as_list(data: dict, *keys: str) -> list:
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


def _today_kst() -> str:
    return datetime.now(_KST).strftime("%Y%m%d")


def _days_ago_kst(days: int) -> str:
    return (datetime.now(_KST) - timedelta(days=max(days, 0))).strftime("%Y%m%d")


async def fetch_daily_cntr_strength(token: str, stk_cd: str, *, days: int = 20) -> tuple[dict, dict]:
    """Fetch ka10047 daily execution-strength trend."""
    stk_cd = normalize_stock_code(stk_cd)
    meta = {"source": "rest", "api_id": "ka10047", "latency_ms": 0, "error": None}
    if not stk_cd:
        meta["error"] = "invalid stk_cd"
        return {}, meta

    url = f"{KIWOOM_BASE_URL}/api/dostk/mrkcond"
    headers = {
        "api-id": "ka10047",
        "authorization": f"Bearer {token}",
        "Content-Type": "application/json;charset=UTF-8",
    }
    t0 = _time.monotonic()
    try:
        resp = await kiwoom_post(url, headers, {"stk_cd": stk_cd}, "ka10047", max_retries=2)
        meta["latency_ms"] = int((_time.monotonic() - t0) * 1000)
        if resp is None:
            meta["error"] = "kiwoom_post returned None"
            return {}, meta
        data = resp.json()
        if not validate_kiwoom_response(data, "ka10047", logger):
            meta["error"] = f"return_code={data.get('return_code')} msg={data.get('return_msg', '')}"
            return {}, meta

        records = _as_list(data, "cntr_str_daly", "output1")[:max(days, 1)]
        strengths = [_safe_number(row.get("cntr_str"), None) for row in records]
        strengths = [value for value in strengths if value is not None]
        if not strengths:
            meta["error"] = "empty cntr_str_daly"
            return {"records": records}, meta

        avg_5_vals = strengths[:5]
        avg_20_vals = strengths[:20]
        summary = {
            "latest": strengths[0],
            "avg_5": sum(avg_5_vals) / len(avg_5_vals),
            "avg_20": sum(avg_20_vals) / len(avg_20_vals),
            "strong_days": sum(1 for value in avg_20_vals if value >= 120.0),
            "records": records,
        }
        return summary, meta
    except Exception as e:
        meta["latency_ms"] = int((_time.monotonic() - t0) * 1000)
        meta["error"] = str(e)
        logger.debug("[http_utils] fetch_daily_cntr_strength [%s] failed: %s", stk_cd, e)
        return {}, meta


async def fetch_same_time_volume_ratio(token: str, stk_cd: str) -> tuple[dict, dict]:
    """Fetch ka10055 today/previous same-time execution-volume ratio."""
    stk_cd = normalize_stock_code(stk_cd)
    meta = {"source": "rest", "api_id": "ka10055", "latency_ms": 0, "error": None}
    if not stk_cd:
        meta["error"] = "invalid stk_cd"
        return {}, meta

    url = f"{KIWOOM_BASE_URL}/api/dostk/stkinfo"
    headers = {
        "api-id": "ka10055",
        "authorization": f"Bearer {token}",
        "Content-Type": "application/json;charset=UTF-8",
    }
    now_hhmmss = datetime.now(_KST).strftime("%H%M%S")

    async def total_qty(tdy_pred: str, cutoff_time: str | None = None) -> tuple[int, str | None]:
        resp = await kiwoom_post(url, headers, {"stk_cd": stk_cd, "tdy_pred": tdy_pred}, "ka10055", max_retries=1)
        if resp is None:
            return 0, None
        data = resp.json()
        if not validate_kiwoom_response(data, "ka10055", logger):
            return 0, None
        total = 0
        latest_time = None
        for row in _as_list(data, "tdy_pred_cntr_qty", "output1"):
            row_time = str(row.get("cntr_tm", ""))
            if tdy_pred == "2" and row_time and row_time > (cutoff_time or now_hhmmss):
                continue
            total += abs(int(_safe_number(row.get("cntr_qty"), 0)))
            if row_time:
                latest_time = max(latest_time or row_time, row_time)
        return total, latest_time

    t0 = _time.monotonic()
    try:
        today_qty, latest_today_time = await total_qty("1")
        prev_qty, _ = await total_qty("2", latest_today_time or now_hhmmss)
        meta["latency_ms"] = int((_time.monotonic() - t0) * 1000)
        ratio = today_qty / prev_qty if prev_qty > 0 else 0.0
        return {
            "today_qty": today_qty,
            "prev_same_time_qty": prev_qty,
            "same_time_volume_ratio": round(ratio, 3),
        }, meta
    except Exception as e:
        meta["latency_ms"] = int((_time.monotonic() - t0) * 1000)
        meta["error"] = str(e)
        logger.debug("[http_utils] fetch_same_time_volume_ratio [%s] failed: %s", stk_cd, e)
        return {}, meta


async def fetch_investor_flow_summary(
    token: str,
    stk_cd: str,
    *,
    days: int = 10,
) -> tuple[dict, dict]:
    """Fetch ka10061 stock investor/institution aggregate flow."""
    stk_cd = normalize_stock_code(stk_cd)
    meta = {"source": "rest", "api_id": "ka10061", "latency_ms": 0, "error": None}
    if not stk_cd:
        meta["error"] = "invalid stk_cd"
        return {}, meta

    url = f"{KIWOOM_BASE_URL}/api/dostk/stkinfo"
    headers = {
        "api-id": "ka10061",
        "authorization": f"Bearer {token}",
        "Content-Type": "application/json;charset=UTF-8",
    }
    body = {
        "stk_cd": stk_cd,
        "strt_dt": _days_ago_kst(days),
        "end_dt": _today_kst(),
        "amt_qty_tp": "1",
        "trde_tp": "0",
        "unit_tp": "1000",
    }
    t0 = _time.monotonic()
    try:
        resp = await kiwoom_post(url, headers, body, "ka10061", max_retries=2)
        meta["latency_ms"] = int((_time.monotonic() - t0) * 1000)
        if resp is None:
            meta["error"] = "kiwoom_post returned None"
            return {}, meta
        data = resp.json()
        if not validate_kiwoom_response(data, "ka10061", logger):
            meta["error"] = f"return_code={data.get('return_code')} msg={data.get('return_msg', '')}"
            return {}, meta

        records = _as_list(data, "stk_invsr_orgn_tot", "output1")
        row = records[0] if records else data
        foreign = _safe_number(row.get("frgnr_invsr"))
        institution = _safe_number(row.get("orgn"))
        individual = _safe_number(row.get("ind_invsr"))
        finance = _safe_number(row.get("fnnc_invt"))
        pension = _safe_number(row.get("penfnd_etc"))
        smart_money = foreign + institution
        summary = {
            "foreign": foreign,
            "institution": institution,
            "individual": individual,
            "finance": finance,
            "pension": pension,
            "smart_money": smart_money,
            "records": records,
        }
        return summary, meta
    except Exception as e:
        meta["latency_ms"] = int((_time.monotonic() - t0) * 1000)
        meta["error"] = str(e)
        logger.debug("[http_utils] fetch_investor_flow_summary [%s] failed: %s", stk_cd, e)
        return {}, meta


async def fetch_investor_flow_daily(
    token: str,
    stk_cd: str,
    *,
    dt: str | None = None,
) -> tuple[list, dict]:
    """Fetch ka10059 stock investor/institution daily rows."""
    stk_cd = normalize_stock_code(stk_cd)
    meta = {"source": "rest", "api_id": "ka10059", "latency_ms": 0, "error": None}
    if not stk_cd:
        meta["error"] = "invalid stk_cd"
        return [], meta

    url = f"{KIWOOM_BASE_URL}/api/dostk/stkinfo"
    headers = {
        "api-id": "ka10059",
        "authorization": f"Bearer {token}",
        "Content-Type": "application/json;charset=UTF-8",
    }
    body = {
        "dt": dt or _today_kst(),
        "stk_cd": stk_cd,
        "amt_qty_tp": "1",
        "trde_tp": "0",
        "unit_tp": "1000",
    }
    t0 = _time.monotonic()
    try:
        resp = await kiwoom_post(url, headers, body, "ka10059", max_retries=2)
        meta["latency_ms"] = int((_time.monotonic() - t0) * 1000)
        if resp is None:
            meta["error"] = "kiwoom_post returned None"
            return [], meta
        data = resp.json()
        if not validate_kiwoom_response(data, "ka10059", logger):
            meta["error"] = f"return_code={data.get('return_code')} msg={data.get('return_msg', '')}"
            return [], meta
        return _as_list(data, "stk_invsr_orgn", "output1"), meta
    except Exception as e:
        meta["latency_ms"] = int((_time.monotonic() - t0) * 1000)
        meta["error"] = str(e)
        logger.debug("[http_utils] fetch_investor_flow_daily [%s] failed: %s", stk_cd, e)
        return [], meta


async def fetch_investor_flow_summary_cached(
    token: str,
    stk_cd: str,
    rdb=None,
    *,
    days: int = 10,
    ttl_sec: int = 1800,
) -> tuple[dict, dict]:
    """Fetch ka10061 through a short Redis cache to avoid repeated per-strategy calls."""
    stk_cd = normalize_stock_code(stk_cd)
    if not rdb or not stk_cd:
        return await fetch_investor_flow_summary(token, stk_cd, days=days)
    cache_key = f"kiwoom:ka10061:flow:{stk_cd}:{days}"
    try:
        cached = await rdb.get(cache_key)
        if cached:
            if isinstance(cached, bytes):
                cached = cached.decode("utf-8")
            payload = json.loads(cached)
            meta = payload.get("meta") or {}
            meta["source"] = "redis"
            return payload.get("summary") or {}, meta
    except Exception as e:
        logger.debug("[http_utils] ka10061 cache read failed [%s]: %s", stk_cd, e)

    summary, meta = await fetch_investor_flow_summary(token, stk_cd, days=days)
    if summary and not meta.get("error"):
        try:
            await rdb.set(cache_key, json.dumps({"summary": summary, "meta": meta}, ensure_ascii=False), ex=ttl_sec)
        except Exception as e:
            logger.debug("[http_utils] ka10061 cache write failed [%s]: %s", stk_cd, e)
    return summary, meta


async def fetch_volume_profile(token: str, stk_cd: str, *, market: str = "000") -> tuple[dict, dict]:
    """Fetch ka10025 volume-price concentration and derive nearby support/resistance."""
    stk_cd = normalize_stock_code(stk_cd)
    meta = {"source": "rest", "api_id": "ka10025", "latency_ms": 0, "error": None, "target_verified": False}
    if not stk_cd:
        meta["error"] = "invalid stk_cd"
        return {}, meta

    url = f"{KIWOOM_BASE_URL}/api/dostk/stkinfo"
    headers = {
        "api-id": "ka10025",
        "authorization": f"Bearer {token}",
        "Content-Type": "application/json;charset=UTF-8",
    }
    body = {
        "mrkt_tp": market,
        "prps_cnctr_rt": "50",
        "cur_prc_entry": "1",
        "prpscnt": "10",
        "cycle_tp": "50",
        "stex_tp": "3",
    }
    t0 = _time.monotonic()
    try:
        resp = await kiwoom_post(url, headers, body, "ka10025", max_retries=2)
        meta["latency_ms"] = int((_time.monotonic() - t0) * 1000)
        if resp is None:
            meta["error"] = "kiwoom_post returned None"
            return {}, meta
        data = resp.json()
        if not validate_kiwoom_response(data, "ka10025", logger):
            err = kiwoom_error_meta(data, "ka10025")
            meta.update(err)
            meta["error"] = f"{err['error_type']} return_code={err.get('return_code')} msg={err.get('return_msg', '')}"
            return {}, meta

        records = _as_list(data, "prps_cnctr", "output1")
        rows_with_code = [
            row for row in records
            if normalize_stock_code(row.get("stk_cd") or row.get("stck_cd") or row.get("code") or "") == stk_cd
        ]
        if rows_with_code:
            records = rows_with_code
            meta["target_verified"] = True
        elif any(row.get("stk_cd") or row.get("stck_cd") or row.get("code") for row in records):
            meta["error"] = "target stk_cd not found in ka10025 response"
            return {"records": records, "target_verified": False}, meta
        else:
            meta["error"] = "ka10025 response missing stk_cd; target not verified"
            return {"records": records, "target_verified": False}, meta

        levels = []
        for row in records:
            start = _safe_number(row.get("pric_strt"), None)
            end = _safe_number(row.get("pric_end"), None)
            ratio = _safe_number(row.get("prps_rt"), 0.0)
            if start is None or end is None:
                continue
            low, high = sorted((start, end))
            levels.append({
                "low": low,
                "high": high,
                "mid": (low + high) / 2.0,
                "ratio": ratio,
                "qty": _safe_number(row.get("prps_qty"), 0.0),
            })
        if not levels:
            meta["error"] = "empty prps_cnctr"
            return {"records": records}, meta

        cur_prc = _safe_number(records[0].get("cur_prc") if records else 0, 0.0)
        support = None
        resistance = None
        if cur_prc > 0:
            below = [level for level in levels if level["high"] < cur_prc]
            above = [level for level in levels if level["low"] > cur_prc]
            if below:
                support = max(below, key=lambda level: (level["ratio"], level["high"]))
            if above:
                resistance = max(above, key=lambda level: (level["ratio"], -level["low"]))
        return {
            "cur_prc": cur_prc,
            "levels": levels,
            "support": support,
            "resistance": resistance,
            "records": records,
            "target_verified": meta["target_verified"],
        }, meta
    except Exception as e:
        meta["latency_ms"] = int((_time.monotonic() - t0) * 1000)
        meta["error"] = str(e)
        logger.debug("[http_utils] fetch_volume_profile [%s] failed: %s", stk_cd, e)
        return {}, meta


async def fetch_program_snapshot(rdb, stk_cd: str) -> dict:
    """Read the latest 0w program-trading snapshot from Redis."""
    stk_cd = normalize_stock_code(stk_cd)
    if not rdb or not stk_cd:
        return {}
    try:
        raw = await rdb.hgetall(f"ws:program:{stk_cd}")
    except Exception as e:
        logger.debug("[http_utils] fetch_program_snapshot redis [%s] failed: %s", stk_cd, e)
        return {}
    if not raw:
        return {}
    return {
        "program_net_buy_amt": _safe_number(raw.get("program_net_buy_amt")),
        "program_net_buy_amt_chg": _safe_number(raw.get("program_net_buy_amt_chg")),
        "program_net_buy_qty": _safe_number(raw.get("program_net_buy_qty")),
        "program_net_buy_qty_chg": _safe_number(raw.get("program_net_buy_qty_chg")),
        "program_buy_amt": _safe_number(raw.get("program_buy_amt")),
        "program_sell_amt": _safe_number(raw.get("program_sell_amt")),
        "program_updated_at_ms": raw.get("updated_at_ms"),
        "program_source": raw.get("source") or "ws_0w",
    }


async def fetch_program_time_trend(token: str, stk_cd: str, *, date: str | None = None) -> tuple[dict, dict]:
    """Fetch ka90008 per-stock intraday program-trading trend."""
    stk_cd = normalize_stock_code(stk_cd)
    meta = {"source": "rest", "api_id": "ka90008", "latency_ms": 0, "error": None}
    if not stk_cd:
        meta["error"] = "invalid stk_cd"
        return {}, meta

    url = f"{KIWOOM_BASE_URL}/api/dostk/mrkcond"
    headers = {
        "api-id": "ka90008",
        "authorization": f"Bearer {token}",
        "Content-Type": "application/json;charset=UTF-8",
    }
    body = {
        "amt_qty_tp": "1",
        "stk_cd": stk_cd,
        "date": date or _today_kst(),
    }
    t0 = _time.monotonic()
    try:
        resp = await kiwoom_post(url, headers, body, "ka90008", max_retries=1)
        meta["latency_ms"] = int((_time.monotonic() - t0) * 1000)
        if resp is None:
            meta["error"] = "kiwoom_post returned None"
            return {}, meta
        data = resp.json()
        if not validate_kiwoom_response(data, "ka90008", logger):
            err = kiwoom_error_meta(data, "ka90008")
            meta.update(err)
            meta["error"] = f"{err['error_type']} return_code={err.get('return_code')} msg={err.get('return_msg', '')}"
            return {}, meta

        records = _as_list(data, "stk_tm_prm_trde_trn", "output1")
        net_values = []
        for row in records[:20]:
            net = _safe_number(
                row.get("prm_netprps_amt")
                or row.get("netprps_amt")
                or row.get("prm_net_buy_amt")
                or row.get("program_net_buy_amt"),
                0.0,
            )
            net_values.append(net)
        latest = net_values[0] if net_values else 0.0
        positive_count = sum(1 for value in net_values if value > 0)
        summary = {
            "latest_net_buy_amt": latest,
            "positive_count": positive_count,
            "negative_count": sum(1 for value in net_values if value < 0),
            "avg_net_buy_amt": sum(net_values) / len(net_values) if net_values else 0.0,
            "records": records,
        }
        return summary, meta
    except Exception as e:
        meta["latency_ms"] = int((_time.monotonic() - t0) * 1000)
        meta["error"] = str(e)
        logger.debug("[http_utils] fetch_program_time_trend [%s] failed: %s", stk_cd, e)
        return {}, meta


def program_drop_reason(snapshot: dict) -> str | None:
    if not snapshot:
        return None
    net_amt = _safe_number(snapshot.get("program_net_buy_amt"))
    net_chg = _safe_number(snapshot.get("program_net_buy_amt_chg"))
    net_qty = _safe_number(snapshot.get("program_net_buy_qty"))
    qty_chg = _safe_number(snapshot.get("program_net_buy_qty_chg"))
    if net_chg < 0 and net_amt <= 0:
        return f"program net-buy amount weakening: chg={net_chg:.0f}, net={net_amt:.0f}"
    if qty_chg < 0 and net_qty <= 0:
        return f"program net-buy quantity weakening: chg={qty_chg:.0f}, net={net_qty:.0f}"
    return None


def apply_volume_profile_rr(signal: dict, profile: dict) -> dict:
    """Adjust public TP/SL fields with ka10025 support/resistance when useful."""
    if not signal or not profile:
        return signal
    try:
        entry = _safe_number(signal.get("entry_price") or signal.get("cur_prc"), 0.0)
        if entry <= 0:
            return signal
        support = profile.get("support") or {}
        resistance = profile.get("resistance") or {}
        changed = False
        if resistance:
            resistance_price = _safe_number(resistance.get("low"), 0.0)
            tp1 = _safe_number(signal.get("tp1_price"), 0.0)
            if resistance_price > entry and (tp1 <= 0 or resistance_price > tp1):
                signal["tp1_price"] = round(resistance_price, 2)
                changed = True
        if support:
            support_price = _safe_number(support.get("low"), 0.0) * 0.98
            sl = _safe_number(signal.get("sl_price"), 0.0)
            if 0 < support_price < entry and (sl <= 0 or support_price > sl):
                signal["sl_price"] = round(support_price, 2)
                changed = True
        if changed:
            tp1 = _safe_number(signal.get("tp1_price"), 0.0)
            sl = _safe_number(signal.get("sl_price"), 0.0)
            if tp1 > entry and 0 < sl < entry:
                signal["rr_ratio"] = round((tp1 - entry) / (entry - sl), 2)
            signal["volume_profile_adjusted"] = True
            signal["volume_profile_support"] = support
            signal["volume_profile_resistance"] = resistance
    except Exception:
        return signal
    return signal


async def fetch_cntr_strength_rest(
    token: str,
    stk_cd: str,
    *,
    count: int = 5,
    timeout: float = 3.0,
) -> tuple[float | None, dict]:
    """
    Redis를 읽지 않고 ka10046 REST API로 직접 체결강도 평균을 조회한다.
    stale Redis 우회 전용 — rdb 파라미터 없음.
    반환: (strength | None, meta)
    meta = {"source": "rest", "api_id": "ka10046",
            "retry_count": int, "latency_ms": int, "error": str | None}
    """
    stk_cd = normalize_stock_code(stk_cd)
    meta: dict = {
        "source": "rest",
        "api_id": "ka10046",
        "retry_count": 0,
        "latency_ms": 0,
        "error": None,
    }
    if not stk_cd:
        meta["error"] = "invalid stk_cd"
        return None, meta

    url = f"{KIWOOM_BASE_URL}/api/dostk/mrkcond"
    headers = {
        "api-id": "ka10046",
        "authorization": f"Bearer {token}",
        "Content-Type": "application/json;charset=UTF-8",
    }
    json_body = {"stk_cd": stk_cd}

    t0 = _time.monotonic()
    try:
        resp = await kiwoom_post(url, headers, json_body, "ka10046", max_retries=2)
        meta["latency_ms"] = int((_time.monotonic() - t0) * 1000)
        if resp is None:
            meta["error"] = "kiwoom_post returned None"
            return None, meta

        data = resp.json()
        if not validate_kiwoom_response(data, "ka10046", logger):
            rc = data.get("return_code", "?")
            msg = data.get("return_msg", "")
            meta["error"] = f"return_code={rc} msg={msg}"
            return None, meta

        # output1 리스트 형식과 cntr_str_tm 필드 형식 모두 지원
        records = data.get("output1") or data.get("cntr_str_tm", [])
        if not records:
            meta["error"] = "empty records"
            return None, meta

        values = []
        for rec in records[:count]:
            raw = rec.get("cntr_str", "")
            try:
                values.append(float(str(raw).replace("+", "").replace(",", "")))
            except (ValueError, TypeError):
                continue

        if not values:
            meta["error"] = "no valid cntr_str values"
            return None, meta

        return sum(values) / len(values), meta

    except Exception as e:
        meta["latency_ms"] = int((_time.monotonic() - t0) * 1000)
        meta["error"] = str(e)
        logger.debug("[http_utils] fetch_cntr_strength_rest [%s] 실패: %s", stk_cd, e)
        return None, meta
