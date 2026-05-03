from __future__ import annotations
"""
ai-engine/strategy_meta.py
──────────────────────────────────────────────────────────────
전략 분류·임계값 단일 소스 (Single Source of Truth)

여러 모듈(scorer.py, strategy_runner.py, stockScore.py 등)이
분산 관리하던 SWING_STRATEGIES / CLAUDE_THRESHOLDS / get_threshold()
를 이 모듈로 통합한다.

변경 시 이 파일 하나만 수정하면 전체 ai-engine에 반영된다.
"""

import os

# ── 전략 분류 ────────────────────────────────────────────────────────────────
# 스윙 전략 기본값 (SWING_STRATEGIES 환경변수로 오버라이드 가능)
_DEFAULT_SWING = (
    "S3_INST_FRGN,S5_PROG_FRGN,"
    "S7_ICHIMOKU_BREAKOUT,S8_GOLDEN_CROSS,S9_PULLBACK_SWING,S10_NEW_HIGH,"
    "S11_FRGN_CONT,S12_CLOSING,S13_BOX_BREAKOUT,"
    "S14_OVERSOLD_BOUNCE,S15_MOMENTUM_ALIGN"
)

#: 스윙 전략 이름 집합 – dedup TTL 86400s (하루 1회), ForceClose 시 보유 유지
SWING_STRATEGIES: frozenset[str] = frozenset(
    os.getenv("SWING_STRATEGIES", _DEFAULT_SWING).split(",")
)

#: 데이 트레이딩 전략 이름 집합 – dedup TTL 3600s (시간당 1회), 장 마감 시 ForceClose
DAY_STRATEGIES: frozenset[str] = frozenset({
    "S1_GAP_OPEN",
    "S2_VI_PULLBACK",
    "S4_BIG_CANDLE",
    "S6_THEME_LAGGARD",
})

#: 전체 전략 이름 집합
ALL_STRATEGIES: frozenset[str] = DAY_STRATEGIES | SWING_STRATEGIES


# ── Claude 호출 임계값 ────────────────────────────────────────────────────────
#: 전략별 규칙 점수 임계값. 이 점수 미만이면 Claude API 호출 없이 CANCEL.
CLAUDE_THRESHOLDS: dict[str, int] = {
    # 데이 트레이딩 전략
    "S1_GAP_OPEN":      55,
    "S2_VI_PULLBACK":   65,
    "S3_INST_FRGN":     60,
    "S4_BIG_CANDLE":    65,
    "S5_PROG_FRGN":     65,
    "S6_THEME_LAGGARD": 60,
    "S7_ICHIMOKU_BREAKOUT": 62,
    # 스윙 전략 — signal 필드 보완 + bid_ratio 중립화 후 재조정
    "S8_GOLDEN_CROSS":     50,   # 65 → 50
    "S9_PULLBACK_SWING":   55,   # 60 → 45 → 55 (거래량 1.3배, pct_ma5 구간 제외 강화)
    "S10_NEW_HIGH":        55,   # 65 → 48 → 55 (등락률 구간 감점, 윗꼬리 필터)
    "S11_FRGN_CONT":       58,   # 60 → 58
    "S12_CLOSING":         60,   # 65 → 60
    "S13_BOX_BREAKOUT":    55,   # 65 → 55
    "S14_OVERSOLD_BOUNCE": 58,   # 65 → 50 → 58 (RSI 범위 22~38, cntr≥105 필수화, cond≥2 강화)
    "S15_MOMENTUM_ALIGN":  60,   # 70 → 65 → 60 (cond_count 3/4 운용 모드 분리)
}

_DEFAULT_THRESHOLD = 65


def get_threshold(strategy: str) -> float:
    """전략별 Claude 호출 임계값 반환 (미등록 전략은 기본값 65)"""
    return float(CLAUDE_THRESHOLDS.get(strategy, _DEFAULT_THRESHOLD))


def is_swing(strategy: str) -> bool:
    """스윙 전략 여부 반환"""
    return strategy in SWING_STRATEGIES
