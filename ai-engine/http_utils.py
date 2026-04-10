"""
http_utils.py
공통 Kiwoom API HTTP 유틸리티 – 전술 파일 간 코드 중복 제거용.
"""

import asyncio
import logging
import os
import time as _time

import httpx

logger = logging.getLogger(__name__)
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")
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

    async def acquire(self) -> None:
        async with self._lock:
            now = _time.monotonic()
            wait = self._interval - (now - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = _time.monotonic()


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
            stk_nm = str(items[0].get("stk_nm", "")).strip() if items else ""
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
    def _sf(v) -> float:
        try:
            return float(str(v).replace(",", "").replace("+", ""))
        except (TypeError, ValueError):
            return 0.0

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


async def fetch_cntr_strength(token: str, stk_cd: str) -> float:
    """
    체결강도 조회 (ka10046 체결강도추이시간별요청).
    최근 5개 cntr_str 평균을 반환. 데이터 없거나 오류 시 100.0 반환.
    """
    try:
        async with kiwoom_client() as client:
            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/mrkcond",
                headers={
                    "api-id": "ka10046",
                    "authorization": f"Bearer {token}",
                    "Content-Type": "application/json;charset=UTF-8",
                },
                json={"stk_cd": stk_cd, "stex_tp": "3"},
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
