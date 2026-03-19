"""
전술 4: 장대양봉 + 거래량 급증 추격매수
타이밍: 장중 상시 (10:00~14:30 집중)
진입 조건:

5분봉 (ka10080) 현재봉: 양봉 몸통 ≥ 3% (고가-저가 대비 몸통 비율 70% 이상)
직전 봉 대비 거래량 ≥ 5배 이상
0B 실시간체결: 체결강도 3분 평균 ≥ 140%
당일 고가 신고가 또는 전고점 돌파 (20일 고가 기준)
상위 이탈원 없음 (ka10053 당일상위이탈원 체크)
"""
from idlelib.multicall import r
from statistics import mean

import httpx
import os

KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL")

async def fetch_minute_chart(token: str, stk_cd: str, scope: int = 5) -> list:
    """ka10080 주식분봉차트 조회"""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/chart",
            headers={"api-id": "ka10080", "authorization": f"Bearer {token}",
                     "Content-Type": "application/json;charset=UTF-8"},
            json={"stk_cd": stk_cd, "tic_scope": str(scope), "upd_stkpc_tp": "1"}
        )
        return resp.json().get("stk_min_pole_chart_qry", [])

async def check_big_candle(token: str, stk_cd: str) -> dict | None:
    candles = await fetch_minute_chart(token, stk_cd, 5)
    if len(candles) < 20:
        return None

    cur = candles[0]
    o = float(cur.get("open_pric", 0))
    h = float(cur.get("high_pric", 0))
    l = float(cur.get("low_pric", 0))
    c = float(cur.get("cur_prc", 0))
    vol = int(cur.get("trde_qty", 0))

    if o <= 0 or h <= l:
        return None

    # 양봉 여부
    if c <= o:
        return None

    # 몸통 비율 (캔들 범위 대비 몸통)
    candle_range = h - l
    body = c - o
    body_ratio = body / candle_range if candle_range > 0 else 0

    # 상승폭 (시가 대비 현재가)
    gain_pct = (c - o) / o * 100

    if body_ratio < 0.7 or gain_pct < 3.0:
        return None

    # 직전 봉 대비 거래량 5배
    prev_vols = [int(x.get("trde_qty", 0)) for x in candles[1:6]]
    avg_prev_vol = mean(prev_vols) if prev_vols else 0
    vol_ratio = vol / avg_prev_vol if avg_prev_vol > 0 else 0

    if vol_ratio < 5.0:
        return None

    # 20일 고가 돌파 여부
    highs_20d = [float(x.get("high_pric", 0)) for x in candles[1:96]]  # 5분봉 96개=8시간
    max_20d = max(highs_20d) if highs_20d else 0
    is_new_high = h >= max_20d

    # 체결강도 확인 (Redis 캐시)
    strength_data = r.lrange(f"ws:strength:{stk_cd}", 0, 2)
    avg_strength = mean([float(s) for s in strength_data]) if strength_data else 100

    if avg_strength < 140:
        return None

    return {
        "stk_cd": stk_cd,
        "strategy": "S4_BIG_CANDLE",
        "gain_pct": round(gain_pct, 2),
        "body_ratio": round(body_ratio, 2),
        "vol_ratio": round(vol_ratio, 1),
        "cntr_strength": round(avg_strength, 1),
        "is_new_high": is_new_high,
        "entry_type": "추격_시장가",
        "target_pct": 4.0,
        "stop_pct": -2.5,   # 추격매수는 손절 약간 넉넉히
    }
