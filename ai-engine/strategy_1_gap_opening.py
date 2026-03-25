"""전술 1: 갭상승 + 체결강도 시초가 매수
타이밍: 8:30 ~ 9:05
진입 조건 (AND):

전일 종가 대비 예상 시초가 갭상승률 ≥ 3% (0H 예상체결)
체결강도 ≥ 130% 확인 (ka10046)
갭상승 당일 전일 거래량 대비 호가잔량 매수 우위 ≥ 1.5배 (0D)
전일 일봉 하락폭 ≤ 3% (갭메우기 제거) OR 신고가 돌파 종목 우선"""

import asyncio
import httpx
import os
import logging
from datetime import datetime

# 키움 REST API 초당 약 5회 제한 → 루프 내 0.25s 대기
_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))

logger = logging.getLogger(__name__)

# NOTE: Python 전술 스캐너 경로 (ENABLE_STRATEGY_SCANNER=true 시 활성화).
# 메인 전술 실행은 api-orchestrator/StrategyService.java에서 이루어집니다.
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")


async def get_expected_execution(rdb, stk_cd: str) -> dict:
    """0H 주식예상체결 WebSocket 데이터 → Redis에서 조회 (비동기)"""
    try:
        return await rdb.hgetall(f"ws:expected:{stk_cd}")
    except Exception:
        return {}


async def fetch_cntr_strength(token: str, stk_cd: str) -> float:
    """ka10046 체결강도추이시간별 → 최근 5분 평균 체결강도"""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/mrkcond",
            headers={"api-id": "ka10046", "authorization": f"Bearer {token}",
                     "Content-Type": "application/json;charset=UTF-8"},
            json={"stk_cd": stk_cd}
        )
        data = resp.json()
        strengths = [float(x.get("cntr_str", 100))
                     for x in data.get("cntr_str_tm", [])[:5]]
        return sum(strengths) / len(strengths) if strengths else 100.0

async def fetch_gap_candidates(token: str) -> list:
    """ka10029 예상체결등락률상위 호출 → 갭 3~15% 후보 반환"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/rkinfo",
                headers={"api-id": "ka10029", "authorization": f"Bearer {token}",
                         "Content-Type": "application/json;charset=UTF-8"},
                json={"mrkt_tp": "000", "sort_tp": "1", "trde_qty_cnd": "10",
                      "stk_cnd": "1", "crd_cnd": "0", "pric_cnd": "8", "stex_tp": "1"},
            )
            items = resp.json().get("exp_cntr_flu_rt_upper", [])
            result = []
            for item in items:
                try:
                    flu_rt = float(str(item.get("flu_rt", "0")).replace("+", "").replace(",", ""))
                    if 3.0 <= flu_rt <= 15.0:
                        result.append(item.get("stk_cd"))
                except Exception:
                    pass
            return result
    except Exception as e:
        logger.warning("[S1] ka10029 호출 실패: %s", e)
        return []


async def scan_gap_opening(token: str, candidates: list, rdb=None) -> list:
    # ka10029 로 갭 후보 먼저 조회
    gap_candidates = await fetch_gap_candidates(token)
    effective = [c for c in candidates if c in gap_candidates] if gap_candidates else candidates
    results = []

    for stk_cd in effective:
        exp = await get_expected_execution(rdb, stk_cd) if rdb else {}
        if not exp:
            continue

        prev_close = float(exp.get("pred_pre_pric", 0))
        exp_price = float(exp.get("exp_cntr_pric", 0))
        if prev_close <= 0 or exp_price <= 0:
            continue

        gap_pct = (exp_price - prev_close) / prev_close * 100

        if gap_pct < 3.0:  # 갭 3% 미만 제외
            continue

        await asyncio.sleep(_API_INTERVAL)   # Rate limit: 초당 5회 제한
        strength = await fetch_cntr_strength(token, stk_cd)

        if strength < 130:  # 체결강도 130% 미만 제외
            continue

        score = gap_pct * 0.5 + (strength - 100) * 0.5
        results.append({
            "stk_cd": stk_cd,
            "cur_prc": round(exp_price),   # 예상체결가 = 시초가 진입가
            "strategy": "S1_GAP_OPEN",
            "gap_pct": round(gap_pct, 2),
            "cntr_strength": round(strength, 1),
            "score": round(score, 2),
            "entry_type": "시초가_시장가",
            "target_pct": 4.0,
            "stop_pct": -2.0,
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]
