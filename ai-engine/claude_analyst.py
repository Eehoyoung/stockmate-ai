from __future__ import annotations

"""
On-demand Claude analysis for `/claude {stock_code}`.

The response is intentionally portfolio-agnostic. It evaluates only the
current stock state and returns a structured ENTER/HOLD/SELL opinion.
"""

import asyncio
import json
import logging
import os
from typing import Any

import anthropic

from http_utils import fetch_cntr_strength_cached, fetch_hoga, fetch_stk_nm
from indicator_atr import get_atr_daily, get_atr_minute
from indicator_bollinger import get_bollinger_daily, get_bollinger_minute
from indicator_macd import get_macd_daily, get_macd_minute
from indicator_rsi import fetch_minute_candles, get_rsi_daily, get_rsi_minute
from indicator_stochastic import get_stochastic_minute
from ma_utils import _safe_price, _safe_vol, fetch_daily_candles
from utils import normalize_stock_code, safe_float as _sf

logger = logging.getLogger(__name__)

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
CLAUDE_TIMEOUT_SEC = int(os.getenv("CLAUDE_ANALYST_TIMEOUT_SEC", "30"))
MINUTE_SCOPE = os.getenv("CLAUDE_ANALYST_MINUTE_SCOPE", "5")

_claude_client: anthropic.AsyncAnthropic | None = None

_STRATEGY_NAMES: dict[str, str] = {
    "s1": "S1_GAP_OPEN",
    "s2": "S2_VI_PULLBACK",
    "s3": "S3_INST_FRGN",
    "s4": "S4_BIG_CANDLE",
    "s5": "S5_PROG_FRGN",
    "s6": "S6_THEME_LAGGARD",
    "s7": "S7_ICHIMOKU_BREAKOUT",
    "s8": "S8_GOLDEN_CROSS",
    "s9": "S9_PULLBACK_SWING",
    "s10": "S10_NEW_HIGH",
    "s11": "S11_FRGN_CONT",
    "s12": "S12_CLOSING",
    "s13": "S13_BOX_BREAKOUT",
    "s14": "S14_OVERSOLD_BOUNCE",
    "s15": "S15_MOMENTUM_ALIGN",
}


def _get_client() -> anthropic.AsyncAnthropic:
    global _claude_client
    if _claude_client is None:
        api_key = os.getenv("CLAUDE_API_KEY")
        if not api_key:
            raise RuntimeError("CLAUDE_API_KEY is required")
        _claude_client = anthropic.AsyncAnthropic(api_key=api_key)
    return _claude_client


def _extract_json_block(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = [line for line in cleaned.splitlines() if not line.startswith("```")]
        cleaned = "\n".join(lines).strip()

    if cleaned.startswith("{") and cleaned.endswith("}"):
        return json.loads(cleaned)

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        return json.loads(cleaned[start:end + 1])

    raise json.JSONDecodeError("No JSON object found", cleaned, 0)


def _normalize_list(value: Any, limit: int = 5) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        source = value
    else:
        source = [value]
    result = [str(item).strip() for item in source if str(item).strip()]
    return result[:limit]


def _normalize_action_response(raw: dict[str, Any]) -> dict[str, Any]:
    action = str(raw.get("action", "HOLD") or "HOLD").upper()
    if action not in {"ENTER", "HOLD", "SELL"}:
        action = "HOLD"

    confidence = str(raw.get("confidence", "LOW") or "LOW").upper()
    if confidence not in {"HIGH", "MEDIUM", "LOW"}:
        confidence = "LOW"

    tp_sl = raw.get("tp_sl") if isinstance(raw.get("tp_sl"), dict) else {}

    return {
        "action": action,
        "confidence": confidence,
        "reasons": _normalize_list(raw.get("reasons")),
        "risk_factors": _normalize_list(raw.get("risk_factors")),
        "action_guide": _normalize_list(raw.get("action_guide")),
        "summary": str(raw.get("summary", "") or "").strip(),
        "tp_sl": {
            "take_profit": _sf(tp_sl.get("take_profit", 0)) or None,
            "stop_loss": _sf(tp_sl.get("stop_loss", 0)) or None,
        },
        "portfolio_not_linked": True,
    }


def _safe_round(value: Any, digits: int = 2) -> float | None:
    numeric = _sf(value)
    if numeric == 0 and value not in (0, "0", "0.0"):
        return None
    return round(numeric, digits)


def _safe_int(value: Any) -> int:
    return int(_sf(value))


def _to_price_list(candles: list[dict[str, Any]], key: str, limit: int | None = None) -> list[float]:
    rows = candles if limit is None else candles[:limit]
    values: list[float] = []
    for candle in rows:
        price = _safe_price(candle.get(key))
        if price > 0:
            values.append(price)
    return values


def _moving_average(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    return round(sum(closes[:period]) / period, 2)


async def _check_candidate_pools(rdb, stk_cd: str) -> list[str]:
    found: list[str] = []
    for strategy in range(1, 16):
        key_name = f"s{strategy}"
        for market in ("001", "101"):
            try:
                members = await rdb.lrange(f"candidates:{key_name}:{market}", 0, -1)
            except Exception:
                members = []
            if stk_cd in members:
                found.append(_STRATEGY_NAMES.get(key_name, key_name))
    return sorted(set(found))


async def _build_market_snapshot(rdb, token: str, stk_cd: str) -> dict[str, Any]:
    tick = await rdb.hgetall(f"ws:tick:{stk_cd}") if rdb else {}
    hoga_raw = await rdb.hgetall(f"ws:hoga:{stk_cd}") if rdb else {}

    cur_prc = _sf(tick.get("cur_prc", 0))
    flu_rt = _safe_round(tick.get("flu_rt", 0), 2) or 0.0
    acc_vol = _safe_int(tick.get("acc_trde_qty", 0))

    try:
        cntr_strength, strength_source = await fetch_cntr_strength_cached(token, stk_cd, rdb=rdb, count=5)
    except Exception:
        cntr_strength, strength_source = (_sf(tick.get("cntr_str", 0)), "tick")

    buy_total = _safe_int(hoga_raw.get("total_buy_bid_req", 0))
    sell_total = _safe_int(hoga_raw.get("total_sel_bid_req", 0))
    buy_to_sell_ratio = round(buy_total / sell_total, 3) if sell_total > 0 else None

    best_bid = _safe_round(tick.get("bid_prc", 0), 0)
    best_ask = _safe_round(tick.get("ask_prc", 0), 0)
    if (buy_to_sell_ratio is None or buy_to_sell_ratio == 0) and token:
        try:
            ratio = await fetch_hoga(token, stk_cd, rdb=rdb)
            if ratio:
                buy_to_sell_ratio = round(float(ratio), 3)
        except Exception:
            logger.debug("[claude_analyst] hoga fallback failed for %s", stk_cd)

    return {
        "cur_prc": cur_prc,
        "flu_rt": flu_rt,
        "cntr_str": round(float(cntr_strength), 2) if cntr_strength is not None else 0.0,
        "cntr_strength_source": strength_source,
        "acc_vol": acc_vol,
        "cntr_tm": tick.get("cntr_tm", ""),
        "hoga": {
            "total_buy_bid_req": buy_total,
            "total_sel_bid_req": sell_total,
            "buy_to_sell_ratio": buy_to_sell_ratio,
            "best_bid": best_bid,
            "best_ask": best_ask,
        },
    }


async def _build_daily_indicators(token: str, stk_cd: str, fallback_price: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candles = await fetch_daily_candles(token, stk_cd, target_count=120) if token else []
    closes = _to_price_list(candles, "cur_prc")
    highs = _to_price_list(candles, "high_pric", 20)
    lows = _to_price_list(candles, "low_pric", 20)
    volumes = [_safe_vol(row.get("trde_qty")) for row in candles[:20]]
    latest_price = fallback_price or (closes[0] if closes else 0.0)

    rsi_daily, macd_daily, bb_daily, atr_daily = await asyncio.gather(
        get_rsi_daily(token, stk_cd) if token else asyncio.sleep(0, result=None),
        get_macd_daily(token, stk_cd) if token else asyncio.sleep(0, result=None),
        get_bollinger_daily(token, stk_cd) if token else asyncio.sleep(0, result=None),
        get_atr_daily(token, stk_cd) if token else asyncio.sleep(0, result=None),
    )

    result = {
        "ma5": _moving_average(closes, 5),
        "ma20": _moving_average(closes, 20),
        "ma60": _moving_average(closes, 60),
        "ma120": _moving_average(closes, 120),
        "rsi14": getattr(rsi_daily, "rsi", None),
        "macd": getattr(macd_daily, "macd", None),
        "macd_signal": getattr(macd_daily, "signal", None),
        "macd_histogram": getattr(macd_daily, "histogram", None),
        "bb_upper": getattr(bb_daily, "upper", None),
        "bb_mid": getattr(bb_daily, "middle", None),
        "bb_lower": getattr(bb_daily, "lower", None),
        "bb_pct_b": getattr(bb_daily, "pct_b", None),
        "atr": getattr(atr_daily, "atr", None),
        "atr_pct": getattr(atr_daily, "atr_pct", None),
        "vol_ma20": round(sum(volumes) / len(volumes), 2) if volumes else None,
        "recent_high_20d": round(max(highs), 2) if highs else None,
        "recent_low_20d": round(min(lows), 2) if lows else None,
        "cur_prc": latest_price,
    }
    return result, candles


async def _build_minute_indicators(token: str, stk_cd: str) -> dict[str, Any]:
    minute_candles = await fetch_minute_candles(token, stk_cd, tic_scope=MINUTE_SCOPE) if token else []

    rsi_min, macd_min, bb_min, stoch_min, atr_min = await asyncio.gather(
        get_rsi_minute(token, stk_cd, tic_scope=MINUTE_SCOPE) if token else asyncio.sleep(0, result=None),
        get_macd_minute(token, stk_cd, tic_scope=MINUTE_SCOPE) if token else asyncio.sleep(0, result=None),
        get_bollinger_minute(token, stk_cd, tic_scope=MINUTE_SCOPE) if token else asyncio.sleep(0, result=None),
        get_stochastic_minute(token, stk_cd, tic_scope=MINUTE_SCOPE) if token else asyncio.sleep(0, result=None),
        get_atr_minute(token, stk_cd, tic_scope=MINUTE_SCOPE) if token else asyncio.sleep(0, result=None),
    )

    closes = _to_price_list(minute_candles, "cur_prc")
    result = {
        "tic_scope": MINUTE_SCOPE,
        "candle_count": len(minute_candles),
        "last_close": closes[0] if closes else None,
        "rsi14": getattr(rsi_min, "rsi", None),
        "macd": getattr(macd_min, "macd", None),
        "macd_signal": getattr(macd_min, "signal", None),
        "macd_histogram": getattr(macd_min, "histogram", None),
        "bb_upper": getattr(bb_min, "upper", None),
        "bb_mid": getattr(bb_min, "middle", None),
        "bb_lower": getattr(bb_min, "lower", None),
        "bb_pct_b": getattr(bb_min, "pct_b", None),
        "stoch_k": getattr(stoch_min, "k", None),
        "stoch_d": getattr(stoch_min, "d", None),
        "atr": getattr(atr_min, "atr", None),
        "atr_pct": getattr(atr_min, "atr_pct", None),
    }
    return result


def _build_prompt(stk_cd: str, stk_nm: str, analysis_input: dict[str, Any]) -> str:
    return (
        "Analyze the Korean stock below and decide one action.\n"
        "This analysis is portfolio-agnostic. Do not assume actual holdings.\n"
        "Interpret HOLD as 'existing-holder perspective still acceptable' and SELL as "
        "'avoid new entry or reduce/exit bias at this zone'.\n"
        "Return JSON only with this schema:\n"
        "{"
        '"action":"ENTER|HOLD|SELL",'
        '"confidence":"HIGH|MEDIUM|LOW",'
        '"reasons":["..."],'
        '"risk_factors":["..."],'
        '"action_guide":["..."],'
        '"tp_sl":{"take_profit":0,"stop_loss":0},'
        '"summary":"..."'
        "}\n\n"
        f"Stock: {stk_nm} ({stk_cd})\n"
        f"Input JSON:\n{json.dumps(analysis_input, ensure_ascii=False, default=str, indent=2)}"
    )


async def _call_claude(stk_cd: str, stk_nm: str, analysis_input: dict[str, Any]) -> dict[str, Any]:
    prompt = _build_prompt(stk_cd, stk_nm, analysis_input)
    response = await _get_client().messages.create(
        model=CLAUDE_MODEL,
        max_tokens=900,
        system=(
            "You are a top-tier Korean equities analyst. "
            "Use only the provided data. Be concise, technically grounded, "
            "and output valid JSON only."
        ),
        messages=[{"role": "user", "content": prompt}],
    )
    raw_text = response.content[0].text
    parsed = _extract_json_block(raw_text)
    normalized = _normalize_action_response(parsed)
    normalized["claude_analysis"] = raw_text.strip()
    return normalized


async def analyze_stock_for_user(rdb, stk_cd: str) -> dict[str, Any]:
    stk_cd = normalize_stock_code(stk_cd)
    if not stk_cd:
        return {"error": "invalid stock code"}

    token = ""
    if rdb:
        try:
            token = (await rdb.get("kiwoom:token")) or ""
        except Exception as exc:
            logger.warning("[claude_analyst] token fetch failed: %s", exc)

    stk_nm = stk_cd
    if token:
        try:
            stk_nm = await fetch_stk_nm(rdb, token, stk_cd)
        except Exception as exc:
            logger.debug("[claude_analyst] stock name fetch failed: %s", exc)

    strategies_in_pool = await _check_candidate_pools(rdb, stk_cd)
    market_snapshot = await _build_market_snapshot(rdb, token, stk_cd)
    daily_indicators, _ = await _build_daily_indicators(token, stk_cd, market_snapshot["cur_prc"])
    minute_indicators = await _build_minute_indicators(token, stk_cd)

    result: dict[str, Any] = {
        "stk_cd": stk_cd,
        "stk_nm": stk_nm,
        "strategies_in_pool": strategies_in_pool,
        "cur_prc": market_snapshot["cur_prc"],
        "flu_rt": market_snapshot["flu_rt"],
        "cntr_str": market_snapshot["cntr_str"],
        "acc_vol": market_snapshot["acc_vol"],
        "cntr_tm": market_snapshot["cntr_tm"],
        "hoga": market_snapshot["hoga"],
        "daily_indicators": daily_indicators,
        "minute_indicators": minute_indicators,
        "portfolio_not_linked": True,
        "error": None,
    }

    # Legacy compatibility fields still used by some bot output and tests.
    result.update({
        "ma5": daily_indicators.get("ma5"),
        "ma20": daily_indicators.get("ma20"),
        "ma60": daily_indicators.get("ma60"),
        "rsi14": daily_indicators.get("rsi14"),
        "bb_upper": daily_indicators.get("bb_upper"),
        "bb_lower": daily_indicators.get("bb_lower"),
        "vol_ma20": daily_indicators.get("vol_ma20"),
        "recent_high_20d": daily_indicators.get("recent_high_20d"),
        "recent_low_20d": daily_indicators.get("recent_low_20d"),
    })

    try:
        claude_payload = await asyncio.wait_for(
            _call_claude(
                stk_cd,
                stk_nm,
                {
                    "market_snapshot": market_snapshot,
                    "daily_indicators": daily_indicators,
                    "minute_indicators": minute_indicators,
                    "strategies_in_pool": strategies_in_pool,
                    "portfolio_not_linked": True,
                },
            ),
            timeout=CLAUDE_TIMEOUT_SEC,
        )
        result.update(claude_payload)
    except asyncio.TimeoutError:
        logger.warning("[claude_analyst] Claude timeout for %s", stk_cd)
        result.update({
            "action": "HOLD",
            "confidence": "LOW",
            "reasons": ["Claude response timed out; do not treat this as a trade signal."],
            "risk_factors": ["AI timeout", "Need manual review"],
            "action_guide": ["Re-run /claude later after market data stabilizes."],
            "tp_sl": {"take_profit": None, "stop_loss": None},
            "summary": "AI analysis timed out. Manual review required.",
            "claude_analysis": "Claude timeout",
            "error": "timeout",
            "portfolio_not_linked": True,
        })
    except Exception as exc:
        logger.error("[claude_analyst] Claude analysis failed for %s: %s", stk_cd, exc)
        result.update({
            "action": "HOLD",
            "confidence": "LOW",
            "reasons": ["Claude analysis failed; treat this output as informational only."],
            "risk_factors": [str(exc)],
            "action_guide": ["Check AI engine logs and retry the command."],
            "tp_sl": {"take_profit": None, "stop_loss": None},
            "summary": "AI analysis failed. Manual review required.",
            "claude_analysis": f"Claude analysis failed: {exc}",
            "error": str(exc),
            "portfolio_not_linked": True,
        })

    return result
