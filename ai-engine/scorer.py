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
from datetime import date

logger  = logging.getLogger(__name__)
MIN_SCORE = float(os.getenv("AI_SCORE_THRESHOLD", "60.0"))

# 전략별 Claude 호출 임계값
CLAUDE_THRESHOLDS = {
    "S1_GAP_OPEN":      70,
    "S2_VI_PULLBACK":   65,
    "S3_INST_FRGN":     60,
    "S4_BIG_CANDLE":    75,
    "S5_PROG_FRGN":     65,
    "S6_THEME_LAGGARD": 60,
    "S7_AUCTION":       70,
}

MAX_CLAUDE_CALLS_PER_DAY = int(os.getenv("MAX_CLAUDE_CALLS_PER_DAY", "100"))


def _safe_float(v, default=0.0) -> float:
    try:
        return float(str(v).replace(",", "").replace("+", ""))
    except (TypeError, ValueError):
        return default


def rule_score(signal: dict, market_ctx: dict) -> float:
    """
    signal: TradingSignalDto 직렬화 JSON
    market_ctx: {
        "tick":    ws:tick Hash,
        "hoga":    ws:hoga Hash,
        "strength": float (평균 체결강도),
        "vi":      vi Hash,
    }
    반환: 0~100 점수
    """
    strategy = signal.get("strategy", "")
    score    = 0.0

    strength = market_ctx.get("strength", 100.0)
    tick     = market_ctx.get("tick", {})
    hoga     = market_ctx.get("hoga", {})

    bid  = _safe_float(hoga.get("total_buy_bid_req"))
    ask  = _safe_float(hoga.get("total_sel_bid_req", "1"))
    bid_ratio = bid / ask if ask > 0 else 0.0

    flu_rt = _safe_float(tick.get("flu_rt"))

    match strategy:
        case "S1_GAP_OPEN":
            gap = _safe_float(signal.get("gap_pct", 0))
            score += 20 if 3 <= gap < 5 else (15 if gap < 8 else (10 if gap < 15 else -10))
            score += 25 if strength > 150 else (20 if strength > 130 else 0)
            score += 25 if bid_ratio > 2 else (20 if bid_ratio > 1.3 else 0)

        case "S2_VI_PULLBACK":
            pullback = abs(_safe_float(signal.get("pullback_pct", 0)))
            score += 30 if 1.0 <= pullback < 2.0 else (20 if pullback < 3.0 else 0)
            score += 15 if signal.get("is_dynamic") else 0
            score += 20 if strength > 110 else 0
            score += 20 if bid_ratio > 1.3 else 0

        case "S3_INST_FRGN":
            net_amt  = _safe_float(signal.get("net_buy_amt", 0))
            cont_days = signal.get("continuous_days", 0) or 0
            score += min(25, net_amt / 1_000_000 * 0.5)
            score += 30 if cont_days >= 5 else (20 if cont_days >= 3 else 0)
            score += 20 if _safe_float(signal.get("vol_ratio", 0)) >= 2 else 0

        case "S4_BIG_CANDLE":
            vol_ratio  = _safe_float(signal.get("vol_ratio", 0))
            body_ratio = _safe_float(signal.get("body_ratio", 0))  # StrategyService.checkBigCandle() 에서 계산
            score += 25 if vol_ratio > 10 else (20 if vol_ratio > 5 else 0)
            score += 20 if body_ratio >= 0.8 else (10 if body_ratio >= 0.7 else 0)
            score += 20 if signal.get("is_new_high") else 0
            score += 15 if strength > 140 else 0

        case "S5_PROG_FRGN":
            net_amt = _safe_float(signal.get("net_buy_amt", 0))
            # 프로그램 순매수 금액 기반 (최대 40점)
            score += min(40, net_amt / 1_000_000 * 0.4)
            # 실시간 체결강도
            score += 20 if strength > 120 else (10 if strength > 100 else 0)
            # 호가 매수 우위
            score += 15 if bid_ratio > 1.5 else (8 if bid_ratio > 1.2 else 0)

        case "S6_THEME_LAGGARD":
            gap = _safe_float(signal.get("gap_pct", 0))
            score += 25 if 1 <= gap < 3 else (15 if gap < 5 else 0)
            score += 25 if strength > 150 else (20 if strength > 120 else 0)
            score += 20 if bid_ratio > 1.5 else 0

        case "S7_AUCTION":
            gap = _safe_float(signal.get("gap_pct", 0))
            score += 25 if 2 <= gap < 5 else (15 if gap < 8 else 0)
            score += 30 if bid_ratio > 3 else (25 if bid_ratio > 2 else 0)
            vol_rank = signal.get("vol_rank", 999) or 999
            score += 20 if vol_rank <= 20 else 0

    # 공통 페널티
    if flu_rt > 15:   # 이미 15% 이상 상승 → 과열
        score -= 20
    if flu_rt < -5:   # 하락 중
        score -= 15

    score = round(max(0.0, min(100.0, score)), 1)
    logger.info(json.dumps({
        "ts": time.time(), "module": "scorer",
        "strategy": strategy, "stk_cd": signal.get("stk_cd", ""),
        "score": score,
    }))
    return score


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
