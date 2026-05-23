from __future__ import annotations

"""
queue_worker.py

Consumes `telegram_queue`, enriches candidate signals with rule-based scoring and
optional AI analysis, then publishes results to `ai_scored_queue`.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from analyzer import analyze_signal
from http_utils import (
    fetch_stk_nm,
    fetch_hoga_rest as _fetch_hoga_rest,
    fetch_cntr_strength_rest as _fetch_str_rest,
    fetch_tick_snapshot as _fetch_tick_snapshot,
)
from position_sizing import ENABLE_MODEL_RELATIVE_POSITION_SIZE, calculate_entry_size
from price_utils import normalize_signal_prices
from strategy_meta import get_persona, get_hold_to_enter_threshold as _get_hold_threshold
from redis_reader import (
    get_avg_cntr_strength,
    get_hoga_data,
    get_market_freshness,
    get_market_index_exp_flu_rt,
    get_market_index_flu_rt,
    get_sector_overheat_count,
    get_stock_market_cap,
    get_tick_data,
    get_vi_status,
    pop_telegram_queue,
    push_score_only_queue,
)
from scorer import check_daily_limit, get_claude_threshold, rule_score, should_skip_ai
from score_utils import normalize_score_0_100
from shadow_features import compute_all_shadow_features
from tp_sl_engine import compute_rr
from utils import normalize_stock_code, safe_float as _fv

try:
    from market_session import MarketSession, current_session
except Exception:
    MarketSession = None
    current_session = None

try:
    from ma_utils import fetch_daily_candles_with_status as _fetch_daily_candles_ws
    from ma_utils import fetch_minute_candles_with_status as _fetch_minute_candles_ws
except ImportError:
    _fetch_daily_candles_ws = None
    _fetch_minute_candles_ws = None

logger = logging.getLogger(__name__)

POLL_INTERVAL = float(os.getenv("POLL_INTERVAL_SEC", "2.0"))
STATUS_DECISION_TTL_SEC = int(os.getenv("STATUS_DECISION_TTL_SEC", "600"))
REDIS_TOKEN_KEY = "kiwoom:token"
FAILURE_ACTION = "FAILED"
FAILURE_TYPE = "PROCESSING_ERROR"

_KST = timezone(timedelta(hours=9))
_PIPELINE_TTL_SEC = 172800

# ── 하드게이트 기준값 (장세 보정 전 기준) ─────────────────────────────────
# 상승장(bull)에서는 _REGIME_GATE_FACTOR 만큼 임계값 완화.
# S1/S6/S13은 데이트레이딩 성격상 신규 추가.
_HARD_GATES = {
    "S1_GAP_OPEN":        {"strength": 110.0, "bid_ratio": 1.3},
    "S4_BIG_CANDLE":      {"strength": 115.0, "bid_ratio": 1.2},
    "S6_THEME_LAGGARD":   {"strength": 120.0, "bid_ratio": 1.2},
    "S10_NEW_HIGH":       {"strength": 115.0, "bid_ratio": 1.2},
    "S12_CLOSING":        {"strength": 120.0, "bid_ratio": 1.5},
    "S13_BOX_BREAKOUT":   {"strength": 115.0, "bid_ratio": 1.3},
    "S15_MOMENTUM_ALIGN": {"strength": 100.0, "bid_ratio": 1.1},
}

# bull: 임계값을 12% 완화, bear: 역방향 전략(S9/S14)은 gates 적용 안 함
_REGIME_GATE_FACTOR = {"bull": 0.88, "sideways": 1.0, "bear": 1.0, "neutral": 1.0}
# bear 장세에서 반등 전략은 weak momentum이 당연하므로 gate 면제
_BEAR_GATE_EXEMPT = {"S9_PULLBACK_SWING", "S14_OVERSOLD_BOUNCE", "S11_FRGN_CONT"}
_RULE_THRESHOLD_RESCUE_FLOORS = {
    "S1_GAP_OPEN": 10.0,
    "S7_ICHIMOKU_BREAKOUT": 35.0,
    "S8_GOLDEN_CROSS": 45.0,
    "S9_PULLBACK_SWING": 40.0,
    "S15_MOMENTUM_ALIGN": 50.0,
}
_BID_ONLY_RESCUE_STRATEGIES = {"S1_GAP_OPEN", "S8_GOLDEN_CROSS", "S15_MOMENTUM_ALIGN"}
_BID_RATIO_ABSOLUTE_CANCEL = 0.30
_BID_RATIO_RESCUE_FLOOR = {
    "S1_GAP_OPEN": 0.60,
    "S15_MOMENTUM_ALIGN": 0.50,
    "S8_GOLDEN_CROSS": 0.70,
}

# freshness 취소 게이트: tick/hoga cancel → CANCEL 판정하는 전략 집합 (문서 4.1)
# _freshness_cancel_reason() 과 _compute_freshness_decision() 이 공유한다.
_STRICT_CANCEL_GATE = {
    "S1_GAP_OPEN", "S2_VI_PULLBACK", "S4_BIG_CANDLE",
    "S10_NEW_HIGH", "S12_CLOSING", "S13_BOX_BREAKOUT",
}

# chart 보강 전략 분류 (P2 — ENABLE_CHART_RETRY=true 시에만 사용)
_CHART_DAILY_STRATEGIES = {
    "S8_GOLDEN_CROSS", "S9_PULLBACK_SWING", "S13_BOX_BREAKOUT",
    "S14_OVERSOLD_BOUNCE", "S15_MOMENTUM_ALIGN",
}
_CHART_MINUTE_STRATEGIES = {"S4_BIG_CANDLE", "S12_CLOSING"}

# ── R:R 사전필터 장세별 임계값 ─────────────────────────────────────────────
# bull: 모멘텀이 슬리피지를 상쇄 → 0.65, bear: 리스크 엄격 → 0.80
_RR_BY_REGIME = {"bull": 0.65, "sideways": 0.75, "bear": 0.80, "neutral": 0.80}

_S12_START_MINUTE = 14 * 60 + 30
_S12_END_MINUTE = 15 * 60 + 10
RR_HARD_CANCEL_THRESHOLD = float(os.getenv("RR_HARD_CANCEL_THRESHOLD", "0.8"))
RR_CAUTION_THRESHOLD = float(os.getenv("RR_CAUTION_THRESHOLD", "1.2"))
S8_SUPPORT_ZONE_CAUTION_GAP_PCT = float(os.getenv("S8_SUPPORT_ZONE_CAUTION_GAP_PCT", "1.5"))
S8_SUPPORT_ZONE_HARD_CANCEL_GAP_PCT = float(os.getenv("S8_SUPPORT_ZONE_HARD_CANCEL_GAP_PCT", "3.5"))
S8_MIN_ZONE_RR = float(os.getenv("S8_MIN_ZONE_RR", "1.5"))
HOLD_TO_ENTER_MIN_AI_SCORE = float(os.getenv("HOLD_TO_ENTER_MIN_AI_SCORE", "80.0"))
SESSION_ENTER_GUARD_ENABLED = os.getenv("SESSION_ENTER_GUARD_ENABLED", "false").lower() == "true"
ENABLE_SCORING_DATA_RETRY = os.getenv("ENABLE_SCORING_DATA_RETRY", "true").lower() == "true"
ENABLE_TICK_REST_FALLBACK = os.getenv("ENABLE_TICK_REST_FALLBACK", "false").lower() == "true"
STRICT_REST_ENTER_GUARD = os.getenv("STRICT_REST_ENTER_GUARD", "false").lower() == "true"
ENABLE_CHART_RETRY = os.getenv("ENABLE_CHART_RETRY", "false").lower() == "true"
CLAUDE_HARD_RULE_CANCEL_TYPE = "CLAUDE_HARD_RULE"
_CLAUDE_PRICE_FIELDS = ("claude_tp1", "claude_tp2", "claude_sl")
_SESSION_ENTER_BLOCKLIST = {
    "pre_market",
    "opening_auction",
    "closing_auction",
    "after_preopen",
    "after_market",
    "post_quiet",
    "closed",
    "off_market",
    "outside_market",
    "out_of_session",
    "after_hours",
    "장외",
}
_STRATEGY_ENTER_SESSIONS = {
    "S1_GAP_OPEN": {"pre_market", "opening_auction", "main_market"},
    "S3_INST_FRGN": {"main_market"},
    "S4_BIG_CANDLE": {"main_market"},
    "S5_PROG_FRGN": {"main_market"},
    "S6_THEME_LAGGARD": {"main_market"},
    "S7_ICHIMOKU_BREAKOUT": {"main_market"},
    "S8_GOLDEN_CROSS": {"main_market"},
    "S9_PULLBACK_SWING": {"main_market"},
    "S10_NEW_HIGH": {"main_market"},
    "S11_FRGN_CONT": {"main_market"},
    "S12_CLOSING": {"main_market", "closing_auction"},
    "S13_BOX_BREAKOUT": {"main_market"},
    "S14_OVERSOLD_BOUNCE": {"main_market"},
    "S15_MOMENTUM_ALIGN": {"main_market"},
}
_SESSION_ENTER_EXEMPT_TYPES = {
    "DAILY_REPORT",
    "FORCE_CLOSE",
    "MIDDAY_REPORT",
    "OVERNIGHT_HOLD",
    "OVERNIGHT_RISK_ALERT",
    "STATUS_REPORT",
}


def _db_writer():
    import db_writer

    return db_writer


async def insert_python_signal(*args, **kwargs):
    return await _db_writer().insert_python_signal(*args, **kwargs)


async def update_signal_score(*args, **kwargs):
    return await _db_writer().update_signal_score(*args, **kwargs)


async def insert_score_components(*args, **kwargs):
    return await _db_writer().insert_score_components(*args, **kwargs)


async def confirm_open_position(*args, **kwargs):
    return await _db_writer().confirm_open_position(*args, **kwargs)


async def create_shadow_trade(*args, **kwargs):
    return await _db_writer().create_shadow_trade(*args, **kwargs)


async def insert_rule_cancel_signal(*args, **kwargs):
    return await _db_writer().insert_rule_cancel_signal(*args, **kwargs)


async def insert_ai_cancel_signal(*args, **kwargs):
    return await _db_writer().insert_ai_cancel_signal(*args, **kwargs)


async def cancel_open_position_by_signal(*args, **kwargs):
    return await _db_writer().cancel_open_position_by_signal(*args, **kwargs)


async def _incr_pipeline(rdb, strategy: str, field: str) -> None:
    """Best-effort per-strategy daily pipeline counters."""
    if not strategy:
        # strategy가 없는 bypass 페이로드(DAILY_REPORT 등)는 카운터를 건너뜀.
        # 빈 strategy로 pipeline_daily:{date}: 키가 생성되는 것을 방지한다.
        return
    try:
        today = datetime.now(_KST).strftime("%Y-%m-%d")
        key = f"pipeline_daily:{today}:{strategy}"
        await rdb.hincrby(key, field, 1)
        await rdb.expire(key, _PIPELINE_TTL_SEC)
    except Exception:
        pass


def _resolve_display_reason(action: str, reason: str, cancel_reason: str | None) -> str:
    if action == "CANCEL" and cancel_reason:
        return cancel_reason
    return reason


def _current_market_session(now: datetime | None = None) -> str:
    if current_session is not None:
        try:
            session = current_session(now)
            value = getattr(session, "value", session)
            return str(value).lower()
        except Exception:
            pass
    now = now or datetime.now(_KST)
    if now.weekday() >= 5:
        return "closed"
    t = now.time()
    if t < datetime.strptime("08:00:00", "%H:%M:%S").time():
        return "closed"
    if t < datetime.strptime("08:50:00", "%H:%M:%S").time():
        return "pre_market"
    if t < datetime.strptime("09:00:30", "%H:%M:%S").time():
        return "opening_auction"
    if t < datetime.strptime("15:20:00", "%H:%M:%S").time():
        return "main_market"
    if t < datetime.strptime("15:30:00", "%H:%M:%S").time():
        return "closing_auction"
    if t < datetime.strptime("15:40:00", "%H:%M:%S").time():
        return "after_preopen"
    if t < datetime.strptime("20:00:00", "%H:%M:%S").time():
        return "after_market"
    if t < datetime.strptime("20:10:00", "%H:%M:%S").time():
        return "post_quiet"
    return "closed"


def _normalize_session_value(value) -> str:
    if value is None:
        return ""
    enum_value = getattr(value, "value", value)
    text = str(enum_value).strip().lower()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def _resolve_signal_session(payload: dict, ctx: dict | None = None) -> str:
    for source in (payload, ctx or {}):
        for field in ("market_session", "session", "ws_session"):
            value = source.get(field)
            if value:
                return _normalize_session_value(value)
    return _current_market_session()


def _is_session_enter_guard_exempt(payload: dict) -> bool:
    strategy = str(payload.get("strategy") or "")
    if strategy.startswith("S2"):
        return True

    item_type = str(payload.get("type") or "").upper()
    if item_type in _SESSION_ENTER_EXEMPT_TYPES:
        return True
    if "REPORT" in item_type or "FORCE_CLOSE" in item_type or "EXIT" in item_type or "CLOSE" in item_type:
        return True

    action = str(payload.get("action") or "").upper()
    return action in {"FORCE_CLOSE", "EXIT", "CLOSE", "SELL"}


def _apply_session_enter_guard(payload: dict, ctx: dict | None = None) -> dict:
    if not SESSION_ENTER_GUARD_ENABLED:
        return payload
    if str(payload.get("action") or "").upper() != "ENTER":
        return payload
    if _is_session_enter_guard_exempt(payload):
        return payload

    session = _resolve_signal_session(payload, ctx)
    strategy = str(payload.get("strategy") or "")
    allowed_sessions = _STRATEGY_ENTER_SESSIONS.get(strategy)
    if allowed_sessions is not None and session in allowed_sessions:
        return payload
    if allowed_sessions is None and session not in _SESSION_ENTER_BLOCKLIST:
        return payload

    reason = f"Session enter guard blocked new ENTER during {session}"
    payload["market_session"] = session
    payload["action"] = "CANCEL"
    payload["confidence"] = "LOW"
    payload["cancel_reason"] = reason
    payload["ai_reason"] = reason
    payload["skip_entry"] = True
    payload["cancel_type"] = "SESSION_ENTER_GUARD"
    _null_claude_prices(payload)
    return payload


def _coerce_rule_score_result(result) -> tuple[float, dict]:
    """Accept the canonical `(score, components)` return and tolerate legacy floats."""
    if isinstance(result, tuple) and len(result) == 2:
        score, components = result
    else:
        score, components = result, {}

    try:
        score_val = float(score)
    except (TypeError, ValueError):
        score_val = 0.0

    if not isinstance(components, dict):
        components = {}

    return normalize_score_0_100(score_val), components


def _build_failure_payload(item: dict, strategy: str, stk_cd: str, error: Exception) -> dict:
    return {
        **item,
        "type": FAILURE_TYPE,
        "action": FAILURE_ACTION,
        "confidence": "LOW",
        "rule_score": None,
        "ai_score": 0.0,
        "ai_reason": f"queue_worker processing failed: {type(error).__name__}",
        "error": str(error),
        "error_type": type(error).__name__,
        "failed_stage": "queue_worker",
        "stk_cd": stk_cd,
        "strategy": strategy,
        "skip_entry": True,
        "error_ts": time.time(),
    }


def _resolve_execution_strength(signal: dict, ctx: dict) -> float:
    signal_strength = signal.get("cntr_strength")
    if signal_strength is None:
        signal_strength = signal.get("cntr_str")
    try:
        if signal_strength is not None and float(signal_strength) > 0:
            return float(signal_strength)
    except (TypeError, ValueError):
        pass

    tick = ctx.get("tick", {}) or {}
    tick_strength = tick.get("cntr_str")
    try:
        if tick_strength is not None and float(str(tick_strength).replace(",", "").replace("+", "")) > 0:
            return float(str(tick_strength).replace(",", "").replace("+", ""))
    except (TypeError, ValueError):
        pass

    try:
        return float(ctx.get("strength", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _resolve_bid_ratio(signal: dict, ctx: dict) -> float | None:
    value = signal.get("bid_ratio")
    try:
        if value is not None:
            return float(str(value).replace(",", "").replace("+", ""))
    except (TypeError, ValueError):
        pass

    hoga = ctx.get("hoga", {}) or {}
    try:
        buy = float(str(hoga.get("total_buy_bid_req", "")).replace(",", "") or 0)
        sell = float(str(hoga.get("total_sel_bid_req", "")).replace(",", "") or 0)
        if sell > 0:
            return round(buy / sell, 3)
    except (TypeError, ValueError):
        pass

    try:
        buy = float(str(signal.get("buy_req", "")).replace(",", "").replace("+", "") or 0)
        sell = float(str(signal.get("sel_req", "")).replace(",", "").replace("+", "") or 0)
        if buy > 0 and sell > 0:
            return round(buy / sell, 3)
    except (TypeError, ValueError):
        pass
    return None


def _normalize_market_type(value) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    text = str(value or "").strip().upper()
    if text in {"001", "0", "KOSPI", "P00101"}:
        return "001"
    if text in {"101", "10", "KOSDAQ", "P10102"}:
        return "101"
    return ""


def _candidate_pool_suffix(strategy: str) -> str:
    code = str(strategy or "").split("_", 1)[0].lower()
    return code if code.startswith("s") and code[1:].isdigit() else ""


async def _resolve_signal_market_type(rdb, stk_cd: str, strategy: str, signal: dict | None = None) -> str:
    for field in ("market_type", "market", "mrkt_tp"):
        market_type = _normalize_market_type((signal or {}).get(field))
        if market_type:
            return market_type

    try:
        for key in (f"stock:market:{stk_cd}", f"stock:market_type:{stk_cd}"):
            market_type = _normalize_market_type(await rdb.get(key))
            if market_type:
                return market_type
    except Exception:
        pass

    suffix = _candidate_pool_suffix(strategy)
    if suffix:
        try:
            kospi, kosdaq = await asyncio.gather(
                rdb.lrange(f"candidates:{suffix}:001", 0, -1),
                rdb.lrange(f"candidates:{suffix}:101", 0, -1),
            )
            code = str(stk_cd)
            if code in {str(x) for x in kospi}:
                return "001"
            if code in {str(x) for x in kosdaq}:
                return "101"
        except Exception:
            pass
    return ""


def _regime_from_flu_rt(value) -> str:
    if value is None:
        return "neutral"
    try:
        flu_rt = float(value)
    except (TypeError, ValueError):
        return "neutral"
    if flu_rt >= 0.5:
        return "bull"
    if flu_rt <= -0.5:
        return "bear"
    return "sideways"


def _detect_market_regime(ctx: dict, strategy: str = "") -> str:
    """시장별 지수 등락률로 장세 판단.
    KOSPI 종목은 KOSPI200 proxy, KOSDAQ 종목은 KOSDAQ150 proxy를 우선 사용한다.
    시장 구분이 없을 때만 KOSPI/KOSDAQ 평균으로 폴백한다.
    bull: ≥+0.5%, bear: ≤-0.5%, sideways: 그 외, neutral: 데이터 없음.

    S1_GAP_OPEN: 08:30~09:00 동시호가 예상 등락률이 있으면 그것을 우선 사용.
    09:05 이후에는 exp 키 TTL(5분) 만료 → 실제 flu_rt로 자동 전환.
    """
    if strategy == "S1_GAP_OPEN":
        kospi  = ctx.get("kospi_exp_flu_rt")  or ctx.get("kospi_flu_rt")
        kosdaq = ctx.get("kosdaq_exp_flu_rt") or ctx.get("kosdaq_flu_rt")
    else:
        kospi  = ctx.get("kospi_flu_rt")
        kosdaq = ctx.get("kosdaq_flu_rt")
    market_type = _normalize_market_type(ctx.get("market_type"))
    if market_type == "001":
        return _regime_from_flu_rt(kospi)
    if market_type == "101":
        return _regime_from_flu_rt(kosdaq)
    vals = []
    for value in (kospi, kosdaq):
        try:
            if value is not None:
                vals.append(float(value))
        except (TypeError, ValueError):
            pass
    if not vals:
        return "neutral"
    avg = sum(vals) / len(vals)
    if avg >= 0.5:
        return "bull"
    if avg <= -0.5:
        return "bear"
    return "sideways"


def _hard_gate_failure(signal: dict, ctx: dict) -> str | None:
    strategy = signal.get("strategy", "")
    gate = _HARD_GATES.get(strategy)
    if not gate:
        return None

    regime = _detect_market_regime(ctx, strategy)

    # 하락장에서 반등 전략은 낮은 체결강도가 당연 — gate 면제
    if regime == "bear" and strategy in _BEAR_GATE_EXEMPT:
        return None

    if strategy == "S12_CLOSING":
        now = datetime.now(_KST)
        minute = now.hour * 60 + now.minute
        if not (_S12_START_MINUTE <= minute < _S12_END_MINUTE):
            return "time window outside 14:30~15:10"

    factor = _REGIME_GATE_FACTOR.get(regime, 1.0)
    req_strength = gate["strength"] * factor
    req_bid      = gate["bid_ratio"] * factor

    strength  = _resolve_execution_strength(signal, ctx)
    bid_ratio = _resolve_bid_ratio(signal, ctx)
    failures = []
    if strength < req_strength:
        failures.append(f"strength {strength:.1f} < {req_strength:.1f}({regime})")
    # 스윙 전략은 WS 미구독 시 bid_ratio None이 정상 — gate 면제
    _SWING_GATE_EXEMPT_BID = {"S15_MOMENTUM_ALIGN", "S9_PULLBACK_SWING", "S14_OVERSOLD_BOUNCE", "S4_BIG_CANDLE"}
    if bid_ratio is None:
        if strategy not in _SWING_GATE_EXEMPT_BID:
            failures.append(f"bid_ratio missing < {req_bid:.2f}({regime})")
    elif bid_ratio < req_bid:
        rescue_floor = _BID_RATIO_RESCUE_FLOOR.get(strategy, req_bid)
        rr = _fv(signal.get("rr_ratio"), None)
        bid_only_rescue = (
            strategy in _BID_ONLY_RESCUE_STRATEGIES
            and strength >= req_strength
            and bid_ratio >= _BID_RATIO_ABSOLUTE_CANCEL
            and bid_ratio >= rescue_floor
            and not any(f.startswith("strength ") for f in failures)
        )
        if strategy == "S1_GAP_OPEN":
            bid_only_rescue = bid_only_rescue and strength >= req_strength * 1.25 and (rr is None or rr >= 1.2)
        elif strategy == "S15_MOMENTUM_ALIGN":
            bid_only_rescue = bid_only_rescue and (rr is None or rr >= 1.5)
        if bid_only_rescue:
            signal["hard_gate_bid_ratio_rescued"] = True
            signal["decision_stage"] = "AI_REVIEW"
            signal["rescue_entry_policy"] = (
                "opening_momentum_size_down" if strategy == "S1_GAP_OPEN" else "limit_or_recheck"
            )
            signal["hard_gate_bid_ratio_rescue_reason"] = (
                f"bid_ratio {bid_ratio:.2f} < {req_bid:.2f}({regime}) but strength {strength:.1f} passed"
            )
        else:
            failures.append(f"bid_ratio {bid_ratio:.2f} < {req_bid:.2f}({regime})")
    if failures:
        return "; ".join(failures)
    return None


def _s8_buy_zone_gate_failure(signal: dict) -> str | None:
    if signal.get("strategy") != "S8_GOLDEN_CROSS":
        return None

    buy_zone = signal.get("buy_zone")
    if not isinstance(buy_zone, dict):
        return None

    cur_prc = _fv(signal.get("cur_prc") or signal.get("entry_price"), None)
    z_low = _fv(buy_zone.get("low"), None)
    z_high = _fv(buy_zone.get("high"), None)
    if cur_prc is None or z_low is None or z_high is None:
        return None
    if cur_prc <= 0 or z_low <= 0 or z_high <= 0 or z_low > z_high:
        return None

    signal["s8_buy_zone_role"] = signal.get("s8_buy_zone_role") or "support_zone"

    if cur_prc < z_low:
        signal["s8_zone_status"] = "hard_cancel"
        signal["s8_zone_entry_policy"] = "no_entry"
        return f"S8 support zone failed: price {cur_prc:.1f} below support low {z_low:.1f}"

    gap_pct = max(0.0, (cur_prc - z_high) / z_high * 100.0)
    signal["s8_buy_zone_high_gap_pct"] = round(gap_pct, 3)

    zone_rr = _fv(signal.get("zone_rr"), None)
    if zone_rr is not None and zone_rr < S8_MIN_ZONE_RR:
        signal["s8_zone_status"] = "hard_cancel"
        signal["s8_zone_entry_policy"] = "no_entry"
        return f"S8 zone_rr {zone_rr:.2f} below {S8_MIN_ZONE_RR:.2f}"

    if gap_pct > S8_SUPPORT_ZONE_HARD_CANCEL_GAP_PCT:
        rr = _fv(signal.get("rr_ratio"), None)
        rule_score_value = _fv(signal.get("rule_score"), 0.0)
        quality_score = _fv(signal.get("signal_quality_score"), 0.0)
        strength = _resolve_execution_strength(signal, {})
        bid_ratio = _fv(signal.get("bid_ratio"), None)
        zone_strength = int(_fv(buy_zone.get("strength"), 0.0) or 0)
        anchors = buy_zone.get("anchors") or []
        anchor_count = len(anchors) if isinstance(anchors, list) else 0
        zone_quality_ok = zone_strength >= 4 and anchor_count >= 3
        demand_ok = (
            bid_ratio is None
            or bid_ratio >= _BID_RATIO_RESCUE_FLOOR["S8_GOLDEN_CROSS"]
            or (strength >= 130.0 and bid_ratio >= 0.50)
        )
        extreme_gap_ok = (
            gap_pct <= 8.0
            or (
                rr is not None and rr >= 2.2
                and rule_score_value >= 82.0
                and quality_score >= 75.0
            )
        )
        momentum_ok = (
            zone_quality_ok
            and demand_ok
            and extreme_gap_ok
            and ((rr is not None and rr >= 1.5) or rule_score_value >= 75.0 or quality_score >= 70.0)
        )
        if momentum_ok:
            signal["s8_zone_status"] = "caution"
            signal["s8_zone_entry_policy"] = "momentum_chase_size_down"
            signal["decision_stage"] = "SIZE_DOWN"
            signal["s8_zone_caution_reason"] = (
                f"support gap {gap_pct:.2f}% above "
                f"{S8_SUPPORT_ZONE_HARD_CANCEL_GAP_PCT:.2f}% but momentum/RR strong"
            )
            return None
        signal["s8_zone_status"] = "hard_cancel"
        signal["s8_zone_entry_policy"] = "no_entry"
        return (
            f"S8 support gap {gap_pct:.2f}% above "
            f"{S8_SUPPORT_ZONE_HARD_CANCEL_GAP_PCT:.2f}%"
        )

    if gap_pct > S8_SUPPORT_ZONE_CAUTION_GAP_PCT:
        signal["s8_zone_status"] = "caution"
        signal["s8_zone_entry_policy"] = "limit_pullback"
        signal["s8_zone_caution_reason"] = (
            f"support gap {gap_pct:.2f}% above "
            f"{S8_SUPPORT_ZONE_CAUTION_GAP_PCT:.2f}%"
        )
    else:
        signal["s8_zone_status"] = "pass"
        signal["s8_zone_entry_policy"] = "current_or_limit"
    return None


async def _refresh_chart_if_needed(
    ctx: dict,
    stk_cd: str,
    token: str | None,
    strategy: str,
    refresh_meta: dict,
) -> None:
    """
    ENABLE_CHART_RETRY=true일 때 전략별 chart 데이터를 보강한다.
    - daily candle: S8/S9/S13/S14/S15
    - minute candle: S4/S12
    chart fallback 사용 시 confidence를 MEDIUM 이하로 제한한다.
    장중 현재가 대체재로 daily candle 사용 금지.
    """
    if not ENABLE_CHART_RETRY or not token:
        return
    if _fetch_daily_candles_ws is None:
        return

    refresh_sources = refresh_meta.get("market_data_sources", {})
    retry_failures = refresh_meta.get("retry_failures", [])

    if strategy in _CHART_DAILY_STRATEGIES:
        try:
            candles, status = await asyncio.wait_for(
                _fetch_daily_candles_ws(token, stk_cd),
                timeout=5.0,
            )
            if candles and status.get("source") != "EMPTY":
                ctx.setdefault("chart", {})["daily"] = candles
                ctx.setdefault("chart", {})["daily_status"] = status
                refresh_sources["chart_daily"] = status.get("source", "rest").lower()
                # 장중 미확정봉(intraday_day_bar=True) 시 메타데이터 경고
                if status.get("intraday_day_bar"):
                    ctx["chart"]["daily_intraday_bar"] = True
                    retry_failures.append("chart_daily:intraday_bar_unconfirmed")
                ctx["chart_fallback_used"] = True
                logger.debug("[Worker] chart daily refreshed [%s %s]: %d candles src=%s",
                             stk_cd, strategy, len(candles), status.get("source"))
            else:
                retry_failures.append("chart_daily:empty")
        except Exception as e:
            retry_failures.append(f"chart_daily:{e}")
            logger.debug("[Worker] chart daily refresh failed [%s %s]: %s", stk_cd, strategy, e)

    elif strategy in _CHART_MINUTE_STRATEGIES and _fetch_minute_candles_ws is not None:
        try:
            candles, status = await asyncio.wait_for(
                _fetch_minute_candles_ws(token, stk_cd, tic_scope="1"),
                timeout=5.0,
            )
            if candles and status.get("source") != "EMPTY":
                ctx.setdefault("chart", {})["minute"] = candles
                ctx.setdefault("chart", {})["minute_status"] = status
                refresh_sources["chart_minute"] = status.get("source", "rest").lower()
                if not status.get("is_current_bar_closed"):
                    ctx["chart"]["minute_bar_open"] = True
                    retry_failures.append("chart_minute:current_bar_open")
                ctx["chart_fallback_used"] = True
                logger.debug("[Worker] chart minute refreshed [%s %s]: %d candles src=%s",
                             stk_cd, strategy, len(candles), status.get("source"))
            else:
                retry_failures.append("chart_minute:empty")
        except Exception as e:
            retry_failures.append(f"chart_minute:{e}")
            logger.debug("[Worker] chart minute refresh failed [%s %s]: %s", stk_cd, strategy, e)


async def _refresh_stale_ctx(ctx: dict, stk_cd: str, rdb, signal: dict, strategy: str = "") -> None:
    """
    tick/hoga/strength 중 stale/missing 항목을 갱신한다.

    우선순위:
      tick     → signal 보유 cur_prc/flu_rt 우선, 없으면 REST (ENABLE_TICK_REST_FALLBACK=true 시)
      strength → REST direct (stale ws:strength Redis list 재사용 금지)
      hoga     → signal bid_ratio 우선, REST direct fallback (stale ws:hoga 재사용 금지)

    stale/missing → REST direct 함수 사용. Redis 캐시(ws:hoga, hoga:rest, ws:strength) 재사용 없음.
    ctx["freshness"]와 ctx["refresh_meta"]를 갱신한다.
    """
    if not ENABLE_SCORING_DATA_RETRY:
        return

    freshness = ctx.get("freshness", {}) or {}
    _refresh_attempted: dict[str, str] = {}
    _refresh_sources: dict[str, str] = {}
    _retry_failures: list[str] = []

    # ── tick: signal 값 우선, 없으면 REST (ENABLE_TICK_REST_FALLBACK) ──────
    tick_state = (freshness.get("tick") or {}).get("state", "fresh")
    if tick_state in ("cancel", "missing"):
        _refresh_attempted["tick"] = tick_state
        _cur = float(signal.get("cur_prc") or 0)
        _flu = float(signal.get("flu_rt") or signal.get("gap_pct") or 0)
        if _cur > 0:
            ctx["tick"] = {"cur_prc": _cur, "flu_rt": _flu}
            freshness["tick"] = {
                "state": "caution", "kind": "tick",
                "age_ms": None, "source": "signal_fallback",
            }
            _refresh_sources["tick"] = "signal_fallback"
            logger.debug("[Worker] tick_ctx refreshed from signal [%s]: prc=%.0f flu=%.2f",
                         stk_cd, _cur, _flu)

    # tick_state 재확인 (signal fallback 후 갱신 여부 반영)
    tick_state_now = (freshness.get("tick") or {}).get("state", tick_state)

    str_state  = (freshness.get("strength") or {}).get("state", "fresh")
    hoga_state = (freshness.get("hoga") or {}).get("state", "fresh")

    # tick REST fallback 대상 여부
    _tick_needs_rest = (
        ENABLE_TICK_REST_FALLBACK
        and tick_state_now in ("cancel", "missing")
    )

    if (str_state not in ("cancel", "missing")
            and hoga_state not in ("cancel", "missing")
            and not _tick_needs_rest):
        ctx["freshness"] = freshness
        _early_meta = {
            "market_data_sources": _refresh_sources,
            "data_refresh_attempted": _refresh_attempted,
            "retry_failures": _retry_failures,
        }
        ctx["refresh_meta"] = _early_meta
        # ── chart 보강 (P2 — ENABLE_CHART_RETRY=true 시에만 실행) ────────
        if ENABLE_CHART_RETRY and strategy:
            try:
                _early_token = await rdb.get("kiwoom:token")
            except Exception:
                _early_token = None
            await _refresh_chart_if_needed(ctx, stk_cd, _early_token, strategy, _early_meta)
        return

    try:
        token = await rdb.get("kiwoom:token")
    except Exception:
        token = None

    # ── tick REST fallback (ENABLE_TICK_REST_FALLBACK=true, signal 값도 없을 때) ──
    if _tick_needs_rest and token:
        try:
            tick_data, tick_meta = await asyncio.wait_for(
                _fetch_tick_snapshot(token, stk_cd), timeout=3.0
            )
            if tick_data.get("cur_prc"):
                ctx["tick"] = {
                    "cur_prc": float(tick_data["cur_prc"]),
                    "flu_rt": float(tick_data.get("flu_rt") or 0),
                }
                freshness["tick"] = {
                    "state": "caution", "kind": "tick",
                    "age_ms": tick_meta.get("latency_ms", 0), "source": "rest",
                }
                _refresh_sources["tick"] = "rest"
                logger.debug("[Worker] tick refreshed via REST direct [%s]: prc=%s",
                             stk_cd, tick_data["cur_prc"])
            else:
                _retry_failures.append("tick:rest_no_data")
                logger.debug("[Worker] tick REST direct failed [%s]: %s", stk_cd, tick_meta.get("error"))
        except Exception as e:
            _retry_failures.append(f"tick:{e}")
            logger.debug("[Worker] tick REST direct failed [%s]: %s", stk_cd, e)

    # ── strength: REST direct — stale ws:strength Redis list 재사용 금지 ──
    if str_state in ("cancel", "missing") and token:
        _refresh_attempted["strength"] = str_state
        try:
            new_str, str_meta = await asyncio.wait_for(
                _fetch_str_rest(token, stk_cd), timeout=3.0
            )
            if new_str is not None:
                ctx["strength"] = new_str
                freshness["strength"] = {
                    "state": "caution", "kind": "strength",
                    "age_ms": str_meta.get("latency_ms", 0), "source": "rest",
                }
                _refresh_sources["strength"] = "rest"
                logger.debug("[Worker] strength refreshed via REST direct [%s]: %.1f", stk_cd, new_str)
            else:
                _retry_failures.append("strength:rest_no_data")
                logger.debug("[Worker] strength REST direct failed [%s]: %s", stk_cd, str_meta.get("error"))
        except Exception as e:
            _retry_failures.append(f"strength:{e}")
            logger.debug("[Worker] strength REST direct failed [%s]: %s", stk_cd, e)

    # ── hoga: signal bid_ratio 우선, 없으면 REST direct — stale ws:hoga 재사용 금지 ──
    if hoga_state in ("cancel", "missing"):
        _refresh_attempted["hoga"] = hoga_state
        sig_bid = signal.get("bid_ratio")
        if sig_bid is not None:
            _b = float(sig_bid)
            ctx["hoga"] = {"total_buy_bid_req": _b, "total_sel_bid_req": 1.0}
            freshness["hoga"] = {
                "state": "caution", "kind": "hoga",
                "age_ms": None, "source": "signal_fallback",
            }
            _refresh_sources["hoga"] = "signal_fallback"
            logger.debug("[Worker] hoga_ctx refreshed from signal [%s]: bid=%.2f", stk_cd, _b)
        elif token:
            try:
                new_bid, hoga_meta = await asyncio.wait_for(
                    _fetch_hoga_rest(token, stk_cd), timeout=3.0
                )
                if new_bid is not None:
                    ctx["hoga"] = {"total_buy_bid_req": float(new_bid), "total_sel_bid_req": 1.0}
                    freshness["hoga"] = {
                        "state": "caution", "kind": "hoga",
                        "age_ms": hoga_meta.get("latency_ms", 0), "source": "rest",
                    }
                    _refresh_sources["hoga"] = "rest"
                    logger.debug("[Worker] hoga refreshed via REST direct [%s]: %.2f", stk_cd, new_bid)
                else:
                    _retry_failures.append("hoga:rest_no_data")
                    logger.debug("[Worker] hoga REST direct failed [%s]: %s", stk_cd, hoga_meta.get("error"))
            except Exception as e:
                _retry_failures.append(f"hoga:{e}")
                logger.debug("[Worker] hoga REST direct failed [%s]: %s", stk_cd, e)
        else:
            _retry_failures.append("hoga:no_token")

    ctx["freshness"] = freshness
    _final_meta = {
        "market_data_sources": _refresh_sources,
        "data_refresh_attempted": _refresh_attempted,
        "retry_failures": _retry_failures,
    }
    ctx["refresh_meta"] = _final_meta
    # ── chart 보강 (P2 — ENABLE_CHART_RETRY=true 시에만 실행) ────────
    await _refresh_chart_if_needed(ctx, stk_cd, token, strategy, _final_meta)
    # ── 운영 metric: data_retry 결과 카운터 ────────────────────────────
    if strategy:
        try:
            _dr_today = datetime.now(_KST).strftime("%Y-%m-%d")
            sources = _final_meta.get("market_data_sources", {})
            failures = _final_meta.get("retry_failures", [])
            for _field, _src in sources.items():
                await rdb.hincrby(f"status:data_retry:{_dr_today}:{strategy}:{_field}", _src, 1)
                await rdb.expire(f"status:data_retry:{_dr_today}:{strategy}:{_field}", _PIPELINE_TTL_SEC)
            for _fail in failures:
                _fail_key = _fail.split(":")[0] if ":" in _fail else _fail
                await rdb.hincrby(f"status:data_retry:{_dr_today}:{strategy}:{_fail_key}", "failed", 1)
                await rdb.expire(f"status:data_retry:{_dr_today}:{strategy}:{_fail_key}", _PIPELINE_TTL_SEC)
        except Exception:
            pass


def _freshness_cancel_reason(ctx: dict, strategy: str = "") -> str | None:
    freshness = ctx.get("freshness", {}) or {}
    for key in ("tick", "hoga", "strength"):
        status = freshness.get(key, {}) or {}
        state = status.get("state")
        if state == "cancel" and strategy in _STRICT_CANCEL_GATE:
            return f"{key} data stale: age_ms={status.get('age_ms')}"
        if state == "missing" and key == "tick" and strategy in _STRICT_CANCEL_GATE:
            return f"tick missing (WS unsubscribed) [{strategy}]"
    vi = ctx.get("vi", {}) or {}
    vi_status = freshness.get("vi", {}) or {}
    if vi and vi_status.get("state") == "cancel":
        return f"vi data stale: age_ms={vi_status.get('age_ms')}"
    return None


def _compute_freshness_decision(freshness: dict, strategy: str) -> str:
    """
    실시간 Redis 데이터 신선도를 종합해 최종 결정을 반환한다.

    전략별 정책 (문서 4.1):
    - S1/S2/S4/S10/S12/S13: tick 또는 hoga cancel → CANCEL
    - S3/S5/S11: REST 기반 – tick stale 이어도 SHADOW 허용
    - 나머지: tick stale → SHADOW, hoga missing → caution

    Returns: PASS | CAUTION | SHADOW | SIZE_DOWN | CANCEL
    """
    rest_strategies = {"S3_INST_FRGN", "S5_PROG_FRGN", "S11_FRGN_CONT"}

    tick_state     = (freshness.get("tick") or {}).get("state", "missing")
    hoga_state     = (freshness.get("hoga") or {}).get("state", "missing")
    strength_state = (freshness.get("strength") or {}).get("state", "missing")

    if strategy in _STRICT_CANCEL_GATE:
        if tick_state == "cancel" or hoga_state == "cancel":
            return "CANCEL"
        if tick_state in ("caution", "missing") or hoga_state in ("caution", "missing"):
            return "CAUTION"
    elif strategy in rest_strategies:
        if tick_state == "cancel":
            return "SHADOW"
        if hoga_state == "cancel":
            return "SIZE_DOWN"
    else:
        if tick_state == "cancel":
            return "SHADOW"
        if hoga_state == "cancel":
            return "CAUTION"
        if strength_state == "cancel":
            return "CAUTION"

    if tick_state == "caution" or hoga_state == "caution":
        return "CAUTION"

    return "PASS"


def _freshness_status_from_decision(decision: str) -> str:
    """
    freshness_decision → position_sizing 이 사용하는 freshness_status 변환.
    PASS          → FRESH
    CAUTION/SIZE_DOWN → CAUTION
    SHADOW/CANCEL → STALE
    """
    if decision == "PASS":
        return "FRESH"
    if decision in ("CAUTION", "SIZE_DOWN"):
        return "CAUTION"
    return "STALE"


def _collect_missing_feature_flags(signal: dict, ctx: dict) -> list[str]:
    """신호와 컨텍스트에서 누락된 필수 피처 목록을 반환한다."""
    missing = []
    # 현재가
    if not _fv(signal.get("cur_prc"), None) and not _fv(signal.get("entry_price"), None):
        missing.append("cur_prc")
    # 체결강도
    strength = ctx.get("strength")
    if not strength:
        missing.append("strength")
    # 호가
    hoga = ctx.get("hoga")
    if not hoga:
        missing.append("hoga")
    # tick
    tick = ctx.get("tick")
    if not tick:
        missing.append("tick")
    # RSI
    if signal.get("rsi") is None and signal.get("rsi14") is None:
        missing.append("rsi")
    # RR ratio
    if signal.get("rr_ratio") is None:
        missing.append("rr_ratio")
    # 수급 (S3/S5/S11)
    strategy = signal.get("strategy", "")
    if strategy in ("S3_INST_FRGN", "S5_PROG_FRGN", "S11_FRGN_CONT"):
        if not signal.get("inst_buy_amt") and not signal.get("frgn_buy_amt"):
            missing.append("supply_demand")
    return missing


def _compute_data_quality(missing_flags: list[str], freshness_decision: str, signal: dict) -> dict:
    """
    data_quality_score (0~100)와 data_quality_decision을 계산한다.

    하드 결측은 큰 감점, 소프트 결측은 소감점.
    freshness_decision 도 반영한다.
    Returns dict with data_quality_score, data_quality_decision, fallback_used.
    """
    score = 100.0
    hard_missing = {"cur_prc", "rr_ratio"}
    for flag in missing_flags:
        if flag in hard_missing:
            score -= 30.0
        else:
            score -= 10.0

    freshness_penalty = {"CANCEL": 40.0, "SHADOW": 20.0, "SIZE_DOWN": 10.0, "CAUTION": 5.0, "PASS": 0.0}
    score -= freshness_penalty.get(freshness_decision, 0.0)
    score = max(0.0, min(100.0, score))

    if score >= 80:
        decision = "PASS"
    elif score >= 60:
        decision = "SHADOW"
    elif score >= 40:
        decision = "SIZE_DOWN"
    else:
        decision = "CANCEL"

    fallback_used = bool(signal.get("fallback_source") or signal.get("fallback_used"))
    return {
        "data_quality_score": round(score, 1),
        "data_quality_decision": decision,
        "missing_feature_flags": missing_flags,
        "fallback_used": fallback_used,
    }


def _rr_prefilter_reason(signal: dict, ctx: dict | None = None) -> str | None:
    rr = _fv(signal.get("rr_ratio"), None)
    if rr is None:
        return None
    strategy = signal.get("strategy", "")
    regime, threshold = _resolve_regime_rr_policy(ctx, strategy)
    _apply_regime_rr_metadata(signal, regime, threshold)
    # 하락장 반등 전략은 bear 장세가 오히려 진입 근거 → bull 임계값으로 완화
    if rr < threshold:
        return f"R:R {rr:.2f} below {threshold:.2f}({regime})"
    return None


def _resolve_regime_rr_policy(ctx: dict | None, strategy: str = "") -> tuple[str, float]:
    regime = _detect_market_regime(ctx or {}, strategy) if ctx else "neutral"
    if regime == "bear" and strategy in _BEAR_GATE_EXEMPT:
        threshold = _RR_BY_REGIME["bull"]
    else:
        threshold = _RR_BY_REGIME.get(regime, RR_HARD_CANCEL_THRESHOLD)
    return regime, float(threshold)


def _apply_regime_rr_metadata(payload: dict, regime: str, threshold: float) -> None:
    payload["rr_policy"] = "market_regime"
    payload["rr_regime"] = regime
    payload["rr_regime_threshold"] = round(float(threshold), 2)


def _rr_quality_bucket(rr: float | None) -> str:
    if rr is None:
        return "unknown"
    if rr < RR_HARD_CANCEL_THRESHOLD:
        return "hard_cancel"
    if rr < RR_CAUTION_THRESHOLD:
        return "caution"
    if rr < 1.5:
        return "acceptable"
    return "strong"


def _maybe_promote_hold_to_enter(
    *,
    strategy: str = "",
    action: str,
    confidence: str,
    reason: str,
    cancel_reason: str | None,
    ai_score: float | None,
) -> tuple[str, str, str, str | None]:
    """Promote high-score Claude HOLD decisions into actionable ENTER signals."""
    if str(action).upper() != "HOLD":
        return action, confidence, reason, cancel_reason
    try:
        score = float(ai_score)
    except (TypeError, ValueError):
        return action, confidence, reason, cancel_reason
    threshold = _get_hold_threshold(strategy) if strategy else HOLD_TO_ENTER_MIN_AI_SCORE
    if score < threshold:
        return action, confidence, reason, cancel_reason

    promoted_reason = (
        f"{reason} | HOLD promoted to ENTER because ai_score "
        f"{score:.1f} >= {threshold:.1f}"
    )
    return "ENTER", confidence or "HIGH", promoted_reason, None


def _rule_threshold_rescue_reason(
    signal: dict,
    ctx: dict,
    *,
    rule_score_value: float,
    threshold: float,
    quality: dict,
) -> str | None:
    strategy = signal.get("strategy", "")
    floor = _RULE_THRESHOLD_RESCUE_FLOORS.get(strategy)
    if floor is None or rule_score_value >= threshold or rule_score_value < floor:
        return None

    rr = _fv(signal.get("rr_ratio"), None)
    strength = _resolve_execution_strength(signal, ctx)
    bid_ratio = _resolve_bid_ratio(signal, ctx)
    quality_score = _fv(quality.get("signal_quality_score"), 0.0)
    vol_ratio = _fv(signal.get("vol_ratio") or signal.get("volume_ratio"), 0.0)

    if bid_ratio is not None and bid_ratio < _BID_RATIO_ABSOLUTE_CANCEL:
        return None

    if strategy == "S7_ICHIMOKU_BREAKOUT":
        cloud_thickness = _fv(signal.get("cloud_thickness_pct"), None)
        chikou_above = bool(signal.get("chikou_above"))
        cond_count = int(_fv(signal.get("cond_count"), 0.0) or 0)
        structure_ok = (
            (cloud_thickness is not None and cloud_thickness <= 1.5)
            or chikou_above
            or cond_count >= 2
        )
        if rr is not None and rr >= 1.8 and strength >= 115.0 and vol_ratio >= 1.5 and structure_ok:
            return (
                f"S7 rescue: rule_score {rule_score_value:.1f} below {threshold:.1f}, "
                f"RR {rr:.2f}, strength {strength:.1f}, vol_ratio {vol_ratio:.2f}"
            )
        return None

    if strategy not in ("S1_GAP_OPEN", "S15_MOMENTUM_ALIGN") and rr is not None and rr >= 1.5 and strength >= 100.0:
        return f"rule_score {rule_score_value:.1f} below {threshold:.1f} but RR {rr:.2f} and strength {strength:.1f} are strong"
    if strategy == "S1_GAP_OPEN" and rr is not None and rr >= 1.2 and strength >= 140.0 and (bid_ratio or 0.0) >= 1.5:
        return f"S1 opening momentum rescue: strength {strength:.1f}, bid_ratio {(bid_ratio or 0.0):.2f}"
    if strategy == "S15_MOMENTUM_ALIGN" and rr is not None and rr >= 1.3 and strength >= 90.0 and (bid_ratio or 0.0) >= 1.5:
        return f"S15 momentum rescue: strength {strength:.1f}, bid_ratio {(bid_ratio or 0.0):.2f}"
    if quality_score >= 70.0 and rr is not None and rr >= 1.2:
        return f"signal quality {quality_score:.1f} offsets rule_score {rule_score_value:.1f} below {threshold:.1f}"
    return None


def _compute_signal_quality(
    signal: dict,
    ctx: dict,
    rule_score_value: float,
    *,
    stale_hoga: bool = False,
) -> dict:
    """Current-signal quality score used before enough live performance data exists."""
    strength = _resolve_execution_strength(signal, ctx)
    bid_ratio = _resolve_bid_ratio(signal, ctx)
    rr = _fv(signal.get("rr_ratio"), None)
    vol_ratio = _fv(signal.get("vol_ratio"), 0.0)
    cond_count = int(signal.get("cond_count", 0) or 0)

    rule_component = max(0.0, min(45.0, rule_score_value * 0.45))
    strength_component = max(0.0, min(20.0, (strength - 80.0) * 0.25))

    bid_component = 0.0
    if bid_ratio is not None:
        if bid_ratio >= 2.0:
            bid_component = 10.0
        elif bid_ratio >= 1.5:
            bid_component = 8.0
        elif bid_ratio >= 1.2:
            bid_component = 5.0
        elif bid_ratio >= 1.0:
            bid_component = 2.0

    # stale hoga → lenient 전략은 bid_component 제거 (신선도 없는 호가 가점 금지)
    if stale_hoga:
        bid_component = 0.0

    if rr is None:
        rr_component = 3.0
    elif rr < RR_HARD_CANCEL_THRESHOLD:
        rr_component = -12.0
    elif rr < RR_CAUTION_THRESHOLD:
        rr_component = -4.0
    elif rr < 1.5:
        rr_component = 6.0
    else:
        rr_component = 10.0

    setup_component = 0.0
    if vol_ratio >= 2.0:
        setup_component += 5.0
    elif vol_ratio >= 1.2:
        setup_component += 3.0
    setup_component += min(cond_count, 4) * 1.5
    if _fv(signal.get("rsi")) > 0:
        setup_component += 2.0

    freshness_component = 5.0
    freshness = ctx.get("freshness", {}) or {}
    for key in ("tick", "hoga", "strength"):
        status = freshness.get(key, {}) or {}
        if status.get("state") == "caution":
            freshness_component -= 1.5
        elif status.get("state") == "cancel":
            freshness_component -= 5.0
            break

    total = rule_component + strength_component + bid_component + rr_component + setup_component + max(0.0, freshness_component)
    total = round(max(0.0, min(100.0, total)), 1)

    if total >= 70:
        bucket = "strong"
    elif total >= 55:
        bucket = "acceptable"
    elif total >= 40:
        bucket = "weak"
    else:
        bucket = "poor"

    return {
        "signal_quality_score": total,
        "signal_quality_bucket": bucket,
        "rr_quality_bucket": _rr_quality_bucket(rr),
        "quality_components": {
            "rule": round(rule_component, 2),
            "strength": round(strength_component, 2),
            "bid": round(bid_component, 2),
            "rr": round(rr_component, 2),
            "setup": round(setup_component, 2),
            "freshness": round(max(0.0, freshness_component), 2),
        },
        "performance_sample_count": 0,
        "performance_ev_status": "insufficient_data",
    }


def _build_rule_only_alert_payload(item: dict, rule_score_value: float, quality: dict) -> dict:
    """Build the lightweight alert emitted as soon as the rule gate passes."""
    payload = {
        **item,
        "type": "RULE_ONLY_SIGNAL",
        "signal_grade": "RULE_ONLY",
        "validation_stage": "RULE_ONLY",
        "action": "ENTER",
        "confidence": "RULE_ONLY",
        "rule_score": rule_score_value,
        "ai_score": rule_score_value,
        "ai_reason": "1차 규칙 통과",
        "human_confirmed": False,
        "claude_confirmed": False,
        **quality,
    }
    payload.pop("cancel_reason", None)
    return payload


def _attach_rescue_shadow_metadata(payload: dict) -> None:
    shadow = payload.get("shadow_features")
    if not isinstance(shadow, dict):
        shadow = {}

    meta_keys = (
        "decision_stage",
        "rule_threshold_rescued",
        "rule_threshold_rescue_reason",
        "hard_gate_bid_ratio_rescued",
        "hard_gate_bid_ratio_rescue_reason",
        "rescue_entry_policy",
        "s8_zone_status",
        "s8_zone_entry_policy",
        "s8_zone_caution_reason",
        "s8_buy_zone_high_gap_pct",
        "entry_size_score",
        "entry_size_tier",
        "entry_size_weight",
        "position_scale",
        "entry_size_basis",
    )
    meta = {
        key: payload.get(key)
        for key in meta_keys
        if payload.get(key) is not None
    }
    if meta:
        shadow["rescue_meta"] = meta
        payload["shadow_features"] = shadow


def _raw_rr(entry: float | None, tp: float | None, sl: float | None) -> float | None:
    entry_f = _fv(entry, None)
    tp_f = _fv(tp, None)
    sl_f = _fv(sl, None)
    if entry_f is None or tp_f is None or sl_f is None:
        return None
    if entry_f <= 0 or tp_f <= entry_f or sl_f >= entry_f:
        return None
    risk = entry_f - sl_f
    if risk <= 0:
        return None
    return round((tp_f - entry_f) / risk, 3)


def _null_claude_prices(payload: dict) -> None:
    for field in _CLAUDE_PRICE_FIELDS:
        payload[field] = None


def _cancel_by_claude_hard_rule(payload: dict, reason: str) -> dict:
    payload["action"] = "CANCEL"
    payload["confidence"] = "LOW"
    payload["cancel_reason"] = reason
    payload["ai_reason"] = reason
    payload["skip_entry"] = True
    payload["cancel_type"] = CLAUDE_HARD_RULE_CANCEL_TYPE
    _null_claude_prices(payload)
    return payload


def _apply_claude_postprocess_hard_rules(payload: dict) -> dict:
    """Apply final schema/risk hard rules after Claude action/TP/SL overrides."""
    action = str(payload.get("action") or "HOLD").upper()
    payload["action"] = action

    if action in ("HOLD", "CANCEL"):
        _null_claude_prices(payload)
        return payload

    if action != "ENTER":
        return payload

    entry = _fv(payload.get("cur_prc") or payload.get("entry_price"), None)
    claude_tp1 = _fv(payload.get("claude_tp1"), None)
    claude_tp2 = _fv(payload.get("claude_tp2"), None)
    claude_sl = _fv(payload.get("claude_sl"), None)

    fallback_tp1 = _fv(payload.get("tp1_price") or payload.get("display_tp2_price"), None)
    fallback_sl = _fv(payload.get("sl_price"), None)
    effective_tp1 = claude_tp1 if claude_tp1 is not None else fallback_tp1
    effective_sl = claude_sl if claude_sl is not None else fallback_sl

    if payload.get("strategy") == "S1_GAP_OPEN" and (
        entry is None or effective_tp1 is None or effective_sl is None
    ):
        return _cancel_by_claude_hard_rule(
            payload,
            "S1 TP/SL hard rule failed: ENTER requires entry, tp1, and sl",
        )

    if payload.get("strategy") == "S1_GAP_OPEN" and not (effective_tp1 > entry > effective_sl):
        return _cancel_by_claude_hard_rule(
            payload,
            "S1 TP/SL hard rule failed: requires tp1 > entry > sl",
        )

    if entry is not None and (claude_tp1 is not None or claude_sl is not None):
        if claude_tp1 is None or claude_sl is None or not (claude_tp1 > entry > claude_sl):
            return _cancel_by_claude_hard_rule(
                payload,
                "Claude TP/SL hard rule failed: requires tp1 > entry > sl",
            )

    if claude_tp2 is not None and claude_tp1 is not None and claude_tp2 < claude_tp1:
        return _cancel_by_claude_hard_rule(
            payload,
            "Claude TP/SL hard rule failed: tp2 must be greater than or equal to tp1",
        )

    return payload


def _apply_claude_rr_override(payload: dict, ctx: dict | None = None) -> dict:
    """Recompute displayed/stored RR when Claude changes executable TP/SL."""
    if payload.get("action") != "ENTER":
        return payload

    entry = _fv(payload.get("cur_prc") or payload.get("entry_price"), None)
    claude_tp = _fv(payload.get("claude_tp1"), None)
    claude_sl = _fv(payload.get("claude_sl"), None)
    if entry is None or claude_tp is None or claude_sl is None:
        return payload

    rr, skip = compute_rr(
        str(payload.get("stk_cd", "")),
        entry,
        claude_tp,
        claude_sl,
        min_rr=None,
    )
    regime, threshold = _resolve_regime_rr_policy(ctx, str(payload.get("strategy", "")))
    _apply_regime_rr_metadata(payload, regime, threshold)
    payload["rr_ratio"] = rr
    payload["effective_rr"] = rr
    payload["single_tp_rr"] = _raw_rr(entry, claude_tp, claude_sl)
    payload["raw_rr"] = payload["single_tp_rr"]
    payload["rr_basis"] = "claude_tp_sl"
    payload["rr_quality_bucket"] = _rr_quality_bucket(rr)
    if rr < threshold:
        payload["action"] = "CANCEL"
        payload["confidence"] = "LOW"
        payload["cancel_reason"] = f"Claude TP/SL R:R {rr:.2f} below market regime threshold {threshold:.2f}({regime})"
        payload["ai_reason"] = payload["cancel_reason"]
        payload["skip_entry"] = True
        payload["rr_skip_reason"] = payload["cancel_reason"]
        payload["cancel_type"] = CLAUDE_HARD_RULE_CANCEL_TYPE
        _null_claude_prices(payload)
    elif skip and not payload.get("rr_skip_reason"):
        payload["rr_skip_reason"] = (
            f"Claude TP/SL effective_rr {rr:.2f} passed market regime threshold "
            f"{threshold:.2f}({regime}); strategy min_rr is advisory"
        )
    return payload


async def _build_market_ctx(rdb, stk_cd: str, *, sector: str = "", signal: dict | None = None) -> dict:
    tasks = [
        get_tick_data(rdb, stk_cd),
        get_hoga_data(rdb, stk_cd),
        get_avg_cntr_strength(rdb, stk_cd, 5),
        get_vi_status(rdb, stk_cd),
        get_market_freshness(rdb, stk_cd),
        get_sector_overheat_count(rdb, sector),
        get_market_index_flu_rt(rdb),
        get_stock_market_cap(rdb, stk_cd),
        get_market_index_exp_flu_rt(rdb),
    ]
    tick, hoga, strength, vi, freshness, sector_count, index_flu, market_cap, exp_flu = await asyncio.gather(*tasks)
    market_type = await _resolve_signal_market_type(
        rdb,
        stk_cd,
        str((signal or {}).get("strategy") or ""),
        signal,
    )
    return {
        "tick": tick,
        "hoga": hoga,
        "strength": strength,
        "vi": vi,
        "freshness": freshness,
        "sector_count": sector_count,
        "kospi_flu_rt": index_flu.get("kospi_flu_rt"),
        "kosdaq_flu_rt": index_flu.get("kosdaq_flu_rt"),
        "kospi_exp_flu_rt": exp_flu.get("kospi_exp_flu_rt"),
        "kosdaq_exp_flu_rt": exp_flu.get("kosdaq_exp_flu_rt"),
        "market_cap_eok": market_cap,
        "market_type": market_type,
    }


async def process_one(rdb, pg_pool=None) -> bool:
    """
    Process one queue item.

    Returns `True` when an item was consumed, otherwise `False`.
    """
    item = await pop_telegram_queue(rdb)
    if not item:
        return False

    normalize_signal_prices(item)

    stk_cd = normalize_stock_code(item.get("stk_cd", ""))
    strategy = item.get("strategy") or ""
    item["stk_cd"] = stk_cd

    # bypass 타입(FORCE_CLOSE, DAILY_REPORT 등)은 strategy 없이 발행되므로
    # _incr_pipeline 보다 먼저 체크해 파이프라인 카운터가 오염되지 않도록 한다.
    item_type = item.get("type", "")
    if item_type in ("FORCE_CLOSE", "DAILY_REPORT"):
        await push_score_only_queue(rdb, item)
        logger.debug("[Worker] bypass item forwarded [%s]", item_type)
        return True

    await _incr_pipeline(rdb, strategy, "candidate")

    if strategy and not item.get("persona"):
        item["persona"] = get_persona(strategy)

    if stk_cd and not item.get("stk_nm"):
        try:
            token = await rdb.get(REDIS_TOKEN_KEY)
            if token:
                item["stk_nm"] = await fetch_stk_nm(rdb, token, stk_cd)
        except Exception as nm_err:
            logger.debug("[Worker] stk_nm lookup failed [%s %s]: %s", stk_cd, strategy, nm_err)

    signal_id = item.get("id")
    signal = item

    try:
        try:
            hb = await rdb.hgetall("ws:py_heartbeat")
            ws_online = bool(hb and hb.get("updated_at"))
        except Exception:
            ws_online = False

        if not ws_online:
            logger.warning("[Worker] websocket heartbeat unavailable [%s %s]", stk_cd, strategy)

        sector = signal.get("sector", "") or ""
        ctx = await _build_market_ctx(rdb, stk_cd, sector=sector, signal=signal)
        if ctx.get("market_type") and not signal.get("market_type"):
            signal["market_type"] = ctx["market_type"]
        # stale/missing 항목을 signal 값 또는 REST로 갱신 (cancel보다 재조회 우선)
        await _refresh_stale_ctx(ctx, stk_cd, rdb, signal, strategy)
        exact_strength = _resolve_execution_strength(signal, ctx)
        ctx["strength"] = exact_strength
        signal["cntr_strength"] = round(exact_strength, 2) if exact_strength > 0 else signal.get("cntr_strength")
        resolved_bid_ratio = _resolve_bid_ratio(signal, ctx)
        if resolved_bid_ratio is not None:
            signal["bid_ratio"] = round(resolved_bid_ratio, 3)
        if signal.get("vol_ratio") is None and signal.get("volume_ratio") is not None:
            signal["vol_ratio"] = signal.get("volume_ratio")
        ctx["ws_online"] = ws_online

        r_score, components = _coerce_rule_score_result(rule_score(signal, ctx))
        signal["rule_score"] = r_score
        logger.info("[Worker] rule score [%s %s]: %.1f", stk_cd, strategy, r_score)
        _hoga_state = (ctx.get("freshness") or {}).get("hoga", {}).get("state", "fresh")
        _stale_hoga = _hoga_state in ("cancel", "missing", "caution")
        quality = _compute_signal_quality(signal, ctx, r_score, stale_hoga=_stale_hoga)
        signal.update(quality)

        threshold = get_claude_threshold(strategy)
        ai_score_val = r_score
        ai_result = {}
        cancel_type = None
        cancel_reason = None

        skip_ai = should_skip_ai(r_score, strategy)
        rescue_reason = (
            _rule_threshold_rescue_reason(
                signal,
                ctx,
                rule_score_value=r_score,
                threshold=threshold,
                quality=quality,
            )
            if skip_ai
            else None
        )
        if skip_ai and not rescue_reason:
            action = "CANCEL"
            confidence = "LOW"
            reason = f"Rule score {r_score:.1f} below threshold"
            cancel_reason = "Rule threshold not met"
            cancel_type = "RULE_THRESHOLD"
            await _incr_pipeline(rdb, strategy, "cancel_score")
        else:
            if rescue_reason:
                signal["rule_threshold_rescued"] = True
                signal["decision_stage"] = "AI_REVIEW"
                signal["rule_threshold_rescue_reason"] = rescue_reason
                await _incr_pipeline(rdb, strategy, "rule_threshold_rescue")
            rr_prefilter_reason = _rr_prefilter_reason(signal, ctx)
            s8_zone_gate_reason = _s8_buy_zone_gate_failure(signal)
            hard_gate_reason = _hard_gate_failure(signal, ctx)
            stale_reason = _freshness_cancel_reason(ctx, strategy)
            if rr_prefilter_reason:
                action = "CANCEL"
                confidence = "LOW"
                reason = rr_prefilter_reason
                cancel_reason = rr_prefilter_reason
                cancel_type = "RR_TOO_LOW"
                await _incr_pipeline(rdb, strategy, "cancel_rr")
            elif s8_zone_gate_reason:
                action = "CANCEL"
                confidence = "LOW"
                reason = s8_zone_gate_reason
                cancel_reason = s8_zone_gate_reason
                cancel_type = "S8_BUY_ZONE"
                await _incr_pipeline(rdb, strategy, "cancel_s8_buy_zone")
            elif hard_gate_reason:
                action = "CANCEL"
                confidence = "LOW"
                reason = f"Hard gate failed: {hard_gate_reason}"
                cancel_reason = reason
                cancel_type = "HARD_GATE"
                await _incr_pipeline(rdb, strategy, "cancel_hard_gate")
            elif stale_reason:
                action = "CANCEL"
                confidence = "LOW"
                reason = stale_reason
                cancel_reason = stale_reason
                cancel_type = "FRESHNESS_STALE"
                await _incr_pipeline(rdb, strategy, "cancel_freshness")
            else:
                await _incr_pipeline(rdb, strategy, "rule_pass")
                can_call = await check_daily_limit(rdb)
                if can_call:
                    try:
                        ai_result = await analyze_signal(signal, ctx, r_score, rdb=rdb)
                        ai_score_val = normalize_score_0_100(ai_result.get("ai_score", r_score))
                        action = ai_result.get("action", "ENTER")
                        confidence = ai_result.get("confidence", "HIGH")
                        reason = ai_result.get("reason", f"Rule score {r_score:.1f} passed")
                        cancel_reason = ai_result.get("cancel_reason")
                        action, confidence, reason, cancel_reason = _maybe_promote_hold_to_enter(
                            strategy=strategy,
                            action=action,
                            confidence=confidence,
                            reason=reason,
                            cancel_reason=cancel_reason,
                            ai_score=ai_score_val,
                        )
                        if action == "ENTER":
                            await _incr_pipeline(rdb, strategy, "ai_pass")
                        else:
                            await _incr_pipeline(rdb, strategy, "cancel_ai")
                    except Exception as claude_err:
                        logger.warning(
                            "[Worker] Claude failed [%s %s]: %s, canceling signal",
                            stk_cd,
                            strategy,
                            claude_err,
                        )
                        action = "CANCEL"
                        confidence = "LOW"
                        reason = f"Claude unavailable: {type(claude_err).__name__}"
                        cancel_reason = "AI analysis unavailable"
                        cancel_type = "AI_UNAVAILABLE"
                        await _incr_pipeline(rdb, strategy, "cancel_ai_unavailable")
                else:
                    action = "CANCEL"
                    confidence = "LOW"
                    reason = "Claude daily limit reached"
                    cancel_reason = "AI daily limit reached"
                    cancel_type = "AI_DAILY_LIMIT"
                    await _incr_pipeline(rdb, strategy, "cancel_ai_limit")

        display_reason = _resolve_display_reason(action, reason, cancel_reason)

        # ── 데이터 품질·신선도 메타데이터 계산 (Phase 1 관측 가능성) ────────────
        _freshness_dec = _compute_freshness_decision(ctx.get("freshness") or {}, strategy)
        # 운영 metric: freshness_decision 분포 추적 (strategy 없는 bypass payload는 건너뜀)
        if strategy:
            try:
                _fd_today = datetime.now(_KST).strftime("%Y-%m-%d")
                await rdb.hincrby(f"status:freshness_decision:{_fd_today}:{strategy}", _freshness_dec, 1)
                await rdb.expire(f"status:freshness_decision:{_fd_today}:{strategy}", _PIPELINE_TTL_SEC)
            except Exception:
                pass
        _missing_flags = _collect_missing_feature_flags(signal, ctx)
        _dq = _compute_data_quality(_missing_flags, _freshness_dec, signal)

        # ── Shadow features (Phase 3 관측 — gate 판단에 미사용) ─────────────────
        try:
            _shadow = compute_all_shadow_features(signal, ctx)
        except Exception as _sf_err:
            logger.debug("[Worker] shadow_features failed [%s %s]: %s", stk_cd, strategy, _sf_err)
            _shadow = {}

        enriched = {
            **item,
            "rule_score": r_score,
            "ai_score": ai_score_val,
            "action": action,
            "confidence": confidence,
            "ai_reason": display_reason,
            "cancel_reason": cancel_reason,
            "adjusted_target_pct": ai_result.get("adjusted_target_pct"),
            "adjusted_stop_pct": ai_result.get("adjusted_stop_pct"),
            "claude_tp1": ai_result.get("claude_tp1"),
            "claude_tp2": ai_result.get("claude_tp2"),
            "claude_sl": ai_result.get("claude_sl"),
            "tp2_price": None,
            "cancel_type": cancel_type or ai_result.get("cancel_type"),
            "decision_stage": signal.get("decision_stage"),
            "rule_threshold_rescued": signal.get("rule_threshold_rescued"),
            "rule_threshold_rescue_reason": signal.get("rule_threshold_rescue_reason"),
            "hard_gate_bid_ratio_rescued": signal.get("hard_gate_bid_ratio_rescued"),
            "hard_gate_bid_ratio_rescue_reason": signal.get("hard_gate_bid_ratio_rescue_reason"),
            "rescue_entry_policy": signal.get("rescue_entry_policy"),
            "s8_zone_status": signal.get("s8_zone_status"),
            "s8_zone_entry_policy": signal.get("s8_zone_entry_policy"),
            "s8_zone_caution_reason": signal.get("s8_zone_caution_reason"),
            "s8_buy_zone_high_gap_pct": signal.get("s8_buy_zone_high_gap_pct"),
            **quality,
            # 데이터 신선도·품질 필드 (관측·검증용)
            "freshness_decision": _freshness_dec,
            # REST 보강 메타데이터 (관측·디버깅용)
            "market_data_sources": (ctx.get("refresh_meta") or {}).get("market_data_sources", {}),
            "data_refresh_attempted": (ctx.get("refresh_meta") or {}).get("data_refresh_attempted", {}),
            "retry_failures": (ctx.get("refresh_meta") or {}).get("retry_failures", []),
            "freshness_status": _freshness_status_from_decision(_freshness_dec),
            **_dq,
            # Shadow features (관측·EV 검증용 — gate 판단에 미사용)
            "shadow_features": _shadow,
        }
        if ENABLE_MODEL_RELATIVE_POSITION_SIZE:
            try:
                sizing = calculate_entry_size(
                    ai_score=enriched.get("ai_score", 0),
                    rule_score=enriched.get("rule_score", 0),
                    confidence=enriched.get("confidence", "LOW"),
                    candidate_quality=enriched.get("candidate_quality", "C"),
                    quality_score=enriched.get("quality_score", 50),
                    chase_risk_score=enriched.get("chase_risk_score", 50),
                    execution_quality=enriched.get("execution_quality", "B"),
                    rr_ratio=enriched.get("rr_ratio", 1.0),
                    rr_quality_bucket=enriched.get("rr_quality_bucket", "FAIR"),
                    stop_pct=enriched.get("stop_pct", 3.0),
                    atr_pct=enriched.get("atr_pct"),
                    trde_amt=enriched.get("trde_amt"),
                    spread_pct=enriched.get("spread_pct"),
                    strategy_id=enriched.get("strategy_id", strategy),
                    market_regime=enriched.get("market_regime", "neutral"),
                    strategy_count=enriched.get("strategy_count", 1),
                    sector_heat_score=enriched.get("sector_heat_score", 50),
                    freshness_status=enriched.get("freshness_status", "FRESH"),
                    rule_threshold_rescued=bool(enriched.get("rule_threshold_rescued")),
                    hard_gate_bid_ratio_rescued=bool(enriched.get("hard_gate_bid_ratio_rescued")),
                    s8_zone_entry_policy=str(enriched.get("s8_zone_entry_policy") or ""),
                )
                enriched.update(sizing)
            except Exception as _sizing_err:
                logger.warning("[Worker] position_sizing failed [%s %s]: %s", stk_cd, strategy, _sizing_err)

        # chart fallback 사용 시 confidence MEDIUM 이하로 제한
        _attach_rescue_shadow_metadata(enriched)

        if ctx.get("chart_fallback_used") and enriched.get("confidence") == "HIGH":
            enriched["confidence"] = "MEDIUM"
        normalize_signal_prices(enriched)
        # REST fallback만으로 aggressive ENTER 금지 (STRICT_REST_ENTER_GUARD=true 시)
        if (STRICT_REST_ENTER_GUARD
                and enriched.get("action") == "ENTER"
                and enriched.get("market_data_sources")
                and all(v == "rest" for v in enriched["market_data_sources"].values())):
            enriched["confidence"] = "LOW"
            enriched["cancel_reason"] = "REST fallback data only — aggressive entry blocked"
            enriched["cancel_type"] = "STRICT_REST_ENTER_GUARD"
            enriched["action"] = "CANCEL"
        enriched = _apply_claude_postprocess_hard_rules(enriched)
        enriched = _apply_claude_rr_override(enriched, ctx)
        enriched = _apply_session_enter_guard(enriched, ctx)
        action = enriched.get("action", action)
        confidence = enriched.get("confidence", confidence)
        cancel_reason = enriched.get("cancel_reason")
        cancel_type = enriched.get("cancel_type")
        reason = enriched.get("ai_reason", reason)
        display_reason = _resolve_display_reason(action, reason, cancel_reason)
        enriched["ai_reason"] = display_reason
        await push_score_only_queue(rdb, enriched)

        rule_only_payload = None
        if cancel_type in ("AI_UNAVAILABLE", "AI_DAILY_LIMIT") or (
            action != "ENTER" and cancel_type is None and not should_skip_ai(r_score, strategy)
        ):
            rule_only_payload = _build_rule_only_alert_payload(signal, r_score, quality)
            normalize_signal_prices(rule_only_payload)
            await push_score_only_queue(rdb, rule_only_payload)

        if action == "ENTER":
            await _incr_pipeline(rdb, strategy, "publish")

        try:
            decision_key = f"status:decisions_10m:{strategy}:{action}"
            await rdb.incr(decision_key)
            await rdb.expire(decision_key, STATUS_DECISION_TTL_SEC)
        except Exception as status_err:
            logger.debug(
                "[Worker] status decision metric failed [%s %s]: %s",
                strategy,
                action,
                status_err,
            )

        if pg_pool:
            if rule_only_payload is not None and not signal_id:
                # cancel_type=None → AI가 명시적으로 CANCEL → ai_cancel_signal에만 기록
                # cancel_type 있음 → AI 불가/한도 → rule_cancel_signal 유지
                if cancel_type is None:
                    await insert_ai_cancel_signal(
                        pg_pool,
                        signal_id=None,
                        stk_cd=stk_cd,
                        strategy=strategy,
                        ai_score=ai_score_val,
                        confidence=confidence,
                        reason=display_reason,
                        cancel_reason="RULE_ONLY_ALERT",
                        raw_payload=rule_only_payload,
                    )
                else:
                    await insert_rule_cancel_signal(
                        pg_pool,
                        signal_id=None,
                        stk_cd=stk_cd,
                        strategy=strategy,
                        rule_score=r_score,
                        cancel_type=cancel_type,
                        reason=display_reason,
                        raw_payload=rule_only_payload,
                    )
                return True

            db_id = signal_id
            if not db_id:
                db_id = await insert_python_signal(
                    pg_pool,
                    enriched,
                    action=action,
                    confidence=confidence,
                    rule_score=r_score,
                    ai_score=ai_score_val,
                    ai_reason=display_reason,
                    skip_entry=(action == "CANCEL"),
                )

            if db_id:
                _flu_mkt = _normalize_market_type(signal.get("market_type") or ctx.get("market_type", ""))
                _market_flu_rt = (
                    ctx.get("kospi_flu_rt") if _flu_mkt == "001"
                    else ctx.get("kosdaq_flu_rt") if _flu_mkt == "101"
                    else None
                )
                await update_signal_score(
                    pg_pool,
                    db_id,
                    rule_score=r_score,
                    ai_score=ai_score_val,
                    rr_ratio=_fv(enriched.get("rr_ratio")),
                    action=action,
                    confidence=confidence,
                    ai_reason=display_reason,
                    tp_method=enriched.get("tp_method"),
                    sl_method=enriched.get("sl_method"),
                    skip_entry=(action == "CANCEL"),
                    ma5=signal.get("ma5"),
                    ma20=signal.get("ma20"),
                    ma60=signal.get("ma60"),
                    rsi14=signal.get("rsi"),
                    bb_upper=signal.get("bb_upper"),
                    bb_lower=signal.get("bb_lower"),
                    atr=signal.get("atr"),
                    market_flu_rt=_market_flu_rt,
                    news_sentiment=enriched.get("news_sentiment") or signal.get("news_sentiment"),
                    news_ctrl=enriched.get("news_ctrl") or signal.get("news_ctrl"),
                    raw_rr=_fv(enriched.get("raw_rr")),
                    single_tp_rr=_fv(enriched.get("single_tp_rr")),
                    effective_rr=_fv(enriched.get("effective_rr")),
                    min_rr_ratio=_fv(enriched.get("min_rr_ratio")),
                    rr_skip_reason=enriched.get("rr_skip_reason"),
                    stop_max_pct=_fv(enriched.get("stop_max_pct")),
                    tp_policy_version=enriched.get("tp_policy_version"),
                    sl_policy_version=enriched.get("sl_policy_version"),
                    exit_policy_version=enriched.get("exit_policy_version"),
                    allow_overnight=enriched.get("allow_overnight"),
                    allow_reentry=enriched.get("allow_reentry"),
                    time_stop_deadline_at=None,
                    stk_nm=enriched.get("stk_nm") or signal.get("stk_nm"),
                )
                await insert_score_components(
                    pg_pool,
                    db_id,
                    strategy,
                    components,
                    total_score=r_score,
                    threshold=threshold,
                )

                if action == "ENTER":
                    entry_for_shadow = _fv(
                        enriched.get("entry_price") or signal.get("entry_price") or
                        enriched.get("cur_prc") or signal.get("cur_prc")
                    )
                    tp1_for_shadow = _fv(enriched.get("claude_tp1") or enriched.get("tp1_price"))
                    tp2_for_shadow = _fv(enriched.get("claude_tp2") or enriched.get("tp2_price"))
                    sl_for_shadow = _fv(enriched.get("claude_sl") or enriched.get("sl_price"))
                    position_confirmed = await confirm_open_position(
                        pg_pool,
                        db_id,
                        ai_score=ai_score_val,
                        tp1_price=tp1_for_shadow,
                        tp2_price=tp2_for_shadow,
                        sl_price=sl_for_shadow,
                        rr_ratio=_fv(enriched.get("rr_ratio")),
                        trailing_pct=_fv(enriched.get("trailing_pct")),
                        trailing_activation=_fv(enriched.get("trailing_activation")),
                        trailing_basis=enriched.get("trailing_basis"),
                        strategy_version=enriched.get("strategy_version"),
                        time_stop_type=enriched.get("time_stop_type"),
                        time_stop_minutes=enriched.get("time_stop_minutes"),
                        time_stop_session=enriched.get("time_stop_session"),
                        raw_rr=_fv(enriched.get("raw_rr")),
                        single_tp_rr=_fv(enriched.get("single_tp_rr")),
                        effective_rr=_fv(enriched.get("effective_rr")),
                        min_rr_ratio=_fv(enriched.get("min_rr_ratio")),
                        rr_skip_reason=enriched.get("rr_skip_reason"),
                        stop_max_pct=_fv(enriched.get("stop_max_pct")),
                        tp_policy_version=enriched.get("tp_policy_version"),
                        sl_policy_version=enriched.get("sl_policy_version"),
                        exit_policy_version=enriched.get("exit_policy_version"),
                        allow_overnight=enriched.get("allow_overnight"),
                        allow_reentry=enriched.get("allow_reentry"),
                    )
                    if position_confirmed:
                        await create_shadow_trade(
                            pg_pool,
                            signal_id=db_id,
                            payload=enriched,
                            entry_price=entry_for_shadow,
                            tp1_price=tp1_for_shadow,
                            tp2_price=tp2_for_shadow,
                            sl_price=sl_for_shadow,
                            data_quality="OK",
                        )
                    else:
                        logger.warning("[Queue] shadow trade skipped because position confirm failed signal_id=%s", db_id)
                else:
                    if cancel_type:
                        await insert_rule_cancel_signal(
                            pg_pool,
                            signal_id=db_id,
                            stk_cd=stk_cd,
                            strategy=strategy,
                            rule_score=r_score,
                            cancel_type=cancel_type,
                            reason=display_reason,
                            raw_payload=enriched,
                        )
                    elif action == "CANCEL":
                        await insert_ai_cancel_signal(
                            pg_pool,
                            signal_id=db_id,
                            stk_cd=stk_cd,
                            strategy=strategy,
                            ai_score=ai_score_val,
                            confidence=confidence,
                            reason=reason,
                            cancel_reason=cancel_reason,
                            raw_payload=enriched,
                        )

                    entry_for_shadow = _fv(enriched.get("entry_price") or enriched.get("cur_prc"))
                    tp1_for_shadow = _fv(enriched.get("claude_tp1") or enriched.get("tp1_price"))
                    tp2_for_shadow = _fv(enriched.get("claude_tp2") or enriched.get("tp2_price"), None)
                    sl_for_shadow = _fv(enriched.get("claude_sl") or enriched.get("sl_price"))
                    await create_shadow_trade(
                        pg_pool,
                        signal_id=db_id,
                        payload=enriched,
                        entry_price=entry_for_shadow,
                        tp1_price=tp1_for_shadow,
                        tp2_price=tp2_for_shadow,
                        sl_price=sl_for_shadow,
                        data_quality="CANCEL_SHADOW",
                        data_quality_detail={
                            "cancel_type": cancel_type,
                            "cancel_reason": cancel_reason,
                            "decision_stage": enriched.get("decision_stage"),
                            "rule_threshold_rescued": bool(enriched.get("rule_threshold_rescued")),
                            "hard_gate_bid_ratio_rescued": bool(enriched.get("hard_gate_bid_ratio_rescued")),
                            "s8_zone_entry_policy": enriched.get("s8_zone_entry_policy"),
                            "entry_size_tier": enriched.get("entry_size_tier"),
                            "entry_size_weight": enriched.get("entry_size_weight"),
                            "position_scale": enriched.get("position_scale"),
                            "rr_ratio": _fv(enriched.get("rr_ratio"), None),
                            "effective_rr": _fv(enriched.get("effective_rr"), None),
                        },
                    )
                    await cancel_open_position_by_signal(pg_pool, db_id)

    except Exception as err:
        logger.error("[Worker] processing failed [%s %s]: %s", stk_cd, strategy, err)
        await _incr_pipeline(rdb, strategy, "processing_error")
        failure_payload = _build_failure_payload(item, strategy, stk_cd, err)
        normalize_signal_prices(failure_payload)

        try:
            dead_payload = json.dumps(failure_payload, ensure_ascii=False, default=str)
            await rdb.lpush("error_queue", dead_payload)
            await rdb.expire("error_queue", 86400)
        except Exception as dlq_err:
            logger.error("[Worker] error_queue publish failed: %s", dlq_err)

        try:
            await push_score_only_queue(rdb, failure_payload)
        except Exception as push_err:
            logger.error(
                "[Worker] failure payload publish failed [%s %s]: %s",
                stk_cd,
                strategy,
                push_err,
            )

    return True


async def run_worker(rdb, pg_pool=None):
    logger.info("[Worker] queue worker started (poll_interval=%.1fs)", POLL_INTERVAL)
    consecutive_empty = 0

    while True:
        try:
            processed = await process_one(rdb, pg_pool)
            if processed:
                consecutive_empty = 0
            else:
                consecutive_empty += 1
                wait = min(POLL_INTERVAL * (1 + consecutive_empty * 0.1), 10.0)
                await asyncio.sleep(wait)
        except Exception as err:
            logger.error("[Worker] loop error: %s", err)
            await asyncio.sleep(5)
