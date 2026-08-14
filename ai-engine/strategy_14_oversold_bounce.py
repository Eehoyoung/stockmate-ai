"""
전술 14: 과매도 오실레이터 수렴 반등
유형: 스윙 / 보유기간: 3~5거래일
활성화: 09:30 ~ 14:00

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
설계 철학 – 탑트레이더의 "바닥매수" 알고리즘화
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  애널리스트 : "RSI 35 이하면 과매도, 기술적 반등 여지"
  탑트레이더 : "여러 오실레이터가 동시에 바닥 신호 → 세력도 본다"
  알고 시스템 : "2/3 이상 과매도 지표 충족 → 진입 규칙 발동"

핵심 원칙: 과매도이되 추세 붕괴(MA60 -15% 이하)는 제외.
  진짜 바닥 = "일시적 과매도 + 추세 살아있음 + 반등 신호 2개 이상 + 매수세 유입"

필수 조건 (AND):
  1. RSI(14) 25~42 – 과매도 반등 정상 범위 (D3/D4: 22~38 → 25~42 완화)
     · RSI < 25: 폭락/패닉 후보 → 자동 진입 금지
     · RSI > 42: 약한 눌림/하락 초입 → 전략 철학과 불일치로 제외
  2. 현재가 ≥ MA60 × 0.88 – 장기 추세 아직 살아있음
  3. ATR%(14) ≤ 4.0% – 패닉 매물 소강, 변동성 정상화 중
  4. 당일 하락폭 ≤ 5% (낙폭과대 급락 당일은 제외 – 아직 추가 하락 가능)
  5. 체결강도 ≥ 105% – 매수세 실질 유입 확인 (보너스에서 최소 조건으로 승격)

선택 조건 (3개 중 2개 이상 → 실전 진입 후보, 1개 → shadow 추적 전용):
  A. Stochastic: %K가 %D를 하단(20 미만)에서 상향 돌파 (바닥 탈출 확인)
  B. Williams %R > -80 (과매도 탈출 시작, -80 돌파 상향)
  C. MFI < 30 → 최근 반등 (mfi > mfi_prev 이거나 mfi > 25)
     = 세력이 저가에서 매집 시작하는 자금 흐름

보너스 점수:
  · RSI 반등 중 (rsi > rsi_prev)                             +10점
  · 모든 선택 조건 충족 (3/3)                                +15점
  · 거래량 비율 ≥ 1.5x (반등 거래량 확인)                    +8점

손절: ATR × 2.0 (동적 손절) 또는 -4% 고정
목표: ATR × 3.5 (비대칭 수익) 또는 +7%
"""

from __future__ import annotations

import asyncio
import logging
import os
import statistics
from collections import Counter, defaultdict

from ma_utils import fetch_daily_candles, _safe_price, _safe_vol, _calc_ma
from indicator_rsi import calc_rsi
from indicator_atr import calc_atr, calc_williams_r
from indicator_bollinger import calc_bollinger
from indicator_stochastic import calc_stochastic
from indicator_volume import calc_mfi
from http_utils import fetch_cntr_strength_cached, fetch_stk_nm
from redis_reader import get_tick_with_status
from tp_sl_engine import calc_tp_sl

logger = logging.getLogger(__name__)
_S14_POOL_READ_LIMIT = int(os.getenv("S14_POOL_READ_LIMIT", "180"))
_S14_SCAN_LIMIT = int(os.getenv("S14_SCAN_LIMIT", "60"))

async def scan_oversold_bounce(token: str, rdb=None) -> list:
    """
    S14: 과매도 오실레이터 수렴 반등 전략
    - RSI/Stoch/MFI/W%R 등 복수 오실레이터가 바닥권에서 동시 반등할 때 진입
    """
    candidates: list[str] = []
    if rdb:
        try:
            # S14 전용 풀 (과매도 후보군)
            kospi = await rdb.lrange("candidates:s14:001", 0, max(_S14_POOL_READ_LIMIT - 1, 0))
            kosdaq = await rdb.lrange("candidates:s14:101", 0, max(_S14_POOL_READ_LIMIT - 1, 0))
            candidates = list(dict.fromkeys(kospi + kosdaq))[:_S14_SCAN_LIMIT]
        except Exception as e:
            logger.warning(f"[S14] 후보 풀 로드 실패: {e}")

    if not candidates:
        logger.info("[S14][scan_summary] candidate_count=0 pass=0 rejects={'no_candidates': 1}")
        return []

    results = []
    reject_counts = Counter()
    reject_samples = defaultdict(list)
    evaluated_count = 0

    def _reject(reason: str, stk_cd: str, **fields) -> None:
        reject_counts[reason] += 1
        if len(reject_samples[reason]) < 5:
            sample = {"stk_cd": stk_cd}
            sample.update(fields)
            reject_samples[reason].append(sample)

    for stk_cd in candidates:
        await asyncio.sleep(float(os.getenv("KIWOOM_API_INTERVAL", "0.8")))

        candles = await fetch_daily_candles(token, stk_cd, target_count=65)
        if len(candles) < 60:
            await asyncio.sleep(1.5)
            candles = await fetch_daily_candles(token, stk_cd, target_count=65)
        if len(candles) < 60:
            _reject("short_candles", stk_cd, candles=len(candles))
            continue

        evaluated_count += 1

        # 데이터 파싱
        closes = [_safe_price(c.get("cur_prc")) for c in candles]
        highs  = [_safe_price(c.get("high_pric")) for c in candles]
        lows   = [_safe_price(c.get("low_pric")) for c in candles]
        vols   = [_safe_vol(c.get("trde_qty")) for c in candles]
        cur_prc = closes[0]

        # ── 필수 조건 1 & 2: RSI 과매도(25~42) & MA60 추세 생존 ──
        # 25~42: 과매도 반등 정상 범위 (D3/D4: 22~38 → 25~42 완화)
        # RSI < 25: 폭락/패닉 후보 — 자동 진입 금지
        # RSI > 42: 약한 눌림/하락 초입 — 전략 철학과 불일치로 제외
        #
        # closes 길이는 위에서 이미 60봉 이상으로 보장되어 있어 calc_rsi()의
        # index 0/1은 항상 실제 계산값이다(0.0도 유효한 RSI). 과거에는
        # "RSI==0.0이면 데이터 부족"으로 오판해 재조회를 시도했는데, 실제로는
        # 진짜 극단적 과매도(RSI=0)를 데이터 오류로 착각한 것이었다 — 이
        # 전략은 어차피 25~42 범위만 통과시키므로 재조회 없이 바로 걸러진다.
        #
        # rsi_out_of_range 비중이 높다고 이 대역을 넓히지 말 것 (2026-08-14 검증).
        # 그날 탈락 표본 185건의 RSI 분포는 최소 42.8 / 중앙 54.2 / 최대 72.3으로,
        # 25~42 근처에 온 후보가 단 하나도 없었다. 게이트가 과하게 조인 게 아니라
        # 후보 자체가 과매도가 아니었다는 뜻이다.
        #
        # 원인은 상류에 있다. 후보 풀은 "오늘 -3~-10% 하락"으로 뽑는데(sort_tp=3),
        # 크게 오른 뒤 하루 빠진 종목은 RSI가 50대로 남는다. 즉 당일 하락률과
        # 다일 과매도(RSI14)가 서로 다른 개념이다. 약세장에서 신호 0건인 것은
        # 눌림 반등 셋업이 실제로 없었다는 정상 동작이며, 억지로 통과시키면
        # 하락 초입에 진입하게 된다.
        rsi_vals = calc_rsi(closes, 14)
        rsi_now  = rsi_vals[0]
        rsi_prev = rsi_vals[1] if len(rsi_vals) > 1 else None
        if not (25 <= rsi_now <= 42):
            _reject("rsi_out_of_range", stk_cd, rsi=round(rsi_now, 1))
            continue

        ma60 = sum(closes[:60]) / 60
        if cur_prc < ma60 * 0.88:
            _reject("below_ma60_floor", stk_cd, cur_prc=round(cur_prc), ma60=round(ma60, 2))
            continue # 추세 완전 붕괴 제외

        # ── 필수 조건 3 & 4: ATR 변동성 안정 & 당일 급락(-5%) 제외 ──
        atr_vals = calc_atr(highs, lows, closes, 14)
        atr_now = atr_vals[0]
        atr_pct = (atr_now / cur_prc) * 100
        if atr_pct > 4.0:
            _reject("atr_pct_over_4", stk_cd, atr_pct=round(atr_pct, 2))
            continue # 변동성 과다(패닉) 구간 제외

        # 실시간 데이터 (Redis)
        flu_rt, cntr_str = 0.0, 100.0
        if rdb:
            try:
                tick_result = await get_tick_with_status(rdb, stk_cd)
                tick = tick_result.get("data") or {}
                if tick:
                    flu_rt = float(str(tick.get("flu_rt", "0")).replace("+", "").replace(",", ""))
                    cntr_str = float(str(tick.get("cntr_str", "100")).replace("+", "").replace(",", ""))
            except Exception as e:
                logger.debug("[S14] realtime tick read failed %s: %s", stk_cd, e)
        if cntr_str <= 100:
            cntr_str, _ = await fetch_cntr_strength_cached(token, stk_cd, rdb=rdb)

        if flu_rt < -5.0:
            _reject("flu_rt_below_neg5", stk_cd, flu_rt=round(flu_rt, 2))
            continue # 하락 진행 중인 칼날 제외

        # ── 필수 조건 5: 체결강도 ≥ 105 (매수세 실질 유입 확인) ──
        # 반등 전략에서 매수세 확인이 보너스에 그치면 하락 지속 종목이 섞임
        if cntr_str < 105.0:
            _reject("cntr_str_below_105", stk_cd, cntr_str=round(cntr_str, 1))
            continue

        # ── 선택 조건 A: Stochastic 골든크로스 ──
        sk, sd = calc_stochastic(highs, lows, closes, 14, 3, 3)
        cond_stoch = (sk[0] > sd[0] and sk[1] <= sd[1] and sk[1] < 25)

        # ── 선택 조건 B: Williams %R -80 상향 돌파 ──
        wr = calc_williams_r(highs, lows, closes, 14)
        cond_wr = (wr[1] < -80 and wr[0] > -80)

        # ── 선택 조건 C: MFI 바닥 탈출 ──
        mfi = calc_mfi(highs, lows, closes, vols, 14)
        cond_mfi = (mfi[0] < 30 and (mfi[0] > mfi[1] or mfi[0] > 25))

        # ── 선택 조건 집계 및 스코어링 ──
        cond_count = sum([cond_stoch, cond_wr, cond_mfi])
        # cond_count == 0: 반등 단서 없음, 완전 제외
        # cond_count == 1: shadow 기록만 허용 (실전 진입 후보 제외)
        # cond_count >= 2: 실전 진입 후보
        if cond_count < 1:
            _reject("cond_count_lt1", stk_cd, cond_count=cond_count)
            continue
        is_shadow = (cond_count == 1)

        vol_ma20 = sum(vols[1:21]) / 20
        vol_ratio = vols[0] / vol_ma20 if vol_ma20 > 0 else 1.0

        # 점수 산정 (RSI 42 상한 기준으로 거리 계산)
        score = (42 - rsi_now) * 0.5 + (cond_count * 10)
        if rsi_prev is not None and rsi_now > rsi_prev: score += 10
        if cond_count == 3: score += 15
        if vol_ratio >= 1.5: score += 8
        # cntr_str은 최소 조건으로 승격되어 여기서는 보너스 없이 조건 통과만 의미

        # 동적 TP/SL — swing_low/MA20/MA60 기반 구조적 손절 (tp_sl_engine)
        ma20_val = sum(closes[:20]) / 20 if len(closes) >= 20 else None
        bb_lower_val = None
        bb_upper_val = None
        bands = calc_bollinger(closes, period=20, num_std=2.0)
        if bands and len(bands) > 0:
            bb_upper_val = bands[0][0]  # (upper, middle, lower)
            bb_lower_val = bands[0][2]
        tp_sl = calc_tp_sl(
            "S14_OVERSOLD_BOUNCE", cur_prc, highs, lows, closes,
            stk_cd=stk_cd, atr=atr_now, ma20=ma20_val, ma60=ma60,
            bb_lower=bb_lower_val, compute_zones=True,
        )
        signal_mode = "SHADOW" if is_shadow else "NORMAL"
        logger.info(
            "[S14][pass] stk=%s mode=%s score=%.2f rsi=%.1f cond=%d cntr=%.1f flu_rt=%.2f",
            stk_cd, signal_mode, score, rsi_now, cond_count, cntr_str, flu_rt,
        )
        results.append({
            "stk_cd": stk_cd,
            "stk_nm": await fetch_stk_nm(rdb, token, stk_cd),
            "cur_prc": round(cur_prc),
            "strategy": "S14_OVERSOLD_BOUNCE",
            "score": round(score, 2),
            "rsi": round(rsi_now, 1),
            "atr": round(atr_now, 2) if atr_now is not None else None,
            "bb_upper": round(bb_upper_val, 2) if bb_upper_val is not None else None,
            "bb_lower": round(bb_lower_val, 2) if bb_lower_val is not None else None,
            "cond_count": cond_count,
            "cntr_strength": round(cntr_str, 1),
            "vol_ratio": round(vol_ratio, 2),
            "atr_pct": round(atr_pct, 2),
            "flu_rt": round(flu_rt, 2),
            "signal_mode": signal_mode,
            "entry_type": "당일종가_또는_익일시가",
            "holding_days": "3~5거래일",
            **tp_sl.to_signal_fields(),
        })

    # 실전 진입 후보(cond_count >= 2)와 shadow(cond_count == 1) 분리
    normal = [r for r in results if r["signal_mode"] == "NORMAL"]
    shadow = [r for r in results if r["signal_mode"] == "SHADOW"]
    top_normal = sorted(normal, key=lambda x: x["score"], reverse=True)[:5]
    # shadow 결과는 상위 3개만 포함 (성과 집계용 — 실전 진입 불가)
    top_shadow = sorted(shadow, key=lambda x: x["score"], reverse=True)[:3]
    returned = top_normal + top_shadow
    logger.info(
        "[S14][scan_summary] candidate_count=%d evaluated=%d pass=%d returned=%d rejects=%s samples=%s",
        len(candidates),
        evaluated_count,
        len(results),
        len(returned),
        dict(reject_counts),
        {key: value for key, value in reject_samples.items()},
    )
    return returned
