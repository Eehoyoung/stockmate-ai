"""
overnight_scorer.py
오버나잇 보유 / 강제청산 여부를 규칙 기반으로 판단하는 스코어링 엔진.
Claude API 미사용 — 실시간 시세 + 포지션 정보 + 기술지표 캐시로 판단.

점수 구성 (베이스 50점):
  1. Java overnight_score 반영   -15 ~ +15
  2. 미실현 P&L                  -25 ~ +15
  3. 체결강도                    -10 ~ +10
  4. 호가비율(매수/매도)          -10 ~ +8
  5. 당일 등락률                  -8 ~ +5
  6. 전략별 오버나잇 적합도       -10 ~ +10
  7. RSI(14) — 캐시 히트 시만    -10 ~ +5
  8. MA 배열   — 캐시 히트 시만   -5 ~ +8

합산 점수 → 판단:
  >= 65 : HOLD, HIGH
  55~65 : HOLD, MEDIUM
  45~55 : FORCE_CLOSE, LOW     (아슬아슬하게 청산)
  < 45  : FORCE_CLOSE, MEDIUM  (명확하게 청산)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# 오버나잇 친화적인 스윙 전략
_SWING_FRIENDLY = {
    "S8_GOLDEN_CROSS", "S9_PULLBACK_SWING", "S10_NEW_HIGH",
    "S11_FRGN_CONT",   "S13_BOX_BREAKOUT",
}
# 오버나잇 중립 전략
_NEUTRAL = {
    "S3_INST_FRGN", "S5_PROG_FRGN", "S6_THEME_LAGGARD",
    "S12_CLOSING",  "S14_OVERSOLD_BOUNCE", "S15_MOMENTUM_ALIGN",
}
# 오버나잇 비적합 데이트레이딩 전략
_DAYTRADING = {"S1_GAP_OPEN", "S2_VI_PULLBACK", "S4_BIG_CANDLE", "S7_AUCTION"}


def _sf(v, default: float = 0.0) -> float:
    try:
        return float(str(v).replace(",", "").replace("+", "").replace(" ", "") or str(default))
    except (TypeError, ValueError):
        return default


# ── 캐시 기반 기술지표 (API 미호출) ────────────────────────────

def _get_cached_candles(stk_cd: str) -> list[dict] | None:
    """
    ma_utils 인메모리 캐시에서 일봉 데이터를 조회.
    전략 스캐너가 당일 이미 fetch 했다면 캐시 히트 가능.
    """
    try:
        from ma_utils import _candle_cache_get, _safe_price
        return _candle_cache_get(stk_cd)
    except Exception:
        return None


def _calc_rsi_from_candles(candles: list[dict], period: int = 14) -> Optional[float]:
    try:
        from ma_utils import _safe_price
        closes = [_safe_price(c.get("cur_prc")) for c in candles if _safe_price(c.get("cur_prc")) > 0]
        if len(closes) < period + 1:
            return None
        gains, losses = [], []
        for i in range(period):
            d = closes[i] - closes[i + 1]
            (gains if d > 0 else losses).append(abs(d))
        avg_gain = sum(gains) / period if gains else 0.0
        avg_loss = sum(losses) / period if losses else 0.0
        if avg_loss == 0:
            return 100.0
        return round(100 - 100 / (1 + avg_gain / avg_loss), 1)
    except Exception:
        return None


def _calc_ma_alignment(candles: list[dict], cur_prc: float) -> Optional[str]:
    """
    정배열/역배열/혼조 반환.
    cur_prc: 현재 실시간 가격 (tick 기준, candles[0] 종가보다 최신)
    """
    try:
        from ma_utils import _safe_price
        closes = [_safe_price(c.get("cur_prc")) for c in candles if _safe_price(c.get("cur_prc")) > 0]
        if len(closes) < 60:
            return None
        ma5  = sum(closes[:5])  / 5
        ma20 = sum(closes[:20]) / 20
        ma60 = sum(closes[:60]) / 60
        p = cur_prc if cur_prc > 0 else closes[0]
        if ma5 > ma20 > ma60 and p >= ma20:
            return "bullish_above_ma20"
        if ma5 > ma20 > ma60:
            return "bullish_below_ma20"
        if ma5 < ma20 < ma60:
            return "bearish"
        return "mixed"
    except Exception:
        return None


# ── 점수 컴포넌트 ───────────────────────────────────────────────

def _score_overnight_base(overnight_score: float) -> float:
    """Java 계산 overnight_score 반영 (-15 ~ +15)"""
    if overnight_score >= 85:   return 15.0
    if overnight_score >= 75:   return 10.0
    if overnight_score >= 65:   return  5.0
    if overnight_score >= 55:   return  0.0
    if overnight_score >= 45:   return -5.0
    return -15.0


def _score_pnl(entry_price: float, cur_prc: float) -> tuple[float, float]:
    """
    미실현 P&L 기반 점수 (-25 ~ +15).
    반환: (점수, pnl_pct)
    """
    if entry_price <= 0 or cur_prc <= 0:
        return 0.0, 0.0
    pnl_pct = (cur_prc - entry_price) / entry_price * 100
    if pnl_pct >= 3.0:    score = 15.0
    elif pnl_pct >= 2.0:  score = 10.0
    elif pnl_pct >= 1.0:  score =  5.0
    elif pnl_pct >= 0.0:  score =  0.0
    elif pnl_pct >= -1.0: score = -10.0
    elif pnl_pct >= -2.0: score = -20.0
    else:                  score = -25.0
    return score, round(pnl_pct, 2)


def _score_cntr_strength(strength: float) -> float:
    """체결강도 기반 점수 (-10 ~ +10)"""
    if strength >= 130:   return 10.0
    if strength >= 110:   return  5.0
    if strength >= 90:    return  0.0
    if strength >= 70:    return -5.0
    return -10.0


def _score_bid_ratio(hoga: dict) -> float:
    """
    호가비율(매수/매도 잔량) 기반 점수 (-10 ~ +8).
    ws:hoga:{stk_cd} 에서 total_buy_bid_req / total_sel_bid_req 사용.
    """
    bid = _sf(hoga.get("total_buy_bid_req", 0))
    ask = _sf(hoga.get("total_sel_bid_req", 1))
    if ask <= 0:
        return 0.0
    ratio = bid / ask
    if ratio >= 2.0:    return  8.0
    if ratio >= 1.5:    return  5.0
    if ratio >= 1.0:    return  2.0
    if ratio >= 0.8:    return -3.0
    return -10.0


def _score_flu_rt(flu_rt: float) -> float:
    """등락률 기반 점수 (-8 ~ +5)"""
    if flu_rt >= 3.0:    return  5.0
    if flu_rt >= 1.0:    return  3.0
    if flu_rt >= 0.0:    return  0.0
    if flu_rt >= -1.0:   return -3.0
    return -8.0


def _score_strategy_fit(strategy: str) -> float:
    """전략별 오버나잇 적합도 (-10 ~ +10)"""
    if strategy in _SWING_FRIENDLY:  return 10.0
    if strategy in _NEUTRAL:         return  3.0
    if strategy in _DAYTRADING:      return -10.0
    return 0.0


def _score_rsi(rsi: Optional[float]) -> float:
    """RSI(14) 기반 점수 (-10 ~ +5). None 이면 0 반환."""
    if rsi is None:
        return 0.0
    if rsi <= 30:    return -3.0   # 과매도 → 추가 하락 우려
    if rsi <= 50:    return  5.0   # 중립 상승권 → 양호
    if rsi <= 65:    return  3.0
    if rsi <= 75:    return -5.0   # 과매수 근접
    return -10.0                   # 과매수 → 오버나잇 위험


def _score_ma_alignment(alignment: Optional[str]) -> float:
    """MA 배열 기반 점수 (-5 ~ +8). None 이면 0 반환."""
    if alignment is None:
        return 0.0
    if alignment == "bullish_above_ma20":  return  8.0
    if alignment == "bullish_below_ma20":  return  3.0
    if alignment == "mixed":               return  0.0
    if alignment == "bearish":             return -5.0
    return 0.0


# ── 메인 판단 함수 ──────────────────────────────────────────────

@dataclass
class OvernightVerdict:
    hold:        bool
    confidence:  str          # HIGH | MEDIUM | LOW
    score:       float
    reason:      str
    detail:      dict = field(default_factory=dict)


def evaluate_overnight(
    item:     dict,
    tick:     dict,
    hoga:     dict,
    strength: float,
) -> OvernightVerdict:
    """
    오버나잇 보유 여부 규칙 기반 판단.

    Parameters
    ----------
    item     : overnight_eval_queue 아이템 (overnight_score, entry_price, strategy 포함)
    tick     : ws:tick:{stk_cd} Redis 해시
    hoga     : ws:hoga:{stk_cd} Redis 해시
    strength : 체결강도 5분 평균 (get_avg_cntr_strength 결과)

    Returns
    -------
    OvernightVerdict
    """
    stk_cd        = item.get("stk_cd", "")
    strategy      = item.get("strategy", "")
    overnight_sc  = float(item.get("overnight_score", 50) or 50)
    entry_price   = _sf(item.get("entry_price", 0))

    cur_prc = _sf(tick.get("cur_prc", 0))
    flu_rt  = _sf(tick.get("flu_rt",  0))

    # ── 기술지표 캐시 조회 (API 미호출) ─────────────────────────
    candles   = _get_cached_candles(stk_cd)
    rsi14     = _calc_rsi_from_candles(candles) if candles else None
    alignment = _calc_ma_alignment(candles, cur_prc) if candles else None

    # ── 개별 점수 계산 ───────────────────────────────────────────
    s_base     = _score_overnight_base(overnight_sc)
    s_pnl, pnl_pct = _score_pnl(entry_price, cur_prc)
    s_strength = _score_cntr_strength(strength)
    s_bid      = _score_bid_ratio(hoga)
    s_flu      = _score_flu_rt(flu_rt)
    s_strategy = _score_strategy_fit(strategy)
    s_rsi      = _score_rsi(rsi14)
    s_ma       = _score_ma_alignment(alignment)

    total = 50.0 + s_base + s_pnl + s_strength + s_bid + s_flu + s_strategy + s_rsi + s_ma
    total = round(max(0.0, min(100.0, total)), 1)

    # ── 판단 ─────────────────────────────────────────────────────
    if total >= 65:
        hold, confidence = True, "HIGH"
    elif total >= 55:
        hold, confidence = True, "MEDIUM"
    elif total >= 45:
        hold, confidence = False, "LOW"
    else:
        hold, confidence = False, "MEDIUM"

    # ── 이유 문자열 구성 ─────────────────────────────────────────
    reason_parts = []

    # P&L 최우선 언급
    if pnl_pct != 0.0:
        reason_parts.append(f"미실현손익 {pnl_pct:+.1f}%")

    # 핵심 지표 요약
    if strength >= 110:
        reason_parts.append(f"체결강도 {strength:.0f} (강)")
    elif strength < 80:
        reason_parts.append(f"체결강도 {strength:.0f} (약)")

    if rsi14 is not None:
        if rsi14 >= 70:
            reason_parts.append(f"RSI {rsi14:.0f} 과매수")
        elif rsi14 <= 35:
            reason_parts.append(f"RSI {rsi14:.0f} 과매도권")

    if alignment == "bearish":
        reason_parts.append("역배열 추세")
    elif alignment == "bullish_above_ma20":
        reason_parts.append("정배열·MA20 위")

    if strategy in _DAYTRADING:
        reason_parts.append("데이트레이딩 전략")

    reason = f"오버나잇 스코어 {total:.0f}점 – " + (
        " | ".join(reason_parts) if reason_parts
        else (f"overnight_score {overnight_sc:.0f}, 등락률 {flu_rt:+.1f}%")
    )
    if hold:
        reason += " → 보유 지속"
    else:
        reason += " → 청산 권고"

    detail = {
        "total_score":      total,
        "overnight_score":  overnight_sc,
        "pnl_pct":          pnl_pct,
        "flu_rt":           flu_rt,
        "cntr_strength":    round(strength, 1),
        "rsi14":            rsi14,
        "ma_alignment":     alignment,
        "strategy":         strategy,
        "components": {
            "base":     s_base,
            "pnl":      s_pnl,
            "strength": s_strength,
            "bid":      s_bid,
            "flu":      s_flu,
            "strategy": s_strategy,
            "rsi":      s_rsi,
            "ma":       s_ma,
        },
    }

    logger.info(
        "[OvernightScorer] %s %s | score=%.0f (base:%.0f pnl:%.0f str:%.0f bid:%.0f "
        "flu:%.0f strat:%.0f rsi:%.0f ma:%.0f) → %s %s",
        stk_cd, strategy, total,
        s_base, s_pnl, s_strength, s_bid, s_flu, s_strategy, s_rsi, s_ma,
        "HOLD" if hold else "CLOSE", confidence,
    )

    return OvernightVerdict(
        hold=hold,
        confidence=confidence,
        score=total,
        reason=reason,
        detail=detail,
    )
