from __future__ import annotations
"""
전술 13: 거래량 폭발 박스권 돌파 스윙
유형: 스윙 / 보유기간: 3~7거래일

진입 조건 (AND) – ka10081 일봉 기반 직접 계산:
  1. 최근 15거래일 (고가 - 저가) / 저가 ≤ 8% (박스권 형성 확인)
  2. 오늘 종가 > 15일 최고가 (박스 상단 돌파)
  3. 오늘 양봉 (종가 > 시가)
  4. 거래량 폭발 확인 — 전일 동시간대 대비(ka10055) ≥ 2.0배, 불완전/실패 시
     당일누적/15일평균거래량 폴백 (resolve_effective_volume_ratio, S7/S8/S9와 동일 패턴)
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
from collections import Counter, defaultdict

from http_utils import (
    apply_volume_profile_rr,
    fetch_program_snapshot,
    fetch_same_time_volume_ratio_cached,
    fetch_stk_nm,
    fetch_volume_profile,
    kiwoom_client,
    KiwoomReservationUnavailable,
    program_drop_reason,
    resolve_effective_volume_ratio,
    validate_kiwoom_response,
)
from indicator_bollinger import calc_bollinger
from indicator_rsi import calc_rsi
from indicator_volume import calc_mfi
from indicator_atr import calc_atr
from ma_utils import fetch_daily_candles, detect_box_breakout, _safe_price, _safe_vol, _calc_ma
from redis_reader import get_tick_with_status
from tp_sl_engine import calc_tp_sl
from execution_quality import assess_execution_quality, should_hard_reject

logger = logging.getLogger(__name__)
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")

# 환경 변수 및 설정
_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.8"))
MIN_CNTR_STR = float(os.getenv("S13_MIN_CNTR_STR", "120.0"))  # 체결강도 하한
BOX_PERIOD = 15     # 박스권 관찰 기간
MAX_BOX_RANGE = 8.0  # 박스권 허용 폭 (%)
VOL_MUL = 2.0        # 거래량 급증 하한 배수 (전일 동시간대 대비, 폴백 시 당일누적/15일평균 대비)
_POOL_READ_LIMIT = int(os.getenv("S13_POOL_READ_LIMIT", "180"))
_SCAN_LIMIT = int(os.getenv("S13_SCAN_LIMIT", "60"))


async def _fetch_minute_chart_raw_s13(token: str, stk_cd: str, scope: int = 5) -> dict:
    """ka10080 분봉차트 원본 응답 반환 (execution_quality 용)."""
    try:
        async with kiwoom_client() as client:
            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/chart",
                headers={
                    "api-id": "ka10080",
                    "authorization": f"Bearer {token}",
                    "Content-Type": "application/json;charset=UTF-8",
                },
                json={
                    "stk_cd": stk_cd.strip(),
                    "tic_scope": str(scope),
                    "upd_stkpc_tp": "1",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if not validate_kiwoom_response(data, "ka10080", logger):
                return {}
            return data
    except KiwoomReservationUnavailable:
        logger.warning("[S13] Kiwoom rate limiter unavailable — 부분 결과로 조기 종료 (api=%s)", "ka10080")
        return {}
    except Exception as exc:
        logger.debug("[S13] ka10080 분봉 조회 실패 [%s]: %s", stk_cd, exc)
        return {}


async def _fetch_hoga_raw_s13(token: str, stk_cd: str) -> dict:
    """ka10004 호가 원본 응답 반환 (execution_quality 용)."""
    try:
        async with kiwoom_client() as client:
            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/mrkcond",
                headers={
                    "api-id": "ka10004",
                    "authorization": f"Bearer {token}",
                    "Content-Type": "application/json;charset=UTF-8",
                },
                json={"stk_cd": stk_cd.strip()},
            )
            resp.raise_for_status()
            data = resp.json()
            if not validate_kiwoom_response(data, "ka10004", logger):
                return {}
            return data
    except KiwoomReservationUnavailable:
        logger.warning("[S13] Kiwoom rate limiter unavailable — 부분 결과로 조기 종료 (api=%s)", "ka10004")
        return {}
    except Exception as exc:
        logger.debug("[S13] ka10004 호가 조회 실패 [%s]: %s", stk_cd, exc)
        return {}

async def scan_box_breakout(token: str, rdb=None) -> list:
    """
    S13: 거래량 폭발 박스권 돌파 전략
    - 박스권 수렴 후 볼린저 밴드 스퀴즈 상태에서 대량 거래와 함께 돌파하는 종목 포착
    """
    candidates: list[str] = []
    if rdb:
        try:
            # Java Orchestrator가 적재한 후보 풀 조회 (S8: 소폭상승 + S10: 신고가 근접 종목군)
            kospi = await rdb.lrange("candidates:s13:001", 0, max(0, _POOL_READ_LIMIT - 1))
            kosdaq = await rdb.lrange("candidates:s13:101", 0, max(0, _POOL_READ_LIMIT - 1))
            candidates = list(dict.fromkeys(kospi + kosdaq))[:_SCAN_LIMIT]
        except Exception as e:
            logger.error(f"[S13] 후보 풀 로드 실패: {e}")

    if not candidates:
        logger.info("[S13][scan_summary] candidate_count=0 pass=0 rejects={'no_candidates': 1}")
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
        await asyncio.sleep(_API_INTERVAL)  # API 호출 제한 준수

        # 1. 일봉 데이터 확보 (최소 120봉 확보 권장 - MA120 계산용)
        candles = await fetch_daily_candles(token, stk_cd, target_count=130)
        if len(candles) < 60:
            _reject("short_candles", stk_cd, candles=len(candles))
            continue

        evaluated_count += 1

        # 데이터 파싱
        closes = [_safe_price(c.get("cur_prc")) for c in candles]
        opens  = [_safe_price(c.get("open_pric")) for c in candles]
        highs  = [_safe_price(c.get("high_pric")) for c in candles]
        lows   = [_safe_price(c.get("low_pric")) for c in candles]
        vols   = [_safe_vol(c.get("trde_qty")) for c in candles]

        cur_prc = closes[0]
        if cur_prc <= 0:
            _reject("invalid_cur_prc", stk_cd)
            continue

        # 2. 박스권 돌파 검증 (detect_box_breakout 유틸 활용 — 박스 형태·가격 돌파만 판정, 거래량은 아래 4번에서 별도 확인)
        is_breakout, box_range_pct = detect_box_breakout(
            candles, box_period=BOX_PERIOD, max_range_pct=MAX_BOX_RANGE
        )
        if not is_breakout:
            _reject("not_breakout", stk_cd, box_range_pct=round(box_range_pct, 2))
            continue

        # 3. 이평선 필터링 (MA20 위 돌파 & MA120 저항선 체크)
        ma20 = _calc_ma(closes, 20)
        ma120 = _calc_ma(closes, 120)

        if cur_prc < ma20:
            _reject("below_ma20", stk_cd, cur_prc=round(cur_prc), ma20=round(ma20, 2))
            continue # 추세 하단 돌파는 제외

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
        daily_volume_ratio = vol_today / vol_avg_15 if vol_avg_15 > 0 else 1.0

        # 전일 동시간대 거래량 비교(ka10055) — 장중 시점과 무관하게 공정한 거래량
        # 급증 판정. 실패/불완전 시 위 daily_volume_ratio(당일누적/15일평균)로 폴백.
        volume_summary = {}
        same_time_volume_meta = {}
        try:
            await asyncio.sleep(_API_INTERVAL)
            volume_summary, same_time_volume_meta = await fetch_same_time_volume_ratio_cached(token, stk_cd, rdb=rdb)
        except Exception as e:
            same_time_volume_meta = {"api_id": "ka10055", "error": str(e)}
        vol_ratio, volume_ratio_source = resolve_effective_volume_ratio(
            daily_volume_ratio, volume_summary, same_time_volume_meta,
        )
        if vol_ratio < VOL_MUL:
            _reject("volume_surge_gate", stk_cd, vol_ratio=round(vol_ratio, 2), source=volume_ratio_source)
            continue

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

        # 6. RSI 계산
        rsi_vals = calc_rsi(closes, 14)
        rsi_now = rsi_vals[0] if rsi_vals else 0.0

        # 7. 실시간 데이터 결합 (Redis Tick)
        flu_rt = 0.0
        cntr_str = 100.0
        if rdb:
            tick_result = await get_tick_with_status(rdb, stk_cd)
            tick = tick_result["data"]
            if tick:
                flu_rt = float(str(tick.get("flu_rt", "0")).replace("+", ""))
                cntr_str = float(str(tick.get("cntr_str", "100")))

        # 과도한 급등(상한가 등) 노이즈 제거
        if not (0 < flu_rt <= 20.0) or cntr_str < MIN_CNTR_STR:
            _reject("flu_or_cntr_str_gate", stk_cd, flu_rt=round(flu_rt, 2), cntr_str=round(cntr_str, 1))
            continue

        # 8. 스코어링 시스템 (S13 특화)
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

        box_upper = max(highs[1:BOX_PERIOD + 1]) if len(highs) > BOX_PERIOD else 0
        box_lower = min(lows[1:BOX_PERIOD + 1]) if len(lows) > BOX_PERIOD else 0
        box_breakout_extension_pct = (
            (cur_prc - box_upper) / box_upper * 100 if box_upper > 0 else 0.0
        )
        pre_breakout_avg_3 = sum(vols[1:4]) / 3 if len(vols) >= 4 else 0
        pre_breakout_avg_15 = sum(vols[1:16]) / 15 if len(vols) >= 16 else 0
        pre_breakout_volume_contraction = (
            pre_breakout_avg_15 > 0 and pre_breakout_avg_3 < pre_breakout_avg_15 * 0.8
        )
        breakout_failure = cur_prc < box_upper if box_upper > 0 else False
        near_resistance = resistance_penalty > 0

        # ATR 계산 (존 너비 보정 및 zone 계산에 활용)
        atr_val = None
        if len(highs) >= 15 and len(lows) >= 15 and len(closes) >= 15:
            atr_vals = calc_atr(highs, lows, closes, 14)
            atr_val = atr_vals[0]

        # 동적 TP/SL 계산 (highs/lows/closes 이미 추출됨)
        tp_sl = calc_tp_sl("S13_BOX_BREAKOUT", cur_prc, highs, lows, closes,
                            stk_cd=stk_cd, atr=atr_val, ma20=ma20,
                            compute_zones=True)

        await asyncio.sleep(_API_INTERVAL)
        hoga_raw = await _fetch_hoga_raw_s13(token, stk_cd)
        await asyncio.sleep(_API_INTERVAL)
        minute_raw = await _fetch_minute_chart_raw_s13(token, stk_cd, scope=5)

        eq_result = assess_execution_quality(
            stk_cd,
            float(cur_prc),
            hoga_raw,
            minute_raw,
            "S13",
            extra={"box_breakout_extension_pct": box_breakout_extension_pct},
        )
        if should_hard_reject(eq_result):
            logger.debug("[S13] execution_quality REJECT skip [%s]", stk_cd)
            _reject("execution_quality_reject", stk_cd, reason=eq_result.get("reject_reason"))
            continue

        signal_mode = "SHADOW" if (
            eq_result["execution_quality"] == "REJECT"
            or near_resistance
            or box_breakout_extension_pct > 3.0
        ) else "NORMAL"
        program_snapshot = await fetch_program_snapshot(rdb, stk_cd)
        program_reason = program_drop_reason(program_snapshot)
        volume_profile, volume_profile_meta = await fetch_volume_profile(token, stk_cd)

        signal = {
            "stk_cd": stk_cd,
            "stk_nm": stk_nm,
            "cur_prc": round(cur_prc),
            "strategy": "S13_BOX_BREAKOUT",
            "score": round(score, 2),
            "flu_rt": round(flu_rt, 2),
            "cntr_strength": round(cntr_str, 1),
            "vol_ratio": round(vol_ratio, 2),
            "daily_volume_ratio": round(daily_volume_ratio, 2),
            "volume_ratio_source": volume_ratio_source,
            "same_time_volume_ratio": round(float(volume_summary.get("same_time_volume_ratio") or 0.0), 2),
            "rsi": round(rsi_now, 1),
            "atr": round(atr_val, 2) if atr_val is not None else None,
            "is_monster_vol": is_monster_vol,
            "bollinger_squeeze": bollinger_squeeze,
            "mfi_confirmed": mfi_confirmed,
            "signal_mode": signal_mode,
            "box_upper": round(box_upper) if box_upper else None,
            "box_lower": round(box_lower) if box_lower else None,
            "box_range_pct": round(box_range_pct, 2),
            "box_breakout_extension_pct": round(box_breakout_extension_pct, 2),
            "pre_breakout_volume_contraction": pre_breakout_volume_contraction,
            "breakout_failure": breakout_failure,
            "near_resistance": near_resistance,
            "spread_pct": eq_result["spread_pct"],
            "depth_score": eq_result["depth_score"],
            "sell_wall_score": eq_result["sell_wall_score"],
            "vwap_position": eq_result["vwap_position"],
            "first_low_break": eq_result["first_low_break"],
            "breakout_line_break": eq_result["breakout_line_break"],
            "upper_shadow_pct": eq_result["upper_shadow_pct"],
            "close_position_pct": eq_result["close_position_pct"],
            "chase_risk_score": eq_result["chase_risk_score"],
            "execution_quality": eq_result["execution_quality"],
            "reject_reason": eq_result["reject_reason"],
            "entry_type": "당일종가_또는_익일눌림",
            "holding_days": "3~7거래일",
            **tp_sl.to_signal_fields(),
        }
        signal.update(program_snapshot)
        if program_reason:
            signal["program_drop_reason"] = program_reason
        signal["volume_profile_meta"] = volume_profile_meta
        signal = apply_volume_profile_rr(signal, volume_profile)
        signal["effective_rr"] = signal.get("rr_ratio")
        logger.info(
            "[S13][pass] stk=%s score=%.2f flu_rt=%.2f cntr=%.1f box_range_pct=%.2f signal_mode=%s",
            stk_cd, score, flu_rt, cntr_str, box_range_pct, signal_mode,
        )
        results.append(signal)

    # 스코어 기준 내림차순 정렬 후 상위 5개 반환
    sorted_results = sorted(results, key=lambda x: x["score"], reverse=True)[:5]
    logger.info(
        "[S13][scan_summary] candidate_count=%d evaluated=%d pass=%d returned=%d rejects=%s samples=%s",
        len(candidates),
        evaluated_count,
        len(results),
        len(sorted_results),
        dict(reject_counts),
        {key: value for key, value in reject_samples.items()},
    )
    return sorted_results
