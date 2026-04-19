from __future__ import annotations
"""
전술 8: 5일선 골든크로스 스윙
유형: 스윙 / 보유기간: 3~7거래일

진입 조건 (AND) – ka10081 일봉 기반 직접 계산:
  1. MA5 > MA20 크로스오버 당일 OR 직근 3일 이내 (이격 ≤ 5%)
  2. 현재가 ≥ MA60 × 0.95 (60일선 지지권 이내)
  3. 당일 거래량 ≥ MA20 거래량 × 1.3 (크로스 당일 거래량 확인)
  4. 당일 등락률 0~15% (양봉 + 과열 제외)
  5. MA5/MA20 이격 ≤ 5% (크로스 직후, 추격 진입 방지)
  6. RSI(14) ≤ 75 – 이미 과열된 후행 골든크로스 제거 (hard gate)

보너스 점수:
  · RSI 45~65 (황금구간, 모멘텀 시작 미과열)       +12점
  · MACD histogram 2봉 연속 양전 확대 (가속 확인)   +10점

NOTE: ka10172 HTS 조건검색 의존도 제거 → ka10081 일봉 직접 계산
"""

import asyncio
import logging
import os

from ma_utils import fetch_daily_candles, detect_golden_cross, _calc_ma, _safe_price, _safe_vol
from indicator_rsi import calc_rsi
from indicator_macd import calc_macd
from indicator_bollinger import calc_bollinger
from indicator_atr import calc_atr
from http_utils import fetch_cntr_strength_cached, fetch_stk_nm
from tp_sl_engine import calc_tp_sl

logger = logging.getLogger(__name__)
_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))

async def scan_golden_cross(token: str, rdb=None) -> list:
    """
    [전술 8] 5일선 골든크로스 스윙 스캔
    - ka10081 일봉 데이터를 직접 계산하여 기술적 지표 산출
    """
    candidates: list[str] = []
    if rdb:
        try:
            # S8 후보 풀 (Orchestrator가 미리 적재한 candidates:s8)
            kospi  = await rdb.lrange("candidates:s8:001", 0, 99)
            kosdaq = await rdb.lrange("candidates:s8:101", 0, 99)
            candidates = list(dict.fromkeys(kospi + kosdaq))[:30]
        except Exception as e:
            logger.warning("[S8] Redis 후보 조회 실패: %s", e)

    if not candidates:
        logger.warning("[S8] candidates:s8:001/101 풀 없음 – candidates_builder 기동 확인 필요")
        return []

    results = []
    for stk_cd in candidates:
        await asyncio.sleep(_API_INTERVAL)

        # 1. 일봉 데이터 조회 (ka10081)
        candles = await fetch_daily_candles(token, stk_cd)
        if len(candles) < 60: # MA60 계산을 위해 최소 60봉 필요
            continue

        # 2. 골든크로스 및 이격도 확인 (MA5/MA20)
        # detect_golden_cross: (오늘크로스, 5%이내근접, 이격률)
        is_today_cross, is_near_cross, gap_pct = detect_golden_cross(candles)

        # 조건 1 & 5: 크로스 발생 또는 3일 이내 근접(이격 5% 이내)
        if not (is_today_cross or is_near_cross):
            continue

        # 3. 가격 및 거래량 리스트 추출
        closes = [_safe_price(c.get("cur_prc")) for c in candles if _safe_price(c.get("cur_prc")) > 0]
        highs  = [_safe_price(c.get("high_pric")) for c in candles]
        lows   = [_safe_price(c.get("low_pric")) for c in candles]
        vols   = [_safe_vol(c.get("trde_qty")) for c in candles]

        if len(closes) < 60: continue

        cur_prc = closes[0]
        vol_today = vols[0]
        vol_ma20 = sum(vols[1:21]) / 20 # 전일까지의 20일 평균 거래량

        # 조건 2: MA60 지지권 확인 ($Price \ge MA_{60} \times 0.95$)
        ma20 = sum(closes[:20]) / 20
        ma60 = sum(closes[:60]) / 60
        if cur_prc < ma60 * 0.95:
            continue

        # 조건 3: 거래량 확인 (당일 거래량 ≥ MA20 거래량 × 1.3)
        if vol_ma20 > 0 and vol_today < vol_ma20 * 1.3:
            continue

        # 4. 보조지표 계산 (RSI, MACD)
        rsi_vals = calc_rsi(closes, 14)
        rsi_now  = rsi_vals[0] if rsi_vals else 0

        # 조건 6: RSI(14) 하드 게이트 (과열된 골든크로스 제거)
        if rsi_now > 75:
            continue

        # MACD 히스토그램 가속 확인
        _, _, histogram = calc_macd(closes)
        hist_now  = histogram[0] if len(histogram) > 0 else 0
        hist_prev = histogram[1] if len(histogram) > 1 else 0
        is_macd_accel = (hist_now > 0) and (hist_now > hist_prev)

        # 5. 실시간 데이터 결합 (Redis Tick)
        flu_rt = 0.0
        cntr_str = 100.0
        if rdb:
            tick = await rdb.hgetall(f"ws:tick:{stk_cd}")
            if tick:
                flu_rt = clean_num(tick.get("flu_rt", 0))
                cntr_str = clean_num(tick.get("cntr_str", 100))
        if cntr_str <= 100:
            cntr_str, _ = await fetch_cntr_strength_cached(token, stk_cd, rdb=rdb)

        # 조건 4: 당일 등락률 필터 (0~15%)
        if not (0.0 <= flu_rt <= 15.0):
            continue

        # 6. 점수 산정 (보너스 포함)
        score = (
                (20 if is_today_cross else 10)           # 당일 크로스 가점
                + (12 if 45 <= rsi_now <= 65 else 0)    # RSI 황금구간 보너스
                + (10 if is_macd_accel else 0)          # MACD 가속 보너스
                + (vol_today / vol_ma20 * 5)            # 거래량 가중치
                + (cntr_str * 0.05)                     # 체결강도 가중치
        )

        stk_nm = await fetch_stk_nm(rdb, token, stk_cd)
        vol_ratio = round(vol_today / vol_ma20, 2) if vol_ma20 > 0 else 0.0

        # 볼린저 상단 계산 (TP 후보)
        bb_upper = None
        if len(closes) >= 20:
            bands = calc_bollinger(closes, period=20, num_std=2.0)
            if bands and bands[0][0] > 0:
                bb_upper = bands[0][0]

        # ATR 계산 (SL 폴백용 — MA20이 정상이면 불필요하지만 이격 클 때 중요)
        atr_val = None
        if len(highs) >= 14 and len(lows) >= 14 and len(closes) >= 14:
            atr_vals = calc_atr(highs, lows, closes, 14)
            atr_val  = atr_vals[0] if atr_vals and atr_vals[0] != 0.0 else None

        # 동적 TP/SL 계산
        ma5 = sum(closes[:5]) / 5 if len(closes) >= 5 else None
        tp_sl = calc_tp_sl("S8_GOLDEN_CROSS", cur_prc, highs, lows, closes,
                            stk_cd=stk_cd, ma5=ma5, ma20=ma20, ma60=ma60,
                            atr=atr_val, bb_upper=bb_upper)

        results.append({
            "stk_cd": stk_cd,
            "stk_nm": stk_nm,
            "cur_prc": round(cur_prc),
            "strategy": "S8_GOLDEN_CROSS",
            "score": round(score, 2),
            "rsi": round(rsi_now, 1),
            "gap_pct": round(gap_pct, 2),
            "flu_rt": flu_rt,
            "cntr_strength": round(cntr_str, 1),
            "vol_ratio": vol_ratio,
            "is_today_cross": is_today_cross,
            "is_macd_accel": is_macd_accel,
            "entry_type": "현재가_종가",
            **tp_sl.to_signal_fields(),
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]

def clean_num(val):
    try:
        # '+' 부호만 제거, '-'는 음수 부호이므로 보존
        return float(str(val).replace("+", "").replace(",", ""))
    except:
        return 0.0
