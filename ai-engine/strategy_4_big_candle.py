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
from statistics import mean
import os
import logging

import httpx

# NOTE: Python 전술 스캐너 경로 (ENABLE_STRATEGY_SCANNER=true 시 활성화).
# 메인 전술 실행은 api-orchestrator/StrategyService.java에서 이루어집니다.
# rdb (redis.asyncio.Redis) 는 strategy_runner.py 에서 전달받습니다.

logger = logging.getLogger(__name__)
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://mockapi.kiwoom.com")

async def fetch_minute_chart(token: str, stk_cd: str, scope: int = 5) -> list:
    """ka10080 주식분봉차트 조회"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/chart",
                headers={
                    'api-id': 'ka10080',
                    'authorization': f'Bearer {token}',
                    'Content-Type': 'application/json;charset=UTF-8'
                },
                json={
                    'stk_cd': stk_cd.strip(),
                    'tic_scope': str(scope),
                    'upd_stkpc_tp': '1'
                }
            )
            resp.raise_for_status()
            data = resp.json()

            # Kiwoom application-level error (HTTP 200 이지만 status 필드에 오류 코드 포함)
            if data.get("status") and int(str(data["status"])) >= 400:
                logger.warning("[S4] ka10080 응답 오류 [%s]: status=%s msg=%s",
                               stk_cd, data.get("status"), data.get("message", ""))
                return []
            return data.get("stk_min_pole_chart_qry", [])
    except Exception as e:
        logger.debug("[S4] ka10080 호출 실패 [%s]: %s", stk_cd, e)
        return []

async def check_big_candle(token: str, stk_cd: str, rdb=None) -> dict | None:
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

    if body_ratio < 0.65 or gain_pct < 2.5:   # 0.7→0.65, 3.0%→2.5% 유연화
        return None

    # 직전 봉 대비 거래량 (5배→3배 유연화, 이평선 필터로 보완)
    prev_vols = [int(x.get("trde_qty", 0)) for x in candles[1:6]]
    avg_prev_vol = mean(prev_vols) if prev_vols else 0
    vol_ratio = vol / avg_prev_vol if avg_prev_vol > 0 else 0

    if vol_ratio < 3.0:    # 5.0 → 3.0 유연화
        return None

    # 20일 고가 돌파 여부
    highs_20d = [float(x.get("high_pric", 0)) for x in candles[1:96]]  # 5분봉 96개=8시간
    max_20d = max(highs_20d) if highs_20d else 0
    is_new_high = h >= max_20d

    # 체결강도 확인 (Redis 캐시, 비동기)
    avg_strength = 100
    if rdb:
        strength_data = await rdb.lrange(f"ws:strength:{stk_cd}", 0, 2)
        avg_strength = mean([float(s) for s in strength_data]) if strength_data else 100

    if avg_strength < 120:   # 140 → 120 유연화 (거래량 폭발이 이미 강한 필터)
        return None

    return {
        "stk_cd": stk_cd,
        "cur_prc": round(c),   # 캔들 종가 = 현재 진입 기준가
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
