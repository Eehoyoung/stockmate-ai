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
    "S1_GAP_OPEN":      70,
    "S2_VI_PULLBACK":   65,
    "S3_INST_FRGN":     60,
    "S4_BIG_CANDLE":    75,
    "S5_PROG_FRGN":     65,
    "S6_THEME_LAGGARD": 60,
    "S7_AUCTION":       70,
    "S10_NEW_HIGH":     65,
    "S11_FRGN_CONT":    60,
    "S12_CLOSING":      65,
    "S8_GOLDEN_CROSS":  65,
    "S9_PULLBACK_SWING": 60,
    "S13_BOX_BREAKOUT":    65,
    "S14_OVERSOLD_BOUNCE": 65,
    "S15_MOMENTUM_ALIGN":  70,
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

    # 14:30~15:30: 종가강도 전략 최적 시간대
    if 870 <= minute_of_day < 930:
        if strategy == "S12_CLOSING":
            return 5.0

    return 0.0


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

    rsi      = _safe_float(signal.get("rsi", 0))
    atr_pct  = _safe_float(signal.get("atr_pct", 0))
    cond_cnt = int(signal.get("cond_count", 0) or 0)

    bid  = _safe_float(hoga.get("total_buy_bid_req"))
    ask  = _safe_float(hoga.get("total_sel_bid_req", "1"))
    bid_ratio = bid / ask if ask > 0 else 0.0

    flu_rt = _safe_float(tick.get("flu_rt"))

    match strategy:
        case "S1_GAP_OPEN":
            gap = _safe_float(signal.get("gap_pct", 0))
            # 갭 점수: 3~5% 최적, 5~8% 보통, 8~15% 약함, 15% 초과 페널티, 3% 미만 0점
            score += 20 if 3 <= gap < 5 else (15 if 5 <= gap < 8 else (10 if 8 <= gap < 15 else (-10 if gap >= 15 else 0)))
            # 체결강도
            score += 30 if strength > 150 else (20 if strength > 130 else (10 if strength > 110 else 0))
            # 호가비율
            score += 25 if bid_ratio > 2 else (20 if bid_ratio > 1.5 else (10 if bid_ratio > 1.3 else 0))
            # 캔들 체결강도 보너스 (신호에 포함된 경우)
            cntr_sig = _safe_float(signal.get("cntr_strength", 0))
            if cntr_sig > 0:
                score += 10 if cntr_sig > 150 else (5 if cntr_sig > 130 else 0)

        case "S2_VI_PULLBACK":
            pullback = abs(_safe_float(signal.get("pullback_pct", 0)))
            score += 30 if 1.0 <= pullback < 2.0 else (20 if pullback < 3.0 else 0)
            # is_dynamic: Java는 Boolean(true/false), Python 전술은 int(1/0) 으로도 전달될 수 있음
            is_dynamic = bool(signal.get("is_dynamic", False))
            score += 15 if is_dynamic else 0
            score += 20 if strength > 120 else (10 if strength > 110 else 0)
            score += 20 if bid_ratio > 1.5 else (10 if bid_ratio > 1.3 else 0)

        case "S3_INST_FRGN":
            net_amt   = _safe_float(signal.get("net_buy_amt", 0))
            cont_days = int(signal.get("continuous_days", 0) or 0)
            vol_ratio = _safe_float(signal.get("vol_ratio", 0))
            # 순매수 금액 (최대 25점)
            score += min(25, net_amt / 1_000_000 * 0.5)
            # 연속 순매수 일수
            score += 30 if cont_days >= 5 else (20 if cont_days >= 3 else (10 if cont_days >= 1 else 0))
            # 거래량 비율
            score += 25 if vol_ratio >= 3 else (20 if vol_ratio >= 2 else (10 if vol_ratio >= 1.5 else 0))

        case "S4_BIG_CANDLE":
            vol_ratio  = _safe_float(signal.get("vol_ratio", 0))
            body_ratio = _safe_float(signal.get("body_ratio", 0))
            score += 25 if vol_ratio > 10 else (20 if vol_ratio > 5 else (10 if vol_ratio > 3 else 0))
            score += 20 if body_ratio >= 0.8 else (10 if body_ratio >= 0.7 else 0)
            score += 20 if signal.get("is_new_high") else 0
            score += 20 if strength > 150 else (15 if strength > 140 else (5 if strength > 120 else 0))

        case "S5_PROG_FRGN":
            net_amt = _safe_float(signal.get("net_buy_amt", 0))
            # 프로그램 순매수 금액 기반 (최대 40점)
            score += min(40, net_amt / 1_000_000 * 0.4)
            # 실시간 체결강도
            score += 25 if strength > 130 else (20 if strength > 120 else (10 if strength > 100 else 0))
            # 호가 매수 우위
            score += 20 if bid_ratio > 2 else (15 if bid_ratio > 1.5 else (8 if bid_ratio > 1.2 else 0))

        case "S6_THEME_LAGGARD":
            gap = _safe_float(signal.get("gap_pct", 0))
            cntr_sig = _safe_float(signal.get("cntr_strength", 0))
            score += 25 if 1 <= gap < 3 else (15 if 3 <= gap < 5 else 0)
            # 체결강도 우선 적용 (신호 내 값 → 없으면 실시간 값)
            effective_strength = cntr_sig if cntr_sig > 0 else strength
            score += 30 if effective_strength > 150 else (20 if effective_strength > 120 else 0)
            score += 20 if bid_ratio > 1.5 else (10 if bid_ratio > 1.2 else 0)

        case "S7_AUCTION":
            gap = _safe_float(signal.get("gap_pct", 0))
            score += 25 if 2 <= gap < 5 else (15 if 5 <= gap < 8 else 0)
            score += 30 if bid_ratio > 3 else (25 if bid_ratio > 2 else (10 if bid_ratio > 1.5 else 0))
            vol_rank = int(signal.get("vol_rank", 999) or 999)
            score += 20 if vol_rank <= 10 else (15 if vol_rank <= 20 else (5 if vol_rank <= 30 else 0))

        case "S10_NEW_HIGH":
            # 52주 신고가: 등락률 + 거래량 급증률 + 체결강도
            # vol_surge_rt: Python 스캐너(ka10023 급증률 %)
            # vol_ratio: Java api-orchestrator(20일 평균 대비 배율) → 급증률로 환산
            vol_surge = _safe_float(signal.get("vol_surge_rt", 0))
            if vol_surge == 0:
                vol_ratio_java = _safe_float(signal.get("vol_ratio", 0))
                vol_surge = max(0.0, (vol_ratio_java - 1.0) * 100)  # 2배 → 100%
            score += 30 if vol_surge >= 300 else (20 if vol_surge >= 200 else (10 if vol_surge >= 100 else 0))
            score += 20 if 2 <= flu_rt <= 8 else (10 if 0 < flu_rt <= 15 else (-10 if flu_rt > 15 else 0))
            # 체결강도: signal 내 cntr_strength(ka10046 REST 조회값) 우선,
            # 없으면 market_ctx strength(ws:strength Redis) 사용
            # 52주 신고가 종목은 WS 미구독이라 market_ctx.strength=100인 경우가 많음
            cntr_sig_s10 = _safe_float(signal.get("cntr_strength", 0))
            effective_str_s10 = cntr_sig_s10 if cntr_sig_s10 > 0 else strength
            score += 30 if effective_str_s10 > 130 else (20 if effective_str_s10 > 110 else (10 if effective_str_s10 > 100 else 0))

        case "S11_FRGN_CONT":
            # 외국인 연속 순매수: 연속일수 + 누적수량 + 체결강도
            dm1 = _safe_float(signal.get("dm1", 0))
            dm2 = _safe_float(signal.get("dm2", 0))
            dm3 = _safe_float(signal.get("dm3", 0))
            cont_days = sum(1 for d in (dm1, dm2, dm3) if d > 0)
            score += 30 if cont_days >= 3 else (20 if cont_days >= 2 else 0)
            score += 20 if flu_rt > 0 else (-10 if flu_rt < -3 else 0)
            score += 30 if strength > 120 else (20 if strength > 100 else 0)

        case "S12_CLOSING":
            # 종가강도: 등락률 + 체결강도(응답 포함) + 호가비율
            cntr_str_sig = _safe_float(signal.get("cntr_strength", 0))
            effective_str = cntr_str_sig if cntr_str_sig > 0 else strength
            score += 30 if 4 <= flu_rt <= 10 else (15 if 10 < flu_rt <= 15 else (-10 if flu_rt > 15 else 0))
            score += 35 if effective_str >= 130 else (25 if effective_str >= 110 else (10 if effective_str >= 100 else 0))
            score += 20 if bid_ratio > 1.5 else (10 if bid_ratio > 1.2 else 0)

        case "S8_GOLDEN_CROSS":
            # 골든크로스 스윙: MA5 > MA20 크로스 + 거래량 확인
            flu_rt_s8 = flu_rt if flu_rt != 0 else _safe_float(signal.get("flu_rt", 0))
            cntr_sig = _safe_float(signal.get("cntr_strength", 0))
            effective_str = cntr_sig if cntr_sig > 0 else strength
            vol_ratio_s8 = _safe_float(signal.get("vol_ratio", 0))
            # 등락률: 1~5% 최적(크로스 초기), 5~10% 보통, 10% 초과 노이즈
            score += 25 if 1 <= flu_rt_s8 <= 5 else (15 if 5 < flu_rt_s8 <= 10 else 0)
            # 거래량 배율: 크로스 당일 거래량 확인
            score += 20 if vol_ratio_s8 >= 3.0 else (12 if vol_ratio_s8 >= 1.5 else (5 if vol_ratio_s8 >= 1.0 else 0))
            # 체결강도
            score += 30 if effective_str > 130 else (20 if effective_str > 110 else (10 if effective_str > 100 else 0))
            # 호가 매수 우위
            score += 15 if bid_ratio > 1.5 else (8 if bid_ratio > 1.2 else 0)
            # RSI 확증: 크로스 후 RSI > 50 이면 모멘텀 신뢰도 상승
            if rsi > 0:
                score += 10 if rsi > 55 else (5 if rsi > 50 else 0)

        case "S9_PULLBACK_SWING":
            # 눌림목 반등 스윙: 정배열 내 5MA 근접 반등, 소폭 상승 + 체결강도
            flu_rt_s9 = flu_rt if flu_rt != 0 else _safe_float(signal.get("flu_rt", 0))
            cntr_sig = _safe_float(signal.get("cntr_strength", 0))
            effective_str = cntr_sig if cntr_sig > 0 else strength
            # 등락률: 0.5~3% 최적(눌림 반등 초기), 3~6% 보통, 이외 0점
            score += 30 if 0.5 <= flu_rt_s9 <= 3 else (20 if 3 < flu_rt_s9 <= 6 else (10 if 6 < flu_rt_s9 <= 10 else 0))
            # 체결강도
            score += 35 if effective_str > 130 else (25 if effective_str > 110 else (10 if effective_str > 100 else 0))
            # 호가
            score += 20 if bid_ratio > 1.5 else (10 if bid_ratio > 1.2 else 0)
            # RSI 눌림목 확증: 40~60 구간이 이상적 눌림
            if rsi > 0:
                score += 10 if 40 <= rsi <= 60 else (5 if 60 < rsi <= 70 else 0)

        case "S13_BOX_BREAKOUT":
            # 박스권 돌파 스윙: 거래량 폭발 + 장대양봉 + 체결강도 ≥ 130
            flu_rt_s13 = flu_rt if flu_rt != 0 else _safe_float(signal.get("flu_rt", 0))
            cntr_sig = _safe_float(signal.get("cntr_strength", 0))
            effective_str = cntr_sig if cntr_sig > 0 else strength
            # 등락률: 3~8% 최적(박스 돌파), 8~15% 보통
            score += 30 if 3 <= flu_rt_s13 <= 8 else (20 if 8 < flu_rt_s13 <= 15 else 0)
            # 체결강도 (S13은 130% 이상 필터 후 진입 — 가중치 높게)
            score += 35 if effective_str > 150 else (25 if effective_str > 130 else (10 if effective_str > 110 else 0))
            # 호가 매수 우위
            score += 25 if bid_ratio > 2 else (15 if bid_ratio > 1.5 else (5 if bid_ratio > 1.2 else 0))
            # RSI 돌파 모멘텀 확증
            if rsi > 0:
                score += 10 if rsi > 60 else (5 if rsi > 50 else 0)

        case "S14_OVERSOLD_BOUNCE":
            # 과매도 반등: RSI < 35 + ATR 변동성 + 체결강도
            cntr_sig = _safe_float(signal.get("cntr_strength", 0))
            effective_str = cntr_sig if cntr_sig > 0 else strength
            # RSI 과매도 구간 (핵심 조건, 최대 40점)
            if rsi > 0:
                score += 40 if rsi < 25 else (30 if rsi < 30 else (20 if rsi < 35 else (10 if rsi < 40 else 0)))
            else:
                score += 15  # RSI 없는 경우 기본 부여
            # ATR% 변동성: 높을수록 반등 탄력 기대
            score += 20 if atr_pct > 3 else (12 if atr_pct > 2 else (5 if atr_pct > 1 else 0))
            # 체결강도 – 반등 초기 매수세 확인
            score += 25 if effective_str > 120 else (15 if effective_str > 110 else (5 if effective_str > 100 else 0))
            # 호가 매수 우위
            score += 15 if bid_ratio > 1.5 else (8 if bid_ratio > 1.2 else 0)

        case "S15_MOMENTUM_ALIGN":
            # 다중 모멘텀 정렬: RSI 상승 구간 + 거래량 증가 + 체결강도
            cntr_sig = _safe_float(signal.get("cntr_strength", 0))
            effective_str = cntr_sig if cntr_sig > 0 else strength
            vol_ratio_s15 = _safe_float(signal.get("vol_ratio", 0))
            flu_rt_s15 = flu_rt if flu_rt != 0 else _safe_float(signal.get("flu_rt", 0))
            # RSI 모멘텀 정렬 구간 (최대 35점)
            if rsi > 0:
                score += 35 if 50 <= rsi <= 65 else (25 if 65 < rsi <= 75 else (10 if 45 <= rsi < 50 else 0))
            else:
                score += 10
            # 거래량 확인 (최대 25점)
            score += 25 if vol_ratio_s15 >= 3.0 else (18 if vol_ratio_s15 >= 2.0 else (10 if vol_ratio_s15 >= 1.5 else 0))
            # 체결강도
            score += 25 if effective_str > 130 else (18 if effective_str > 110 else (8 if effective_str > 100 else 0))
            # 호가
            score += 15 if bid_ratio > 1.5 else (8 if bid_ratio > 1.2 else 0)
            # 등락률: 1~5% 모멘텀 초기 진입 최적
            score += 5 if 1 <= flu_rt_s15 <= 5 else (3 if 5 < flu_rt_s15 <= 8 else 0)

    # 조건 충족 수 보너스 (다수 조건 충족 시 신뢰도 상승)
    if cond_cnt >= 4:
        score += 10
    elif cond_cnt == 3:
        score += 5

    # 시간대 보너스
    score += _time_bonus(strategy)

    # 공통 페널티
    if flu_rt > 15:   # 이미 15% 이상 상승 → 과열
        score -= 20
    elif flu_rt > 10:  # 10~15% 구간 – 주의
        score -= 10
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
