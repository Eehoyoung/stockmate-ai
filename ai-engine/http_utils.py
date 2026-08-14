from __future__ import annotations
"""
http_utils.py
공통 Kiwoom API HTTP 유틸리티 – 전술 파일 간 코드 중복 제거용.
"""

import asyncio
import json
import logging
import math
import os
import time as _time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import httpx
import redis.asyncio as redis_async

from config import KIWOOM_BASE_URL, REDIS_HOST, REDIS_PASSWORD, REDIS_PORT
from redis_reader import get_hoga_with_status, get_strength_with_status, get_tick_with_status
from utils import safe_float as _sf_global, normalize_stock_code

logger = logging.getLogger(__name__)
_DEFAULT_TIMEOUT = 10.0
_KST = timezone(timedelta(hours=9))
KIWOOM_RATE_LIMIT_CODES = {"1700", "1687"}
KIWOOM_AUTH_ERROR_CODES = {"8005", "8050", "8103"}


class KiwoomReservationUnavailable(RuntimeError):
    """Raised when the cross-process Kiwoom reservation cannot be acquired safely."""


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


# Kiwoom REST "heavy" TR: 차트/페이지네이션/대량조회 성격의 TR. 이 TR들은
# 응답이 크거나(차트) 다중 페이지를 순회하므로(ka10055 등) 더 보수적인 간격을
# 적용한다. 실제 각 TR의 성격은 docs/kiwoom-rest-api/apis/*.md 로 확인했다:
#   ka10025 매물대집중요청(시장 전체 일괄조회), ka10047 체결강도추이일별요청(차트),
#   ka10055 당일전일체결량요청(최대 20페이지 순회 x2), ka10059 종목별투자자기관별요청(차트),
#   ka10061 종목별투자자기관별합계요청(기간조회), ka10064 장중투자자별매매차트요청(차트),
#   ka10080 주식분봉차트조회요청, ka10081 주식일봉차트조회요청,
#   ka90003 프로그램순매수상위50요청(대량조회), ka90008 종목시간별프로그램매매추이요청(차트),
#   ka90009 외국인기관매매상위요청(대량조회).
_DEFAULT_HEAVY_TR_IDS = frozenset({
    "ka10025", "ka10047", "ka10055", "ka10059", "ka10061", "ka10064",
    "ka10080", "ka10081", "ka90003", "ka90008", "ka90009",
})


# ──────────────────────────────────────────────────────────────
# 동시 중복 요청 합치기 (in-flight coalescing)
# ──────────────────────────────────────────────────────────────
#
# 10:00~14:30에는 11~13개 전략이 동시에 스캔하며 상당수가 같은 종목의 같은 TR을
# 각자 호출한다. Redis/메모리 캐시는 "캐시 적중" 이후에만 효과가 있어서, 캐시가
# 비어 있는 첫 조회가 동시에 몰리면(cache stampede) TR별 초당 1건 예산을 그대로
# 중복 소모한다. 여기서 같은 (TR, 인자) 요청 하나만 실제로 나가게 합친다.
_INFLIGHT_REQUESTS: dict[tuple, "asyncio.Task"] = {}


async def coalesce_request(key: tuple, factory):
    """같은 key의 동시 요청을 하나의 실제 호출로 합친다.

    factory: 인자 없는 async 콜러블. 캐시 미스일 때만 호출된다.

    asyncio.shield가 핵심이다. Task를 그냥 await 하면, 대기 중인 호출자가
    취소될 때 그 취소가 안쪽 Task까지 전파되어 같은 데이터를 기다리던 다른
    호출자들의 요청까지 함께 죽는다. 이 저장소는 전략 타임아웃(S8 500s,
    S9 450s 등)으로 취소가 일상적으로 발생하므로 반드시 shield로 끊어야 한다.
    """
    task = _INFLIGHT_REQUESTS.get(key)
    if task is None or task.done():
        task = asyncio.ensure_future(factory())
        _INFLIGHT_REQUESTS[key] = task
        # 생성자가 취소돼도 정리가 누락되지 않도록 Task 완료 시점에 제거한다.
        task.add_done_callback(lambda t, k=key: _INFLIGHT_REQUESTS.pop(k, None))
    return await asyncio.shield(task)


class _KiwoomRateLimiter:
    """asyncio 토큰 버킷 – TR(api-id)별 독립 속도 제한, heavy/light 티어 구분.

    키움증권 공지(2026-06-12): REST는 TR당 초당 5건(모의투자 1건)이 허용되며,
    여러 TR을 동시에 호출해도 TR별로 각각 초당 5건이다. 과거 구현은 이 예산을
    전체 Kiwoom 호출(모든 TR 합산, Java까지 포함)에 단일 버킷으로 적용해서
    서로 무관한 TR끼리 불필요하게 경합했다 — 이 경합이 강화된 예외 raise와
    맞물려 S3/S5/S6/S10/S11 스캔이 반복 실패한 원인이었다(2026-07-26 조사).
    이제 로컬 페이싱과 Redis 교차프로세스 코디네이션 모두 api_id(TR)별로
    독립 관리하여, Java KiwoomRateLimiter와도 TR 단위로만 예산을 공유한다.

    실무 가이드(레포 오너, 2026-08-05 조사): 키움 공식 "초당 5건"은 이론상
    상한이며, 서버 응답 지연·자동 속도조절 탓에 실제로는 안정적으로 채우기
    어렵다. 차트/대량조회/페이지네이션 TR(heavy)은 최소 1.0초 간격,
    그 외 일반 TR(light)도 최소 0.8초 간격을 기본값으로 두고, 실패 시에는
    지수 백오프로 재시도하며 다수 요청은 TR별 FIFO 잠금으로 직렬화한다.
    """

    def __init__(
        self,
        real_rate: float = 1.25,
        real_rate_heavy: float = 1.0,
        mock_rate: float = 1.0,
        heavy_tr_ids: frozenset[str] | None = None,
    ):
        kiwoom_mode = os.getenv("KIWOOM_MODE", "real").strip().lower()
        is_mock = kiwoom_mode == "mock"
        light_default = mock_rate if is_mock else real_rate
        heavy_default = mock_rate if is_mock else real_rate_heavy
        light_rate = float(os.getenv("KIWOOM_REST_RATE_PER_TR", str(light_default)))
        heavy_rate = float(os.getenv("KIWOOM_REST_RATE_HEAVY_TR", str(heavy_default)))

        heavy_ids_env = os.getenv("KIWOOM_HEAVY_TR_IDS")
        if heavy_ids_env is not None:
            self._heavy_ids = frozenset(x.strip() for x in heavy_ids_env.split(",") if x.strip())
        elif heavy_tr_ids is not None:
            self._heavy_ids = frozenset(heavy_tr_ids)
        else:
            self._heavy_ids = _DEFAULT_HEAVY_TR_IDS

        self._light_interval = 1.0 / max(light_rate, 0.001)  # light TR 최소 호출 간격 (초)
        self._heavy_interval = 1.0 / max(heavy_rate, 0.001)  # heavy TR 최소 호출 간격 (초)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._last: dict[str, float] = defaultdict(float)
        self._global_enabled = os.getenv("KIWOOM_GLOBAL_RATE_LIMIT_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
        self._global_interval_ms_light = int(
            os.getenv("KIWOOM_GLOBAL_RATE_LIMIT_INTERVAL_MS", str(int(1000 / light_rate)))
        )
        self._global_interval_ms_heavy = int(
            os.getenv("KIWOOM_GLOBAL_RATE_LIMIT_INTERVAL_MS_HEAVY", str(int(1000 / heavy_rate)))
        )
        self._global_key = os.getenv("KIWOOM_GLOBAL_RATE_LIMIT_KEY", "kiwoom:global_rate_limit:lock")
        # 요율을 낮췄으므로 정상적인 FIFO 대기가 false "deadline exceeded"로
        # 드롭되지 않도록 기본 대기 한도를 5000ms → 8000ms로 상향한다.
        self._global_wait_ms = int(os.getenv("KIWOOM_GLOBAL_RATE_LIMIT_WAIT_MS", "8000"))
        self._unavailable_backoff_ms = int(os.getenv("KIWOOM_GLOBAL_RATE_LIMIT_UNAVAILABLE_BACKOFF_MS", "30000"))
        self._redis = None
        self._global_disabled_until = 0.0

    def _is_heavy(self, api_id: str) -> bool:
        return api_id in self._heavy_ids

    def _local_interval(self, api_id: str) -> float:
        return self._heavy_interval if self._is_heavy(api_id) else self._light_interval

    def _global_interval_ms(self, api_id: str) -> int:
        return self._global_interval_ms_heavy if self._is_heavy(api_id) else self._global_interval_ms_light

    async def acquire(self, api_id: str = "unknown") -> None:
        metric_api = api_id or "unknown"
        started = _time.monotonic()
        await self._metric(metric_api, "requested", 1)
        await self._metric(metric_api, "pending", 1)
        interval = self._local_interval(metric_api)
        async with self._locks[metric_api]:
            now = _time.monotonic()
            wait = interval - (now - self._last[metric_api])
            if wait > 0:
                await asyncio.sleep(wait)
            self._last[metric_api] = _time.monotonic()
        try:
            await self._acquire_global(metric_api)
            await self._metric(metric_api, "granted", 1)
            await self._metric(metric_api, "wait_ms_total", int((_time.monotonic() - started) * 1000))
        finally:
            await self._metric(metric_api, "pending", -1)

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

    async def _acquire_global(self, api_id: str = "unknown") -> None:
        if not self._global_enabled:
            return
        now = _time.monotonic()
        if now < self._global_disabled_until:
            await self._metric(api_id, "dropped.coordinator_unavailable", 1)
            raise KiwoomReservationUnavailable("global limiter unavailable")
        deadline = now + max(self._global_wait_ms, 0) / 1000.0
        client = self._redis_client()
        key = f"{self._global_key}:{api_id}"
        interval_ms = self._global_interval_ms(api_id)
        while True:
            try:
                ok = await client.set(key, "python", nx=True, px=max(interval_ms, 1))
                if ok:
                    return
            except Exception as exc:
                self._global_disabled_until = _time.monotonic() + max(self._unavailable_backoff_ms, 0) / 1000.0
                logger.warning(
                    "[http_utils] global Kiwoom rate limiter unavailable; calls blocked for %.0fms: %s",
                    self._unavailable_backoff_ms,
                    exc,
                )
                await self._metric(api_id, "dropped.coordinator_unavailable", 1)
                raise KiwoomReservationUnavailable("global limiter unavailable") from exc
            if _time.monotonic() >= deadline:
                logger.warning(
                    "[http_utils] global Kiwoom rate limiter(%s) wait exceeded %.0fms; call dropped",
                    api_id, self._global_wait_ms,
                )
                await self._metric(api_id, "dropped.global_deadline", 1)
                raise KiwoomReservationUnavailable("global limiter deadline exceeded")
            await asyncio.sleep(0.025)

    async def _metric(self, api_id: str, field: str, delta: int) -> None:
        try:
            client = self._redis_client()
            await client.hincrby("status:kiwoom_rest_reservations", f"python.{api_id}.{field}", delta)
            await client.expire("status:kiwoom_rest_reservations", 7 * 86400)
        except Exception:
            pass


# 전역 싱글턴 – 모든 Kiwoom API 호출에서 공유 (TR별 독립 예산)
kiwoom_rate_limiter = _KiwoomRateLimiter()


def kiwoom_client(timeout: float = _DEFAULT_TIMEOUT) -> httpx.AsyncClient:
    """Rate Limiter가 내장된 Kiwoom API 전용 httpx AsyncClient 팩토리.

    Usage:
        async with kiwoom_client() as client:
            resp = await client.post(url, headers=..., json=...)
    """
    async def _rate_hook(request: httpx.Request) -> None:
        await kiwoom_rate_limiter.acquire(request.headers.get("api-id", "unknown"))

    return httpx.AsyncClient(
        timeout=timeout,
        event_hooks={"request": [_rate_hook]},
    )


# 일반(비-429) HTTP 오류 재시도 지연 – 실무 가이드에 따라 0.5s → 1s → 2s 지수
# 백오프를 적용한다. 429(진짜 rate-limit 비즈니스 에러)는 별도로 backoff_base
# 기반의 훨씬 긴 지수 백오프를 그대로 사용한다(아래 분기 참고).
_GENERIC_RETRY_BACKOFF_SEC = (0.5, 1.0, 2.0, 4.0)


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
                wait = _GENERIC_RETRY_BACKOFF_SEC[min(attempt, len(_GENERIC_RETRY_BACKOFF_SEC) - 1)]
                logger.warning(
                    "[http_utils] %s HTTP 오류 %s – %.1fs 대기 후 재시도 (attempt %d/%d)",
                    api_id, e.response.status_code, wait, attempt + 1, max_retries + 1,
                )
                await asyncio.sleep(wait)
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
            hoga_result = await get_hoga_with_status(rdb, stk_cd)
            ws_hoga = hoga_result["data"]
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
            strength_result = await get_strength_with_status(rdb, stk_cd, count=count)
            if strength_result.get("data") is not None:
                return float(strength_result["data"]), str(strength_result.get("source") or "redis")
        except Exception as e:
            logger.debug("[http_utils] fetch_cntr_strength_cached redis [%s] failed: %s", stk_cd, e)

        try:
            tick_result = await get_tick_with_status(rdb, stk_cd)
            tick = tick_result["data"]
            raw = tick.get("cntr_str") if tick else None
            if raw not in (None, ""):
                return float(str(raw).replace("+", "").replace(",", "")), "tick"
        except Exception as e:
            logger.debug("[http_utils] fetch_cntr_strength_cached tick [%s] failed: %s", stk_cd, e)

    # Redis/tick 캐시가 모두 비면 REST(ka10001)로 떨어진다. 14곳에서 호출되며
    # 여러 전략이 같은 종목을 동시에 평가하므로 여기서 중복 호출을 합친다.
    strength = await coalesce_request(
        ("ka10001:cntr_strength", stk_cd),
        lambda: fetch_cntr_strength(token, stk_cd),
    )
    return strength, "rest"


def _safe_number(value, default: float | None = 0.0) -> float | None:
    try:
        text = str(value).replace(",", "").replace("+", "").strip()
        if not text or text == "--":
            return default
        if text.startswith("--"):
            text = "-" + text[2:]
        return float(text)
    except (TypeError, ValueError):
        return default


def resolve_effective_volume_ratio(
    daily_partial_ratio: float,
    same_time_summary: dict | None,
    same_time_meta: dict | None,
) -> tuple[float, str]:
    """Prefer a valid ka10055 same-time ratio over a partial daily-bar ratio.

    A paged ka10055 caller may explicitly mark a partial response with
    ``complete=False``.  Such a response, an API error, or a malformed ratio
    must not replace the existing daily-bar fallback.
    """
    fallback = _safe_number(daily_partial_ratio, 0.0)
    summary = same_time_summary if isinstance(same_time_summary, dict) else {}
    meta = same_time_meta if isinstance(same_time_meta, dict) else {}
    if meta.get("complete") is False or meta.get("error"):
        return fallback, "daily_partial"
    if "same_time_volume_ratio" not in summary:
        return fallback, "daily_partial"

    ratio = _safe_number(summary.get("same_time_volume_ratio"), None)
    if ratio is None or not math.isfinite(ratio) or ratio < 0:
        return fallback, "daily_partial"
    return ratio, "ka10055_same_time"


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

    async def total_qty(
        tdy_pred: str,
        cutoff_time: str | None = None,
    ) -> tuple[int, str | None, bool, int]:
        total = 0
        latest_time = None
        request_headers = dict(headers)
        seen_next_keys: set[str] = set()
        page_count = 0
        max_pages = 20

        while page_count < max_pages:
            resp = await kiwoom_post(
                url,
                request_headers,
                {"stk_cd": stk_cd, "tdy_pred": tdy_pred},
                "ka10055",
                max_retries=1,
            )
            if resp is None:
                return total, latest_time, False, page_count
            data = resp.json()
            if not validate_kiwoom_response(data, "ka10055", logger):
                return total, latest_time, False, page_count

            page_count += 1
            for row in _as_list(data, "tdy_pred_cntr_qty", "output1"):
                row_time = str(row.get("cntr_tm", ""))
                if tdy_pred == "2" and row_time and row_time > (cutoff_time or now_hhmmss):
                    continue
                total += abs(int(_safe_number(row.get("cntr_qty"), 0)))
                if row_time:
                    latest_time = max(latest_time or row_time, row_time)

            cont_yn = str(resp.headers.get("cont-yn", "N")).upper()
            next_key = str(resp.headers.get("next-key", "")).strip()
            if cont_yn != "Y":
                return total, latest_time, True, page_count
            if not next_key or next_key in seen_next_keys:
                return total, latest_time, False, page_count
            seen_next_keys.add(next_key)
            request_headers["cont-yn"] = "Y"
            request_headers["next-key"] = next_key

        return total, latest_time, False, page_count

    t0 = _time.monotonic()
    try:
        today_qty, latest_today_time, today_complete, today_pages = await total_qty("1")
        prev_qty, _, prev_complete, prev_pages = await total_qty("2", latest_today_time or now_hhmmss)
        meta["latency_ms"] = int((_time.monotonic() - t0) * 1000)
        meta["complete"] = today_complete and prev_complete
        meta["today_pages"] = today_pages
        meta["prev_pages"] = prev_pages
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


_KA10055_SHARED_CACHE_PREFIX = "kiwoom:ka10055:same_time"


async def get_same_time_volume_ratio_cache(rdb, stk_cd: str) -> dict | None:
    """Read the shared cross-strategy ka10055 same-time-ratio cache.

    S3/S7/S8/S9 스캔 시간대가 09:30~14:30 구간에서 겹치며, 같은 종목을 캐싱
    없이 반복 조회해 ka10055 TR 예산을 놓고 경합했다(2026-08-05 조사). 이
    캐시는 여러 전략이 하나의 Redis 키를 공유하도록 해서 같은 종목에 대한
    중복 호출을 제거한다. 값 형식이 예상과 다르면(다른 캐시 스킴 등) 조용히
    캐시 미스로 취급한다.
    """
    stk_cd = normalize_stock_code(stk_cd)
    if not rdb or not stk_cd:
        return None
    try:
        cached = await rdb.get(f"{_KA10055_SHARED_CACHE_PREFIX}:{stk_cd}")
        if not cached:
            return None
        if isinstance(cached, bytes):
            cached = cached.decode("utf-8")
        payload = json.loads(cached)
        if not isinstance(payload, dict):
            return None
        summary = payload.get("summary")
        return summary if isinstance(summary, dict) else None
    except Exception as e:
        logger.debug("[http_utils] ka10055 shared cache read failed [%s]: %s", stk_cd, e)
        return None


async def set_same_time_volume_ratio_cache(
    rdb,
    stk_cd: str,
    summary: dict,
    *,
    meta: dict | None = None,
    ttl_sec: int = 60,
) -> None:
    """Populate the shared cross-strategy ka10055 cache (see get_same_time_volume_ratio_cache)."""
    stk_cd = normalize_stock_code(stk_cd)
    if not rdb or not stk_cd or not summary:
        return
    try:
        payload = {
            "summary": summary,
            "meta": meta or {"source": "rest", "api_id": "ka10055"},
        }
        await rdb.set(
            f"{_KA10055_SHARED_CACHE_PREFIX}:{stk_cd}",
            json.dumps(payload, ensure_ascii=False),
            ex=max(ttl_sec, 1),
        )
    except Exception as e:
        logger.debug("[http_utils] ka10055 shared cache write failed [%s]: %s", stk_cd, e)


async def fetch_same_time_volume_ratio_cached(
    token: str,
    stk_cd: str,
    rdb=None,
    *,
    ttl_sec: int = 60,
) -> tuple[dict, dict]:
    """ka10055(당일전일체결량) 조회를 공유 Redis 캐시로 감싼 버전.

    S7/S8/S9가 이 함수를 사용한다. TTL 기본값(60초)은
    STRATEGY_SCAN_INTERVAL_SEC 기본 스캔 주기(60초)에 맞춘 것으로, 같은
    스캔 사이클 내에서는 캐시를 재사용하고 다음 사이클에는 새로 조회한다.
    ``meta.complete`` 가 False(페이지네이션 미완료)이거나 에러가 있으면
    캐시에 쓰지 않는다 — 부분 데이터가 다른 전략에 완전한 값처럼 재사용되는
    것을 막기 위함이다.
    """
    stk_cd = normalize_stock_code(stk_cd)
    if not stk_cd:
        return {}, {"source": "rest", "api_id": "ka10055", "error": "invalid stk_cd"}

    if rdb:
        cached_summary = await get_same_time_volume_ratio_cache(rdb, stk_cd)
        if cached_summary is not None:
            return cached_summary, {"source": "redis", "api_id": "ka10055", "complete": True}

    # ka10055는 heavy TR(최대 20페이지 x2 순회)이라 중복 호출 비용이 가장 크다.
    # S7/S8/S9가 같은 사이클에 같은 종목을 평가하면 캐시 적재 전까지 각자
    # 전체 페이지네이션을 반복하므로, 실제 호출을 하나로 합친다.
    summary, meta = await coalesce_request(
        ("ka10055", stk_cd),
        lambda: fetch_same_time_volume_ratio(token, stk_cd),
    )
    if rdb and summary and not meta.get("error") and meta.get("complete"):
        await set_same_time_volume_ratio_cache(rdb, stk_cd, summary, meta=meta, ttl_sec=ttl_sec)
    return summary, meta


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


def summarize_intraday_investor_flow(
    records: list[dict],
    *,
    sample_limit: int = 5,
) -> dict:
    """Derive live ka10064 flow slope and recent reversal features."""
    recent = sorted(
        (row for row in (records or []) if row.get("tm")),
        key=lambda row: str(row.get("tm", "")),
        reverse=True,
    )[:max(1, int(sample_limit))]
    if not recent:
        return {}

    foreign = [float(_safe_number(row.get("frgnr_invsr"), 0.0)) for row in recent]
    institution = [float(_safe_number(row.get("orgn"), 0.0)) for row in recent]
    combined = [f + i for f, i in zip(foreign, institution)]

    def _slope(values: list[float]) -> float | None:
        if len(values) < 2:
            return None
        return round((values[0] - values[-1]) / (len(values) - 1), 3)

    latest_delta = round(combined[0] - combined[1], 3) if len(combined) >= 2 else None
    previous_delta = round(combined[1] - combined[2], 3) if len(combined) >= 3 else None
    reversal_direction = "none"
    if latest_delta is not None and previous_delta is not None:
        if latest_delta > 0 and previous_delta <= 0:
            reversal_direction = "positive"
        elif latest_delta < 0 and previous_delta >= 0:
            reversal_direction = "negative"

    return {
        "api_id": "ka10064",
        "observed_at": str(recent[0].get("tm", "")),
        "sample_count": len(recent),
        "latest_foreign": round(foreign[0], 3),
        "latest_institution": round(institution[0], 3),
        "latest_combined": round(combined[0], 3),
        "foreign_slope": _slope(foreign),
        "institution_slope": _slope(institution),
        "combined_slope": _slope(combined),
        "latest_delta": latest_delta,
        "previous_delta": previous_delta,
        "recent_reversal": reversal_direction != "none",
        "recent_reversal_direction": reversal_direction,
    }


async def fetch_intraday_investor_flow(
    token: str,
    stk_cd: str,
    *,
    market: str = "000",
    sample_limit: int = 5,
) -> tuple[dict, dict]:
    """Fetch ka10064 and return live intraday investor-flow features."""
    stk_cd = normalize_stock_code(stk_cd)
    meta = {"source": "rest", "api_id": "ka10064", "latency_ms": 0, "error": None}
    if not stk_cd:
        meta["error"] = "invalid stk_cd"
        return {}, meta

    headers = {
        "api-id": "ka10064",
        "authorization": f"Bearer {token}",
        "Content-Type": "application/json;charset=UTF-8",
    }
    body = {
        "mrkt_tp": str(market or "000"),
        "amt_qty_tp": "1",
        "trde_tp": "0",
        "stk_cd": stk_cd,
    }
    t0 = _time.monotonic()
    try:
        resp = await kiwoom_post(
            f"{KIWOOM_BASE_URL}/api/dostk/chart",
            headers,
            body,
            "ka10064",
            max_retries=1,
        )
        meta["latency_ms"] = int((_time.monotonic() - t0) * 1000)
        if resp is None:
            meta["error"] = "kiwoom_post returned None"
            return {}, meta
        data = resp.json()
        if not validate_kiwoom_response(data, "ka10064", logger):
            meta["error"] = f"return_code={data.get('return_code')} msg={data.get('return_msg', '')}"
            return {}, meta
        summary = summarize_intraday_investor_flow(
            _as_list(data, "opmr_invsr_trde_chart", "output1"),
            sample_limit=sample_limit,
        )
        if not summary:
            meta["error"] = "empty records"
        return summary, meta
    except Exception as e:
        meta["latency_ms"] = int((_time.monotonic() - t0) * 1000)
        meta["error"] = str(e)
        logger.debug("[http_utils] fetch_intraday_investor_flow [%s] failed: %s", stk_cd, e)
        return {}, meta


async def fetch_intraday_investor_flow_cached(
    token: str,
    stk_cd: str,
    rdb=None,
    *,
    market: str = "000",
    sample_limit: int = 5,
    ttl_sec: int = 60,
) -> tuple[dict, dict]:
    """Short cache shared by S3/S11 so ka10064 remains a bounded enrichment."""
    stk_cd = normalize_stock_code(stk_cd)
    if not rdb or not stk_cd:
        return await fetch_intraday_investor_flow(
            token, stk_cd, market=market, sample_limit=sample_limit,
        )
    cache_key = f"kiwoom:ka10064:flow:{market}:{stk_cd}:{sample_limit}"
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
        logger.debug("[http_utils] ka10064 cache read failed [%s]: %s", stk_cd, e)

    summary, meta = await fetch_intraday_investor_flow(
        token, stk_cd, market=market, sample_limit=sample_limit,
    )
    if summary and not meta.get("error"):
        try:
            await rdb.set(
                cache_key,
                json.dumps({"summary": summary, "meta": meta}, ensure_ascii=False),
                ex=ttl_sec,
            )
        except Exception as e:
            logger.debug("[http_utils] ka10064 cache write failed [%s]: %s", stk_cd, e)
    return summary, meta


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

    # ka10061도 heavy TR(기간 조회)이며 6곳에서 호출된다. Redis TTL이 30분으로
    # 길어 정상 상황에선 적중률이 높지만, TTL 만료 직후 여러 전략이 동시에
    # 몰리면 같은 종목을 중복 조회하므로 실제 호출을 합친다.
    summary, meta = await coalesce_request(
        ("ka10061", stk_cd, days),
        lambda: fetch_investor_flow_summary(token, stk_cd, days=days),
    )
    if summary and not meta.get("error"):
        try:
            await rdb.set(cache_key, json.dumps({"summary": summary, "meta": meta}, ensure_ascii=False), ex=ttl_sec)
        except Exception as e:
            logger.debug("[http_utils] ka10061 cache write failed [%s]: %s", stk_cd, e)
    return summary, meta


_VOLUME_PROFILE_MARKET_CACHE: dict[str, tuple[list[dict], float]] = {}
_VOLUME_PROFILE_MARKET_LOCKS: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


async def _fetch_volume_profile_market_records(
    token: str,
    market: str,
) -> tuple[list[dict], dict]:
    """Fetch the market-wide ka10025 response once and share it across stocks."""
    market = str(market or "000")
    now = _time.monotonic()
    cached = _VOLUME_PROFILE_MARKET_CACHE.get(market)
    if cached and now < cached[1]:
        return cached[0], {"source": "memory", "complete": True}

    async with _VOLUME_PROFILE_MARKET_LOCKS[market]:
        now = _time.monotonic()
        cached = _VOLUME_PROFILE_MARKET_CACHE.get(market)
        if cached and now < cached[1]:
            return cached[0], {"source": "memory", "complete": True}

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
        resp = await kiwoom_post(url, headers, body, "ka10025", max_retries=2)
        if resp is None:
            return [], {"source": "rest", "complete": False, "error": "kiwoom_post returned None"}
        data = resp.json()
        if not validate_kiwoom_response(data, "ka10025", logger):
            err = kiwoom_error_meta(data, "ka10025")
            return [], {
                "source": "rest",
                "complete": False,
                "error": f"{err['error_type']} return_code={err.get('return_code')} msg={err.get('return_msg', '')}",
                **err,
            }
        records = _as_list(data, "prps_cnctr", "output1")
        ttl_sec = max(1, int(os.getenv("KIWOOM_KA10025_MARKET_CACHE_TTL_SEC", "30")))
        _VOLUME_PROFILE_MARKET_CACHE[market] = (records, _time.monotonic() + ttl_sec)
        return records, {"source": "rest", "complete": True}


async def fetch_volume_profile(token: str, stk_cd: str, *, market: str = "000") -> tuple[dict, dict]:
    """Fetch ka10025 volume-price concentration and derive nearby support/resistance."""
    stk_cd = normalize_stock_code(stk_cd)
    meta = {"source": "rest", "api_id": "ka10025", "latency_ms": 0, "error": None, "target_verified": False}
    if not stk_cd:
        meta["error"] = "invalid stk_cd"
        return {}, meta

    t0 = _time.monotonic()
    try:
        records, fetch_meta = await _fetch_volume_profile_market_records(token, market)
        meta["latency_ms"] = int((_time.monotonic() - t0) * 1000)
        meta.update(fetch_meta)
        if fetch_meta.get("error"):
            return {}, meta
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

        records = _as_list(
            data,
            "stk_tm_prm_trde_trnsn",  # ka90008 official response key
            "stk_tm_prm_trde_trn",    # backward-compatible legacy typo
            "output1",
        )
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
