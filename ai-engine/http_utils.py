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
                json={"stk_cd": stk_cd},
            )
            resp.raise_for_status()
            data = resp.json()

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
