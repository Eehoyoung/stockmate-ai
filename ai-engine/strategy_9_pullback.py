from __future__ import annotations
"""
전술 9: 정배열 눌림목 지지 반등 스윙
유형: 스윙 / 보유기간: 3~5거래일

진입 조건 (AND) – ka10081 일봉 기반 직접 계산:
  1. MA5 > MA20 > MA60 정배열 (상승 추세 확인)
  2. 현재가가 MA5 기준 -3% ~ +3% 범위 (눌림 구간 진입)
  3. 당일 양봉 (현재가 > 시가) + 등락률 > 0
  4. 당일 거래량 ≥ 전일 거래량 × 1.1 (반등 거래량 소폭 확인)
  5. MA20 대비 이격 ≤ 15% (추세 내 눌림, 과열 버블 제외)
  6. RSI(14) ≤ 68 – 눌림 중 과매수 종목 제거 (hard gate)
     탑트레이더 관점: RSI 높은 눌림은 "눌림"이 아니라 고점 노출

보너스 점수:
  · Stochastic %K > %D 상향 돌파 (반등 시작 확인)             +12점
  · RSI 40~58 (눌림 후 회복 초입, 추가 상승 여력 충분)        +8점

NOTE: ka10172 HTS 조건검색 의존도 제거 → ka10081 일봉 직접 계산
"""

import asyncio
import logging
import os

from ma_utils import fetch_daily_candles, detect_pullback_setup, _safe_price, _safe_vol
from indicator_rsi import calc_rsi
from indicator_stochastic import calc_stochastic
from http_utils import fetch_cntr_strength, fetch_stk_nm
from tp_sl_engine import calc_tp_sl

logger = logging.getLogger(__name__)
_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))

async def scan_pullback_swing(token: str, rdb=None) -> list:
    """
    [전술 9] 정배열 눌림목 지지 반등 스윙 스캔
    - ka10081 일봉 기반 직접 계산
    - MA5/20/60 정배열 및 MA5 근접도 확인
    - Stochastic 및 RSI를 통한 반등 모멘텀 점수화
    """
    candidates: list[str] = []
    if rdb:
        try:
            logger.debug("[S9] using candidates:s9 strategy-owned pool for pullback scan")
            kospi  = await rdb.lrange("candidates:s9:001", 0, 99)
            kosdaq = await rdb.lrange("candidates:s9:101", 0, 99)
            candidates = list(dict.fromkeys(kospi + kosdaq))[:30]
        except Exception as e:
            logger.warning("[S9] Redis 후보 조회 실패: %s", e)

    if not candidates:
        logger.warning("[S9] candidates:s9:001/101 pool 없음 – candidates_builder 기동 확인 필요")
        return []

    results = []
    for stk_cd in candidates:
        await asyncio.sleep(_API_INTERVAL)

        # 1. 일봉 데이터 조회 (ka10081)
        candles = await fetch_daily_candles(token, stk_cd)
        if len(candles) < 62: # 정배열 및 보조지표 계산을 위한 충분한 데이터
            continue

        # 2. 정배열 + 눌림목 상태 확인 (ma_utils 활용)
        # is_setup: MA5 > MA20 > MA60 AND 현재가가 MA5 기준 -3% ~ +3% 이내
        is_setup, pct_ma5, pct_ma20 = detect_pullback_setup(candles)
        if not is_setup:
            continue

        # 조건 5: MA20 대비 이격 ≤ 15% (과열권 제외)
        if pct_ma20 > 15.0:
            continue

        # 3. 기술적 데이터 추출
        closes = [_safe_price(c.get("cur_prc")) for c in candles if _safe_price(c.get("cur_prc")) > 0]
        highs  = [_safe_price(c.get("high_pric")) for c in candles]
        lows   = [_safe_price(c.get("low_pric")) for c in candles]
        vols   = [_safe_vol(c.get("trde_qty")) for c in candles]

        if len(closes) < 20: continue

        # 조건 3: 당일 양봉 및 등락률 확인
        t_close = closes[0]
        t_open  = _safe_price(candles[0].get("open_pric"))
        if t_close <= t_open: # 음봉 제외
            continue

        # 조건 4: 거래량 확인 (전일 대비 1.1배 이상)
        if vols[1] > 0 and vols[0] < vols[1] * 1.1:
            continue

        # 4. 보조지표 계산 및 하드 게이트 적용
        # 조건 6: RSI(14) ≤ 68 (과매수 상태의 눌림은 배제)
        rsi_vals = calc_rsi(closes, 14)
        rsi_now  = rsi_vals[0] if rsi_vals else 0
        if rsi_now > 68:
            continue

        # 보너스: Stochastic %K > %D 골든크로스 (반등 신호)
        stoch_k, stoch_d = calc_stochastic(highs, lows, closes, 14, 3, 3)
        stoch_gc = (stoch_k[0] > stoch_d[0]) and (stoch_k[1] <= stoch_d[1]) if len(stoch_k) > 1 else False

        # 5. 실시간 체결 데이터 (Redis Tick)
        # S9는 스윙 전략 — WS 미구독 종목은 tick = {} → flu_rt = 0
        # 일봉(candles[0])의 당일 등락 여부로 양봉 조건(조건 3)을 대체 적용
        flu_rt = 0.0
        cntr_str = 100.0
        if rdb:
            tick = await rdb.hgetall(f"ws:tick:{stk_cd}")
            if tick:
                flu_rt = float(str(tick.get("flu_rt", 0)).replace("+", ""))
                cntr_str = float(str(tick.get("cntr_str", 100)).replace(",", ""))

        # WS 미구독(flu_rt=0)이면 일봉 양봉 조건(t_close > t_open)으로 대체
        # WS 구독 종목은 기존대로 마이너스 등락률 시 제외
        if flu_rt < 0: continue  # 명시적 하락 확인 시 제외 (0은 미구독으로 허용)

        # 6. 최종 점수 산정
        score = (
                flu_rt * 0.5
                + max(cntr_str - 100, 0) * 0.2
                + max(5.0 - abs(pct_ma5), 0) * 2          # MA5에 딱 붙을수록 가산
                + (10 if -1.0 <= pct_ma5 <= 2.0 else 0)   # 최적 반등 타점 구간
                + (12 if stoch_gc else 0)                  # 스토캐스틱 골든크로스
                + (8 if 40 <= rsi_now <= 58 else 0)       # RSI 회복 초입 구간
        )

        stk_nm = await fetch_stk_nm(rdb, token, stk_cd)
        vol_ma20 = sum(vols[1:21]) / 20 if len(vols) >= 21 else 0
        vol_ratio = round(vols[0] / vol_ma20, 2) if vol_ma20 > 0 else 0.0

        # 동적 TP/SL 계산 (highs/lows 이미 추출됨)
        ma5  = sum(closes[:5])  / 5  if len(closes) >= 5  else None
        ma20 = sum(closes[:20]) / 20 if len(closes) >= 20 else None
        ma60 = sum(closes[:60]) / 60 if len(closes) >= 60 else None
        tp_sl = calc_tp_sl("S9_PULLBACK_SWING", t_close, highs, lows, closes,
                            stk_cd=stk_cd, ma5=ma5, ma20=ma20, ma60=ma60,
                            compute_zones=True)

        results.append({
            "stk_cd": stk_cd,
            "stk_nm": stk_nm,
            "cur_prc": round(t_close),
            "strategy": "S9_PULLBACK_SWING",
            "score": round(score, 2),
            "pct_ma5": round(pct_ma5, 2),
            "rsi": round(rsi_now, 1),
            "stoch_gc": stoch_gc,
            "cntr_strength": round(cntr_str, 1),
            "vol_ratio": vol_ratio,
            "flu_rt": round(flu_rt, 2),
            "entry_type": "현재가_종가_분할매수",
            **tp_sl.to_signal_fields(),
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]
