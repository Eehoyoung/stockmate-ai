"""
http_utils.py
공통 Kiwoom API HTTP 유틸리티 – 전술 파일 간 코드 중복 제거용.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")
_DEFAULT_TIMEOUT = 10.0


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
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
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


async def fetch_cntr_strength(token: str, stk_cd: str) -> float:
    """
    체결강도 조회 (ka10046 체결강도추이시간별요청).
    최근 5개 cntr_str 평균을 반환. 데이터 없거나 오류 시 100.0 반환.
    """
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/mrkcond",
                headers={
                    "api-id": "ka10046",
                    "authorization": f"Bearer {token}",
                    "Content-Type": "application/json;charset=UTF-8",
                },
                json={"stk_cd": stk_cd, "stex_tp": "1"},
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
