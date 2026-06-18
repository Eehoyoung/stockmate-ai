from __future__ import annotations
"""
http_utils.py
공통 Kiwoom API HTTP 유틸리티 – 전술 파일 간 코드 중복 제거용.
"""

import asyncio
import logging
import os
import time as _time

import httpx
import redis.asyncio as redis_async

from config import KIWOOM_BASE_URL, REDIS_HOST, REDIS_PASSWORD, REDIS_PORT
from utils import safe_float as _sf_global, normalize_stock_code

logger = logging.getLogger(__name__)
_DEFAULT_TIMEOUT = 10.0


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
            return
        deadline = now + max(self._global_wait_ms, 0) / 1000.0
        client = self._redis_client()
        while True:
            try:
                ok = await client.set(self._global_key, "python", nx=True, px=max(self._global_interval_ms, 1))
                if ok:
                    return
            except Exception as exc:
                self._global_disabled_until = _time.monotonic() + 30.0
                logger.warning("[http_utils] global Kiwoom rate limiter unavailable; fail-open for 30s: %s", exc)
                return
            if _time.monotonic() >= deadline:
                logger.warning("[http_utils] global Kiwoom rate limiter wait exceeded %.0fms; fail-open", self._global_wait_ms)
                return
            await asyncio.sleep(0.025)


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
        _log.warning("[%s] Kiwoom return_code=%s msg=%s", api_id, rc, data.get("return_msg", ""))
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
        return ""

    stk_cd = normalize_stock_code(stk_cd)
    if not stk_cd:
        return ""

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
