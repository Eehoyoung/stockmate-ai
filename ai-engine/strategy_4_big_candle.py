from __future__ import annotations
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


# NOTE: Python 메인 전술 실행자 (strategy_runner.py 에서 호출).
# Java api-orchestrator 는 토큰 관리·후보 풀 적재(candidates:s{N}:{market})만 담당.
# rdb (redis.asyncio.Redis) 는 strategy_runner.py 에서 전달받습니다.

logger = logging.getLogger(__name__)
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")

from http_utils import fetch_cntr_strength_cached, fetch_stk_nm, validate_kiwoom_response, kiwoom_client
from indicator_atr import get_atr_minute
from tp_sl_engine import calc_tp_sl

# 부호 및 콤마 제거를 위한 유틸리티 함수
def clean_numeric(value: str) -> float:
    if not value: return 0.0
    return float(str(value).replace("+", "").replace("-", "").replace(",", ""))

async def fetch_minute_chart(token: str, stk_cd: str, scope: int = 5) -> list:
    """ka10080 주식분봉차트 조회"""
    try:
        async with kiwoom_client() as client:
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
                    'upd_stkpc_tp': '1'  # 수정주가 적용
                }
            )
            resp.raise_for_status()
            data = resp.json()
            if not validate_kiwoom_response(data, "ka10080", logger):
                return []
            return data.get("stk_min_pole_chart_qry", [])
    except Exception as e:
        logger.error("[S4] ka10080 호출 실패 [%s]: %s", stk_cd, e)
        return []

async def check_big_candle(token: str, stk_cd: str, rdb=None) -> dict | None:
    candles = await fetch_minute_chart(token, stk_cd, 5)
    # 최소 20개 이상의 봉 데이터가 있어야 비교 가능
    if len(candles) < 20:
        return None

    # 1. 현재봉(Index 0) 데이터 파싱 및 부호 제거
    cur = candles[0]
    o = clean_numeric(cur.get("open_pric", 0))
    h = clean_numeric(cur.get("high_pric", 0))
    l = clean_numeric(cur.get("low_pric", 0))
    c = clean_numeric(cur.get("cur_prc", 0))
    vol = int(clean_numeric(cur.get("trde_qty", 0)))

    if o <= 0 or h <= l: return None

    # 2. 진입 조건 검사
    # 양봉 조건 및 몸통 비율 (Body vs Total Range)
    is_bull = c > o
    candle_range = h - l
    body_size = c - o
    body_ratio = body_size / candle_range if candle_range > 0 else 0
    gain_pct = (c - o) / o * 100

    # 전술 조건: 양봉 몸통 ≥ 3% (2.5% 유연화), 몸통 비율 70%(65% 유연화)
    if not is_bull or body_ratio < 0.65 or gain_pct < 2.5:
        return None

    # 3. 거래량 급증 검사 (직전 5봉 평균 대비 3배)
    prev_vols = [int(clean_numeric(x.get("trde_qty", 0))) for x in candles[1:6]]
    avg_prev_vol = mean(prev_vols) if prev_vols else 0
    vol_ratio = vol / avg_prev_vol if avg_prev_vol > 0 else 0

    if vol_ratio < 3.0:
        return None

    # 4. 전고점 돌파 확인 (최근 96개 봉 = 약 1일치 데이터 중 최고가)
    # '20일' 신고가는 별도의 일봉 조회가 효율적이나, 여기서는 '당일 신고가' 개념으로 접근
    highs_ref = [clean_numeric(x.get("high_pric", 0)) for x in candles[1:96]]
    max_ref = max(highs_ref) if highs_ref else 0
    is_breakout = c >= max_ref

    if not is_breakout:
        return None

    # 5. 실시간 체결강도 확인 (Redis)
    avg_strength, _ = await fetch_cntr_strength_cached(token, stk_cd, rdb=rdb, count=3)
    if rdb:
        # 최근 3분 평균을 위해 List 사용
        strength_data = await rdb.lrange(f"ws:strength:{stk_cd}", 0, 2)
        if strength_data:
            avg_strength = mean([float(s) for s in strength_data])

    if avg_strength < 120:
        return None

    # ── 윗꼬리 비율 계산 ──
    # 윗꼬리 = 고가 - 종가 (매도 압력 지표)
    # 윗꼬리가 전체 range의 20% 이상이면 감점, 30% 이상이면 큰 감점
    upper_shadow = h - c
    upper_shadow_ratio = upper_shadow / candle_range if candle_range > 0 else 0.0
    upper_shadow_penalty = 0.0
    if upper_shadow_ratio >= 0.30:
        upper_shadow_penalty = 15.0  # 강한 윗꼬리 — 고점 부근 매도 압력
    elif upper_shadow_ratio >= 0.20:
        upper_shadow_penalty = 8.0   # 약한 윗꼬리 — 감점

    # ── entry_type 분리 ──
    # 종가가 고가에 가깝다면 추격 진입(R:R 불리)
    # 종가가 중간 이하라면 장대양봉 눌림 타점 가능성
    price_position = (c - l) / candle_range if candle_range > 0 else 1.0
    entry_type = "추격_시장가" if price_position >= 0.8 else "눌림_확인"

    # 모든 조건 통과 시 종목명 가져오기 및 결과 반환
    stk_nm = await fetch_stk_nm(rdb, token, stk_cd)

    # 동적 TP/SL — 5분봉 ATR (장대양봉 이후 단기 변동성 기준)
    atr_val = None
    try:
        atr_result = await get_atr_minute(token, stk_cd, tic_scope="5", period=7)
        atr_val = atr_result.atr
    except Exception:
        pass
    # candle_low=l(장대양봉 저점→SL 기준), candle_high=h(고점→TP 기준)
    tp_sl = calc_tp_sl("S4_BIG_CANDLE", c, [], [], [], stk_cd=stk_cd, atr=atr_val,
                        candle_low=l, candle_high=h, min_rr=1.0)

    # 스코어 계산 (gain_pct 기반 + 윗꼬리 페널티)
    base_score = gain_pct * 2 + (avg_strength - 100) * 0.3
    score = max(0.0, base_score - upper_shadow_penalty - (10 if entry_type == "추격_시장가" else 0))

    return {
        "stk_cd": stk_cd,
        "stk_nm": stk_nm,
        "cur_prc": round(c),
        "strategy": "S4_BIG_CANDLE",
        "gain_pct": round(gain_pct, 2),
        "vol_ratio": round(vol_ratio, 1),
        "body_ratio": round(body_ratio, 2),
        "upper_shadow_ratio": round(upper_shadow_ratio, 2),
        "price_position": round(price_position, 2),
        "is_new_high": is_breakout,
        "cntr_strength": round(avg_strength, 1),
        "score": round(score, 2),
        "entry_type": entry_type,
        **tp_sl.to_signal_fields(),
    }
