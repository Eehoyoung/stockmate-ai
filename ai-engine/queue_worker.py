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
from db_writer import (
    cancel_open_position_by_signal,
    confirm_open_position,
    insert_ai_cancel_signal,
    insert_python_signal,
    insert_rule_cancel_signal,
    insert_score_components,
    update_signal_score,
)
from http_utils import fetch_stk_nm
from price_utils import normalize_signal_prices
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
from tp_sl_engine import compute_rr
from utils import normalize_stock_code, safe_float as _fv

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
    "S4_BIG_CANDLE":      {"strength": 125.0, "bid_ratio": 1.4},
    "S6_THEME_LAGGARD":   {"strength": 120.0, "bid_ratio": 1.2},
    "S10_NEW_HIGH":       {"strength": 115.0, "bid_ratio": 1.2},
    "S12_CLOSING":        {"strength": 120.0, "bid_ratio": 1.5},
    "S13_BOX_BREAKOUT":   {"strength": 115.0, "bid_ratio": 1.3},
    "S15_MOMENTUM_ALIGN": {"strength": 120.0, "bid_ratio": 1.3},
}

# bull: 임계값을 12% 완화, bear: 역방향 전략(S9/S14)은 gates 적용 안 함
_REGIME_GATE_FACTOR = {"bull": 0.88, "sideways": 1.0, "bear": 1.0, "neutral": 1.0}
# bear 장세에서 반등 전략은 weak momentum이 당연하므로 gate 면제
_BEAR_GATE_EXEMPT = {"S9_PULLBACK_SWING", "S14_OVERSOLD_BOUNCE", "S11_FRGN_CONT"}

# ── R:R 사전필터 장세별 임계값 ─────────────────────────────────────────────
# bull: 모멘텀이 슬리피지를 상쇄 → 0.65, bear: 리스크 엄격 → 0.80
_RR_BY_REGIME = {"bull": 0.65, "sideways": 0.75, "bear": 0.80, "neutral": 0.80}

_S12_START_MINUTE = 14 * 60 + 30
_S12_END_MINUTE = 15 * 60 + 10
RR_HARD_CANCEL_THRESHOLD = float(os.getenv("RR_HARD_CANCEL_THRESHOLD", "0.8"))
RR_CAUTION_THRESHOLD = float(os.getenv("RR_CAUTION_THRESHOLD", "1.2"))
HOLD_TO_ENTER_MIN_AI_SCORE = float(os.getenv("HOLD_TO_ENTER_MIN_AI_SCORE", "80.0"))
S1_CLAUDE_MIN_EFFECTIVE_RR = 1.8
CLAUDE_HARD_RULE_CANCEL_TYPE = "CLAUDE_HARD_RULE"
_CLAUDE_PRICE_FIELDS = ("claude_tp1", "claude_tp2", "claude_sl")


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

    return score_val, components


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
    return None


def _detect_market_regime(ctx: dict, strategy: str = "") -> str:
    """KOSPI/KOSDAQ 지수 등락률 평균으로 장세 판단.
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
    vals = [v for v in (kospi, kosdaq) if v is not None]
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
    if bid_ratio is None:
        failures.append(f"bid_ratio missing < {req_bid:.2f}({regime})")
    elif bid_ratio < req_bid:
        failures.append(f"bid_ratio {bid_ratio:.2f} < {req_bid:.2f}({regime})")
    if failures:
        return "; ".join(failures)
    return None


def _freshness_cancel_reason(ctx: dict) -> str | None:
    freshness = ctx.get("freshness", {}) or {}
    for key in ("tick", "hoga", "strength"):
        status = freshness.get(key, {}) or {}
        if status.get("state") == "cancel":
            return f"{key} data stale: age_ms={status.get('age_ms')}"
    vi = ctx.get("vi", {}) or {}
    vi_status = freshness.get("vi", {}) or {}
    if vi and vi_status.get("state") == "cancel":
        return f"vi data stale: age_ms={vi_status.get('age_ms')}"
    return None


def _rr_prefilter_reason(signal: dict, ctx: dict | None = None) -> str | None:
    rr = _fv(signal.get("rr_ratio"), None)
    if rr is None:
        return None
    strategy = signal.get("strategy", "")
    regime = _detect_market_regime(ctx, strategy) if ctx else "neutral"
    # 하락장 반등 전략은 bear 장세가 오히려 진입 근거 → bull 임계값으로 완화
    if regime == "bear" and strategy in _BEAR_GATE_EXEMPT:
        threshold = _RR_BY_REGIME["bull"]
    else:
        threshold = _RR_BY_REGIME.get(regime, RR_HARD_CANCEL_THRESHOLD)
    if rr < threshold:
        return f"R:R {rr:.2f} below {threshold:.2f}({regime})"
    return None


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
    if score < HOLD_TO_ENTER_MIN_AI_SCORE:
        return action, confidence, reason, cancel_reason

    promoted_reason = (
        f"{reason} | HOLD promoted to ENTER because ai_score "
        f"{score:.1f} >= {HOLD_TO_ENTER_MIN_AI_SCORE:.1f}"
    )
    return "ENTER", confidence or "HIGH", promoted_reason, None


def _compute_signal_quality(signal: dict, ctx: dict, rule_score_value: float) -> dict:
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
        if status.get("state") == "warn":
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

    if payload.get("strategy") == "S1_GAP_OPEN":
        rr = _fv(payload.get("effective_rr") or payload.get("rr_ratio"), None)
        if rr is not None and rr < S1_CLAUDE_MIN_EFFECTIVE_RR:
            return _cancel_by_claude_hard_rule(
                payload,
                f"S1 effective R:R {rr:.2f} below {S1_CLAUDE_MIN_EFFECTIVE_RR:.2f}",
            )

    return payload


def _apply_claude_rr_override(payload: dict) -> dict:
    """Recompute displayed/stored RR when Claude changes executable TP/SL."""
    if payload.get("action") != "ENTER":
        return payload

    entry = _fv(payload.get("cur_prc") or payload.get("entry_price"), None)
    claude_tp = _fv(payload.get("claude_tp1"), None)
    claude_sl = _fv(payload.get("claude_sl"), None)
    if entry is None or claude_tp is None or claude_sl is None:
        return payload

    min_rr = _fv(payload.get("min_rr_ratio"), None)
    rr, skip = compute_rr(
        str(payload.get("stk_cd", "")),
        entry,
        claude_tp,
        claude_sl,
        min_rr=min_rr if min_rr is not None else None,
    )
    payload["rr_ratio"] = rr
    payload["effective_rr"] = rr
    payload["single_tp_rr"] = _raw_rr(entry, claude_tp, claude_sl)
    payload["raw_rr"] = payload["single_tp_rr"]
    payload["rr_basis"] = "claude_tp_sl"
    payload["rr_quality_bucket"] = _rr_quality_bucket(rr)
    if rr < RR_HARD_CANCEL_THRESHOLD:
        payload["action"] = "CANCEL"
        payload["confidence"] = "LOW"
        payload["cancel_reason"] = f"Claude TP/SL R:R {rr:.2f} below {RR_HARD_CANCEL_THRESHOLD:.2f}"
        payload["ai_reason"] = payload["cancel_reason"]
        payload["skip_entry"] = True
        payload["rr_skip_reason"] = payload["cancel_reason"]
    elif skip and not payload.get("rr_skip_reason"):
        payload["rr_skip_reason"] = f"Claude TP/SL effective_rr {rr:.2f} < min_rr {float(min_rr):.2f}" if min_rr is not None else None
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
        exact_strength = _resolve_execution_strength(signal, ctx)
        ctx["strength"] = exact_strength
        signal["cntr_strength"] = round(exact_strength, 2) if exact_strength > 0 else signal.get("cntr_strength")
        ctx["ws_online"] = ws_online

        r_score, components = _coerce_rule_score_result(rule_score(signal, ctx))
        logger.info("[Worker] rule score [%s %s]: %.1f", stk_cd, strategy, r_score)
        quality = _compute_signal_quality(signal, ctx, r_score)
        signal.update(quality)

        threshold = get_claude_threshold(strategy)
        ai_score_val = r_score
        ai_result = {}
        cancel_type = None
        cancel_reason = None

        if should_skip_ai(r_score, strategy):
            action = "CANCEL"
            confidence = "LOW"
            reason = f"Rule score {r_score:.1f} below threshold"
            cancel_reason = "Rule threshold not met"
            cancel_type = "RULE_THRESHOLD"
            await _incr_pipeline(rdb, strategy, "cancel_score")
        else:
            rr_prefilter_reason = _rr_prefilter_reason(signal, ctx)
            hard_gate_reason = _hard_gate_failure(signal, ctx)
            stale_reason = _freshness_cancel_reason(ctx)
            if rr_prefilter_reason:
                action = "CANCEL"
                confidence = "LOW"
                reason = rr_prefilter_reason
                cancel_reason = rr_prefilter_reason
                cancel_type = "RR_TOO_LOW"
                await _incr_pipeline(rdb, strategy, "cancel_rr")
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
                        ai_score_val = ai_result.get("ai_score", r_score)
                        action = ai_result.get("action", "ENTER")
                        confidence = ai_result.get("confidence", "HIGH")
                        reason = ai_result.get("reason", f"Rule score {r_score:.1f} passed")
                        cancel_reason = ai_result.get("cancel_reason")
                        action, confidence, reason, cancel_reason = _maybe_promote_hold_to_enter(
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
            **quality,
        }
        normalize_signal_prices(enriched)
        enriched = _apply_claude_rr_override(enriched)
        enriched = _apply_claude_postprocess_hard_rules(enriched)
        action = enriched.get("action", action)
        confidence = enriched.get("confidence", confidence)
        cancel_reason = enriched.get("cancel_reason")
        cancel_type = enriched.get("cancel_type")
        reason = enriched.get("ai_reason", reason)
        display_reason = _resolve_display_reason(action, reason, cancel_reason)
        enriched["ai_reason"] = display_reason
        await push_score_only_queue(rdb, enriched)

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
                    market_flu_rt=None,
                    news_sentiment=None,
                    news_ctrl=None,
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
                    await confirm_open_position(
                        pg_pool,
                        db_id,
                        ai_score=ai_score_val,
                        tp1_price=_fv(enriched.get("claude_tp1") or enriched.get("tp1_price")),
                        tp2_price=_fv(enriched.get("claude_tp2") or enriched.get("tp2_price")),
                        sl_price=_fv(enriched.get("claude_sl") or enriched.get("sl_price")),
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
