"""
scorer.py
Claude API 호출 전 규칙 기반 1차 스코어링.
낮은 점수는 Claude API 호출 없이 CANCEL 처리하여 비용 절감.
전략별 임계값 + 일별 호출 상한을 적용한다.
"""

import json
import logging
import os
import time
from datetime import date, datetime

logger  = logging.getLogger(__name__)
MIN_SCORE = float(os.getenv("AI_SCORE_THRESHOLD", "60.0"))

# 전략별 Claude 호출 임계값
CLAUDE_THRESHOLDS = {
    # 데이 트레이딩 전략 — 현행 유지
    "S1_GAP_OPEN":      70,
    "S2_VI_PULLBACK":   65,
    "S3_INST_FRGN":     60,
    "S4_BIG_CANDLE":    75,
    "S5_PROG_FRGN":     65,
    "S6_THEME_LAGGARD": 60,
    "S7_AUCTION":       70,
    # 스윙 전략 — signal 필드 보완 + bid_ratio 중립화 후 재조정
    "S8_GOLDEN_CROSS":     60,   # 65 → 60
    "S9_PULLBACK_SWING":   55,   # 60 → 55
    "S10_NEW_HIGH":        58,   # 65 → 58
    "S11_FRGN_CONT":       58,   # 60 → 58
    "S12_CLOSING":         60,   # 65 → 60
    "S13_BOX_BREAKOUT":    62,   # 65 → 62
    "S14_OVERSOLD_BOUNCE": 58,   # 65 → 58
    "S15_MOMENTUM_ALIGN":  65,   # 70 → 65
}

MAX_CLAUDE_CALLS_PER_DAY = int(os.getenv("MAX_CLAUDE_CALLS_PER_DAY", "100"))


def _safe_float(v, default=0.0) -> float:
    try:
        return float(str(v).replace(",", "").replace("+", ""))
    except (TypeError, ValueError):
        return default


def _time_bonus(strategy: str) -> float:
    """
    시간대별 전략 보너스 점수 (+0~5점).
    장 시간 외에는 0 반환.
    """
    now = datetime.now()
    h, m = now.hour, now.minute
    minute_of_day = h * 60 + m

    # 09:00~09:30: 갭 개장·경매 전략 최적 시간대
    if 540 <= minute_of_day < 570:
        if strategy in ("S1_GAP_OPEN", "S7_AUCTION"):
            return 5.0

    # 09:00~10:30: 크로스/돌파 전략 초반 모멘텀
    if 540 <= minute_of_day < 630:
        if strategy in ("S8_GOLDEN_CROSS", "S9_PULLBACK_SWING", "S13_BOX_BREAKOUT"):
            return 5.0

    # 09:30~11:30: 테마 모멘텀 집중 시간대 (테마 후발주는 장 초반 에너지가 강함)
    if 570 <= minute_of_day < 690:
        if strategy == "S6_THEME_LAGGARD":
            return 5.0

    # 10:00~13:00: 52주 신고가·외인 연속 스윙 신호 포착 최적 시간대
    if 600 <= minute_of_day < 780:
        if strategy in ("S10_NEW_HIGH", "S11_FRGN_CONT"):
            return 5.0

    # 14:30~15:30: 종가강도 전략 최적 시간대
    if 870 <= minute_of_day < 930:
        if strategy == "S12_CLOSING":
            return 5.0

    # 10:00~13:00: 과매도 반등 — 패닉 저점 이후 회복 구간
    if 600 <= minute_of_day < 780:
        if strategy == "S14_OVERSOLD_BOUNCE":
            return 5.0

    # 09:30~12:00: 모멘텀 정렬 — 지표 동조 후 초기 진입 최적
    if 570 <= minute_of_day < 720:
        if strategy == "S15_MOMENTUM_ALIGN":
            return 5.0

    return 0.0


def rule_score(signal: dict, market_ctx: dict) -> tuple[float, dict]:
    """
    signal: TradingSignalDto 직렬화 JSON
    market_ctx: {
        "tick":    ws:tick Hash,
        "hoga":    ws:hoga Hash,
        "strength": float (평균 체결강도),
        "vi":      vi Hash,
    }
    반환: (0~100 점수, 컴포넌트 상세 dict)
    컴포넌트 dict 구조:
    {
        "vol_score": float,       # 거래량 관련
        "momentum_score": float,  # 모멘텀 (등락률, 체결강도)
        "technical_score": float, # 기술지표 (RSI, MA 등)
        "demand_score": float,    # 수급 (호가, 기관/외인)
        "risk_penalty": float,    # 리스크 패널티
        "strategy_specific": dict, # 전략별 특화 데이터
    }
    """
    strategy = signal.get("strategy", "")
    score    = 0.0

    strength = market_ctx.get("strength", 100.0)
    tick     = market_ctx.get("tick", {})
    hoga     = market_ctx.get("hoga", {})

    rsi      = _safe_float(signal.get("rsi", 0))
    atr_pct  = _safe_float(signal.get("atr_pct", 0))
    cond_cnt = int(signal.get("cond_count", 0) or 0)

    # bid_ratio: hoga dict가 비어있으면 WS 데이터 없음 → None (0점 아닌 스킵)
    _hoga_available = bool(hoga)
    bid  = _safe_float(hoga.get("total_buy_bid_req", 0))
    ask  = _safe_float(hoga.get("total_sel_bid_req", 1))
    bid_ratio = (bid / ask) if (_hoga_available and ask > 0) else None

    flu_rt = _safe_float(tick.get("flu_rt"))

    # 컴포넌트별 누적 변수
    _vol_score      = 0.0
    _momentum_score = 0.0
    _technical_score = 0.0
    _demand_score   = 0.0
    _strategy_data  = {}

    match strategy:
        case "S1_GAP_OPEN":
            gap = _safe_float(signal.get("gap_pct", 0))
            _gap_sc = 20 if 3 <= gap < 5 else (15 if 5 <= gap < 8 else (10 if 8 <= gap < 15 else (-10 if gap >= 15 else 0)))
            _str_sc = 30 if strength > 150 else (20 if strength > 130 else (10 if strength > 110 else 0))
            _bid_sc = 0.0
            if bid_ratio is not None:
                _bid_sc = 25 if bid_ratio > 2 else (20 if bid_ratio > 1.5 else (10 if bid_ratio > 1.3 else 0))
            cntr_sig = _safe_float(signal.get("cntr_strength", 0))
            _cntr_sc = (10 if cntr_sig > 150 else (5 if cntr_sig > 130 else 0)) if cntr_sig > 0 else 0
            score += _gap_sc + _str_sc + _bid_sc + _cntr_sc
            _momentum_score += _str_sc + _cntr_sc
            _demand_score   += _bid_sc
            _strategy_data = {"gap_pct": gap, "gap_score": _gap_sc}

        case "S2_VI_PULLBACK":
            pullback = abs(_safe_float(signal.get("pullback_pct", 0)))
            _pb_sc = 30 if 1.0 <= pullback < 2.0 else (20 if pullback < 3.0 else 0)
            is_dynamic = bool(signal.get("is_dynamic", False))
            _dyn_sc = 15 if is_dynamic else 0
            cntr_sig_s2 = _safe_float(signal.get("cntr_strength", 0))
            effective_str_s2 = cntr_sig_s2 if cntr_sig_s2 > 0 else strength
            _str_sc = 20 if effective_str_s2 > 120 else (10 if effective_str_s2 > 110 else 0)
            s2_bid = bid_ratio if bid_ratio is not None else (
                _safe_float(signal.get("bid_ratio", -1), -1) if signal.get("bid_ratio") is not None else None
            )
            _bid_sc = 0.0
            if s2_bid is not None and s2_bid >= 0:
                _bid_sc = 20 if s2_bid > 1.5 else (10 if s2_bid > 1.3 else 0)
            score += _pb_sc + _dyn_sc + _str_sc + _bid_sc
            _momentum_score += _pb_sc + _str_sc + _dyn_sc
            _demand_score   += _bid_sc
            _strategy_data = {"pullback_pct": pullback, "is_dynamic": is_dynamic}

        case "S3_INST_FRGN":
            net_amt   = _safe_float(signal.get("net_buy_amt", 0))
            cont_days = int(signal.get("continuous_days", 0) or 0)
            vol_ratio = _safe_float(signal.get("vol_ratio", 0))
            # net_buy_amt: 원(KRW) 기준. 10억(1B) 이상에서 만점(25pt)
            _net_sc  = min(25, net_amt / 1_000_000_000 * 25)
            _cont_sc = 30 if cont_days >= 5 else (20 if cont_days >= 3 else (10 if cont_days >= 1 else 0))
            _vol_sc  = 25 if vol_ratio >= 3 else (20 if vol_ratio >= 2 else (10 if vol_ratio >= 1.5 else 0))
            score += _net_sc + _cont_sc + _vol_sc
            _demand_score += _net_sc + _cont_sc
            _vol_score    += _vol_sc
            _strategy_data = {"net_buy_amt": net_amt, "continuous_days": cont_days, "vol_ratio": vol_ratio}

        case "S4_BIG_CANDLE":
            vol_ratio  = _safe_float(signal.get("vol_ratio", 0))
            body_ratio = _safe_float(signal.get("body_ratio", 0))
            _vol_sc  = 25 if vol_ratio > 10 else (20 if vol_ratio > 5 else (10 if vol_ratio > 3 else 0))
            _body_sc = 20 if body_ratio >= 0.8 else (10 if body_ratio >= 0.7 else (5 if body_ratio >= 0.65 else 0))
            _high_sc = 20 if signal.get("is_new_high") else 0
            _str_sc  = 20 if strength > 150 else (15 if strength > 140 else (5 if strength > 120 else 0))
            score += _vol_sc + _body_sc + _high_sc + _str_sc
            _vol_score      += _vol_sc
            _momentum_score += _str_sc + _body_sc + _high_sc
            _strategy_data = {"vol_ratio": vol_ratio, "body_ratio": body_ratio, "is_new_high": bool(signal.get("is_new_high"))}

        case "S5_PROG_FRGN":
            net_amt = _safe_float(signal.get("net_buy_amt", 0))
            # net_buy_amt: 원(KRW) 기준. 1000억(100B) 이상에서 만점(40pt)
            _net_sc = min(40, net_amt / 100_000_000_000 * 40)
            # WS 오프라인 시 체결강도 미지 → 중립 10점 부여 (기회비용 방어)
            ws_online_s5 = market_ctx.get("ws_online", True)
            if not ws_online_s5 and strength == 100.0:
                _str_sc = 10  # 중립 점수
            else:
                _str_sc = 25 if strength > 130 else (20 if strength > 120 else (10 if strength > 100 else 0))
            _bid_sc = 0.0
            if bid_ratio is not None:
                _bid_sc = 20 if bid_ratio > 2 else (15 if bid_ratio > 1.5 else (8 if bid_ratio > 1.2 else 0))
            score += _net_sc + _str_sc + _bid_sc
            _demand_score   += _net_sc + _bid_sc
            _momentum_score += _str_sc
            _strategy_data = {"net_buy_amt": net_amt}

        case "S6_THEME_LAGGARD":
            flu_rt_s6 = _safe_float(signal.get("flu_rt", 0))
            cntr_sig = _safe_float(signal.get("cntr_strength", 0))
            _flu_sc = 25 if 1 <= flu_rt_s6 < 3 else (15 if 3 <= flu_rt_s6 < 5 else 0)
            effective_strength = cntr_sig if cntr_sig > 0 else strength
            _str_sc = 30 if effective_strength > 150 else (20 if effective_strength > 120 else 0)
            _bid_sc = 0.0
            if bid_ratio is not None:
                _bid_sc = 20 if bid_ratio > 1.5 else (10 if bid_ratio > 1.2 else 0)
            score += _flu_sc + _str_sc + _bid_sc
            _momentum_score += _flu_sc + _str_sc
            _demand_score   += _bid_sc
            _strategy_data = {"flu_rt": flu_rt_s6, "theme_name": signal.get("theme_name", "")}

        case "S7_AUCTION":
            gap = _safe_float(signal.get("gap_pct", 0))
            _gap_sc = 25 if 2 <= gap < 5 else (15 if 5 <= gap < 8 else 0)
            s7_bid = bid_ratio if bid_ratio is not None else (
                _safe_float(signal.get("bid_ratio", -1), -1) if signal.get("bid_ratio") is not None else None
            )
            _bid_sc = 0.0
            if s7_bid is not None and s7_bid >= 0:
                _bid_sc = 30 if s7_bid > 3 else (25 if s7_bid > 2 else (10 if s7_bid > 1.5 else 0))
            vol_rank = int(signal.get("vol_rank", 999) or 999)
            _vr_sc = 20 if vol_rank <= 10 else (15 if vol_rank <= 20 else (5 if vol_rank <= 30 else 0))
            score += _gap_sc + _bid_sc + _vr_sc
            _momentum_score += _gap_sc
            _demand_score   += _bid_sc
            _vol_score      += _vr_sc
            _strategy_data = {"gap_pct": gap, "vol_rank": vol_rank}

        case "S10_NEW_HIGH":
            vol_surge = _safe_float(signal.get("vol_surge_rt", 0))
            if vol_surge == 0:
                vol_ratio_java = _safe_float(signal.get("vol_ratio", 0))
                vol_surge = max(0.0, (vol_ratio_java - 1.0) * 100)
            _vol_sc = 30 if vol_surge >= 300 else (20 if vol_surge >= 200 else (10 if vol_surge >= 100 else 0))
            flu_rt_s10 = flu_rt if flu_rt != 0 else _safe_float(signal.get("flu_rt", 0))
            _flu_sc = 20 if 2 <= flu_rt_s10 <= 8 else (10 if 0 < flu_rt_s10 <= 15 else (-10 if flu_rt_s10 > 15 else 0))
            _base_bonus = 8
            cntr_sig_s10 = _safe_float(signal.get("cntr_strength", 0))
            effective_str_s10 = cntr_sig_s10 if cntr_sig_s10 > 0 else strength
            _str_sc = (30 if effective_str_s10 > 130 else 20 if effective_str_s10 > 110
                       else 12 if effective_str_s10 > 90 else 6 if effective_str_s10 > 70 else 0)
            _bid_sc = 0.0
            sig_bid = signal.get("bid_ratio")
            if sig_bid is not None:
                sig_bid_f = _safe_float(sig_bid, -1.0)
                if sig_bid_f >= 0:
                    _bid_sc = 10 if sig_bid_f > 1.5 else (5 if sig_bid_f > 1.2 else 0)
            score += _vol_sc + _flu_sc + _base_bonus + _str_sc + _bid_sc
            _vol_score      += _vol_sc
            _momentum_score += _flu_sc + _str_sc + _base_bonus
            _demand_score   += _bid_sc
            _strategy_data  = {"vol_surge_rt": vol_surge, "flu_rt": flu_rt_s10, "new_high_bonus": _base_bonus}

        case "S11_FRGN_CONT":
            dm1 = _safe_float(signal.get("dm1", 0))
            dm2 = _safe_float(signal.get("dm2", 0))
            dm3 = _safe_float(signal.get("dm3", 0))
            cont_days = sum(1 for d in (dm1, dm2, dm3) if d > 0)
            _cont_sc = 30 if cont_days >= 3 else (20 if cont_days >= 2 else 0)
            flu_rt_s11 = flu_rt if flu_rt != 0 else _safe_float(signal.get("flu_rt", 0))
            _flu_sc = 20 if flu_rt_s11 > 0 else (-10 if flu_rt_s11 < -3 else 0)
            cntr_sig_s11 = _safe_float(signal.get("cntr_strength", 0))
            effective_str_s11 = cntr_sig_s11 if cntr_sig_s11 > 0 else strength
            _str_sc = 30 if effective_str_s11 > 120 else (20 if effective_str_s11 > 100 else 0)
            score += _cont_sc + _flu_sc + _str_sc
            _demand_score   += _cont_sc
            _momentum_score += _flu_sc + _str_sc
            _strategy_data  = {"cont_days": cont_days, "dm1": dm1, "dm2": dm2, "dm3": dm3}

        case "S12_CLOSING":
            cntr_str_sig = _safe_float(signal.get("cntr_strength", 0))
            effective_str = cntr_str_sig if cntr_str_sig > 0 else strength
            flu_rt_s12 = flu_rt if flu_rt != 0 else _safe_float(signal.get("flu_rt", 0))
            _flu_sc = 30 if 4 <= flu_rt_s12 <= 10 else (15 if 10 < flu_rt_s12 <= 15 else (-10 if flu_rt_s12 > 15 else 0))
            _str_sc = 35 if effective_str >= 130 else (25 if effective_str >= 110 else (10 if effective_str >= 100 else 0))
            buy_req = _safe_float(signal.get("buy_req", 0))
            sel_req = _safe_float(signal.get("sel_req", 0))
            local_bid_ratio = (buy_req / sel_req) if (sel_req > 0 and buy_req > 0) else bid_ratio
            _bid_sc = 0.0
            if local_bid_ratio is not None:
                _bid_sc = 20 if local_bid_ratio > 1.5 else (10 if local_bid_ratio > 1.2 else 0)
            score += _flu_sc + _str_sc + _bid_sc
            _momentum_score += _flu_sc + _str_sc
            _demand_score   += _bid_sc
            _strategy_data  = {"flu_rt": flu_rt_s12, "cntr_strength": effective_str}

        case "S8_GOLDEN_CROSS":
            flu_rt_s8 = flu_rt if flu_rt != 0 else _safe_float(signal.get("flu_rt", 0))
            cntr_sig = _safe_float(signal.get("cntr_strength", 0))
            effective_str = cntr_sig if cntr_sig > 0 else strength
            vol_ratio_s8 = _safe_float(signal.get("vol_ratio", 0))
            _flu_sc = 25 if 1 <= flu_rt_s8 <= 5 else (15 if 5 < flu_rt_s8 <= 10 else 0)
            _vol_sc = 20 if vol_ratio_s8 >= 3.0 else (12 if vol_ratio_s8 >= 1.5 else (5 if vol_ratio_s8 >= 1.0 else 0))
            _str_sc = 30 if effective_str > 130 else (20 if effective_str > 110 else (10 if effective_str > 100 else 0))
            _bid_sc = 0.0
            if bid_ratio is not None:
                _bid_sc = 15 if bid_ratio > 1.5 else (8 if bid_ratio > 1.2 else 0)
            _rsi_sc = (10 if rsi > 55 else (5 if rsi > 50 else 0)) if rsi > 0 else 0
            _cross_sc = 10 if bool(signal.get("is_today_cross", False)) else 0
            _macd_sc  = 8  if bool(signal.get("is_macd_accel", False)) else 0
            score += _flu_sc + _vol_sc + _str_sc + _bid_sc + _rsi_sc + _cross_sc + _macd_sc
            _momentum_score  += _flu_sc + _str_sc
            _vol_score       += _vol_sc
            _technical_score += _rsi_sc + _cross_sc + _macd_sc
            _demand_score    += _bid_sc
            _strategy_data   = {"is_today_cross": bool(signal.get("is_today_cross")),
                                 "is_macd_accel": bool(signal.get("is_macd_accel")),
                                 "vol_ratio": vol_ratio_s8, "gc_score": _cross_sc}

        case "S9_PULLBACK_SWING":
            flu_rt_s9 = flu_rt if flu_rt != 0 else _safe_float(signal.get("flu_rt", 0))
            cntr_sig = _safe_float(signal.get("cntr_strength", 0))
            effective_str = cntr_sig if cntr_sig > 0 else strength
            _flu_sc = 30 if 0.5 <= flu_rt_s9 <= 3 else (20 if 3 < flu_rt_s9 <= 6 else (10 if 6 < flu_rt_s9 <= 10 else 0))
            _str_sc = 35 if effective_str > 130 else (25 if effective_str > 110 else (10 if effective_str > 100 else 0))
            _bid_sc = 0.0
            if bid_ratio is not None:
                _bid_sc = 20 if bid_ratio > 1.5 else (10 if bid_ratio > 1.2 else 0)
            _rsi_sc = (15 if 40 <= rsi <= 52 else (8 if 52 < rsi <= 62 else (3 if 30 <= rsi < 40 else 0))) if rsi > 0 else 0
            pct_ma5 = _safe_float(signal.get("pct_ma5", 999))
            _ma_sc  = (15 if -1.0 <= pct_ma5 <= 2.0 else (8 if abs(pct_ma5) <= 4.0 else 0)) if pct_ma5 != 999 else 0
            _stoch_sc = 10 if bool(signal.get("stoch_gc", False)) else 0
            score += _flu_sc + _str_sc + _bid_sc + _rsi_sc + _ma_sc + _stoch_sc
            _momentum_score  += _flu_sc + _str_sc
            _technical_score += _rsi_sc + _ma_sc + _stoch_sc
            _demand_score    += _bid_sc
            _strategy_data   = {"pct_ma5": pct_ma5, "stoch_gc": bool(signal.get("stoch_gc")), "flu_rt": flu_rt_s9}

        case "S13_BOX_BREAKOUT":
            flu_rt_s13 = flu_rt if flu_rt != 0 else _safe_float(signal.get("flu_rt", 0))
            cntr_sig = _safe_float(signal.get("cntr_strength", 0))
            effective_str = cntr_sig if cntr_sig > 0 else strength
            _flu_sc  = 30 if 3 <= flu_rt_s13 <= 8 else (20 if 8 < flu_rt_s13 <= 15 else 0)
            _str_sc  = 35 if effective_str > 150 else (25 if effective_str > 130 else (10 if effective_str > 110 else 0))
            _bid_sc  = 0.0
            if bid_ratio is not None:
                _bid_sc = 25 if bid_ratio > 2 else (15 if bid_ratio > 1.5 else (5 if bid_ratio > 1.2 else 0))
            _rsi_sc  = (10 if rsi > 60 else (5 if rsi > 50 else 0)) if rsi > 0 else 0
            _bb_sc   = 10 if bool(signal.get("bollinger_squeeze", False)) else 0
            _mfi_sc  = 8  if bool(signal.get("mfi_confirmed", False)) else 0
            score += _flu_sc + _str_sc + _bid_sc + _rsi_sc + _bb_sc + _mfi_sc
            _momentum_score  += _flu_sc + _str_sc
            _demand_score    += _bid_sc
            _technical_score += _rsi_sc + _bb_sc + _mfi_sc
            _strategy_data   = {"flu_rt": flu_rt_s13, "bollinger_squeeze": bool(signal.get("bollinger_squeeze")),
                                 "mfi_confirmed": bool(signal.get("mfi_confirmed"))}

        case "S14_OVERSOLD_BOUNCE":
            cntr_sig = _safe_float(signal.get("cntr_strength", 0))
            effective_str = cntr_sig if cntr_sig > 0 else strength
            _rsi_sc = (40 if rsi < 25 else (30 if rsi < 30 else (20 if rsi < 35 else (10 if rsi < 40 else 0)))) if rsi > 0 else 15
            _atr_sc = 15 if 1.0 <= atr_pct <= 2.5 else (5 if 0.5 <= atr_pct < 1.0 else (-5 if atr_pct > 3.0 else 0))
            _str_sc = 25 if effective_str > 120 else (15 if effective_str > 110 else (5 if effective_str > 100 else 0))
            _bid_sc = 0.0
            if bid_ratio is not None:
                _bid_sc = 15 if bid_ratio > 1.5 else (8 if bid_ratio > 1.2 else 0)
            score += _rsi_sc + _atr_sc + _str_sc + _bid_sc
            _technical_score += _rsi_sc + _atr_sc
            _momentum_score  += _str_sc
            _demand_score    += _bid_sc
            _strategy_data   = {"rsi": rsi, "atr_pct": atr_pct, "rsi_score": _rsi_sc, "cond_count": cond_cnt}

        case "S15_MOMENTUM_ALIGN":
            cntr_sig = _safe_float(signal.get("cntr_strength", 0))
            effective_str = cntr_sig if cntr_sig > 0 else strength
            vol_ratio_s15 = _safe_float(signal.get("vol_ratio", 0))
            flu_rt_s15 = flu_rt if flu_rt != 0 else _safe_float(signal.get("flu_rt", 0))
            _rsi_sc = (35 if 50 <= rsi <= 65 else (25 if 65 < rsi <= 75 else (10 if 45 <= rsi < 50 else 0))) if rsi > 0 else 0
            _vol_sc = 25 if vol_ratio_s15 >= 3.0 else (18 if vol_ratio_s15 >= 2.0 else (10 if vol_ratio_s15 >= 1.5 else 0))
            _str_sc = 25 if effective_str > 130 else (18 if effective_str > 110 else (8 if effective_str > 100 else 0))
            _bid_sc = 0.0
            if bid_ratio is not None:
                _bid_sc = 15 if bid_ratio > 1.5 else (8 if bid_ratio > 1.2 else 0)
            _flu_sc = 5 if 1 <= flu_rt_s15 <= 5 else (3 if 5 < flu_rt_s15 <= 8 else 0)
            score += _rsi_sc + _vol_sc + _str_sc + _bid_sc + _flu_sc
            _technical_score += _rsi_sc
            _vol_score       += _vol_sc
            _momentum_score  += _str_sc + _flu_sc
            _demand_score    += _bid_sc
            _strategy_data   = {"rsi": rsi, "vol_ratio": vol_ratio_s15, "flu_rt": flu_rt_s15}

    # 조건 충족 수 보너스
    _cond_bonus = 10 if cond_cnt >= 4 else (5 if cond_cnt == 3 else 0)
    score += _cond_bonus
    _technical_score += _cond_bonus

    # 시간대 보너스
    _tb = _time_bonus(strategy)
    score += _tb

    # 공통 페널티
    flu_rt_for_penalty = flu_rt if flu_rt != 0 else _safe_float(signal.get("flu_rt", 0))
    _risk_penalty = 0.0
    if flu_rt_for_penalty > 15:
        _risk_penalty = -20.0
    elif flu_rt_for_penalty > 10:
        _risk_penalty = -10.0
    if flu_rt_for_penalty < -5:
        _risk_penalty += -15.0
    score += _risk_penalty

    score = round(max(0.0, min(100.0, score)), 1)

    components = {
        "vol_score":       round(_vol_score, 2),
        "momentum_score":  round(_momentum_score, 2),
        "technical_score": round(_technical_score, 2),
        "demand_score":    round(_demand_score, 2),
        "time_bonus":      round(_tb, 2),
        "risk_penalty":    round(_risk_penalty, 2),
        "strategy_specific": _strategy_data,
    }

    logger.info(json.dumps({
        "ts": time.time(), "module": "scorer",
        "strategy": strategy, "stk_cd": signal.get("stk_cd", ""),
        "score": score,
    }))
    return score, components


def get_claude_threshold(strategy: str) -> float:
    """전략별 Claude 호출 임계값 반환"""
    return float(CLAUDE_THRESHOLDS.get(strategy, 65))


def should_skip_ai(score: float, strategy: str = "") -> bool:
    """
    Claude API 호출을 건너뛸지 결정.
    전략별 임계값 사용, strategy 미지정 시 기본 MIN_SCORE 적용.
    """
    threshold = get_claude_threshold(strategy) if strategy else MIN_SCORE
    return score < threshold


async def check_daily_limit(rdb) -> bool:
    """
    일별 Claude 호출 상한 확인.
    반환: True = 한도 내 (호출 가능), False = 한도 초과 (건너뜀)
    """
    today_str = date.today().strftime("%Y%m%d")
    key = f"claude:daily_calls:{today_str}"
    try:
        count = await rdb.incr(key)
        if count == 1:
            await rdb.expire(key, 86400)
        if count > MAX_CLAUDE_CALLS_PER_DAY:
            logger.warning("[Scorer] 일별 Claude 호출 상한 초과 (%d/%d) – 건너뜀",
                           count, MAX_CLAUDE_CALLS_PER_DAY)
            return False
        return True
    except Exception as e:
        logger.error("[Scorer] 일별 카운터 오류: %s – 호출 허용으로 처리", e)
        return True
