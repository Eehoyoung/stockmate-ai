"""
전술 13: 거래량 폭발 박스권 돌파 스윙
유형: 스윙 / 보유기간: 3~7거래일

진입 조건 (AND) – ka10081 일봉 기반 직접 계산:
  1. 최근 15거래일 (고가 - 저가) / 저가 ≤ 8% (박스권 형성 확인)
  2. 오늘 종가 > 15일 최고가 (박스 상단 돌파)
  3. 오늘 양봉 (종가 > 시가)
  4. 오늘 거래량 ≥ 15일 평균 거래량 × 2.0 (거래량 폭발 확인)
  5. 현재가 ≥ MA20 (추세 위 돌파만 유효)
  6. 체결강도 ≥ 120% (기존 130 → 유연화)
  7. 당일 등락률 ≤ 20% (상한가 노이즈 제외)

보너스 점수:
  · 볼린저 밴드폭(20일) < 6% – 스퀴즈 → 폭발 패턴 (수익 기대치 높음)  +15점
  · MFI(14) > 55 – 자금 실제 유입 확인 (거래량 품질 검증)               +10점

NOTE: ka10172 HTS 조건검색 의존도 제거 → ka10081 일봉 직접 계산
"""

import asyncio
import logging
import os
import statistics
from datetime import datetime

# 기존 유틸리티 모듈 임포트
from ma_utils import fetch_daily_candles, detect_box_breakout, _safe_price, _safe_vol, _calc_ma
from indicator_bollinger import calc_bollinger
from indicator_volume import calc_mfi
from http_utils import fetch_stk_nm

logger = logging.getLogger(__name__)

# 환경 변수 및 설정
_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))
MIN_CNTR_STR = float(os.getenv("S13_MIN_CNTR_STR", "120.0"))  # 체결강도 하한
BOX_PERIOD = 15     # 박스권 관찰 기간
MAX_BOX_RANGE = 8.0  # 박스권 허용 폭 (%)

async def scan_box_breakout(token: str, rdb=None) -> list:
    """
    S13: 거래량 폭발 박스권 돌파 전략
    - 박스권 수렴 후 볼린저 밴드 스퀴즈 상태에서 대량 거래와 함께 돌파하는 종목 포착
    """
    candidates: list[str] = []
    if rdb:
        try:
            # Java Orchestrator가 적재한 후보 풀 조회 (S8: 소폭상승 + S10: 신고가 근접 종목군)
            kospi = await rdb.lrange("candidates:s13:001", 0, 99)
            kosdaq = await rdb.lrange("candidates:s13:101", 0, 99)
            candidates = list(dict.fromkeys(kospi + kosdaq))[:30] # 중복 제거 후 상위 30개 검사
        except Exception as e:
            logger.error(f"[S13] 후보 풀 로드 실패: {e}")

    if not candidates:
        return []

    results = []
    for stk_cd in candidates:
        await asyncio.sleep(_API_INTERVAL)  # API 호출 제한 준수

        # 1. 일봉 데이터 확보 (최소 120봉 확보 권장 - MA120 계산용)
        candles = await fetch_daily_candles(token, stk_cd, target_count=130)
        if len(candles) < 60: continue

        # 데이터 파싱
        closes = [_safe_price(c.get("cur_prc")) for c in candles]
        opens  = [_safe_price(c.get("open_pric")) for c in candles]
        highs  = [_safe_price(c.get("high_pric")) for c in candles]
        lows   = [_safe_price(c.get("low_pric")) for c in candles]
        vols   = [_safe_vol(c.get("trde_qty")) for c in candles]

        cur_prc = closes[0]
        if cur_prc <= 0: continue

        # 2. 박스권 돌파 검증 (detect_box_breakout 유틸 활용)
        is_breakout, box_range_pct = detect_box_breakout(
            candles, box_period=BOX_PERIOD, max_range_pct=MAX_BOX_RANGE, vol_mul=2.0
        )
        if not is_breakout: continue

        # 3. 이평선 필터링 (MA20 위 돌파 & MA120 저항선 체크)
        ma20 = _calc_ma(closes, 20)
        ma120 = _calc_ma(closes, 120)

        if cur_prc < ma20: continue # 추세 하단 돌파는 제외

        # [고도화] 장기 저항선(MA120)이 바로 위에 있으면 돌파 실패 확률 높음
        resistance_penalty = 0
        if ma120 and cur_prc < ma120:
            dist_to_ma120 = (ma120 - cur_prc) / cur_prc * 100
            if dist_to_ma120 < 1.5: # 1.5% 이내면 강한 저항권
                resistance_penalty = 10

        # 4. 거래량 품질 검증 (최근 60일 내 최대 거래량 여부)
        vol_today = vols[0]
        vol_max_60 = max(vols[1:61]) if len(vols) >= 61 else 0
        is_monster_vol = vol_today > vol_max_60

        vol_avg_15 = sum(vols[1:16]) / 15
        vol_ratio = vol_today / vol_avg_15 if vol_avg_15 > 0 else 1.0

        # 5. 보너스 지표 계산 (Bollinger Squeeze & MFI)
        # 볼린저 밴드 스퀴즈 확인 (20일 기준 밴드폭 6% 미만)
        bollinger_squeeze = False
        bands = calc_bollinger(closes, period=20, num_std=2.0)
        if bands and bands[0][1] > 0:
            upper, middle, lower = bands[0]
            bandwidth = (upper - lower) / middle * 100
            bollinger_squeeze = bandwidth < 6.0

        # MFI (14) 확인 (55 이상이면 자금 유입 신뢰도 높음)
        mfi_confirmed = False
        mfi_vals = calc_mfi(highs, lows, closes, vols, period=14)
        if mfi_vals and mfi_vals[0] > 55.0:
            mfi_confirmed = True

        # 6. 실시간 데이터 결합 (Redis Tick)
        flu_rt = 0.0
        cntr_str = 100.0
        if rdb:
            tick = await rdb.hgetall(f"ws:tick:{stk_cd}")
            if tick:
                flu_rt = float(str(tick.get("flu_rt", "0")).replace("+", ""))
                cntr_str = float(str(tick.get("cntr_str", "100")))

        # 과도한 급등(상한가 등) 노이즈 제거
        if not (0 < flu_rt <= 20.0) or cntr_str < MIN_CNTR_STR:
            continue

        # 7. 스코어링 시스템 (S13 특화)
        # 기본 점수: 등락률 + 체결강도 가중치
        score = (flu_rt * 0.5) + (max(cntr_str - 100, 0) * 0.3)

        # 거래량 가중치 (최대 20점)
        score += min(vol_ratio, 10.0) * 2
        if is_monster_vol: score += 10 # 60일 신고 거래량 보너스

        # 박스권 수렴도 가중치 (좁을수록 폭발력 높음)
        score += max(8.0 - box_range_pct, 0) * 1.5

        # 패턴 보너스
        if bollinger_squeeze: score += 15
        if mfi_confirmed: score += 10

        # 페널티
        score -= resistance_penalty

        stk_nm = await fetch_stk_nm(rdb, token, stk_cd)
        results.append({
            "stk_cd": stk_cd,
            "stk_nm": stk_nm,
            "cur_prc": round(cur_prc),
            "strategy": "돌파매매",
            "score": round(score, 2),
            "flu_rt": round(flu_rt, 2),
            "cntr_strength": round(cntr_str, 1),
            "vol_ratio": round(vol_ratio, 2),
            "is_monster_vol": is_monster_vol,
            "bollinger_squeeze": bollinger_squeeze,
            "mfi_confirmed": mfi_confirmed,
            "entry_type": "당일종가_또는_익일눌림",
            "holding_days": "3~7거래일",
            "target_pct": 10.0,
            "stop_pct": -5.0
        })

    # 스코어 기준 내림차순 정렬 후 상위 5개 반환
    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]
