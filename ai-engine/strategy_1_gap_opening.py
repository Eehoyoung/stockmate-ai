"""전술 1: 갭상승 + 체결강도 시초가 매수
타이밍: 8:30 ~ 9:05
진입 조건 (AND):

전일 종가 대비 예상 시초가 갭상승률 ≥ 3% (0H 예상체결)
체결강도 ≥ 130% 확인 (ka10046)
갭상승 당일 전일 거래량 대비 호가잔량 매수 우위 ≥ 1.5배 (0D)
전일 일봉 하락폭 ≤ 3% (갭메우기 제거) OR 신고가 돌파 종목 우선"""

import asyncio, httpx, json, redis
from datetime import datetime
import os

KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL")

r = redis.Redis(host='localhost', decode_responses=True)

async def get_expected_execution(token: str, stk_cd: str) -> dict:
    """0H 주식예상체결 WebSocket 데이터 → Redis에서 조회"""
    cached = r.hgetall(f"ws:expected:{stk_cd}")
    return cached  # Java WebSocket consumer가 미리 저장

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

async def scan_gap_opening(token: str, candidates: list) -> list:
    results = []
    now = datetime.now()

    for stk_cd in candidates:
        exp = await get_expected_execution(token, stk_cd)
        if not exp:
            continue

        prev_close = float(exp.get("pred_pre_pric", 0))
        exp_price = float(exp.get("exp_cntr_pric", 0))
        if prev_close <= 0 or exp_price <= 0:
            continue

        gap_pct = (exp_price - prev_close) / prev_close * 100

        if gap_pct < 3.0:  # 갭 3% 미만 제외
            continue

        strength = await fetch_cntr_strength(token, stk_cd)

        if strength < 130:  # 체결강도 130% 미만 제외
            continue

        score = gap_pct * 0.5 + (strength - 100) * 0.5
        results.append({
            "stk_cd": stk_cd,
            "strategy": "S1_GAP_OPEN",
            "gap_pct": round(gap_pct, 2),
            "cntr_strength": round(strength, 1),
            "score": round(score, 2),
            "entry_type": "시초가_시장가",
            "target_pct": 4.0,
            "stop_pct": -2.0,
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]
