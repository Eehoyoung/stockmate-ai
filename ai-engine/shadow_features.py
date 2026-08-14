"""
shadow_features.py — Phase 3 shadow feature 계산 모듈

결과는 신호 payload 의 shadow_features 키로 저장되며
기존 ENTER/CANCEL gate 판단에는 사용하지 않는다.
2~4주 데이터 수집 후 EV/MFE/MAE 기반으로 gate 승격 여부를 결정한다.

구현 원칙
- 0 추가 API 호출: ctx/signal 에 이미 있는 데이터만으로 계산한다.
- 분봉/일봉 캔들이 전달되면 CVD·VWAP·ADX 도 계산한다.
- 개별 feature 오류는 None 으로 처리해 전체 실패를 방지한다.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ── 내부 helpers ────────────────────────────────────────────────────────────────

def _sf(v, default: float = 0.0) -> float:
    try:
        return float(str(v).replace(",", "")) if v is not None else default
    except (ValueError, TypeError):
        return default


def _si(v, default: int = 0) -> int:
    try:
        return int(str(v).replace(",", "")) if v is not None else default
    except (ValueError, TypeError):
        return default


# ── 1. 호가 imbalance ────────────────────────────────────────────────────────────

def compute_orderbook_imbalance(hoga: dict) -> dict:
    """
    총잔량 및 1호가 잔량 기반 매수/매도 imbalance 를 계산한다.

    Redis ws:hoga:{stk_cd} 에 저장된 필드를 그대로 사용한다:
      total_buy_bid_req / total_sel_bid_req : 총 매수/매도 잔량
      buy_bid_req_1 / sel_bid_req_1         : 1호가 잔량

    Returns:
        imbalance_total      : (buy - sell) / (buy + sell) ∈ [-1, 1]
        imbalance_1st_level  : 1호가 imbalance
        buy_qty_total        : 총 매수잔량
        sell_qty_total       : 총 매도잔량
        buy_qty_1st          : 1호가 매수잔량
        sell_qty_1st         : 1호가 매도잔량
    """
    buy_total = _si(hoga.get("total_buy_bid_req"))
    sell_total = _si(hoga.get("total_sel_bid_req"))
    buy_1 = _si(hoga.get("buy_bid_req_1"))
    sell_1 = _si(hoga.get("sel_bid_req_1"))

    total = buy_total + sell_total
    imb_total = round((buy_total - sell_total) / total, 4) if total > 0 else 0.0

    total_1 = buy_1 + sell_1
    imb_1 = round((buy_1 - sell_1) / total_1, 4) if total_1 > 0 else 0.0

    return {
        "imbalance_total": imb_total,
        "imbalance_1st_level": imb_1,
        "buy_qty_total": buy_total,
        "sell_qty_total": sell_total,
        "buy_qty_1st": buy_1,
        "sell_qty_1st": sell_1,
    }


# ── 2. 상대강도 (vs 지수) ────────────────────────────────────────────────────────

def compute_relative_strength(signal: dict, ctx: dict) -> dict:
    """
    종목 등락률(flu_rt) 대비 KOSPI/KOSDAQ 지수 등락률로 상대강도를 계산한다.
    모두 ctx/signal 에 이미 로드된 값을 사용하므로 추가 API 호출이 없다.

    Returns:
        rs_pct      : stk_flu_rt - idx_flu_rt  (양수 = outperform)
        rs_trend    : "outperform" | "inline" | "underperform"
        stk_flu_rt  : 종목 등락률
        idx_flu_rt  : 기준 지수 등락률
    """
    stk_flu = _sf(signal.get("flu_rt") or signal.get("change_pct"), None)  # type: ignore[arg-type]
    if stk_flu is None:
        stk_flu = _sf(signal.get("flu_rt"), None)  # type: ignore[arg-type]

    market_type = str(ctx.get("market_type") or signal.get("market_type") or "001")
    idx_flu = (
        _sf(ctx.get("kosdaq_flu_rt"), None)  # type: ignore[arg-type]
        if market_type == "101"
        else _sf(ctx.get("kospi_flu_rt"), None)  # type: ignore[arg-type]
    )

    if stk_flu is None or idx_flu is None:
        return {
            "rs_pct": None,
            "rs_trend": "unknown",
            "stk_flu_rt": stk_flu,
            "idx_flu_rt": idx_flu,
        }

    rs_pct = round(stk_flu - idx_flu, 3)
    trend = "outperform" if rs_pct >= 1.0 else ("underperform" if rs_pct <= -1.0 else "inline")

    return {
        "rs_pct": rs_pct,
        "rs_trend": trend,
        "stk_flu_rt": stk_flu,
        "idx_flu_rt": idx_flu,
    }


# ── 3. 체결강도 기반 매수 압력 ──────────────────────────────────────────────────

def compute_tick_buy_pressure(tick: dict, ctx: dict) -> dict:
    """
    체결강도·현재가·1호가 스프레드 기반 매수 압력 지표.
    추가 API 없이 이미 로드된 tick / hoga 데이터만 사용한다.

    Returns:
        cntr_strength       : 체결강도
        spread_pct          : (매도1호가 - 매수1호가) / 매수1호가 * 100
        buy_pressure_label  : "strong" | "moderate" | "weak"
    """
    hoga = ctx.get("hoga") or {}
    strength = _sf(ctx.get("strength") or tick.get("cntr_str"))
    bid_prc = _sf(hoga.get("buy_bid_pric_1"))
    ask_prc = _sf(hoga.get("sel_bid_pric_1"))

    spread_pct: Optional[float] = None
    if bid_prc > 0 and ask_prc > 0:
        spread_pct = round((ask_prc - bid_prc) / bid_prc * 100, 4)

    label = "strong" if strength > 120 else ("moderate" if strength > 100 else "weak")

    return {
        "cntr_strength": strength,
        "spread_pct": spread_pct,
        "buy_pressure_label": label,
    }


# ── 4. CVD (Cumulative Volume Delta) ─────────────────────────────────────────

def compute_cvd_from_candles(candles: list[dict]) -> Optional[dict]:
    """
    분봉 OHLCV 에서 CVD 를 근사한다 (입력: 최신순 — index 0 이 최신봉).

    정확한 CVD 는 tick 단위 체결 방향이 필요하지만, 분봉 기반 근사를 사용한다:
      delta_bar = volume * (close - low) / range - volume * (high - close) / range
    즉, 봉이 고점 부근에서 마감할수록 매수 압력이 높은 것으로 본다.

    Returns:
        cvd_total           : 전체 누적 CVD (매수 우세 > 0)
        cvd_last5           : 최근 5봉 CVD 합계
        cvd_slope           : 최근 5봉 선형회귀 기울기
        aggressive_buy_ratio: 매수 pressure / 전체 절대 pressure ∈ [0, 1]
    """
    if not candles:
        return None

    deltas: list[float] = []
    for c in reversed(candles):  # 오래된 봉부터 누산
        try:
            o  = float(c.get("stk_opnpric") or 0)
            h  = float(c.get("stk_hgpric")  or 0)
            l  = float(c.get("stk_lwpric")  or 0)
            cl = float(c.get("stk_clpr")    or 0)
            vol = int(c.get("acml_vol")     or 0)
        except (ValueError, TypeError):
            continue

        price_range = h - l
        if price_range < 1e-9 or vol == 0:
            deltas.append(0.0)
            continue

        buy_ratio  = (cl - l) / price_range
        sell_ratio = (h - cl) / price_range
        deltas.append(vol * (buy_ratio - sell_ratio))

    if not deltas:
        return None

    cvd_total = round(sum(deltas), 0)
    cvd_last5 = round(sum(deltas[-5:]), 0)

    slope = 0.0
    if len(deltas) >= 5:
        recent = deltas[-5:]
        n = len(recent)
        x_mean = (n - 1) / 2
        y_mean = sum(recent) / n
        num = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(recent))
        den = sum((i - x_mean) ** 2 for i in range(n))
        slope = round(num / den, 2) if den > 1e-9 else 0.0

    total_abs = sum(abs(d) for d in deltas)
    buy_vol = sum(d for d in deltas if d > 0)
    aggressive_buy_ratio = round(buy_vol / total_abs, 4) if total_abs > 0 else 0.5

    return {
        "cvd_total": cvd_total,
        "cvd_last5": cvd_last5,
        "cvd_slope": slope,
        "aggressive_buy_ratio": aggressive_buy_ratio,
        "bar_count": len(deltas),
    }


# ── 5. Anchored VWAP ─────────────────────────────────────────────────────────

def compute_anchored_vwap(
    candles: list[dict],
    cur_prc: Optional[float] = None,
    anchor_type: str = "day",
) -> Optional[dict]:
    """
    당일 전체 분봉을 기준으로 Day-anchored VWAP 을 계산한다.
    입력: 최신순 분봉 리스트 (index 0 = 가장 최근).

    Returns:
        anchored_vwap      : VWAP 가격
        price_vs_vwap_pct  : (현재가 - VWAP) / VWAP * 100
        vwap_total_vol     : 계산에 사용된 총 거래량
        anchor_type        : "day"
        above_vwap         : 현재가 >= VWAP 여부
    """
    if not candles:
        return None

    vwap_num = 0.0
    total_vol = 0
    for c in reversed(candles):  # 오래된 것부터
        try:
            h   = float(c.get("stk_hgpric") or 0)
            l   = float(c.get("stk_lwpric") or 0)
            cl  = float(c.get("stk_clpr")   or 0)
            vol = int(c.get("acml_vol")      or 0)
        except (ValueError, TypeError):
            continue
        if vol <= 0:
            continue
        typical = (h + l + cl) / 3.0
        vwap_num += typical * vol
        total_vol += vol

    if total_vol == 0:
        return None

    vwap = round(vwap_num / total_vol, 2)

    price_vs_vwap_pct: Optional[float] = None
    above_vwap: Optional[bool] = None
    if cur_prc and cur_prc > 0:
        price_vs_vwap_pct = round((cur_prc - vwap) / vwap * 100, 3)
        above_vwap = cur_prc >= vwap

    return {
        "anchored_vwap": vwap,
        "price_vs_vwap_pct": price_vs_vwap_pct,
        "vwap_total_vol": total_vol,
        "anchor_type": anchor_type,
        "above_vwap": above_vwap,
    }


# ── 6. ADX / DMI ─────────────────────────────────────────────────────────────

def compute_adx(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> Optional[dict]:
    """
    Wilder's ADX/DMI 계산 (일봉 기반 추천).

    Args:
        highs/lows/closes : 오래된 것부터 정렬된 가격 리스트
        period            : ADX 기간 (기본 14)

    Returns:
        adx              : Average Directional Index (0~100)
        plus_di          : +DI
        minus_di         : -DI
        trend_strength   : "strong"(≥25) | "moderate"(≥15) | "weak"(<15)
        trend_direction  : "up" | "down"
    """
    n = len(closes)
    if n < period * 2 + 1:
        return None

    tr_list: list[float] = []
    plus_dm: list[float] = []
    minus_dm: list[float] = []

    for i in range(1, n):
        h, l, c_prev = highs[i], lows[i], closes[i - 1]
        tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
        tr_list.append(tr)

        up   = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up   if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)

    def _rma(data: list[float], p: int) -> list[float]:
        if len(data) < p:
            return []
        result = [sum(data[:p]) / p]
        for v in data[p:]:
            result.append((result[-1] * (p - 1) + v) / p)
        return result

    atr_s    = _rma(tr_list,   period)
    pdm_s    = _rma(plus_dm,   period)
    mdm_s    = _rma(minus_dm,  period)

    if not atr_s:
        return None

    dx_list: list[float] = []
    for atr, pdm, mdm in zip(atr_s, pdm_s, mdm_s):
        if atr < 1e-9:
            dx_list.append(0.0)
            continue
        pdi = 100.0 * pdm / atr
        mdi = 100.0 * mdm / atr
        di_sum = pdi + mdi
        dx_list.append(100.0 * abs(pdi - mdi) / di_sum if di_sum > 1e-9 else 0.0)

    adx_s = _rma(dx_list, period)
    if not adx_s:
        return None

    last_atr = atr_s[-1]
    last_pdi = round(100.0 * pdm_s[-1] / last_atr, 2) if last_atr > 1e-9 else 0.0
    last_mdi = round(100.0 * mdm_s[-1] / last_atr, 2) if last_atr > 1e-9 else 0.0
    last_adx = round(adx_s[-1], 2)

    return {
        "adx": last_adx,
        "plus_di": last_pdi,
        "minus_di": last_mdi,
        "trend_strength": "strong" if last_adx >= 25 else ("moderate" if last_adx >= 15 else "weak"),
        "trend_direction": "up" if last_pdi > last_mdi else "down",
    }


# ── 7. 통합 진입점 ─────────────────────────────────────────────────────────────

def _extract_intraday_investor_flow(signal: dict) -> Optional[dict]:
    """Normalize Python/Java ka10064 enrichment into one shadow feature."""
    extra = signal.get("extra") if isinstance(signal.get("extra"), dict) else {}
    direct = signal.get("intraday_investor_flow") or extra.get("intraday_investor_flow")
    if isinstance(direct, dict):
        return dict(direct)

    # Java strategy extras are flattened by TradingSignalDto.toQueuePayload.
    aliases = {
        "observed_at": ("s3_flow_observed_at", "s11_flow_observed_at"),
        "sample_count": ("s3_flow_sample_count", "s11_flow_sample_count"),
        "latest_foreign": ("s3_foreign_amount", "s11_foreign_amount"),
        "latest_institution": ("s3_institution_amount", "s11_institution_amount"),
        "latest_combined": ("s3_latest_combined_amount", "s11_latest_combined_amount"),
        "combined_slope": ("s3_flow_combined_slope", "s11_flow_combined_slope"),
        "foreign_slope": ("s3_flow_foreign_slope", "s11_flow_foreign_slope"),
        "institution_slope": ("s3_flow_institution_slope", "s11_flow_institution_slope"),
        "latest_delta": ("s3_flow_latest_delta", "s11_flow_latest_delta"),
        "recent_reversal": ("s3_flow_recent_reversal", "s11_flow_recent_reversal"),
        "recent_reversal_direction": (
            "s3_flow_recent_reversal_direction",
            "s11_flow_recent_reversal_direction",
        ),
        "source": ("s3_investor_flow_source", "s11_investor_flow_source"),
    }
    normalized = {}
    for target, keys in aliases.items():
        for key in keys:
            value = signal.get(key, extra.get(key))
            if value is not None:
                normalized[target] = value
                break
    return normalized or None


def compute_live_feature_adjustment(features: dict) -> dict:
    """Convert previously observational features into a bounded live score adjustment."""
    adjustment = 0.0
    reasons: list[str] = []

    orderbook = features.get("orderbook") or {}
    imbalance = _sf(orderbook.get("imbalance_total"), None)
    if imbalance is not None:
        delta = max(-4.0, min(4.0, imbalance * 8.0))
        adjustment += delta
        reasons.append(f"orderbook={delta:+.1f}")

    relative = features.get("relative_strength") or {}
    rs_pct = _sf(relative.get("rs_pct"), None)
    if rs_pct is not None:
        delta = max(-4.0, min(4.0, rs_pct * 1.5))
        adjustment += delta
        reasons.append(f"relative_strength={delta:+.1f}")

    pressure = features.get("tick_pressure") or {}
    label = str(pressure.get("buy_pressure_label") or "").lower()
    delta = {"strong": 4.0, "moderate": 1.5, "weak": -4.0}.get(label, 0.0)
    adjustment += delta
    if label:
        reasons.append(f"tick_pressure={delta:+.1f}")

    flow = features.get("intraday_investor_flow") or {}
    slope = _sf(flow.get("combined_slope"), None)
    latest_delta = _sf(flow.get("latest_delta"), None)
    reversal = bool(flow.get("recent_reversal"))
    reversal_direction = str(flow.get("recent_reversal_direction") or "").lower()
    flow_delta = 0.0
    if slope is not None:
        flow_delta += 3.0 if slope > 0 else (-3.0 if slope < 0 else 0.0)
    if latest_delta is not None:
        flow_delta += 2.0 if latest_delta > 0 else (-2.0 if latest_delta < 0 else 0.0)
    if reversal:
        flow_delta += 2.0 if reversal_direction in {"up", "positive", "buy"} else -2.0
    flow_delta = max(-6.0, min(6.0, flow_delta))
    adjustment += flow_delta
    if flow:
        reasons.append(f"investor_flow={flow_delta:+.1f}")

    adjustment = round(max(-15.0, min(15.0, adjustment)), 2)
    return {
        "score_adjustment": adjustment,
        "reasons": reasons,
        "hard_reject": adjustment <= -12.0,
        "mode": "LIVE",
    }


def compute_all_shadow_features(
    signal: dict,
    ctx: dict,
    minute_candles: Optional[list[dict]] = None,
    daily_candles: Optional[list[dict]] = None,
) -> dict:
    """
    모든 shadow feature 를 계산해 하나의 dict 로 반환한다.
    개별 feature 오류는 해당 키를 None 으로 처리해 전체 실패를 방지한다.

    Args:
        signal         : 신호 payload
        ctx            : _build_market_ctx 결과 (tick, hoga, strength, 지수 등락률 등)
        minute_candles : 5분봉 등 분봉 리스트 (최신순). None 이면 CVD/VWAP 스킵
        daily_candles  : 일봉 리스트 (최신순). None 이면 ADX 스킵

    Returns:
        {
          "orderbook"       : compute_orderbook_imbalance 결과 or None,
          "relative_strength": compute_relative_strength 결과 or None,
          "tick_pressure"   : compute_tick_buy_pressure 결과 or None,
          "cvd"             : compute_cvd_from_candles 결과 or None,
          "anchored_vwap"   : compute_anchored_vwap 결과 or None,
          "adx"             : compute_adx 결과 or None,
        }
    """
    hoga = ctx.get("hoga") or {}
    tick = ctx.get("tick") or {}

    cur_prc_raw = (
        tick.get("cur_prc") or tick.get("stk_prpr")
        or signal.get("cur_prc") or signal.get("entry_price")
    )
    try:
        cur_prc: Optional[float] = float(str(cur_prc_raw).replace(",", "")) if cur_prc_raw else None
    except (ValueError, TypeError):
        cur_prc = None

    result: dict = {}

    # 즉시 계산 가능 (ctx 데이터만 사용)
    for key, fn, args in [
        ("orderbook",        compute_orderbook_imbalance, (hoga,)),
        ("relative_strength", compute_relative_strength,  (signal, ctx)),
        ("tick_pressure",    compute_tick_buy_pressure,   (tick, ctx)),
    ]:
        try:
            result[key] = fn(*args)
        except Exception as e:
            logger.debug("[Shadow] %s error: %s", key, e)
            result[key] = None

    # 분봉 캔들 기반 (없으면 None)
    if minute_candles:
        for key, fn, args in [
            ("cvd",          compute_cvd_from_candles, (minute_candles,)),
            ("anchored_vwap", compute_anchored_vwap,   (minute_candles, cur_prc)),
        ]:
            try:
                result[key] = fn(*args)
            except Exception as e:
                logger.debug("[Shadow] %s error: %s", key, e)
                result[key] = None
    else:
        result["cvd"] = None
        result["anchored_vwap"] = None

    # 일봉 캔들 기반 ADX (없거나 봉 수 부족이면 None)
    if daily_candles and len(daily_candles) >= 30:
        try:
            highs  = [float(c.get("stk_hgpric") or 0) for c in reversed(daily_candles)]
            lows   = [float(c.get("stk_lwpric")  or 0) for c in reversed(daily_candles)]
            closes = [float(c.get("stk_clpr")    or 0) for c in reversed(daily_candles)]
            result["adx"] = compute_adx(highs, lows, closes)
        except Exception as e:
            logger.debug("[Shadow] adx error: %s", e)
            result["adx"] = None
    else:
        result["adx"] = None

    # ka10064 is normalized here and consumed by the live feature adjustment.
    result["intraday_investor_flow"] = _extract_intraday_investor_flow(signal)

    return result
