from __future__ import annotations

"""
queue_worker.py

Consumes `telegram_queue`, enriches candidate signals with rule-based scoring and
optional AI analysis, then publishes results to `ai_scored_queue`.
"""

import asyncio
import logging
import math
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
from family_scoring import compute_family_shadow_score
from price_utils import normalize_signal_prices
from strategy_meta import (
    detect_market_regime as _detect_market_regime,
    get_persona,
    get_regime_rr_multiplier,
    get_strategy_base_rr_gate,
    get_strategy_rr_group,
    normalize_market_type as _normalize_market_type,
    regime_from_flu_rt as _regime_from_flu_rt,
    SWING_STRATEGIES as _SWING_STRATEGIES,
)
from strategy_catalog import ALL_SETUP_IDS, family_lineage, family_lineage_enabled
from redis_reader import (
    get_avg_cntr_strength,
    get_hoga_data,
    get_market_freshness,
    get_market_index_exp_flu_rt,
    get_market_index_flu_rt,
    get_market_investor_flow,
    get_market_investor_flow_series,
    get_runtime_flag,
    get_sector_overheat_count,
    get_stock_market_cap,
    get_tick_data,
    get_vi_status,
    summarize_market_flow_trend,
    pop_telegram_queue,
    push_hold_monitor_queue,
    push_score_only_queue,
)
from repositories import shadow_trade_repository, signal_repository
from toss_client import fetch_stock_risk_context
from scorer import check_daily_limit, get_claude_threshold, rule_score, should_skip_ai
from score_utils import normalize_score_0_100
from scoring_pipeline.execution_decision import (
    apply_execution_decision as _ed_apply_execution_decision,
    apply_session_enter_guard as _ed_apply_session_enter_guard,
    canonicalize_execution_payload as _ed_canonicalize_execution_payload,
    current_market_session as _ed_current_market_session,
    execution_decision_from_action as _ed_execution_decision_from_action,
    is_session_enter_guard_exempt as _ed_is_session_enter_guard_exempt,
    normalize_session_value as _ed_normalize_session_value,
    resolve_signal_session as _ed_resolve_signal_session,
)
from scoring_pipeline.data_quality import (
    compute_data_quality as _dq_compute_data_quality,
    compute_freshness_decision as _dq_compute_freshness_decision,
    freshness_status_from_decision as _dq_freshness_status_from_decision,
)
from scoring_pipeline.risk_decision import (
    keep_hold_as_watch as _risk_keep_hold_as_watch,
    rr_quality_bucket as _risk_rr_quality_bucket,
)
from scoring_pipeline.status_decision import select_pre_ai_decision
from scoring_pipeline.ai_decision import evaluate_ai_decision
from scoring_pipeline.publisher import route_execution_payload
from scoring_pipeline.status_metrics import (
    build_market_data_observability,
    record_execution_decision_metric,
    record_freshness_decision_metric,
    record_market_data_observability_metric,
)
from scoring_pipeline.failure_handler import (
    build_failure_payload,
    handle_processing_failure,
)
from scoring_pipeline.persistence_handler import persist_processed_signal
from shadow_features import compute_all_shadow_features, compute_live_feature_adjustment
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
STOCK_ARBITRATION_TTL_SEC = int(os.getenv("STOCK_ARBITRATION_TTL_SEC", "1800"))
QUEUE_SIGNAL_MAX_AGE_SEC = float(os.getenv("QUEUE_SIGNAL_MAX_AGE_SEC", "30"))
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

# bull: execution gate 임계값을 12% 완화, bear/sideways/neutral은 기본 gate 유지
_REGIME_GATE_FACTOR = {"bull": 0.88, "sideways": 1.0, "bear": 1.0, "neutral": 1.0}
# bear 장세에서 반등 전략은 일부 momentum gate 면제
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
_PROGRAM_DROP_GATE_STRATEGIES = {"S5_PROG_FRGN", "S13_BOX_BREAKOUT", "S16_ACCUMULATION_SHADOW"}

# freshness 취소 게이트: tick/hoga cancel → CANCEL 판정하는 전략 집합 (문서 4.1)
# _freshness_cancel_reason() 과 _compute_freshness_decision() 이 공유한다.
_STRICT_CANCEL_GATE = {
    "S1_GAP_OPEN", "S2_VI_PULLBACK", "S4_BIG_CANDLE",
    "S10_NEW_HIGH", "S12_CLOSING", "S13_BOX_BREAKOUT",
}
_VI_STALE_CANCEL_STRATEGIES = {"S2_VI_PULLBACK"}

# chart 보강 전략 분류 (P2 — ENABLE_CHART_RETRY=true 시에만 사용)
_CHART_DAILY_STRATEGIES = {
    "S8_GOLDEN_CROSS", "S9_PULLBACK_SWING", "S13_BOX_BREAKOUT",
    "S14_OVERSOLD_BOUNCE", "S15_MOMENTUM_ALIGN",
}
_CHART_MINUTE_STRATEGIES = {"S4_BIG_CANDLE", "S12_CLOSING"}

_S12_START_MINUTE = 14 * 60 + 30
_S12_END_MINUTE = 15 * 60 + 10
RR_HARD_CANCEL_THRESHOLD = float(os.getenv("RR_HARD_CANCEL_THRESHOLD", "0.8"))
RR_CAUTION_THRESHOLD = float(os.getenv("RR_CAUTION_THRESHOLD", "1.2"))
RULE_THRESHOLD_WATCH_MIN_QUALITY = float(os.getenv("RULE_THRESHOLD_WATCH_MIN_QUALITY", "45.0"))
S8_SUPPORT_ZONE_CAUTION_GAP_PCT = float(os.getenv("S8_SUPPORT_ZONE_CAUTION_GAP_PCT", "1.5"))
S8_SUPPORT_ZONE_HARD_CANCEL_GAP_PCT = float(os.getenv("S8_SUPPORT_ZONE_HARD_CANCEL_GAP_PCT", "3.5"))
S8_MIN_ZONE_RR = float(os.getenv("S8_MIN_ZONE_RR", "1.5"))
S1_FALLBACK_MIN_STRENGTH = float(os.getenv("S1_FALLBACK_MIN_STRENGTH", "130.0"))
S1_FALLBACK_MIN_BID_RATIO = float(os.getenv("S1_FALLBACK_MIN_BID_RATIO", "0.8"))
# Not currently read by the HOLD decision path — keep_hold_as_watch() always keeps
# Claude HOLD as HOLD/WATCH regardless of ai_score. Kept for potential future gating.
HOLD_TO_ENTER_MIN_AI_SCORE = float(os.getenv("HOLD_TO_ENTER_MIN_AI_SCORE", "80.0"))
SESSION_ENTER_GUARD_ENABLED = os.getenv("SESSION_ENTER_GUARD_ENABLED", "false").lower() == "true"
ENABLE_SCORING_DATA_RETRY = os.getenv("ENABLE_SCORING_DATA_RETRY", "true").lower() == "true"
ENABLE_TICK_REST_FALLBACK = os.getenv("ENABLE_TICK_REST_FALLBACK", "false").lower() == "true"
STRICT_REST_ENTER_GUARD = os.getenv("STRICT_REST_ENTER_GUARD", "false").lower() == "true"
ENABLE_STRATEGY_FAMILY_SHADOW_SCORING = (
    os.getenv("ENABLE_STRATEGY_FAMILY_SHADOW_SCORING", "false").lower() == "true"
)
# REST 단독 데이터로 ENTER를 허용할 최대 나이(ms). tick의 cancel 컷오프(5000ms)보다
# 보수적으로 잡아 tick caution 컷오프(3000ms)에 맞춘다.
REST_ENTER_MAX_AGE_MS = int(os.getenv("REST_ENTER_MAX_AGE_MS", "3000"))
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
    "S16_ACCUMULATION_SHADOW": {"main_market"},
}
_SESSION_ENTER_EXEMPT_TYPES = {
    "DAILY_REPORT",
    "FORCE_CLOSE",
    "MIDDAY_REPORT",
    "OVERNIGHT_HOLD",
    "OVERNIGHT_RISK_ALERT",
    "STATUS_REPORT",
}


async def insert_python_signal(*args, **kwargs):
    return await signal_repository.insert_python_signal(*args, **kwargs)


async def update_signal_score(*args, **kwargs):
    return await signal_repository.update_signal_score(*args, **kwargs)


async def insert_score_components(*args, **kwargs):
    return await signal_repository.insert_score_components(*args, **kwargs)


async def confirm_open_position(*args, **kwargs):
    return await signal_repository.confirm_open_position(*args, **kwargs)


async def create_shadow_trade(*args, **kwargs):
    return await shadow_trade_repository.create_shadow_trade(*args, **kwargs)


async def insert_rule_cancel_signal(*args, **kwargs):
    return await signal_repository.insert_rule_cancel_signal(*args, **kwargs)


async def insert_ai_cancel_signal(*args, **kwargs):
    return await signal_repository.insert_ai_cancel_signal(*args, **kwargs)


async def insert_signal_freshness_log(*args, **kwargs):
    return await signal_repository.insert_signal_freshness_log(*args, **kwargs)


async def cancel_open_position_by_signal(*args, **kwargs):
    return await signal_repository.cancel_open_position_by_signal(*args, **kwargs)


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


def _execution_decision_from_action(action: str, *, cancel_type: str | None = None) -> str:
    return _ed_execution_decision_from_action(action, cancel_type=cancel_type)


def _apply_execution_decision(payload: dict, decision: str, *, reason: str | None = None) -> dict:
    return _ed_apply_execution_decision(payload, decision, reason=reason)


def _canonicalize_execution_payload(payload: dict) -> dict:
    return _ed_canonicalize_execution_payload(payload)


def _size_policy_from_legacy(signal: dict) -> str:
    mode = str(signal.get("signal_mode") or signal.get("entry_policy") or "").upper()
    if mode == "AUTO_SMALL":
        return "SIZE_DOWN"
    return str(signal.get("size_policy") or "NORMAL").upper()


def _current_market_session(now: datetime | None = None) -> str:
    return _ed_current_market_session(current_session_func=current_session, now=now)


def _normalize_session_value(value) -> str:
    return _ed_normalize_session_value(value)


def _resolve_signal_session(payload: dict, ctx: dict | None = None) -> str:
    return _ed_resolve_signal_session(payload, ctx, current_session_func=current_session)


def _is_session_enter_guard_exempt(payload: dict) -> bool:
    return _ed_is_session_enter_guard_exempt(payload, _SESSION_ENTER_EXEMPT_TYPES)


#: STRICT_REST_ENTER_GUARD가 나이를 검사하는 실시간 데이터 종류.
#: chart_daily/chart_minute은 freshness 사전에 없고 봉 단위 의미라 제외한다.
_REST_GUARD_REALTIME_KINDS = ("tick", "hoga", "strength")


def _is_rest_only_sources(sources: dict | None) -> bool:
    """모든 시장 데이터 출처가 REST인지 여부."""
    if not sources:
        return False
    return all(v == "rest" for v in sources.values())


def _rest_only_enter_stale_reason(payload: dict, ctx: dict | None) -> str | None:
    """REST 단독 ENTER를 차단해야 하면 사유 문자열, 허용 가능하면 None.

    기존 가드는 출처가 REST라는 이유만으로 무조건 CANCEL했다. 그런데 REST는
    요청 시점에 즉시 받아오므로 실측 age가 0.1초 수준으로, 3초 컷오프에 걸린
    WS 데이터보다 오히려 신선한 경우가 많다(2026-08-10 실측: REST 평균 0.1s,
    WS 평균 0.9s). 그 결과 정상적인 진입 신호가 출처만으로 차단됐다
    (7월 이후 이 사유로 80건 취소).

    이제 출처가 아니라 **나이**로 판단한다. REST 단독이어도 모든 실시간 항목이
    REST_ENTER_MAX_AGE_MS 이내면 통과시키고, 나이를 확인할 수 없거나 기준을
    넘으면 종전대로 차단한다. signal_fallback(큐 페이로드 재사용)은 애초에
    'rest'가 아니므로 이 완화 경로를 타지 않는다.
    """
    sources = payload.get("market_data_sources")
    if not _is_rest_only_sources(sources):
        return None

    freshness = (ctx or {}).get("freshness") or {}
    stale: list[str] = []
    verified = 0

    for kind in _REST_GUARD_REALTIME_KINDS:
        if kind not in sources:
            continue
        age_ms = (freshness.get(kind) or {}).get("age_ms")
        if age_ms is None:
            stale.append(f"{kind}:age_unknown")
            continue
        verified += 1
        if float(age_ms) > REST_ENTER_MAX_AGE_MS:
            stale.append(f"{kind}:{int(float(age_ms))}ms>{REST_ENTER_MAX_AGE_MS}ms")

    if stale:
        return ", ".join(stale)
    if verified == 0:
        # REST 단독인데 나이를 하나도 검증하지 못했다 → 보수적으로 차단 유지.
        return "no_verifiable_realtime_age"
    return None


def _apply_session_enter_guard(payload: dict, ctx: dict | None = None, *, enabled: bool | None = None) -> dict:
    return _ed_apply_session_enter_guard(
        payload,
        ctx,
        enabled=SESSION_ENTER_GUARD_ENABLED if enabled is None else enabled,
        enter_sessions=_STRATEGY_ENTER_SESSIONS,
        blocklist=_SESSION_ENTER_BLOCKLIST,
        exempt_types=_SESSION_ENTER_EXEMPT_TYPES,
        current_session_func=current_session,
        null_claude_prices=_null_claude_prices,
    )


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
    return build_failure_payload(
        item,
        strategy=strategy,
        stk_cd=stk_cd,
        error=error,
        failure_type=FAILURE_TYPE,
        failure_action=FAILURE_ACTION,
        now_fn=time.time,
    )


_SIGNAL_TIME_FIELDS = (
    "enqueued_at",
    "queue_enqueued_at",
    "hold_monitor_enqueued_at",
    "signal_time",
    "created_at",
    "timestamp",
    "ts",
)


def _parse_signal_timestamp(value) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 100_000_000_000:
            timestamp /= 1000.0
        return timestamp if math.isfinite(timestamp) and timestamp > 0 else None
    text = str(value).strip()
    try:
        timestamp = float(text)
        if timestamp > 100_000_000_000:
            timestamp /= 1000.0
        return timestamp if math.isfinite(timestamp) and timestamp > 0 else None
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=_KST)
            return parsed.timestamp()
        except (TypeError, ValueError, OverflowError):
            return None


def _signal_age_info(signal: dict, *, now_ts: float | None = None,
                     max_age_sec: float | None = None) -> dict:
    now = time.time() if now_ts is None else float(now_ts)
    max_age = QUEUE_SIGNAL_MAX_AGE_SEC if max_age_sec is None else max(0.0, float(max_age_sec))
    for field in _SIGNAL_TIME_FIELDS:
        timestamp = _parse_signal_timestamp(signal.get(field))
        if timestamp is None:
            continue
        age_sec = max(0.0, now - timestamp)
        return {
            "source": field,
            "timestamp": timestamp,
            "age_sec": age_sec,
            "max_age_sec": max_age,
            "fallback_allowed": age_sec <= max_age,
        }
    return {
        "source": None,
        "timestamp": None,
        "age_sec": None,
        "max_age_sec": max_age,
        "fallback_allowed": False,
    }


def _ensure_signal_age_ctx(ctx: dict, signal: dict) -> dict:
    info = ctx.get("signal_age")
    if not isinstance(info, dict):
        info = _signal_age_info(signal)
        ctx["signal_age"] = info
    ctx["signal_fallback_allowed"] = bool(info.get("fallback_allowed"))
    return info


def _sanitize_unusable_scoring_inputs(ctx: dict, signal: dict) -> None:
    """Keep cancelled market data and expired queue fields out of direct scorers."""
    freshness = ctx.get("freshness") or {}
    fallback_allowed = bool(ctx.get("signal_fallback_allowed"))
    unusable = {"cancel", "missing"}

    if ((freshness.get("tick") or {}).get("state")) in unusable:
        ctx["tick"] = {}
        if not fallback_allowed:
            signal.pop("cur_prc", None)
            signal.pop("flu_rt", None)
    if ((freshness.get("hoga") or {}).get("state")) in unusable:
        ctx["hoga"] = {}
        if not fallback_allowed:
            for field in ("bid_ratio", "buy_req", "sel_req"):
                signal.pop(field, None)
    if ((freshness.get("strength") or {}).get("state")) in unusable:
        ctx["strength"] = 0.0
        if not fallback_allowed:
            signal.pop("cntr_strength", None)
            signal.pop("cntr_str", None)


def _freshness_usable(ctx: dict, kind: str) -> bool:
    state = ((ctx.get("freshness") or {}).get(kind) or {}).get("state", "fresh")
    return state in ("fresh", "caution")


def _resolve_execution_strength(signal: dict, ctx: dict) -> float:
    # Fresh Redis or a successful REST refresh always outranks queue payload fields.
    if _freshness_usable(ctx, "strength"):
        try:
            strength = float(ctx.get("strength", 0) or 0)
            if strength > 0:
                return strength
        except (TypeError, ValueError):
            pass

    tick = ctx.get("tick", {}) or {}
    if _freshness_usable(ctx, "tick"):
        tick_strength = tick.get("cntr_str")
        try:
            if tick_strength is not None and float(str(tick_strength).replace(",", "").replace("+", "")) > 0:
                return float(str(tick_strength).replace(",", "").replace("+", ""))
        except (TypeError, ValueError):
            pass

    if ctx.get("signal_fallback_allowed"):
        signal_strength = signal.get("cntr_strength")
        if signal_strength is None:
            signal_strength = signal.get("cntr_str")
        try:
            if signal_strength is not None and float(signal_strength) > 0:
                return float(signal_strength)
        except (TypeError, ValueError):
            pass
    return 0.0


def _resolve_bid_ratio(signal: dict, ctx: dict) -> float | None:
    hoga = ctx.get("hoga", {}) or {}
    if _freshness_usable(ctx, "hoga"):
        try:
            buy = float(str(hoga.get("total_buy_bid_req", "")).replace(",", "") or 0)
            sell = float(str(hoga.get("total_sel_bid_req", "")).replace(",", "") or 0)
            if sell > 0:
                return round(buy / sell, 3)
        except (TypeError, ValueError):
            pass

    if not ctx.get("signal_fallback_allowed"):
        return None

    value = signal.get("bid_ratio")
    try:
        if value is not None:
            return float(str(value).replace(",", "").replace("+", ""))
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


def _program_flow_gate_failure(signal: dict) -> str | None:
    strategy = signal.get("strategy", "")
    if strategy not in _PROGRAM_DROP_GATE_STRATEGIES:
        return None
    explicit_reason = signal.get("program_drop_reason")
    if explicit_reason:
        return str(explicit_reason)
    net_amt = _fv(signal.get("program_net_buy_amt"), 0.0)
    net_chg = _fv(signal.get("program_net_buy_amt_chg"), 0.0)
    net_qty = _fv(signal.get("program_net_buy_qty"), 0.0)
    qty_chg = _fv(signal.get("program_net_buy_qty_chg"), 0.0)
    if net_chg < 0 and net_amt <= 0:
        return f"program net-buy amount weakening: chg={net_chg:.0f}, net={net_amt:.0f}"
    if qty_chg < 0 and net_qty <= 0:
        return f"program net-buy quantity weakening: chg={qty_chg:.0f}, net={net_qty:.0f}"
    return None


def _s1_fallback_quality_failure(signal: dict, ctx: dict) -> str | None:
    if signal.get("strategy") != "S1_GAP_OPEN":
        return None
    source_status = str(
        signal.get("candidate_source_status")
        or signal.get("s1_candidate_source_status")
        or ""
    ).upper()
    if "FALLBACK" not in source_status:
        return None

    strength = _resolve_execution_strength(signal, ctx)
    bid_ratio = _resolve_bid_ratio(signal, ctx)
    freshness = ctx.get("freshness", {}) or {}
    failures = []
    if strength < S1_FALLBACK_MIN_STRENGTH:
        failures.append(f"strength {strength:.1f} < {S1_FALLBACK_MIN_STRENGTH:.1f}")
    if bid_ratio is None:
        failures.append(f"bid_ratio missing < {S1_FALLBACK_MIN_BID_RATIO:.2f}")
    elif bid_ratio < S1_FALLBACK_MIN_BID_RATIO:
        failures.append(f"bid_ratio {bid_ratio:.2f} < {S1_FALLBACK_MIN_BID_RATIO:.2f}")
    for key in ("tick", "hoga"):
        state = (freshness.get(key) or {}).get("state")
        if state in ("cancel", "missing"):
            failures.append(f"{key} freshness {state}")
    vi_state = (freshness.get("vi") or {}).get("state")
    if ctx.get("vi") and vi_state == "cancel":
        failures.append("vi freshness cancel")

    if not failures:
        signal["s1_fallback_quality_status"] = "pass"
        return None
    signal["s1_fallback_quality_status"] = "failed"
    signal["s1_fallback_entry_policy"] = "skip_fallback_candidate"
    return "S1 fallback quality failed: " + "; ".join(failures)


def _s1_execution_policy_gate(signal: dict) -> tuple[str, str, str] | None:
    if signal.get("strategy") != "S1_GAP_OPEN":
        return None
    policy = str(signal.get("s1_entry_policy") or "ENTER_CANDIDATE").upper()
    reasons = signal.get("s1_entry_policy_reasons") or []
    if isinstance(reasons, str):
        reason_text = reasons
    else:
        reason_text = "; ".join(str(reason) for reason in reasons if reason)
    reason_text = reason_text or policy

    if policy == "CANCEL":
        return ("CANCEL", f"S1 execution policy failed: {reason_text}", "S1_EXECUTION_POLICY")
    if policy == "HOLD_RECHECK":
        return ("HOLD", f"S1 waiting for opening confirmation: {reason_text}", "S1_HOLD_RECHECK")
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
      tick     → REST 우선(활성화 시), 최근 queue signal fallback
      strength → REST direct (stale ws:strength Redis list 재사용 금지)
      hoga     → REST 우선, 최근 queue signal fallback (stale ws:hoga 재사용 금지)

    stale/missing → REST direct 함수 사용. Redis 캐시(ws:hoga, hoga:rest, ws:strength) 재사용 없음.
    ctx["freshness"]와 ctx["refresh_meta"]를 갱신한다.
    """
    signal_age = _ensure_signal_age_ctx(ctx, signal)
    signal_fallback_allowed = bool(signal_age.get("fallback_allowed"))

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

    # tick_state 재확인
    tick_state_now = (freshness.get("tick") or {}).get("state", tick_state)

    str_state  = (freshness.get("strength") or {}).get("state", "fresh")
    hoga_state = (freshness.get("hoga") or {}).get("state", "fresh")

    # tick REST fallback 대상 여부
    _tick_needs_refresh = tick_state_now in ("cancel", "missing")

    if (str_state not in ("cancel", "missing")
            and hoga_state not in ("cancel", "missing")
            and not _tick_needs_refresh):
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

    # ── tick REST refresh (ENABLE_TICK_REST_FALLBACK=true) ──
    if _tick_needs_refresh and ENABLE_TICK_REST_FALLBACK and token:
        try:
            tick_data, tick_meta = await asyncio.wait_for(
                _fetch_tick_snapshot(token, stk_cd), timeout=3.0
            )
            if tick_data.get("cur_prc"):
                refreshed_tick = dict(ctx.get("tick") or {})
                refreshed_tick.update({
                    "cur_prc": float(tick_data["cur_prc"]),
                    "flu_rt": float(tick_data.get("flu_rt") or 0),
                })
                ctx["tick"] = refreshed_tick
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

    # A queue payload is only a bounded-age fallback. Reusing an old payload
    # with a fresh caution marker launders stale data and can pass strict gates.
    tick_state_now = (freshness.get("tick") or {}).get("state", tick_state)
    if tick_state_now in ("cancel", "missing"):
        _cur = float(signal.get("cur_prc") or 0)
        _flu = float(signal.get("flu_rt") or signal.get("gap_pct") or 0)
        if _cur > 0 and signal_fallback_allowed:
            # Preserve cumulative volume/amount from the last websocket tick.
            refreshed_tick = dict(ctx.get("tick") or {})
            refreshed_tick.update({"cur_prc": _cur, "flu_rt": _flu})
            if signal.get("acc_trde_prica") not in (None, ""):
                refreshed_tick["acc_trde_prica"] = signal.get("acc_trde_prica")
            if signal.get("acc_trde_qty") not in (None, ""):
                refreshed_tick["acc_trde_qty"] = signal.get("acc_trde_qty")
            ctx["tick"] = refreshed_tick
            freshness["tick"] = {
                "state": "caution", "kind": "tick",
                "age_ms": signal_age["age_sec"] * 1000.0,
                "source": "signal_fallback",
            }
            _refresh_sources["tick"] = "signal_fallback"
            logger.debug("[Worker] tick_ctx refreshed from recent signal [%s]: prc=%.0f flu=%.2f age=%.3fs",
                         stk_cd, _cur, _flu, signal_age["age_sec"])
        elif _cur > 0:
            _retry_failures.append("tick:signal_stale_or_undated")

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

    # ── hoga: REST direct 우선 — stale ws:hoga 재사용 금지 ──
    if hoga_state in ("cancel", "missing"):
        _refresh_attempted["hoga"] = hoga_state
        if token:
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

        hoga_state_now = (freshness.get("hoga") or {}).get("state", hoga_state)
        sig_bid = signal.get("bid_ratio")
        if hoga_state_now in ("cancel", "missing") and sig_bid is not None:
            if signal_fallback_allowed:
                _b = float(sig_bid)
                ctx["hoga"] = {"total_buy_bid_req": _b, "total_sel_bid_req": 1.0}
                freshness["hoga"] = {
                    "state": "caution", "kind": "hoga",
                    "age_ms": signal_age["age_sec"] * 1000.0,
                    "source": "signal_fallback",
                }
                _refresh_sources["hoga"] = "signal_fallback"
                logger.debug("[Worker] hoga_ctx refreshed from recent signal [%s]: bid=%.2f age=%.3fs",
                             stk_cd, _b, signal_age["age_sec"])
            else:
                _retry_failures.append("hoga:signal_stale_or_undated")

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
    if vi and vi_status.get("state") == "cancel" and strategy in _VI_STALE_CANCEL_STRATEGIES:
        return f"vi data stale: age_ms={vi_status.get('age_ms')}"
    return None


def _freshness_age_diagnostics(ctx: dict) -> dict:
    freshness = ctx.get("freshness", {}) or {}
    result = {}
    stale_sources = []
    for key in ("tick", "hoga", "strength", "vi"):
        status = freshness.get(key, {}) or {}
        state = status.get("state")
        age_ms = status.get("age_ms")
        result[f"{key}_freshness_state"] = state
        result[f"{key}_age_ms"] = age_ms
        if state == "cancel":
            stale_sources.append(key)
    result["stale_sources"] = stale_sources
    result["stale_source"] = stale_sources[0] if stale_sources else None
    return result


def _build_failed_gate_diagnostics(
    *,
    rule_score_value: float,
    threshold: float,
    skip_ai: bool,
    rescue_reason: str | None,
    rr_reason: str | None,
    s8_zone_reason: str | None,
    s1_fallback_reason: str | None,
    hard_gate_reason: str | None,
    program_flow_reason: str | None,
    freshness_reason: str | None,
) -> list[dict]:
    failures = []
    if skip_ai and not rescue_reason:
        failures.append({
            "gate": "RULE_THRESHOLD",
            "reason": f"rule_score {rule_score_value:.1f} < threshold {threshold:.1f}",
            "actual": round(rule_score_value, 2),
            "threshold": round(threshold, 2),
            "score_margin": round(rule_score_value - threshold, 2),
        })
    for gate, reason in (
        ("RR_TOO_LOW", rr_reason),
        ("S8_BUY_ZONE", s8_zone_reason),
        ("S1_FALLBACK_QUALITY", s1_fallback_reason),
        ("HARD_GATE", hard_gate_reason),
        ("PROGRAM_FLOW", program_flow_reason),
        ("FRESHNESS_STALE", freshness_reason),
    ):
        if reason:
            failures.append({"gate": gate, "reason": reason})
    return failures


def _compute_freshness_decision(freshness: dict, strategy: str) -> str:
    return _dq_compute_freshness_decision(
        freshness,
        strategy,
        strict_cancel_gate=_STRICT_CANCEL_GATE,
        vi_stale_cancel_strategies=_VI_STALE_CANCEL_STRATEGIES,
    )
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
    return _dq_freshness_status_from_decision(decision)
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
    return _dq_compute_data_quality(missing_flags, freshness_decision, signal)
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
    base = get_strategy_base_rr_gate(strategy)
    multiplier = get_regime_rr_multiplier(strategy, regime)
    threshold = base * multiplier
    return regime, float(threshold)


def _apply_regime_rr_metadata(payload: dict, regime: str, threshold: float) -> None:
    strategy = str(payload.get("strategy") or "")
    payload["rr_policy"] = "strategy_base_x_regime"
    payload["rr_regime"] = regime
    payload["rr_strategy_group"] = get_strategy_rr_group(strategy)
    payload["rr_strategy_base_gate"] = round(get_strategy_base_rr_gate(strategy), 2)
    payload["rr_regime_multiplier"] = round(get_regime_rr_multiplier(strategy, regime), 3)
    payload["rr_regime_threshold"] = round(float(threshold), 2)
    payload["final_rr_gate"] = round(float(threshold), 2)


def _rr_quality_bucket(rr: float | None) -> str:
    return _risk_rr_quality_bucket(
        rr,
        hard_cancel_threshold=RR_HARD_CANCEL_THRESHOLD,
        caution_threshold=RR_CAUTION_THRESHOLD,
    )


def _maybe_promote_hold_to_enter(
    *,
    strategy: str = "",
    action: str,
    confidence: str,
    reason: str,
    cancel_reason: str | None,
    ai_score: float | None,
) -> tuple[str, str, str, str | None]:
    """Despite the name, this never promotes: delegates to keep_hold_as_watch(),
    which always keeps a Claude HOLD as HOLD/WATCH regardless of ai_score."""
    return _risk_keep_hold_as_watch(
        action=action,
        confidence=confidence,
        reason=reason,
        cancel_reason=cancel_reason,
        ai_score=ai_score,
    )


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


async def _apply_cross_strategy_arbitration(rdb, payload: dict) -> dict:
    """Allow only the first ENTER for a stock during a short cross-strategy window."""
    if payload.get("execution_decision") != "ENTER":
        return payload
    stk_cd = normalize_stock_code(payload.get("stk_cd", ""))
    strategy = str(payload.get("strategy") or "")
    if not stk_cd or not strategy or STOCK_ARBITRATION_TTL_SEC <= 0:
        return payload
    key = f"arbitration:enter:{stk_cd}"
    try:
        existing = await rdb.get(key)
        if existing and str(existing) != strategy:
            blocked = dict(payload)
            blocked["action"] = "CANCEL"
            blocked["execution_decision"] = "BLOCK"
            blocked["confidence"] = "LOW"
            blocked["skip_entry"] = True
            blocked["cancel_type"] = "CROSS_STRATEGY_ARBITRATION"
            blocked["representative_strategy"] = str(existing)
            blocked["supporting_strategies"] = list(dict.fromkeys([
                *(blocked.get("supporting_strategies") or []),
                strategy,
            ]))
            reason = f"Cross-strategy arbitration: {stk_cd} already represented by {existing}"
            blocked["cancel_reason"] = reason
            blocked["ai_reason"] = reason
            return blocked
        if not existing:
            await rdb.set(key, strategy, ex=STOCK_ARBITRATION_TTL_SEC, nx=True)
    except Exception as arb_err:
        logger.debug("[Worker] cross-strategy arbitration skipped [%s %s]: %s", stk_cd, strategy, arb_err)
    return payload


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


#: 종목별 토스 리스크(공매도/신용/대차/매수유의사항) 조회 대상 — 스윙 전략 전체
#: (2026-08-11, 사용자 지시: "스윙 포지션에는 꼭 붙여"). 데이트레이딩 전략(S1/S2/S4/S6)은
#: 당일 청산이라 T+1 반영되는 신용/대차 데이터와의 관련성이 낮아 제외한다.
#: strategy_meta.SWING_STRATEGIES를 그대로 참조해 스윙 전략 목록의 단일 소스를 유지한다.
_TOSS_RISK_STRATEGIES = _SWING_STRATEGIES


async def _build_market_ctx(rdb, stk_cd: str, *, sector: str = "", signal: dict | None = None) -> dict:
    strategy = str((signal or {}).get("strategy") or "")
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
        get_market_investor_flow(rdb),
    ]
    is_swing = strategy in _TOSS_RISK_STRATEGIES
    if is_swing:
        tasks.append(fetch_stock_risk_context(rdb, stk_cd))
    results = await asyncio.gather(*tasks)
    tick, hoga, strength, vi, freshness, sector_count, index_flu, market_cap, exp_flu, investor_flow = results[:10]
    toss_risk = results[10] if len(results) > 10 else {}

    investor_flow_trend: dict = {}
    if is_swing:
        # 스윙 포지션은 하루 이상 보유하므로 종목 개별 리스크(toss_risk)뿐 아니라
        # 시장 전체 수급이 최근 30분간 가속/둔화하는지도 함께 본다 — 지수 분단위
        # 시계열(TossMarketScheduler가 1분마다 ZADD)에서 계산하는 순수 함수라
        # 추가 외부 API 호출 없이 Redis 조회만 발생한다.
        kospi_series, kosdaq_series = await asyncio.gather(
            get_market_investor_flow_series(rdb, "kospi", minutes=30),
            get_market_investor_flow_series(rdb, "kosdaq", minutes=30),
        )
        trend = {
            "kospi": summarize_market_flow_trend(kospi_series),
            "kosdaq": summarize_market_flow_trend(kosdaq_series),
        }
        investor_flow_trend = {k: v for k, v in trend.items() if v}

    market_type = await _resolve_signal_market_type(rdb, stk_cd, strategy, signal)
    ctx = {
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
        "investor_flow": investor_flow,
    }
    if toss_risk:
        ctx["toss_risk"] = toss_risk
    if investor_flow_trend:
        ctx["investor_flow_trend"] = investor_flow_trend
    return ctx


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
    if (
        str(os.getenv("LIVE_ONLY_MODE", "true")).strip().lower() == "true"
        and str(item.get("signal_mode", "")).upper() == "SHADOW"
    ):
        await _incr_pipeline(rdb, strategy, "non_live_rejected")
        logger.warning("[Worker] live-only policy rejected non-live candidate [%s %s]", strategy, stk_cd)
        return True

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
        _ensure_signal_age_ctx(ctx, signal)
        if ctx.get("market_type") and not signal.get("market_type"):
            signal["market_type"] = ctx["market_type"]
        # stale/missing 항목을 signal 값 또는 REST로 갱신 (cancel보다 재조회 우선)
        await _refresh_stale_ctx(ctx, stk_cd, rdb, signal, strategy)
        _sanitize_unusable_scoring_inputs(ctx, signal)
        exact_strength = _resolve_execution_strength(signal, ctx)
        ctx["strength"] = exact_strength
        signal["cntr_strength"] = round(exact_strength, 2) if exact_strength > 0 else signal.get("cntr_strength")
        resolved_bid_ratio = _resolve_bid_ratio(signal, ctx)
        if resolved_bid_ratio is not None:
            signal["bid_ratio"] = round(resolved_bid_ratio, 3)
        if signal.get("vol_ratio") is None and signal.get("volume_ratio") is not None:
            signal["vol_ratio"] = signal.get("volume_ratio")
        ctx["ws_online"] = ws_online

        try:
            _computed_shadow = compute_all_shadow_features(signal, ctx)
            _existing_shadow = signal.get("shadow_features")
            _shadow = {
                **(_existing_shadow if isinstance(_existing_shadow, dict) else {}),
                **_computed_shadow,
            }
            _shadow_live = compute_live_feature_adjustment(_shadow)
        except Exception as _sf_err:
            logger.debug("[Worker] live feature calculation failed [%s %s]: %s", stk_cd, strategy, _sf_err)
            _shadow = signal.get("shadow_features") if isinstance(signal.get("shadow_features"), dict) else {}
            _shadow_live = {"score_adjustment": 0.0, "reasons": [], "hard_reject": False, "mode": "LIVE"}
        signal["shadow_features"] = _shadow
        signal["shadow_feature_live"] = _shadow_live

        r_score, components = _coerce_rule_score_result(rule_score(signal, ctx))
        if str(os.getenv("LIVE_FEATURE_ADJUSTMENTS_ENABLED", "true")).strip().lower() == "true":
            r_score = max(0.0, min(100.0, r_score + _shadow_live["score_adjustment"]))
            if isinstance(components, dict):
                components["shadow_feature_live"] = _shadow_live
        signal["rule_score"] = r_score
        logger.info("[Worker] rule score [%s %s]: %.1f", stk_cd, strategy, r_score)
        _hoga_state = (ctx.get("freshness") or {}).get("hoga", {}).get("state", "fresh")
        _stale_hoga = _hoga_state in ("cancel", "missing", "caution")
        quality = _compute_signal_quality(signal, ctx, r_score, stale_hoga=_stale_hoga)
        signal.update(quality)

        threshold = get_claude_threshold(strategy)
        ai_score_val = r_score
        ai_result = {}
        hold_promoted_to_enter = False
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
            rr_prefilter_reason = _rr_prefilter_reason(signal, ctx)
            s8_zone_gate_reason = _s8_buy_zone_gate_failure(dict(signal))
            s1_fallback_quality_reason = _s1_fallback_quality_failure(dict(signal), ctx)
            s1_execution_policy = _s1_execution_policy_gate(dict(signal))
            hard_gate_reason = _hard_gate_failure(dict(signal), ctx)
            if not hard_gate_reason and _shadow_live.get("hard_reject"):
                hard_gate_reason = "shadow_feature_live_reject"
            program_flow_reason = _program_flow_gate_failure(dict(signal))
            stale_reason = _freshness_cancel_reason(ctx, strategy)
        else:
            rr_prefilter_reason = _rr_prefilter_reason(signal, ctx)
            s8_zone_gate_reason = _s8_buy_zone_gate_failure(signal)
            s1_fallback_quality_reason = _s1_fallback_quality_failure(signal, ctx)
            s1_execution_policy = _s1_execution_policy_gate(signal)
            hard_gate_reason = _hard_gate_failure(signal, ctx)
            if not hard_gate_reason and _shadow_live.get("hard_reject"):
                hard_gate_reason = "shadow_feature_live_reject"
            program_flow_reason = _program_flow_gate_failure(signal)
            stale_reason = _freshness_cancel_reason(ctx, strategy)
        failed_gates = _build_failed_gate_diagnostics(
            rule_score_value=r_score,
            threshold=threshold,
            skip_ai=skip_ai,
            rescue_reason=rescue_reason,
            rr_reason=rr_prefilter_reason,
            s8_zone_reason=s8_zone_gate_reason,
            s1_fallback_reason=s1_fallback_quality_reason,
            hard_gate_reason=hard_gate_reason,
            program_flow_reason=program_flow_reason,
            freshness_reason=stale_reason,
        )
        if family_lineage_enabled() and strategy in ALL_SETUP_IDS:
            for key, value in family_lineage(strategy).items():
                signal.setdefault(key, value)
        family_shadow = None
        if ENABLE_STRATEGY_FAMILY_SHADOW_SCORING and strategy in ALL_SETUP_IDS:
            family_shadow = compute_family_shadow_score(
                signal,
                ctx,
                legacy_rule_score=r_score,
                legacy_components=components,
                failed_gates=failed_gates,
            )
            signal.update(family_shadow)
            if isinstance(components, dict):
                components["family_shadow"] = family_shadow
        pre_ai_decision = select_pre_ai_decision(
            skip_ai=skip_ai,
            rescue_reason=rescue_reason,
            rule_score_value=r_score,
            threshold=threshold,
            quality_score=quality.get("signal_quality_score", 0.0),
            watch_min_quality=RULE_THRESHOLD_WATCH_MIN_QUALITY,
            rr_prefilter_reason=rr_prefilter_reason,
            s8_zone_gate_reason=s8_zone_gate_reason,
            s1_fallback_quality_reason=s1_fallback_quality_reason,
            s1_execution_policy=s1_execution_policy,
            hard_gate_reason=hard_gate_reason,
            program_flow_reason=program_flow_reason,
            stale_reason=stale_reason,
            strategy=strategy,
            current_s8_zone_status=signal.get("s8_zone_status"),
        )
        signal.update(pre_ai_decision.get("signal_updates") or {})
        if pre_ai_decision.get("decision_stage"):
            signal["decision_stage"] = pre_ai_decision["decision_stage"]
        for metric in pre_ai_decision.get("metrics", []):
            await _incr_pipeline(rdb, strategy, metric)

        if pre_ai_decision.get("terminal"):
            action = pre_ai_decision["action"]
            confidence = pre_ai_decision["confidence"]
            reason = pre_ai_decision["reason"]
            cancel_reason = pre_ai_decision.get("cancel_reason")
            cancel_type = pre_ai_decision.get("cancel_type")
        else:
            async def _check_signal_ai_budget(db):
                scope = "hold_recheck" if signal.get("hold_monitor_recheck") else "primary"
                return await check_daily_limit(db, scope=scope)

            ai_decision = await evaluate_ai_decision(
                signal=signal,
                ctx=ctx,
                rule_score_value=r_score,
                rdb=rdb,
                check_daily_limit_fn=_check_signal_ai_budget,
                analyze_signal_fn=analyze_signal,
                normalize_score_fn=normalize_score_0_100,
                hold_policy_fn=_maybe_promote_hold_to_enter,
            )
            if ai_decision.get("error"):
                logger.warning(
                    "[Worker] Claude failed [%s %s]: %s, canceling signal",
                    stk_cd,
                    strategy,
                    ai_decision["error"],
                )
            ai_result = ai_decision.get("ai_result") or {}
            ai_score_val = ai_decision["ai_score"]
            action = ai_decision["action"]
            confidence = ai_decision["confidence"]
            reason = ai_decision["reason"]
            cancel_reason = ai_decision.get("cancel_reason")
            cancel_type = ai_decision.get("cancel_type")
            hold_promoted_to_enter = bool(ai_decision.get("hold_promoted_to_enter"))
            for metric in ai_decision.get("metrics", []):
                await _incr_pipeline(rdb, strategy, metric)

        display_reason = _resolve_display_reason(action, reason, cancel_reason)

        # ── 데이터 품질·신선도 메타데이터 계산 (Phase 1 관측 가능성) ────────────
        _freshness_dec = _compute_freshness_decision(ctx.get("freshness") or {}, strategy)
        # 운영 metric: freshness_decision 분포 추적 (strategy 없는 bypass payload는 건너뜀)
        await record_freshness_decision_metric(
            rdb,
            strategy=strategy,
            decision=_freshness_dec,
            ttl_sec=_PIPELINE_TTL_SEC,
            logger=logger,
        )
        _missing_flags = _collect_missing_feature_flags(signal, ctx)
        _dq = _compute_data_quality(_missing_flags, _freshness_dec, signal)
        _freshness_diag = _freshness_age_diagnostics(ctx)
        _market_data_observability = build_market_data_observability(ctx)
        await record_market_data_observability_metric(
            rdb,
            strategy=strategy,
            snapshot=_market_data_observability,
            ttl_sec=_PIPELINE_TTL_SEC,
            logger=logger,
        )

        enriched = {
            **item,
            "signal_age_sec": (ctx.get("signal_age") or {}).get("age_sec"),
            "signal_time_source": (ctx.get("signal_age") or {}).get("source"),
            "signal_fallback_allowed": bool(ctx.get("signal_fallback_allowed")),
            "rule_score": r_score,
            "ai_score": ai_score_val,
            "action": action,
            "execution_decision": _execution_decision_from_action(action, cancel_type=cancel_type),
            "confidence": confidence,
            "ai_reason": display_reason,
            "cancel_reason": cancel_reason,
            "legacy_signal_mode": item.get("signal_mode"),
            "size_policy": _size_policy_from_legacy(item),
            "adjusted_target_pct": ai_result.get("adjusted_target_pct"),
            "adjusted_stop_pct": ai_result.get("adjusted_stop_pct"),
            "claude_tp1": ai_result.get("claude_tp1"),
            "claude_tp2": ai_result.get("claude_tp2"),
            "claude_sl": ai_result.get("claude_sl"),
            "tp2_price": None,
            "cancel_type": cancel_type or ai_result.get("cancel_type"),
            "threshold_used": threshold,
            "score_margin": round(r_score - threshold, 2),
            "failed_gates": failed_gates,
            "family_shadow": family_shadow,
            "decision_stage": signal.get("decision_stage"),
            "rule_threshold_rescued": signal.get("rule_threshold_rescued"),
            "hold_promoted_to_enter": hold_promoted_to_enter,
            "rule_threshold_rescue_reason": signal.get("rule_threshold_rescue_reason"),
            "hard_gate_bid_ratio_rescued": signal.get("hard_gate_bid_ratio_rescued"),
            "hard_gate_bid_ratio_rescue_reason": signal.get("hard_gate_bid_ratio_rescue_reason"),
            "rescue_entry_policy": signal.get("rescue_entry_policy"),
            "s8_zone_status": signal.get("s8_zone_status"),
            "s8_zone_entry_policy": signal.get("s8_zone_entry_policy"),
            "s8_zone_caution_reason": signal.get("s8_zone_caution_reason"),
            "s8_buy_zone_high_gap_pct": signal.get("s8_buy_zone_high_gap_pct"),
            "s1_fallback_quality_status": signal.get("s1_fallback_quality_status"),
            "s1_fallback_entry_policy": signal.get("s1_fallback_entry_policy"),
            **quality,
            # 데이터 신선도·품질 필드 (관측·검증용)
            "freshness_decision": _freshness_dec,
            # REST 보강 메타데이터 (관측·디버깅용)
            "market_data_sources": (ctx.get("refresh_meta") or {}).get("market_data_sources", {}),
            "data_refresh_attempted": (ctx.get("refresh_meta") or {}).get("data_refresh_attempted", {}),
            "retry_failures": (ctx.get("refresh_meta") or {}).get("retry_failures", []),
            "market_data_observability": _market_data_observability,
            "freshness_status": _freshness_status_from_decision(_freshness_dec),
            **_freshness_diag,
            **_dq,
            # Historical shadow feature payload, now promoted into live scoring/gating.
            "shadow_features": _shadow,
            "shadow_feature_live": _shadow_live,
            # 스윙 전략 공매도/신용/대차/매수유의사항 (토스) — 텔레그램 ENTER 메시지에
            # 참고정보로 노출. 데이트레이딩 전략은 ctx에 애초에 존재하지 않아 None.
            "toss_risk": ctx.get("toss_risk"),
            # 지수 분단위 시계열 기반 최근 30분 시장 수급 추세 (토스) — toss_risk와
            # 같은 스윙 전용 게이트를 공유한다.
            "investor_flow_trend": ctx.get("investor_flow_trend"),
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
        # REST fallback ENTER 판정 (STRICT_REST_ENTER_GUARD=true 시)
        if STRICT_REST_ENTER_GUARD and enriched.get("action") == "ENTER":
            _stale_reason = _rest_only_enter_stale_reason(enriched, ctx)
            if _stale_reason is not None:
                enriched["confidence"] = "LOW"
                enriched["cancel_reason"] = (
                    f"REST fallback data stale — aggressive entry blocked ({_stale_reason})"
                )
                enriched["cancel_type"] = "STRICT_REST_ENTER_GUARD"
                enriched["action"] = "CANCEL"
            elif _is_rest_only_sources(enriched.get("market_data_sources")):
                # REST 단독이지만 나이가 충분히 신선하다 → 진입은 허용하되
                # 실시간 스트림이 없다는 사실은 confidence로 남긴다.
                if enriched.get("confidence") == "HIGH":
                    enriched["confidence"] = "MEDIUM"
                enriched["rest_only_entry"] = True
        enriched = _apply_claude_postprocess_hard_rules(enriched)
        enriched = _apply_claude_rr_override(enriched, ctx)
        session_guard_enabled = await get_runtime_flag(rdb, "session_enter_guard", SESSION_ENTER_GUARD_ENABLED)
        enriched = _apply_session_enter_guard(enriched, ctx, enabled=session_guard_enabled)
        enriched = _canonicalize_execution_payload(enriched)
        enriched = await _apply_cross_strategy_arbitration(rdb, enriched)
        enriched = _canonicalize_execution_payload(enriched)
        action = enriched.get("action", action)
        execution_decision = enriched.get("execution_decision", _execution_decision_from_action(action, cancel_type=cancel_type))
        confidence = enriched.get("confidence", confidence)
        cancel_reason = enriched.get("cancel_reason")
        cancel_type = enriched.get("cancel_type")
        reason = enriched.get("ai_reason", reason)
        display_reason = _resolve_display_reason(action, reason, cancel_reason)
        enriched["ai_reason"] = display_reason
        await route_execution_payload(
            rdb=rdb,
            payload=enriched,
            strategy=strategy,
            stk_cd=stk_cd,
            execution_decision=execution_decision,
            display_reason=display_reason,
            push_hold_monitor_queue_fn=push_hold_monitor_queue,
            push_score_only_queue_fn=push_score_only_queue,
            incr_pipeline_fn=_incr_pipeline,
            logger=logger,
        )

        rule_only_payload = None
        if execution_decision == "ENTER":
            await _incr_pipeline(rdb, strategy, "publish")

        await record_execution_decision_metric(
            rdb,
            strategy=strategy,
            decision=execution_decision,
            ttl_sec=STATUS_DECISION_TTL_SEC,
            logger=logger,
        )

        if pg_pool:
            persistence_terminal = await persist_processed_signal(
                pg_pool=pg_pool,
                signal_id=signal_id,
                signal=signal,
                enriched=enriched,
                ctx=ctx,
                strategy=strategy,
                stk_cd=stk_cd,
                action=action,
                confidence=confidence,
                reason=reason,
                display_reason=display_reason,
                cancel_reason=cancel_reason,
                cancel_type=cancel_type,
                r_score=r_score,
                ai_score_val=ai_score_val,
                threshold=threshold,
                components=components,
                rule_only_payload=rule_only_payload,
                insert_python_signal_fn=insert_python_signal,
                update_signal_score_fn=update_signal_score,
                insert_score_components_fn=insert_score_components,
                confirm_open_position_fn=confirm_open_position,
                create_shadow_trade_fn=create_shadow_trade,
                shadow_persistence_enabled=(
                    str(os.getenv("LIVE_ONLY_MODE", "true")).strip().lower() != "true"
                ),
                insert_rule_cancel_signal_fn=insert_rule_cancel_signal,
                insert_ai_cancel_signal_fn=insert_ai_cancel_signal,
                insert_signal_freshness_log_fn=insert_signal_freshness_log,
                cancel_open_position_by_signal_fn=cancel_open_position_by_signal,
                normalize_market_type_fn=_normalize_market_type,
                fv_fn=_fv,
                logger=logger,
            )
            if persistence_terminal:
                return True
    except Exception as err:
        logger.error("[Worker] processing failed [%s %s]: %s", stk_cd, strategy, err)
        await _incr_pipeline(rdb, strategy, "processing_error")
        await handle_processing_failure(
            rdb=rdb,
            item=item,
            strategy=strategy,
            stk_cd=stk_cd,
            error=err,
            normalize_signal_prices_fn=normalize_signal_prices,
            push_score_only_queue_fn=push_score_only_queue,
            logger=logger,
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
