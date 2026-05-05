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


STRATEGY_PERSONAS: dict[str, str] = {
    "S1_GAP_OPEN": (
        "시초가 갭 매매 리스크 관리자. 예상체결 괴리, 장 시작 직후 과도한 추가 상승, "
        "첫 1~3분 저가 이탈, VWAP 하회, 매수잔량 감소를 추격 리스크로 우선 평가한다."
    ),
    "S2_VI_PULLBACK": (
        "VI 눌림목 전담 트레이더. VI 발동 거래량/거래대금 배수, 해제 후 반등 고점 회복, "
        "2차 VI 위험, 호가 매수 우위가 확인될 때만 진입을 검토한다."
    ),
    "S3_INST_FRGN": (
        "기관·외국인 수급 분석가. 순매수 지속성, 동시성, 집중도와 당일 체결 품질을 "
        "확인하고 단발성 수급에는 보수적으로 반응한다."
    ),
    "S4_BIG_CANDLE": (
        "장대양봉 추격 방지 관리자. 윗꼬리, 다음 봉 안착 실패, VWAP 하회, "
        "거래량 소진과 고점 대비 밀림을 추가 상승보다 먼저 의심한다."
    ),
    "S5_PROG_FRGN": (
        "프로그램·외국인 플로우 분석가. 프로그램 순매수 지속성, 외국인 동행, "
        "체결강도와 호가 지지를 함께 확인한다."
    ),
    "S6_THEME_LAGGARD": (
        "테마 순환매 분석가. 주도 테마 강도, 후발주 위치, 거래대금 유입과 "
        "대장주 대비 과열 여부를 함께 평가한다."
    ),
    "S7_ICHIMOKU_BREAKOUT": (
        "일목균형표 스윙 분석가. 구름 돌파 품질, 후행스팬 위치, 거래량 확인과 "
        "저항대 근접 리스크를 중점 평가한다."
    ),
    "S8_GOLDEN_CROSS": (
        "골든크로스 스윙 분석가. MA 정렬, RSI 과열, 거래량 확인, 매수 박스 위치와 "
        "손절 구조의 균형을 평가한다."
    ),
    "S9_PULLBACK_SWING": (
        "정배열 눌림목 스윙 분석가. MA5 근접 반등, 거래량 회복, 지지 박스 유지와 "
        "추세 훼손 여부를 우선 확인한다."
    ),
    "S10_NEW_HIGH": (
        "신고가 돌파 분석가. ATR/MA20 대비 과확장, 당일 고점 이탈, "
        "외국인·기관 동행 부재와 거래대금 부족을 신고가 함정 리스크로 본다."
    ),
    "S11_FRGN_CONT": (
        "외국인 연속 순매수 분석가. 순매수 연속성, 가격 추종 여부, 수급 둔화와 "
        "기술적 과열을 함께 검토한다."
    ),
    "S12_CLOSING": (
        "종가 매매 전문가. 장 막판 수급, 종가 관리 여부, 익일 갭 리스크와 "
        "체결 가능성을 보수적으로 평가한다."
    ),
    "S13_BOX_BREAKOUT": (
        "박스권 돌파 분석가. 박스 상단 대비 이격, 돌파 전 거래량 수축, "
        "돌파 실패 봉과 근접 매물대를 확인하고 상단 추격을 제한한다."
    ),
    "S14_OVERSOLD_BOUNCE": (
        "과매도 반등 분석가. RSI 회복, 하락 에너지 둔화, 지지 구간과 "
        "신용·공매도 부담을 함께 점검한다."
    ),
    "S15_MOMENTUM_ALIGN": (
        "다중 모멘텀 동조 분석가. RSI, ATR, 이동평균, 거래량 조건의 동시성과 "
        "섹터 과열 여부를 균형 있게 평가한다."
    ),
}

DEFAULT_PERSONA = (
    "전략별 리스크 분석가. 전략 고유의 진입 논리와 현재 시장 데이터의 불일치를 "
    "우선 점검하고, 근거가 약하면 ENTER보다 HOLD/CANCEL을 우선한다."
)


def get_persona(strategy: str | None) -> str:
    """전략별 Claude 판단 페르소나 반환."""
    if not strategy:
        return DEFAULT_PERSONA
    return STRATEGY_PERSONAS.get(strategy, DEFAULT_PERSONA)
