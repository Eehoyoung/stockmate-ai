from __future__ import annotations

import math


RUNNER_SCORE_RAW_FIELD = "runner_score_raw"
SCORE_SCALE_FIELD = "score_scale"
SCORE_SCALE_0_100 = "0_100"


_RUNNER_SCORE_MAX_BY_STRATEGY = {
    "S1_GAP_OPEN": 60.0,
    "S4_BIG_CANDLE": 60.0,
    "S7_ICHIMOKU_BREAKOUT": 100.0,
    "S8_GOLDEN_CROSS": 80.0,
    "S9_PULLBACK_SWING": 60.0,
    "S10_NEW_HIGH": 80.0,
    "S11_FRGN_CONT": 100.0,
    "S12_CLOSING": 30.0,
    "S13_BOX_BREAKOUT": 100.0,
    "S14_OVERSOLD_BOUNCE": 75.0,
    "S15_MOMENTUM_ALIGN": 100.0,
}


def coerce_score(value, default: float = 0.0) -> float:
    try:
        score = float(str(value).replace(",", "").replace("+", ""))
    except (TypeError, ValueError):
        return float(default)
    if not math.isfinite(score):
        return float(default)
    return score


def normalize_score_0_100(value, default: float = 0.0, ndigits: int = 1) -> float:
    score = coerce_score(value, default)
    return round(max(0.0, min(100.0, score)), ndigits)


def normalize_runner_score(value, strategy: str = "", ndigits: int = 1) -> float:
    raw_score = coerce_score(value)
    max_score = _RUNNER_SCORE_MAX_BY_STRATEGY.get(strategy)
    if max_score and max_score > 0:
        return normalize_score_0_100(raw_score / max_score * 100.0, ndigits=ndigits)
    return normalize_score_0_100(raw_score, ndigits=ndigits)


def normalize_runner_signal(signal: dict, strategy: str = "") -> dict:
    if "score" not in signal:
        return signal

    raw_score = coerce_score(signal.get(RUNNER_SCORE_RAW_FIELD, signal.get("score")))
    normalized = normalize_runner_score(raw_score, strategy or signal.get("strategy", ""))
    signal[RUNNER_SCORE_RAW_FIELD] = round(raw_score, 2)
    signal["score"] = normalized
    signal["runner_score"] = normalized
    signal[SCORE_SCALE_FIELD] = SCORE_SCALE_0_100
    return signal
