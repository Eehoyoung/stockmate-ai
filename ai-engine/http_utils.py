"""
http_utils.py
공통 Kiwoom API HTTP 유틸리티 – 전술 파일 간 코드 중복 제거용.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://mockapi.kiwoom.com")
_DEFAULT_TIMEOUT = 10.0


async def fetch_cntr_strength(token: str, stk_cd: str) -> float:
    """
    체결강도 조회 (ka10003 체결정보요청).
    종목코드(stk_cd)를 입력받아 최근 체결정보의 cntr_str 반환.
    """
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/stkinfo",
                headers={
                    "api-id": "ka10003",
                    "authorization": f"Bearer {token}",
                    "Content-Type": "application/json;charset=UTF-8",
                },
                json={"stk_cd": stk_cd},
            )
            resp.raise_for_status()
            data = resp.json()

        cntr_infr = data.get("cntr_infr", [])
        if not cntr_infr:
            return 0.0

        latest = cntr_infr[0]
        strength = latest.get("cntr_str", "0")
        return float(strength)
    except (ValueError, TypeError):
        return 0.0
    except Exception as e:
        logger.debug("[http_utils] fetch_cntr_strength [%s] 실패: %s", stk_cd, e)
        return 0.0
