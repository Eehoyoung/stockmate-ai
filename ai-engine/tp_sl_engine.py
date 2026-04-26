"""
tp_sl_engine.py
동적 TP/SL 계산 엔진 — 트레이더 페르소나 원칙 기반

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
트레이더 원칙
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SL = "가설 무효화 가격" — 진입 근거가 틀렸다고 확인되는 가격
       (MA 지지 이탈, 스윙 저점 붕괴, 박스 상단 복귀)
  TP = "다음 구조적 저항" — 스윙 고점 클러스터, 볼린저 상단, 피보나치 확장
  ATR = 변동성 컨텍스트 보조 입력 (SL/TP의 유일 기준 ×)
  R:R = 슬리피지·수수료 반영 실효치, 최소 1.3 미달 → skip_entry=True

지원 단계:
  Phase 1 (현재): S8/S9/S13/S15 — 일봉 기반, 추가 API 호출 없음
  Phase 2       : S10/S11/S12   — 일봉 기반, 피보나치 확장
  Phase 3       : S1/S2/S4     — 5분봉 ATR 기반 데이트레이딩
  Phase 4       : S7/S8~S15    — 스윙/추세 기반 TP/SL
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

from price_utils import round_to_tick

logger = logging.getLogger(__name__)

MIN_RR_RATIO    = float(os.getenv("MIN_RR_RATIO",   "1.3"))
TP_SL_STRATEGY_VERSION = os.getenv("TP_SL_STRATEGY_VERSION", "ta_v2_2026_04")
SLIP_FEE_KOSPI  = float(os.getenv("SLIP_FEE_KOSPI",  "0.0035"))   # 편도 0.35%
SLIP_FEE_KOSDAQ = float(os.getenv("SLIP_FEE_KOSDAQ", "0.0045"))   # 편도 0.45%

_DAY_TRADE_STRATEGIES = {
    "S1_GAP_OPEN",
    "S2_VI_PULLBACK",
    "S4_BIG_CANDLE",
    "S6_THEME_LAGGARD",
}

_SWING_TRAILING_DEFAULT = {
    "trail_activation_r": 1.0,
    "allow_overnight": True,
    "allow_reentry": True,
}

_STRATEGY_POLICY: dict[str, dict[str, object]] = {
    "S1_GAP_OPEN": {
        "min_rr": 1.8,
        "stop_max_pct": 2.2,
        "time_stop_type": "intraday_minutes",
        "time_stop_minutes": 30,
        "time_stop_session": "same_day_close",
        "tp_policy_version": TP_SL_STRATEGY_VERSION,
        "sl_policy_version": TP_SL_STRATEGY_VERSION,
        "exit_policy_version": TP_SL_STRATEGY_VERSION,
        "allow_overnight": False,
        "allow_reentry": False,
        "trail_activation_r": None,
    },
    "S2_VI_PULLBACK": {
        "min_rr": 1.8,
        "stop_max_pct": 2.0,
        "time_stop_type": "intraday_minutes",
        "time_stop_minutes": 15,
        "time_stop_session": "same_day_close",
        "tp_policy_version": TP_SL_STRATEGY_VERSION,
        "sl_policy_version": TP_SL_STRATEGY_VERSION,
        "exit_policy_version": TP_SL_STRATEGY_VERSION,
        "allow_overnight": False,
        "allow_reentry": False,
        "trail_activation_r": None,
    },
    "S3_INST_FRGN": {"min_rr": 1.45, "trail_activation_r": 1.0, "allow_overnight": True, "allow_reentry": True},
    "S4_BIG_CANDLE": {
        "min_rr": 1.7,
        "stop_max_pct": 2.5,
        "time_stop_type": "intraday_minutes",
        "time_stop_minutes": 20,
        "time_stop_session": "same_day_close",
        "tp_policy_version": TP_SL_STRATEGY_VERSION,
        "sl_policy_version": TP_SL_STRATEGY_VERSION,
        "exit_policy_version": TP_SL_STRATEGY_VERSION,
        "allow_overnight": False,
        "allow_reentry": False,
        "trail_activation_r": None,
    },
    "S5_PROG_FRGN": {"min_rr": 1.45, "trail_activation_r": 1.0, "allow_overnight": True, "allow_reentry": True},
    "S6_THEME_LAGGARD": {
        "min_rr": 1.6,
        "stop_max_pct": 3.0,
        "time_stop_type": "session_close",
        "time_stop_session": "same_day_close",
        "tp_policy_version": TP_SL_STRATEGY_VERSION,
        "sl_policy_version": TP_SL_STRATEGY_VERSION,
        "exit_policy_version": TP_SL_STRATEGY_VERSION,
        "allow_overnight": False,
        "allow_reentry": False,
        "trail_activation_r": None,
    },
    "S7_ICHIMOKU_BREAKOUT": {"min_rr": 1.55, "trail_activation_r": 1.5, "allow_overnight": True, "allow_reentry": True},
    "S8_GOLDEN_CROSS": {"min_rr": 1.55, "trail_activation_r": 1.0, "allow_overnight": True, "allow_reentry": True},
    "S9_PULLBACK_SWING": {"min_rr": 1.55, "trail_activation_r": 1.0, "allow_overnight": True, "allow_reentry": True},
    "S10_NEW_HIGH": {"min_rr": 1.55, "trail_activation_r": 1.0, "allow_overnight": True, "allow_reentry": True},
    "S11_FRGN_CONT": {"min_rr": 1.55, "trail_activation_r": 1.0, "allow_overnight": True, "allow_reentry": True},
    "S12_CLOSING": {
        "min_rr": 1.45,
        "time_stop_type": "session_close",
        "time_stop_session": "next_day_morning",
        "allow_overnight": True,
        "allow_reentry": False,
        "trail_activation_r": 1.0,
    },
    "S13_BOX_BREAKOUT": {"min_rr": 1.55, "trail_activation_r": 1.5, "allow_overnight": True, "allow_reentry": True},
    "S14_OVERSOLD_BOUNCE": {"min_rr": 1.45, "trail_activation_r": 1.2, "allow_overnight": True, "allow_reentry": True},
    "S15_MOMENTUM_ALIGN": {"min_rr": 1.55, "trail_activation_r": 1.0, "allow_overnight": True, "allow_reentry": True},
}


def _is_day_trade_strategy(strategy: str) -> bool:
    return strategy.upper() in _DAY_TRADE_STRATEGIES


def _strategy_policy(strategy: str) -> dict[str, object]:
    base = {
        "min_rr": MIN_RR_RATIO,
        "stop_max_pct": None,
        "time_stop_type": "",
        "time_stop_minutes": None,
        "time_stop_session": "",
        "tp_policy_version": TP_SL_STRATEGY_VERSION,
        "sl_policy_version": TP_SL_STRATEGY_VERSION,
        "exit_policy_version": TP_SL_STRATEGY_VERSION,
        **_SWING_TRAILING_DEFAULT,
    }
    base.update(_STRATEGY_POLICY.get(strategy.upper(), {}))
    return base


# ──────────────────────────────────────────────────────────────
# 결과 데이터클래스
# ──────────────────────────────────────────────────────────────

@dataclass
class TpSlResult:
    """동적 TP/SL 계산 결과"""
    sl_price:   int            = 0
    tp1_price:  int            = 0
    tp2_price:  Optional[int]  = None
    sl_method:  str            = ""   # 예: "MA20_support", "swing_low_D15", "ATR×2"
    tp_method:  str            = ""   # 예: "swing_resistance", "bollinger_upper", "fib_1272"
    rr_ratio:   float          = 0.0  # 슬리피지 반영 실효 R:R
    skip_entry: bool           = False  # rr_ratio < MIN_RR_RATIO
    trailing_pct: Optional[float] = None
    trailing_activation: Optional[float] = None
    trailing_basis: str = ""
    time_stop_type: str = ""
    time_stop_minutes: Optional[int] = None
    time_stop_session: str = ""
    strategy_version: str = TP_SL_STRATEGY_VERSION
    raw_rr: Optional[float] = None
    single_tp_rr: Optional[float] = None
    effective_rr: Optional[float] = None
    min_rr_ratio: Optional[float] = None
    rr_skip_reason: str = ""
    stop_max_pct: Optional[float] = None
    tp_policy_version: str = TP_SL_STRATEGY_VERSION
    sl_policy_version: str = TP_SL_STRATEGY_VERSION
    exit_policy_version: str = TP_SL_STRATEGY_VERSION
    allow_overnight: Optional[bool] = None
    allow_reentry: Optional[bool] = None

    def to_signal_fields(self) -> dict:
        """전략 결과 dict에 merge할 TP/SL 필드 반환"""
        d: dict = {
            "sl_price":   round_to_tick(self.sl_price, "nearest"),
            "tp1_price":  round_to_tick(self.tp1_price, "nearest"),
            "sl_method":  self.sl_method,
            "tp_method":  self.tp_method,
            "rr_ratio":   round(self.rr_ratio, 2),
            "skip_entry": self.skip_entry,
            "strategy_version": self.strategy_version,
        }
        if self.raw_rr is not None:
            d["raw_rr"] = round(float(self.raw_rr), 3)
        if self.single_tp_rr is not None:
            d["single_tp_rr"] = round(float(self.single_tp_rr), 3)
        if self.effective_rr is not None:
            d["effective_rr"] = round(float(self.effective_rr), 3)
        if self.min_rr_ratio is not None:
            d["min_rr_ratio"] = round(float(self.min_rr_ratio), 2)
        if self.rr_skip_reason:
            d["rr_skip_reason"] = self.rr_skip_reason
        if self.stop_max_pct is not None:
            d["stop_max_pct"] = round(float(self.stop_max_pct), 2)
        if self.tp_policy_version:
            d["tp_policy_version"] = self.tp_policy_version
        if self.sl_policy_version:
            d["sl_policy_version"] = self.sl_policy_version
        if self.exit_policy_version:
            d["exit_policy_version"] = self.exit_policy_version
        if self.allow_overnight is not None:
            d["allow_overnight"] = bool(self.allow_overnight)
        if self.allow_reentry is not None:
            d["allow_reentry"] = bool(self.allow_reentry)
        if self.tp2_price:
            d["tp2_price"] = round_to_tick(self.tp2_price, "nearest")
        if self.trailing_pct is not None:
            d["trailing_pct"] = round(float(self.trailing_pct), 2)
        if self.trailing_activation is not None:
            d["trailing_activation"] = round_to_tick(self.trailing_activation, "nearest")
        if self.trailing_basis:
            d["trailing_basis"] = self.trailing_basis
        if self.time_stop_type:
            d["time_stop_type"] = self.time_stop_type
        if self.time_stop_minutes is not None:
            d["time_stop_minutes"] = int(self.time_stop_minutes)
        if self.time_stop_session:
            d["time_stop_session"] = self.time_stop_session
        return d


# ──────────────────────────────────────────────────────────────
# 보조 함수: 스윙 고점·저점 탐지
# ──────────────────────────────────────────────────────────────

def find_swing_highs(
    highs: list[float],
    cur_prc: float,
    lookback: int = 40,
    cluster_pct: float = 1.0,
) -> list[float]:
    """
    최근 lookback봉에서 스윙 고점(저항선) 탐지.

    Args:
        highs:       고가 리스트 (최신순, index 0 = 오늘)
        cur_prc:     현재가 — cur_prc 위의 레벨만 반환
        lookback:    탐색 봉 수 (index 1~lookback, 오늘 제외)
        cluster_pct: 이 비율(%) 이내 레벨은 병합

    Returns:
        저항 가격 리스트 (오름차순 — 가장 가까운 저항 first)

    알고리즘:
        index i(= newest=0)에서 볼 때,
        highs[i] > highs[i-1] (더 최근이 낮음) AND
        highs[i] > highs[i+1] (더 오래된 것이 낮음)
        → 로컬 최대값 = 스윙 고점
    """
    n = min(len(highs), lookback + 2)
    candidates: list[float] = []

    # index 0 (당일 미완성 봉) 제외 → i=1부터 탐색
    for i in range(1, n - 1):
        h = highs[i]
        if h > cur_prc and h > highs[i - 1] and h > highs[i + 1]:
            candidates.append(h)

    if not candidates:
        return []

    # 클러스터링: 오름차순 정렬 후 1% 이내 레벨 병합
    candidates.sort()
    merged: list[float] = []
    for lvl in candidates:
        if merged and abs(lvl - merged[-1]) / merged[-1] * 100 <= cluster_pct:
            merged[-1] = (merged[-1] + lvl) / 2.0  # 두 레벨의 평균
        else:
            merged.append(lvl)

    return merged  # 오름차순: merged[0]이 cur_prc와 가장 가까운 저항


def find_swing_lows(
    lows: list[float],
    cur_prc: float,
    lookback: int = 40,
    cluster_pct: float = 1.0,
) -> list[float]:
    """
    최근 lookback봉에서 스윙 저점(지지선) 탐지.

    Returns:
        지지 가격 리스트 (내림차순 — 가장 가까운 지지 first)
    """
    n = min(len(lows), lookback + 2)
    candidates: list[float] = []

    for i in range(1, n - 1):
        l = lows[i]
        if l < cur_prc and l < lows[i - 1] and l < lows[i + 1]:
            candidates.append(l)

    if not candidates:
        return []

    # 클러스터링: 내림차순 정렬 (cur_prc에 가까운 지지부터)
    candidates.sort(reverse=True)
    merged: list[float] = []
    for lvl in candidates:
        if merged and abs(merged[-1] - lvl) / merged[-1] * 100 <= cluster_pct:
            merged[-1] = (merged[-1] + lvl) / 2.0
        else:
            merged.append(lvl)

    return merged  # 내림차순: merged[0]이 cur_prc와 가장 가까운 지지


def find_ma_support(
    cur_prc: float,
    ma5:   Optional[float] = None,
    ma20:  Optional[float] = None,
    ma60:  Optional[float] = None,
    ma120: Optional[float] = None,
) -> tuple[float, str]:
    """
    cur_prc 아래에서 가장 가까운 MA 지지선 반환.

    Returns:
        (level, name) — 예: (48500.0, "MA20")
        유효한 MA 없으면 (0.0, "")
    """
    levels = [
        (ma5,   "MA5"),
        (ma20,  "MA20"),
        (ma60,  "MA60"),
        (ma120, "MA120"),
    ]
    # cur_prc 아래인 MA 중 가장 높은 것 (= 가장 가까운 지지)
    best_level = 0.0
    best_name  = ""
    for val, name in levels:
        if val and 0 < val < cur_prc:
            if val > best_level:
                best_level = val
                best_name  = name
    return best_level, best_name


# ──────────────────────────────────────────────────────────────
# 보조 함수: 피보나치 확장
# ──────────────────────────────────────────────────────────────

def calc_fibonacci_extension(
    swing_low: float,
    swing_high: float,
) -> tuple[float, float, float]:
    """
    스윙 레인지 기반 피보나치 확장 레벨 계산.

    Returns:
        (tp_100, tp_1272, tp_1618)
        tp_100  = swing_high (= 1.0 retest)
        tp_1272 = swing_high + range × 0.272  (Fib 1.272 확장)
        tp_1618 = swing_high + range × 0.618  (Fib 1.618 확장)
    """
    r = swing_high - swing_low
    if r <= 0:
        return swing_high, swing_high, swing_high
    return (
        swing_high,
        swing_high + r * 0.272,
        swing_high + r * 0.618,
    )


# ──────────────────────────────────────────────────────────────
# 보조 함수: R:R 계산
# ──────────────────────────────────────────────────────────────

def _calc_rr(
    cur_prc: float,
    tp_price: float,
    sl_price: float,
    slip_fee: float,   # 편도 비율 (예: 0.0035)
    min_rr: float = MIN_RR_RATIO,
) -> tuple[float, bool]:
    """
    슬리피지·수수료 반영 실효 R:R 계산.

    편도 slip_fee 기준으로 왕복(진입+청산) 적용:
      실효 수익 = (tp - cur_prc)/cur_prc - 2×slip_fee
      실효 리스크 = (cur_prc - sl)/cur_prc + 2×slip_fee

    Returns:
        (rr_ratio, skip_entry)
    """
    if cur_prc <= 0 or sl_price <= 0 or tp_price <= cur_prc or sl_price >= cur_prc:
        return 0.0, True

    rt = 2 * slip_fee  # 왕복 수수료
    reward = (tp_price - cur_prc) / cur_prc - rt
    risk   = (cur_prc - sl_price) / cur_prc + rt

    if risk <= 0:
        return 0.0, True

    rr = reward / risk
    return round(rr, 3), rr < min_rr


def _calc_raw_rr(cur_prc: float, tp_price: float, sl_price: float) -> float | None:
    if cur_prc <= 0 or tp_price <= cur_prc or sl_price >= cur_prc:
        return None
    risk = cur_prc - sl_price
    if risk <= 0:
        return None
    return round((tp_price - cur_prc) / risk, 3)


def _bounded_distance(cur_prc: float, *, min_pct: float, max_pct: float, atr: Optional[float], atr_mult: float) -> int:
    atr_dist = atr * atr_mult if atr else cur_prc * min_pct
    min_dist = cur_prc * min_pct
    max_dist = cur_prc * max_pct
    return int(min(max(atr_dist, min_dist), max_dist))


def _nearest_resistance(highs: list[float], cur_prc: float, *, lookback: int, min_pct: float = 0.0) -> int | None:
    swing_highs = find_swing_highs(highs, cur_prc, lookback=lookback)
    for level in swing_highs:
        if level > cur_prc * (1.0 + min_pct):
            return int(level)
    return None


def _slip_fee(stk_cd: str) -> float:
    """종목코드 기반 슬리피지+수수료 비율 (편도)"""
    return SLIP_FEE_KOSPI if str(stk_cd).startswith("0") else SLIP_FEE_KOSDAQ


def _resolve_strategy_min_rr(strategy: str, requested_min_rr: float) -> float:
    """
    전략군별 최소 실효 R:R 하한.

    호출자가 명시적으로 더 큰 값/다른 값을 넘긴 경우는 존중한다.
    기본값(MIN_RR_RATIO)만 들어온 경우에만 전략군별 하한으로 교체한다.
    """
    if requested_min_rr != MIN_RR_RATIO:
        return requested_min_rr
    return float(_strategy_policy(strategy).get("min_rr", requested_min_rr))


def _consolidate_single_tp(
    result: TpSlResult,
    *,
    strategy: str,
    cur_prc: float,
    slip: float,
    min_rr: float,
) -> TpSlResult:
    """
    Collapse TP1/TP2 into one executable TP.

    When TP2 exists, the unified TP is the 50/50 expected target that used to be
    represented by partial exits. Monitoring and R:R then use a single target.
    """
    if result.tp2_price is not None and result.tp2_price > result.tp1_price > 0:
        if _is_day_trade_strategy(strategy):
            result.tp2_price = None
            result.tp_method = f"{result.tp_method}+single_tp_primary"
            result.rr_ratio, result.skip_entry = _calc_rr(cur_prc, result.tp1_price, result.sl_price, slip, min_rr)
            return result
        old_tp1 = result.tp1_price
        old_tp2 = result.tp2_price
        result.tp1_price = int((old_tp1 + old_tp2) / 2)
        result.tp2_price = None
        result.tp_method = f"{result.tp_method}+single_tp_avg({old_tp1}/{old_tp2})"
        result.rr_ratio, result.skip_entry = _calc_rr(
            cur_prc,
            result.tp1_price,
            result.sl_price,
            slip,
            min_rr,
        )
        if result.trailing_activation is not None:
            result.trailing_activation = result.tp1_price
    return result


def _attach_time_stop_policy(strategy: str, result: TpSlResult) -> TpSlResult:
    """
    전략별 시간청산 메타데이터 부착.

    실제 판정은 position_monitor.py에서 수행한다.
    """
    policy = _strategy_policy(strategy)
    result.time_stop_type = str(policy.get("time_stop_type") or result.time_stop_type or "")
    result.time_stop_minutes = (
        int(policy["time_stop_minutes"])
        if policy.get("time_stop_minutes") is not None
        else result.time_stop_minutes
    )
    result.time_stop_session = str(policy.get("time_stop_session") or result.time_stop_session or "")
    return result


def _apply_policy_metadata(strategy: str, result: TpSlResult, *, cur_prc: float, min_rr: float) -> TpSlResult:
    policy = _strategy_policy(strategy)
    raw_rr = _calc_raw_rr(cur_prc, result.tp1_price, result.sl_price)
    result.raw_rr = raw_rr
    result.single_tp_rr = raw_rr
    result.effective_rr = result.rr_ratio
    result.min_rr_ratio = min_rr
    result.stop_max_pct = policy.get("stop_max_pct")
    result.tp_policy_version = str(policy.get("tp_policy_version") or TP_SL_STRATEGY_VERSION)
    result.sl_policy_version = str(policy.get("sl_policy_version") or TP_SL_STRATEGY_VERSION)
    result.exit_policy_version = str(policy.get("exit_policy_version") or TP_SL_STRATEGY_VERSION)
    result.allow_overnight = bool(policy.get("allow_overnight", not _is_day_trade_strategy(strategy)))
    result.allow_reentry = bool(policy.get("allow_reentry", not _is_day_trade_strategy(strategy)))
    if result.trailing_pct is not None and not _is_day_trade_strategy(strategy):
        activation_r = policy.get("trail_activation_r")
        if activation_r is not None:
            risk = max(cur_prc - result.sl_price, 1)
            activation = int(cur_prc + risk * float(activation_r))
            result.trailing_activation = min(result.tp1_price, activation) if result.tp1_price > cur_prc else activation
    if result.stop_max_pct is not None:
        stop_pct = (cur_prc - result.sl_price) / cur_prc * 100 if cur_prc > 0 else 0.0
        if stop_pct > float(result.stop_max_pct):
            result.skip_entry = True
            result.rr_skip_reason = f"stop_pct {stop_pct:.2f}% > {float(result.stop_max_pct):.2f}%"
    if result.skip_entry and not result.rr_skip_reason:
        result.rr_skip_reason = f"effective_rr {result.rr_ratio:.2f} < min_rr {min_rr:.2f}"
    return result


def compute_rr(
    stk_cd: str,
    cur_prc: float,
    tp_price: float,
    sl_price: float,
    min_rr: float | None = None,
) -> tuple[float, bool]:
    """
    공개 R:R 계산 헬퍼 – 슬리피지·수수료 반영.

    :param stk_cd:   종목코드 (KOSPI/KOSDAQ 구분에 사용)
    :param cur_prc:  현재가 (진입가)
    :param tp_price: 목표가
    :param sl_price: 손절가
    :param min_rr:   최소 R:R (None 이면 환경변수 MIN_RR_RATIO 또는 1.3)
    :returns: (rr_ratio, skip_entry) — skip_entry=True 이면 진입 취소 대상
    """
    slip = _slip_fee(stk_cd)
    _min = min_rr if min_rr is not None else MIN_RR_RATIO
    return _calc_rr(cur_prc, tp_price, sl_price, slip, _min)


def _is_macd_weakening(
    macd_line: Optional[float],
    macd_signal: Optional[float],
    macd_hist: Optional[float],
) -> bool:
    if macd_hist is not None and macd_hist < 0:
        return True
    if macd_line is not None and macd_signal is not None and macd_line < macd_signal:
        return True
    return False


def _finalize_swing_result(
    result: TpSlResult,
    *,
    cur_prc: float,
    trailing_pct: float,
    trailing_basis: str,
    macd_line: Optional[float] = None,
    macd_signal: Optional[float] = None,
    macd_hist: Optional[float] = None,
) -> TpSlResult:
    result.strategy_version = TP_SL_STRATEGY_VERSION
    result.trailing_pct = trailing_pct
    risk = max(cur_prc - result.sl_price, 1)
    result.trailing_activation = int(cur_prc + risk)
    result.trailing_basis = trailing_basis

    min_tp1 = int(cur_prc * 1.03)
    if result.tp1_price <= min_tp1:
        result.tp1_price = min_tp1
        result.tp_method = f"{result.tp_method}+min_3pct" if result.tp_method else "min_3pct"

    if result.tp2_price is not None and result.tp2_price <= result.tp1_price:
        result.tp2_price = int(result.tp1_price * 1.04)

    if _is_macd_weakening(macd_line, macd_signal, macd_hist):
        result.trailing_pct = max(0.8, trailing_pct - 0.4)
        if result.tp2_price is not None:
            tightened_tp2 = max(int(result.tp1_price * 1.02), int((result.tp1_price + result.tp2_price) / 2))
            result.tp2_price = max(tightened_tp2, result.tp1_price + 1)
        elif result.tp1_price > cur_prc:
            result.tp1_price = max(int(cur_prc * 1.03), int((result.tp1_price + cur_prc) / 2))
        result.tp_method = f"{result.tp_method}+macd_guard" if result.tp_method else "macd_guard"

    return result


# ──────────────────────────────────────────────────────────────
# 메인 함수: 통합 TP/SL 계산
# ──────────────────────────────────────────────────────────────

def calc_tp_sl(
    strategy:    str,
    cur_prc:     float,
    highs:       list[float],
    lows:        list[float],
    closes:      list[float],
    stk_cd:      str            = "",
    atr:         Optional[float] = None,
    ma5:         Optional[float] = None,
    ma20:        Optional[float] = None,
    ma60:        Optional[float] = None,
    ma120:       Optional[float] = None,
    bb_upper:    Optional[float] = None,
    bb_lower:    Optional[float] = None,
    macd_line:   Optional[float] = None,
    macd_signal: Optional[float] = None,
    macd_hist:   Optional[float] = None,
    min_rr:      float           = MIN_RR_RATIO,
    # ── 전략별 구조적 가격 (추가) ──────────────────────────────
    prev_close:  Optional[float] = None,   # S1: 전일 종가 (갭 베이스)
    vi_price:    Optional[float] = None,   # S2: VI 발동가 (TP 목표)
    candle_low:  Optional[float] = None,   # S4: 장대양봉 저점 (SL 기준)
    candle_high: Optional[float] = None,   # S4: 장대양봉 고점 (TP 기준)
) -> TpSlResult:
    """
    전략별 동적 TP/SL 계산 통합 진입점.

    모든 데이터는 최신순 (index 0 = 가장 최근).
    추가 API 호출 없이 이미 fetch된 일봉/분봉 데이터 재사용.

    Args:
        strategy:  전략 식별자 ("S8_GOLDEN_CROSS" 등)
        cur_prc:   현재가 (진입 기준가)
        highs:     고가 리스트 (최신순)
        lows:      저가 리스트 (최신순)
        closes:    종가 리스트 (최신순)
        stk_cd:    종목코드 (슬리피지 구분용)
        atr:       14봉 ATR 절대값 (원), 없으면 None
        ma5/20/60/120: 이동평균 (없으면 None)
        bb_upper/lower: 볼린저 밴드 상·하단
        min_rr:    최소 R:R (기본 1.3)

    Returns:
        TpSlResult
    """
    slip = _slip_fee(stk_cd)

    # 전략별 디스패치 (번호 오름차순)
    s = strategy.upper()
    min_rr = _resolve_strategy_min_rr(s, min_rr)

    def finalize(result: TpSlResult) -> TpSlResult:
        result = _consolidate_single_tp(result, strategy=s, cur_prc=cur_prc, slip=slip, min_rr=min_rr)
        result = _attach_time_stop_policy(strategy, result)
        return _apply_policy_metadata(strategy, result, cur_prc=cur_prc, min_rr=min_rr)

    # ── 데이트레이딩 (S1/S2/S4) ───────────────────────────────
    if "S1_" in s or "GAP_OPEN" in s:
        return finalize(_tp_sl_gap_open(cur_prc, highs, prev_close, atr, slip, min_rr))

    if "S2_" in s or "VI_PULLBACK" in s:
        return finalize(_tp_sl_vi_pullback(cur_prc, highs, vi_price, atr, slip, min_rr))

    if "S3_" in s or "INST_FRGN" in s:
        _ma20 = ma20 or (sum(closes[:20]) / 20 if len(closes) >= 20 else None)
        return finalize(_tp_sl_inst_frgn(cur_prc, highs, lows, closes, _ma20, atr, slip, min_rr))

    if "S4_" in s or "BIG_CANDLE" in s:
        return finalize(_tp_sl_big_candle(cur_prc, candle_low, candle_high, atr, slip, min_rr))

    if "S5_" in s or "PROG_FRGN" in s:
        _ma20 = ma20 or (sum(closes[:20]) / 20 if len(closes) >= 20 else None)
        return finalize(_tp_sl_program_buy(cur_prc, highs, lows, closes, _ma20, atr, slip, min_rr))

    if "S6_" in s or "THEME" in s:
        _ma5 = ma5 or (sum(closes[:5]) / 5 if len(closes) >= 5 else None)
        return finalize(_tp_sl_theme(cur_prc, highs, lows, closes, _ma5, atr, slip, min_rr))

    # S7은 더 이상 장전/데이트레이딩 전략이 아니라 일목 스윙으로 고정한다.
    if "S7_" in s:
        return finalize(_tp_sl_ichimoku_breakout(
            cur_prc, highs, lows, closes, atr, slip, min_rr,
            macd_line=macd_line, macd_signal=macd_signal, macd_hist=macd_hist,
        ))

    # ── 스윙 (S8~S15) ─────────────────────────────────────────
    if "S8_" in s or "GOLDEN" in s:
        return finalize(_tp_sl_golden_cross(cur_prc, highs, lows, closes,
                                            ma5, ma20, ma60, atr, bb_upper, slip, min_rr,
                                            macd_line=macd_line, macd_signal=macd_signal, macd_hist=macd_hist))
    if "S9_" in s or "PULLBACK_SWING" in s:
        return finalize(_tp_sl_pullback(cur_prc, highs, lows, closes,
                                        ma5, ma20, ma60, atr, slip, min_rr,
                                        macd_line=macd_line, macd_signal=macd_signal, macd_hist=macd_hist))
    if "S10_" in s or "NEW_HIGH" in s:
        return finalize(_tp_sl_new_high(cur_prc, highs, lows, closes,
                                        ma20, atr, slip, min_rr,
                                        macd_line=macd_line, macd_signal=macd_signal, macd_hist=macd_hist))
    if "S11_" in s or "FRGN_CONT" in s:
        return finalize(_tp_sl_frgn_cont(cur_prc, highs, lows, closes,
                                         ma20, bb_upper, slip, min_rr,
                                         macd_line=macd_line, macd_signal=macd_signal, macd_hist=macd_hist))
    if "S12_" in s or "CLOSING" in s:
        return finalize(_tp_sl_closing(cur_prc, highs, lows, closes,
                                       ma5, ma20, atr, slip, min_rr,
                                       macd_line=macd_line, macd_signal=macd_signal, macd_hist=macd_hist))
    if "S13_" in s or "BOX" in s:
        return finalize(_tp_sl_box_breakout(cur_prc, highs, lows, closes,
                                            atr, slip, min_rr,
                                            macd_line=macd_line, macd_signal=macd_signal, macd_hist=macd_hist))
    if "S14_" in s or "OVERSOLD" in s:
        _ma20 = ma20 or (sum(closes[:20]) / 20 if len(closes) >= 20 else None)
        _ma60 = ma60 or (sum(closes[:60]) / 60 if len(closes) >= 60 else None)
        return finalize(_tp_sl_oversold(cur_prc, highs, lows, _ma20, _ma60, atr, slip, min_rr,
                                        macd_line=macd_line, macd_signal=macd_signal, macd_hist=macd_hist))
    if "S15_" in s or "MOMENTUM" in s:
        return finalize(_tp_sl_momentum_align(cur_prc, highs, lows, closes,
                                              ma20, atr, bb_upper, slip, min_rr,
                                              macd_line=macd_line, macd_signal=macd_signal, macd_hist=macd_hist))

    # 알 수 없는 전략 — ATR 폴백 또는 기본값
    logger.warning("[TP/SL] 알 수 없는 전략: %s → ATR 폴백", strategy)
    return finalize(_tp_sl_atr_fallback(cur_prc, atr, slip, min_rr))


# ──────────────────────────────────────────────────────────────
# 전략별 TP/SL 구현
# ──────────────────────────────────────────────────────────────

# ── S1: 갭 상승 개장 ──────────────────────────────────────────

def _tp_sl_gap_open(
    cur_prc:    float,
    highs:      list[float],
    prev_close: Optional[float],
    atr:        Optional[float],
    slip:       float,
    min_rr:     float,
) -> TpSlResult:
    """
    S1 갭 상승 개장 TP/SL  (당일 단타, 시초가 진입)

    갭 상승 = 전일 종가 대비 갭. 진입 근거 = 갭 유지.
    SL: 전일 종가 × 0.995  — 갭 필(gap fill) = 갭 진입 근거 완전 무효
        → 없으면 ATR_5min × 1.5 (타이트)
    TP: ATR_5min × 3.0    — 갭 모멘텀 추종 (당일 2~4시간 목표)
        → 없으면 +4% 고정

    근거: 갭 상승 후 갭 필은 당일 추가 상승 기대 소멸 신호.
    갭 베이스(전일 종가) 이탈 즉시 청산이 데이트레이더 원칙.
    """
    stop_dist = _bounded_distance(cur_prc, min_pct=0.012, max_pct=0.018, atr=atr, atr_mult=0.9)
    sl_price = int(cur_prc - stop_dist)
    sl_method = "intraday_invalidation(cap_1.8%)"
    if prev_close and 0 < prev_close < cur_prc:
        prev_close_stop = int(prev_close * 0.999)
        if prev_close_stop < cur_prc and (cur_prc - prev_close_stop) / cur_prc * 100 <= 2.2:
            sl_price = max(sl_price, prev_close_stop)
            sl_method = f"gap_support(prev_close)={int(prev_close)}"

    sl_price = max(sl_price, 1)
    if sl_price >= cur_prc:
        sl_price  = int(cur_prc * 0.982)
        sl_method = "intraday_hard_cap_1.8%"
    resistance_tp = _nearest_resistance(highs, cur_prc, lookback=15, min_pct=0.008)
    if resistance_tp:
        tp1_price = resistance_tp
        tp_method = "first_resistance_intraday"
    else:
        target_dist = _bounded_distance(cur_prc, min_pct=0.025, max_pct=0.045, atr=atr, atr_mult=2.0)
        tp1_price = int(cur_prc + target_dist)
        tp_method = "intraday_gap_target(2.5~4.5%)"

    rr_ratio, skip = _calc_rr(cur_prc, tp1_price, sl_price, slip, min_rr)
    return TpSlResult(sl_price=sl_price, tp1_price=tp1_price,
                      sl_method=sl_method, tp_method=tp_method,
                      rr_ratio=rr_ratio, skip_entry=skip)


# ── S2: VI 눌림목 반등 ────────────────────────────────────────

def _tp_sl_vi_pullback(
    cur_prc:  float,
    highs:    list[float],
    vi_price: Optional[float],
    atr:      Optional[float],
    slip:     float,
    min_rr:   float,
) -> TpSlResult:
    """
    S2 VI 눌림목 반등 TP/SL  (당일 단타)

    VI 발동 → -1~3% 눌림목 진입 → VI 레벨 재탈환 목표.
    SL: ATR_5min × 1.0  — 눌림목 저점 이탈 (타이트, VI 반등 실패 즉시 청산)
        → 없으면 -2% 고정
    TP: VI 발동가 × 1.005 — VI 레벨 재도달 + 0.5% 버퍼 (눌림목 반등 목표)
        → 없으면 ATR × 2.0

    근거: VI 발동 = 단기 급등. 눌림목 = 조정 후 재상승 기대.
    TP = VI 발동가 재탈환 (심리적 저항선 돌파 목표).
    SL = 눌림목 저점 이탈 = 반등 실패 확인 (빠른 손절 필수).
    """
    stop_dist = _bounded_distance(cur_prc, min_pct=0.01, max_pct=0.015, atr=atr, atr_mult=0.75)
    sl_price = int(cur_prc - stop_dist)
    sl_method = "vi_reclaim_stop(1.0~1.5%)"

    sl_price = max(sl_price, 1)
    if sl_price >= cur_prc:
        sl_price  = int(cur_prc * 0.985)
        sl_method = "vi_reclaim_cap_1.5%"

    resistance_tp = _nearest_resistance(highs, cur_prc, lookback=12, min_pct=0.005)
    if vi_price and vi_price > cur_prc:
        tp1_price = int(min(max(vi_price * 1.002, cur_prc * 1.02), cur_prc * 1.035))
        tp_method = f"vi_reclaim_target={int(vi_price)}"
    elif resistance_tp:
        tp1_price = resistance_tp
        tp_method = "first_resistance_vi"
    elif atr:
        tp1_price = int(cur_prc + _bounded_distance(cur_prc, min_pct=0.02, max_pct=0.035, atr=atr, atr_mult=1.5))
        tp_method = "vi_rebound_target(2.0~3.5%)"
    else:
        tp1_price = int(cur_prc * 1.025)
        tp_method = "pct_2.5%_fallback"

    rr_ratio, skip = _calc_rr(cur_prc, tp1_price, sl_price, slip, min_rr)
    return TpSlResult(sl_price=sl_price, tp1_price=tp1_price,
                      sl_method=sl_method, tp_method=tp_method,
                      rr_ratio=rr_ratio, skip_entry=skip)


# ── S3: 기관+외인 동시 매수 ──────────────────────────────────

def _tp_sl_inst_frgn(
    cur_prc: float,
    highs:   list[float],
    lows:    list[float],
    closes:  list[float],
    ma20:    Optional[float],
    atr:     Optional[float],
    slip:    float,
    min_rr:  float,
) -> TpSlResult:
    """
    S3 기관+외인 동시 매수 TP/SL  (2~3거래일 스윙)

    기관/외인 동시 수급 = 중단기 추세 형성 신호.
    SL: MA20 × 0.99 → swing_low_D15 → ATR × 1.5
    TP: swing_high(40봉) vs fib_1272 중 더 원거리 → ATR × 4.0
    """
    if ma20 and ma20 > 0 and ma20 < cur_prc:
        sl_price  = int(ma20 * 0.99)
        sl_method = "MA20(×0.99)"
    else:
        swing_lows = find_swing_lows(lows, cur_prc, lookback=15)
        if swing_lows and swing_lows[0] > cur_prc * 0.90:
            sl_price  = int(swing_lows[0] * 0.99)
            sl_method = "swing_low_D15(×0.99)"
        elif atr:
            sl_price  = int(cur_prc - atr * 1.5)
            sl_method = "ATR×1.5"
        else:
            sl_price  = int(cur_prc * 0.95)
            sl_method = "pct_5%_fallback"

    sl_price = max(sl_price, 1)
    if sl_price >= cur_prc:
        sl_price  = int(cur_prc * 0.95)
        sl_method = "pct_5%_fallback"

    recent_low = min(lows[1:21]) if len(lows) >= 2 else 0.0
    fib_base   = recent_low if recent_low > 0 else sl_price
    _, fib_1272, fib_1618 = calc_fibonacci_extension(fib_base, cur_prc)

    tp2_price   = None
    swing_highs = find_swing_highs(highs, cur_prc, lookback=40)
    swing_tp    = int(swing_highs[0]) if swing_highs else 0
    fib_tp      = int(fib_1272)       if fib_1272 > cur_prc * 1.03 else 0

    if swing_tp >= fib_tp and swing_tp > cur_prc * 1.03:
        tp1_price = swing_tp
        tp2_price = int(swing_highs[1]) if len(swing_highs) > 1 else int(fib_1618)
        tp_method = "swing_resistance(D40)"
    elif fib_tp > 0:
        tp1_price = fib_tp
        tp2_price = swing_tp if swing_tp > fib_tp else int(fib_1618)
        tp_method = "fib_1272(inst_frgn_swing)"
    elif atr:
        tp1_price = int(cur_prc + atr * 4.0)
        tp_method = "ATR×4.0"
    else:
        tp1_price = int(cur_prc * 1.08)
        tp_method = "pct_8%_fallback"

    rr_ratio, skip = _calc_rr(cur_prc, tp1_price, sl_price, slip, min_rr)
    return TpSlResult(sl_price=sl_price, tp1_price=tp1_price, tp2_price=tp2_price,
                      sl_method=sl_method, tp_method=tp_method,
                      rr_ratio=rr_ratio, skip_entry=skip)


# ── S4: 장대양봉 ──────────────────────────────────────────────

def _tp_sl_big_candle(
    cur_prc:     float,
    candle_low:  Optional[float],
    candle_high: Optional[float],
    atr:         Optional[float],
    slip:        float,
    min_rr:      float,
) -> TpSlResult:
    """
    S4 장대양봉 TP/SL  (당일 단타, 5분봉 기준)

    장대양봉 = 강한 추세봉. 봉 구조(저점/고점) = SL/TP 기준.
    SL: 장대양봉 저점 × 0.995  — 봉 저점 이탈 = 추세봉 패턴 무효화
        → 없으면 ATR_5min × 1.5
    TP: 장대양봉 고점 + ATR × 1.5  — 돌파 모멘텀 연속 목표
        → 고점만 있으면: 고점 × 1.02
        → 없으면 ATR × 2.5

    근거: 장대양봉의 저점 = 당일 강력 지지선 (세력 매수 단가 근방).
    TP = 고점 돌파 후 추가 상승 (모멘텀 연속성).
    """
    if candle_low and 0 < candle_low < cur_prc and (cur_prc - candle_low) / cur_prc * 100 <= 2.5:
        sl_price  = int(max(candle_low * 0.999, cur_prc * 0.98))
        sl_method = f"candle_low_follow_through={int(candle_low)}"
    else:
        stop_dist = _bounded_distance(cur_prc, min_pct=0.015, max_pct=0.02, atr=atr, atr_mult=1.0)
        sl_price  = int(cur_prc - stop_dist)
        sl_method = "big_candle_cap(1.5~2.0%)"

    sl_price = max(sl_price, 1)
    if sl_price >= cur_prc:
        sl_price  = int(cur_prc * 0.98)
        sl_method = "big_candle_cap_2.0%"
    if candle_high and candle_high > cur_prc and candle_low and candle_high > candle_low:
        candle_range = candle_high - candle_low
        tp1_price = int(max(candle_high + candle_range * 0.8, cur_prc * 1.035))
        tp1_price = min(tp1_price, int(cur_prc * 1.055))
        tp_method = f"measured_move_0.8x={int(candle_high)}"
    elif candle_high and candle_high > cur_prc:
        tp1_price = int(min(max(candle_high * 1.01, cur_prc * 1.035), cur_prc * 1.055))
        tp_method = f"candle_high_follow_through={int(candle_high)}"
    elif atr:
        tp1_price = int(cur_prc + _bounded_distance(cur_prc, min_pct=0.035, max_pct=0.055, atr=atr, atr_mult=2.0))
        tp_method = "big_candle_target(3.5~5.5%)"
    else:
        tp1_price = int(cur_prc * 1.04)
        tp_method = "pct_4%_fallback"

    rr_ratio, skip = _calc_rr(cur_prc, tp1_price, sl_price, slip, min_rr)
    return TpSlResult(sl_price=sl_price, tp1_price=tp1_price,
                      sl_method=sl_method, tp_method=tp_method,
                      rr_ratio=rr_ratio, skip_entry=skip)


# ── S5: 프로그램+외인 수급 ────────────────────────────────────

def _tp_sl_program_buy(
    cur_prc: float,
    highs:   list[float],
    lows:    list[float],
    closes:  list[float],
    ma20:    Optional[float],
    atr:     Optional[float],
    slip:    float,
    min_rr:  float,
) -> TpSlResult:
    """
    S5 프로그램+외인 수급 TP/SL  (2~3거래일 스윙)

    프로그램 순매수 + 외인 동반 = 기관성 수급 이벤트 → 단기 스윙.
    SL: MA20 × 0.99 → swing_low_D10 → ATR × 1.5
    TP: swing_high(40봉) → ATR × 3.0
    """
    if ma20 and ma20 > 0 and ma20 < cur_prc:
        sl_price  = int(ma20 * 0.99)
        sl_method = "MA20(×0.99)"
    else:
        swing_lows = find_swing_lows(lows, cur_prc, lookback=10)
        if swing_lows and swing_lows[0] > cur_prc * 0.92:
            sl_price  = int(swing_lows[0] * 0.99)
            sl_method = "swing_low_D10(×0.99)"
        elif atr:
            sl_price  = int(cur_prc - atr * 1.5)
            sl_method = "ATR×1.5"
        else:
            sl_price  = int(cur_prc * 0.95)
            sl_method = "pct_5%_fallback"

    sl_price = max(sl_price, 1)
    if sl_price >= cur_prc:
        sl_price  = int(cur_prc * 0.95)
        sl_method = "pct_5%_fallback"

    swing_highs = find_swing_highs(highs, cur_prc, lookback=40)
    tp2_price   = None
    if swing_highs and swing_highs[0] > cur_prc * 1.03:
        tp1_price = int(swing_highs[0])
        tp2_price = int(swing_highs[1]) if len(swing_highs) > 1 else None
        tp_method = "swing_resistance(D40)"
    elif atr:
        tp1_price = int(cur_prc + atr * 3.0)
        tp_method = "ATR×3.0"
    else:
        tp1_price = int(cur_prc * 1.06)
        tp_method = "pct_6%_fallback"

    rr_ratio, skip = _calc_rr(cur_prc, tp1_price, sl_price, slip, min_rr)
    return TpSlResult(sl_price=sl_price, tp1_price=tp1_price, tp2_price=tp2_price,
                      sl_method=sl_method, tp_method=tp_method,
                      rr_ratio=rr_ratio, skip_entry=skip)


# ── S6: 테마 후발주 ───────────────────────────────────────────

def _tp_sl_theme(
    cur_prc: float,
    highs:   list[float],
    lows:    list[float],
    closes:  list[float],
    ma5:     Optional[float],
    atr:     Optional[float],
    slip:    float,
    min_rr:  float,
) -> TpSlResult:
    """
    S6 테마 후발주 TP/SL  (당일~2거래일 단기)

    테마 과열 위험 → 타이트 손절, 빠른 익절.
    SL: MA5 × 0.99 → swing_low_D5 → ATR × 1.2 (타이트)
    TP: swing_high(20봉) → ATR × 2.5

    근거: 테마는 빠르게 식음. MA5 이탈 = 단기 모멘텀 소멸.
    TP = 가장 가까운 저항 (다음 저항에서 익절, 욕심 금지).
    """
    if ma5 and ma5 > 0 and ma5 < cur_prc and (cur_prc - ma5) / cur_prc * 100 <= 2.5:
        sl_price  = int(ma5 * 0.995)
        sl_method = "MA5_theme_support"
    else:
        stop_dist = _bounded_distance(cur_prc, min_pct=0.02, max_pct=0.025, atr=atr, atr_mult=1.2)
        sl_price  = int(cur_prc - stop_dist)
        sl_method = "theme_laggard_cap(2.0~2.5%)"

    sl_price = max(sl_price, 1)
    if sl_price >= cur_prc:
        sl_price  = int(cur_prc * 0.975)
        sl_method = "theme_laggard_cap_2.5%"

    resistance_tp = _nearest_resistance(highs, cur_prc, lookback=20, min_pct=0.015)
    tp2_price   = None
    if resistance_tp:
        tp1_price = min(resistance_tp, int(cur_prc * 1.06))
        tp_method = "theme_first_resistance"
    elif atr:
        tp1_price = int(cur_prc + _bounded_distance(cur_prc, min_pct=0.04, max_pct=0.06, atr=atr, atr_mult=2.5))
        tp_method = "theme_laggard_target(4.0~6.0%)"
    else:
        tp1_price = int(cur_prc * 1.045)
        tp_method = "pct_4.5%_fallback"

    rr_ratio, skip = _calc_rr(cur_prc, tp1_price, sl_price, slip, min_rr)
    return TpSlResult(sl_price=sl_price, tp1_price=tp1_price, tp2_price=tp2_price,
                      sl_method=sl_method, tp_method=tp_method,
                      rr_ratio=rr_ratio, skip_entry=skip)


# ── S7: 일목균형표 구름대 돌파 스윙 ───────────────────────────

def _tp_sl_ichimoku_breakout(
    cur_prc: float,
    highs:   list[float],
    lows:    list[float],
    closes:  list[float],
    atr:     Optional[float],
    slip:    float,
    min_rr:  float,
    macd_line: Optional[float] = None,
    macd_signal: Optional[float] = None,
    macd_hist: Optional[float] = None,
) -> TpSlResult:
    """
    S7 일목균형표 구름대 돌파 TP/SL  (3~7거래일 스윙)

    진입 근거: 기준선(Kijun/26) 지지 위 돌파 확인.
    SL = max(swing_low_D20 × 0.998, cur_prc - ATR × 1.5)
         → 기준선 하락 이탈 = 구름대 돌파 가설 무효화
    TP1 = 가장 가까운 스윙 고점 (30봉 저항)
    TP2 = Fibonacci 1.272 확장 (swing_low ~ tp1)
    """
    # ── SL: 스윙 저점 vs ATR×1.5 중 더 높은 값 ─────────────────
    swing_lows = find_swing_lows(lows, cur_prc, lookback=20)
    if swing_lows and swing_lows[0] > cur_prc * 0.88:
        sl_swing  = int(swing_lows[0] * 0.998)
        swing_ref = swing_lows[0]
        sl_method = "swing_low_D20(×0.998)"
    else:
        sl_swing  = 0
        swing_ref = lows[1] if len(lows) > 1 else cur_prc * 0.95
        sl_method = ""

    if atr:
        sl_atr = int(cur_prc - atr * 1.5)
        if sl_swing > 0:
            sl_price  = max(sl_swing, sl_atr)
            sl_method = "swing_low_D20_or_ATR×1.5"
        else:
            sl_price  = sl_atr
            sl_method = "ATR×1.5"
    else:
        sl_price = sl_swing if sl_swing > 0 else int(cur_prc * 0.95)
        if not sl_method:
            sl_method = "pct_5%_fallback"

    sl_price = max(sl_price, 1)
    if sl_price >= cur_prc:
        sl_price  = int(cur_prc * 0.95)
        sl_method = "pct_5%_fallback"

    # ── TP1: 가장 가까운 스윙 고점 저항 (30봉) ──────────────────
    swing_highs = find_swing_highs(highs, cur_prc, lookback=30)
    tp2_price   = None

    if swing_highs and swing_highs[0] > cur_prc * 1.03:
        tp1_price = int(swing_highs[0])
        # TP2: Fibonacci 1.272 (swing_low ~ tp1 레인지 기준)
        fib_base = swing_ref if swing_ref < cur_prc else sl_price
        _, fib_1272, _ = calc_fibonacci_extension(fib_base, tp1_price)
        tp2_price = int(fib_1272) if fib_1272 > tp1_price else (
            int(swing_highs[1]) if len(swing_highs) > 1 else None
        )
        tp_method = "swing_resistance(D30)"
    else:
        # 스윙 고점 없음 → Fibonacci 확장
        fib_base = swing_ref if swing_ref < cur_prc else sl_price
        _, fib_1272, fib_1618 = calc_fibonacci_extension(fib_base, cur_prc)
        tp1_price = int(fib_1272) if fib_1272 > cur_prc * 1.03 else int(cur_prc * 1.08)
        tp2_price = int(fib_1618) if fib_1618 > tp1_price else int(cur_prc * 1.15)
        tp_method = "fib_1272(ichimoku_swing)"

    rr_ratio, skip = _calc_rr(cur_prc, tp1_price, sl_price, slip, min_rr)
    return _finalize_swing_result(
        TpSlResult(sl_price=sl_price, tp1_price=tp1_price, tp2_price=tp2_price,
                   sl_method=sl_method, tp_method=tp_method,
                   rr_ratio=rr_ratio, skip_entry=skip),
        cur_prc=cur_prc,
        trailing_pct=2.5,
        trailing_basis="tp1_or_kijun",
        macd_line=macd_line,
        macd_signal=macd_signal,
        macd_hist=macd_hist,
    )


# ── S8: 골든크로스 ────────────────────────────────────────────

def _tp_sl_golden_cross(
    cur_prc:  float,
    highs:    list[float],
    lows:     list[float],
    closes:   list[float],
    ma5:      Optional[float],
    ma20:     Optional[float],
    ma60:     Optional[float],
    atr:      Optional[float],
    bb_upper: Optional[float],
    slip:     float,
    min_rr:   float,
    macd_line: Optional[float] = None,
    macd_signal: Optional[float] = None,
    macd_hist: Optional[float] = None,
) -> TpSlResult:
    """
    S8 골든크로스 TP/SL

    SL 우선순위:
      1. MA20 × 0.99 (크로스 무효화 = MA20 이탈)
      2. ATR × 2.0 아래
      3. 최근 스윙 저점

    TP 우선순위:
      1. 최근 스윙 고점 (가장 가까운 저항)
      2. 볼린저 상단
      3. ATR × 3.0
    """
    # ── SL 설정 ───────────────────────────────────────────────
    if ma20 and ma20 > 0:
        sl_price = int(ma20 * 0.99)
        sl_method = "MA20_support(×0.99)"
    elif atr:
        sl_price = int(cur_prc - atr * 2.0)
        sl_method = "ATR×2.0"
    else:
        swing_lows = find_swing_lows(lows, cur_prc, lookback=20)
        sl_price  = int(swing_lows[0] * 0.995) if swing_lows else int(cur_prc * 0.95)
        sl_method = "swing_low_D20" if swing_lows else "pct_5%"

    sl_price = max(sl_price, 1)
    if sl_price >= cur_prc:   # 이상값 방어
        sl_price = int(cur_prc * 0.95)
        sl_method = "pct_5%_fallback"

    # ── TP 설정 ───────────────────────────────────────────────
    swing_highs = find_swing_highs(highs, cur_prc, lookback=40)
    tp2_price   = None
    if swing_highs:
        tp1_price = int(swing_highs[0])
        tp2_price = int(swing_highs[1]) if len(swing_highs) > 1 else None
        tp_method = "swing_resistance"
    elif bb_upper and bb_upper > cur_prc:
        tp1_price = int(bb_upper)
        tp_method = "bollinger_upper"
    elif atr:
        tp1_price = int(cur_prc + atr * 3.0)
        tp_method = "ATR×3.0"
    else:
        tp1_price = int(cur_prc * 1.10)
        tp_method = "pct_10%_fallback"

    rr_ratio, skip = _calc_rr(cur_prc, tp1_price, sl_price, slip, min_rr)
    return _finalize_swing_result(
        TpSlResult(sl_price=sl_price, tp1_price=tp1_price, tp2_price=tp2_price,
                   sl_method=sl_method, tp_method=tp_method,
                   rr_ratio=rr_ratio, skip_entry=skip),
        cur_prc=cur_prc,
        trailing_pct=2.5,
        trailing_basis="tp1_hit",
        macd_line=macd_line,
        macd_signal=macd_signal,
        macd_hist=macd_hist,
    )


def _tp_sl_pullback(
    cur_prc: float,
    highs:   list[float],
    lows:    list[float],
    closes:  list[float],
    ma5:     Optional[float],
    ma20:    Optional[float],
    ma60:    Optional[float],
    atr:     Optional[float],
    slip:    float,
    min_rr:  float,
    macd_line: Optional[float] = None,
    macd_signal: Optional[float] = None,
    macd_hist: Optional[float] = None,
) -> TpSlResult:
    """
    S9 눌림목 반등 TP/SL

    SL: 최근 15봉 내 스윙 저점 (1% 버퍼)
        → 없으면 MA20 × 0.99 (추세 이탈 확인)
    TP: 최근 40봉 스윙 고점 (이전 피크 = 자연 저항)
        → 없으면 MA60 × 1.05, 없으면 ATR×2.5
    """
    # ── SL ───────────────────────────────────────────────────
    swing_lows = find_swing_lows(lows, cur_prc, lookback=15)
    if swing_lows:
        sl_price  = int(swing_lows[0] * 0.99)   # 1% 버퍼
        sl_method = "swing_low_D15(×0.99)"
    elif ma20 and ma20 > 0:
        sl_price  = int(ma20 * 0.99)
        sl_method = "MA20_support(×0.99)"
    elif atr:
        sl_price  = int(cur_prc - atr * 2.0)
        sl_method = "ATR×2.0"
    else:
        sl_price  = int(cur_prc * 0.96)
        sl_method = "pct_4%_fallback"

    sl_price = max(sl_price, 1)
    if sl_price >= cur_prc:
        sl_price  = int(cur_prc * 0.96)
        sl_method = "pct_4%_fallback"

    # ── TP ───────────────────────────────────────────────────
    swing_highs = find_swing_highs(highs, cur_prc, lookback=40)
    tp2_price   = None
    if swing_highs:
        tp1_price = int(swing_highs[0])
        tp2_price = int(swing_highs[1]) if len(swing_highs) > 1 else None
        tp_method = "prev_swing_high"
    elif ma60 and ma60 > cur_prc:
        tp1_price = int(ma60 * 1.05)
        tp_method = "MA60×1.05"
    elif atr:
        tp1_price = int(cur_prc + atr * 2.5)
        tp_method = "ATR×2.5"
    else:
        tp1_price = int(cur_prc * 1.06)
        tp_method = "pct_6%_fallback"

    rr_ratio, skip = _calc_rr(cur_prc, tp1_price, sl_price, slip, min_rr)
    return _finalize_swing_result(
        TpSlResult(sl_price=sl_price, tp1_price=tp1_price, tp2_price=tp2_price,
                   sl_method=sl_method, tp_method=tp_method,
                   rr_ratio=rr_ratio, skip_entry=skip),
        cur_prc=cur_prc,
        trailing_pct=2.5,
        trailing_basis="tp1_hit",
        macd_line=macd_line,
        macd_signal=macd_signal,
        macd_hist=macd_hist,
    )


def _tp_sl_box_breakout(
    cur_prc: float,
    highs:   list[float],
    lows:    list[float],
    closes:  list[float],
    atr:     Optional[float],
    slip:    float,
    min_rr:  float,
    macd_line: Optional[float] = None,
    macd_signal: Optional[float] = None,
    macd_hist: Optional[float] = None,
) -> TpSlResult:
    """
    S13 박스권 돌파 TP/SL

    SL: 박스 상단(돌파 레벨) × 0.99
        → 박스 복귀 = 돌파 실패 확인
    TP: 피보나치 확장
        TP1 = box_high + box_range × 0.618  (Fib 1.618)
        TP2 = box_high + box_range × 1.0    (100% 확장)

    박스 범위: 최근 2~16봉 (오늘 제외)
    """
    BOX_PERIOD = 15
    # 박스 최고가/최저가 계산 (오늘 봉 제외 = index 1~BOX_PERIOD)
    past_highs = highs[1: BOX_PERIOD + 1]
    past_lows  = lows[1:  BOX_PERIOD + 1]

    if not past_highs:
        return _tp_sl_atr_fallback(cur_prc, atr, slip, min_rr)

    box_high  = max(past_highs)
    box_low   = min(past_lows)
    box_range = max(box_high - box_low, 1.0)

    # SL: 박스 상단 아래로 회귀 = 진입 무효
    sl_price  = int(box_high * 0.99)
    sl_method = f"box_top(×0.99)={int(box_high)}"
    sl_price  = max(sl_price, 1)

    if sl_price >= cur_prc:
        # 이미 박스 상단보다 많이 올라온 경우 → ATR 폴백
        if atr:
            sl_price  = int(cur_prc - atr * 1.5)
            sl_method = "ATR×1.5(box_already_cleared)"
        else:
            sl_price  = int(cur_prc * 0.95)
            sl_method = "pct_5%_fallback"

    # TP: 피보나치 확장
    _, tp_1272, tp_1618 = calc_fibonacci_extension(box_low, box_high)
    tp1_price = int(tp_1272)
    tp2_price = int(tp_1618)
    tp_method = f"fib_1272={tp1_price}/fib_1618={tp2_price}"

    # TP1이 cur_prc 아래면 더 먼 목표로 대체
    if tp1_price <= cur_prc:
        tp1_price = int(cur_prc * 1.08)
        tp2_price = int(cur_prc * 1.15)
        tp_method = "pct_8%_15%_fallback"

    rr_ratio, skip = _calc_rr(cur_prc, tp1_price, sl_price, slip, min_rr)
    return _finalize_swing_result(
        TpSlResult(sl_price=sl_price, tp1_price=tp1_price, tp2_price=tp2_price,
                   sl_method=sl_method, tp_method=tp_method,
                   rr_ratio=rr_ratio, skip_entry=skip),
        cur_prc=cur_prc,
        trailing_pct=2.0,
        trailing_basis="tp1_hit",
        macd_line=macd_line,
        macd_signal=macd_signal,
        macd_hist=macd_hist,
    )


def _tp_sl_momentum_align(
    cur_prc:  float,
    highs:    list[float],
    lows:     list[float],
    closes:   list[float],
    ma20:     Optional[float],
    atr:      Optional[float],
    bb_upper: Optional[float],
    slip:     float,
    min_rr:   float,
    macd_line: Optional[float] = None,
    macd_signal: Optional[float] = None,
    macd_hist: Optional[float] = None,
) -> TpSlResult:
    """
    S15 모멘텀 정렬 TP/SL  (5~10거래일 스윙)

    진입 근거: 현재가 ≥ MA20 (필수 조건)
    → MA20 이탈 = 진입 근거 무효화 = SL 기준선

    SL 우선순위 (구조적 지지 기반, ATR 배수 의존 제거):
      1. 최근 15봉 스윙 저점 × 0.99  — 가장 가까운 기술적 지지 이탈
      2. MA20 × 0.99                  — 모멘텀 정렬 가설 무효화 (MA20이 2~6% 아래인 경우)
      3. ATR × 1.5                    — 데이터 부족 시 마지막 폴백 (×2.0 제거)

    TP 우선순위 (스윙 목표 = 구조적 저항 또는 피보나치 확장):
      1. 최근 60봉 스윙 고점이 fib_1272 이상 → 스윙 고점 (신뢰도 높은 저항)
      2. 피보나치 1.272 확장 (최근 20봉 저점~현재가 레인지 기준)
      3. 볼린저 상단 (단, cur_prc × 1.05 이상일 때만)
      4. ATR × 5.0                    — 5~10거래일 스윙 목표 상한 폴백

    TP 최소 거리 보장: 3% 미만이면 fib_1272 또는 ATR×4.0으로 강제 교체.
    볼린저 상단은 단독 TP1으로 사용 금지 (너무 근접 — 스윙 목표 미달).
    """
    # ── SL: 구조적 지지 기반 ─────────────────────────────────
    swing_lows = find_swing_lows(lows, cur_prc, lookback=15)
    if swing_lows and swing_lows[0] > cur_prc * 0.87:   # 13% 이내 지지만 유효
        sl_price  = int(swing_lows[0] * 0.99)
        sl_method = "swing_low_D15(×0.99)"
    elif ma20 and ma20 > 0:
        sl_price  = int(ma20 * 0.99)
        sl_method = "MA20_support(×0.99)"
    elif atr:
        sl_price  = int(cur_prc - atr * 1.5)            # ×2.0 → ×1.5 (타이트)
        sl_method = "ATR×1.5"
    else:
        sl_price  = int(cur_prc * 0.95)
        sl_method = "pct_5%_fallback"

    sl_price = max(sl_price, 1)
    if sl_price >= cur_prc:
        sl_price  = int(cur_prc * 0.95)
        sl_method = "pct_5%_fallback"

    # ── 피보나치 기준 레인지 (최근 20봉 저점 ~ 현재가) ────────
    recent_low = min(lows[1:21]) if len(lows) >= 2 else 0.0
    fib_base   = recent_low if recent_low > 0 else sl_price
    _, fib_1272, fib_1618 = calc_fibonacci_extension(fib_base, cur_prc)

    # ── TP: 스윙 고점 vs 피보나치 — 더 원거리 구조적 저항 선택 ─
    tp2_price   = None
    swing_highs = find_swing_highs(highs, cur_prc, lookback=60)   # lookback 40→60

    swing_tp = int(swing_highs[0]) if swing_highs else 0
    fib_tp   = int(fib_1272)       if fib_1272 > cur_prc else 0

    if swing_tp >= fib_tp and swing_tp > cur_prc * 1.03:
        # 스윙 고점이 피보나치 이상이고 3% 넘으면 스윙 고점 우선 (신뢰도↑)
        tp1_price = swing_tp
        tp2_price = int(swing_highs[1]) if len(swing_highs) > 1 else (
            int(fib_1618) if fib_1618 > swing_tp else None
        )
        tp_method = "swing_resistance(D60)"
    elif fib_tp > cur_prc * 1.03:
        # 피보나치가 3% 이상 → 스윙 목표 기준 피보나치
        tp1_price = fib_tp
        # TP2: 스윙 고점이 fib_1272보다 멀면 사용, 없으면 fib_1618
        if swing_tp > fib_tp:
            tp2_price = swing_tp
        else:
            tp2_price = int(fib_1618) if fib_1618 > fib_tp else None
        tp_method = "fib_1272(swing_momentum)"
    elif bb_upper and bb_upper > cur_prc * 1.05:
        # 볼린저 상단이 5% 이상 → 차선책 (3~4% 이내는 제외)
        tp1_price = int(bb_upper)
        tp_method = "bollinger_upper(≥5%)"
        further   = find_swing_highs(highs, bb_upper, lookback=40)
        if further:
            tp2_price = int(further[0])
        elif fib_1618 > bb_upper:
            tp2_price = int(fib_1618)
    elif atr:
        tp1_price = int(cur_prc + atr * 5.0)   # 5~10거래일 스윙 목표
        tp_method = "ATR×5.0(swing_5to10d)"
    else:
        tp1_price = int(cur_prc * 1.12)
        tp_method = "pct_12%_fallback"

    # ── TP 최소 거리 보장: 3% 미만이면 fib_1272 / ATR×4 강제 ──
    if tp1_price < cur_prc * 1.03:
        if fib_tp > cur_prc * 1.03:
            tp1_price = fib_tp
            tp_method += "+fib_min3pct"
        elif atr:
            tp1_price = int(cur_prc + atr * 4.0)
            tp_method += "+ATR×4_min3pct"
        else:
            tp1_price = int(cur_prc * 1.10)
            tp_method += "+pct_10%_min"

    rr_ratio, skip = _calc_rr(cur_prc, tp1_price, sl_price, slip, min_rr)
    return _finalize_swing_result(
        TpSlResult(sl_price=sl_price, tp1_price=tp1_price, tp2_price=tp2_price,
                   sl_method=sl_method, tp_method=tp_method,
                   rr_ratio=rr_ratio, skip_entry=skip),
        cur_prc=cur_prc,
        trailing_pct=2.5,
        trailing_basis="tp1_hit",
        macd_line=macd_line,
        macd_signal=macd_signal,
        macd_hist=macd_hist,
    )


def _tp_sl_new_high(
    cur_prc: float,
    highs:   list[float],
    lows:    list[float],
    closes:  list[float],
    ma20:    Optional[float],
    atr:     Optional[float],
    slip:    float,
    min_rr:  float,
    macd_line: Optional[float] = None,
    macd_signal: Optional[float] = None,
    macd_hist: Optional[float] = None,
) -> TpSlResult:
    """
    S10 신고가 돌파 TP/SL

    신고가 돌파는 과거 저항이 없으므로 피보나치 확장 사용.
    SL: 52주 고점(= 돌파 직전 기록) × 0.98 (고점 이탈 = 돌파 실패)
        → 없으면 ATR × 2.0
    TP: 피보나치 1.272 (보수적), 1.618 (공격적)
        기준 레인지: 최근 저점(MA20 근방)~현재가
    """
    # 돌파 직전 고점 = index 1~60 중 최대 (오늘 제외)
    prev_high = max(highs[1:61]) if len(highs) >= 2 else 0.0

    # SL: 돌파 기준 레벨 이탈
    if prev_high > 0 and prev_high < cur_prc:
        sl_price  = int(prev_high * 0.98)
        sl_method = f"breakout_level(×0.98)={int(prev_high)}"
    elif atr:
        sl_price  = int(cur_prc - atr * 2.0)
        sl_method = "ATR×2.0"
    else:
        sl_price  = int(cur_prc * 0.94)
        sl_method = "pct_6%_fallback"

    if sl_price <= 0 or sl_price >= cur_prc:
        sl_price  = int(cur_prc * 0.94)
        sl_method = "pct_6%_fallback"

    # TP: 피보나치 확장 (레인지 기준 = MA20~현재가 or 최근 저점~현재가)
    recent_low = min(lows[1:21]) if len(lows) >= 2 else 0.0
    fib_base   = recent_low if recent_low > 0 else sl_price
    _, tp_1272, tp_1618 = calc_fibonacci_extension(fib_base, cur_prc)

    tp1_price = int(tp_1272)
    tp2_price = int(tp_1618)
    tp_method = f"fib_1272={tp1_price}/fib_1618={tp2_price}"

    if tp1_price <= cur_prc:
        tp1_price = int(cur_prc * 1.08)
        tp2_price = int(cur_prc * 1.15)
        tp_method = "pct_8%_15%_fallback"

    rr_ratio, skip = _calc_rr(cur_prc, tp1_price, sl_price, slip, min_rr)
    return _finalize_swing_result(
        TpSlResult(sl_price=sl_price, tp1_price=tp1_price, tp2_price=tp2_price,
                   sl_method=sl_method, tp_method=tp_method,
                   rr_ratio=rr_ratio, skip_entry=skip),
        cur_prc=cur_prc,
        trailing_pct=2.0,
        trailing_basis="tp1_hit",
        macd_line=macd_line,
        macd_signal=macd_signal,
        macd_hist=macd_hist,
    )


def _tp_sl_frgn_cont(
    cur_prc:  float,
    highs:    list[float],
    lows:     list[float],
    closes:   list[float],
    ma20:     Optional[float],
    bb_upper: Optional[float],
    slip:     float,
    min_rr:   float,
    macd_line: Optional[float] = None,
    macd_signal: Optional[float] = None,
    macd_hist: Optional[float] = None,
) -> TpSlResult:
    """
    S11 외인 지속 매수 TP/SL

    외인 수급 지속 = 트렌드 팔로잉 전략 → 추세 이탈이 SL 기준.
    SL: MA20 이탈 확인 (단, MA20이 6% 이상 아래에 있으면 swing_low 우선 — 과대 손절 방지)
    TP: 볼린저 상단 또는 스윙 고점
    """
    if ma20 and ma20 > 0:
        ma20_gap = (cur_prc - ma20) / cur_prc
        if ma20_gap > 0.06:
            # MA20이 6% 이상 아래 → swing_low가 더 가까운 기술적 지지
            swing_lows = find_swing_lows(lows, cur_prc, lookback=15)
            if swing_lows and swing_lows[0] > cur_prc * 0.88:
                sl_price  = int(swing_lows[0] * 0.99)
                sl_method = "swing_low_D15(MA20_gap>6%)"
            else:
                sl_price  = int(cur_prc * 0.94)
                sl_method = "pct_6%_cap(MA20_gap>6%)"
        else:
            sl_price  = int(ma20 * 0.98)
            sl_method = "MA20(×0.98)"
    else:
        swing_lows = find_swing_lows(lows, cur_prc, lookback=20)
        sl_price   = int(swing_lows[0] * 0.99) if swing_lows else int(cur_prc * 0.95)
        sl_method  = "swing_low_D20" if swing_lows else "pct_5%_fallback"

    sl_price = max(sl_price, 1)
    if sl_price >= cur_prc:
        sl_price  = int(cur_prc * 0.95)
        sl_method = "pct_5%_fallback"

    tp2_price = None
    if bb_upper and bb_upper > cur_prc:
        tp1_price = int(bb_upper)
        tp_method = "bollinger_upper"
    else:
        swing_highs = find_swing_highs(highs, cur_prc, lookback=40)
        if swing_highs:
            tp1_price = int(swing_highs[0])
            tp2_price = int(swing_highs[1]) if len(swing_highs) > 1 else None
            tp_method = "swing_resistance"
        else:
            tp1_price = int(cur_prc * 1.08)
            tp_method = "pct_8%_fallback"

    rr_ratio, skip = _calc_rr(cur_prc, tp1_price, sl_price, slip, min_rr)
    return _finalize_swing_result(
        TpSlResult(sl_price=sl_price, tp1_price=tp1_price, tp2_price=tp2_price,
                   sl_method=sl_method, tp_method=tp_method,
                   rr_ratio=rr_ratio, skip_entry=skip),
        cur_prc=cur_prc,
        trailing_pct=2.5,
        trailing_basis="tp1_hit",
        macd_line=macd_line,
        macd_signal=macd_signal,
        macd_hist=macd_hist,
    )


def _tp_sl_closing(
    cur_prc: float,
    highs:   list[float],
    lows:    list[float],
    closes:  list[float],
    ma5:     Optional[float],
    ma20:    Optional[float],
    atr:     Optional[float],
    slip:    float,
    min_rr:  float,
    macd_line: Optional[float] = None,
    macd_signal: Optional[float] = None,
    macd_hist: Optional[float] = None,
) -> TpSlResult:
    """
    S12 종가 강도 TP/SL  (2~5거래일 스윙)

    종가매매 진입 후 2~5거래일 보유. 기관 수급 동반 급등 종목.

    SL 우선순위 (급등일 과대 손절 방지 — today_low 단독 사용 폐기):
      1. 최근 5봉 스윙 저점 × 0.99   — 단기 구조적 지지 이탈 (가장 신뢰)
      2. MA5 × 0.99                   — 단기 추세 이탈 확인
      3. 당일 저점 × 0.995 with -6% 캡 — 급등일 과대 손절 방지 (캡 중요)
      4. MA20 × 0.99                  — 중기 추세 이탈

    TP 우선순위 (lookback 20 → 40 확장, 3% 미만 스윙 고점 보완):
      1. 최근 40봉 스윙 고점          — 직전 저항 (3% 이상일 때만)
         단, 3% 미만 → fib_1272 우선
      2. 피보나치 1.272 확장          — 최근 10봉 저점~현재가 기준
      3. ATR × 3.0                    — 2~5거래일 수익 목표 폴백
    """
    # ── SL: 구조적 지지 + 급등일 캡 ─────────────────────────
    swing_lows = find_swing_lows(lows, cur_prc, lookback=5)
    if swing_lows and swing_lows[0] > cur_prc * 0.92:   # 8% 이내 지지
        sl_price  = int(swing_lows[0] * 0.99)
        sl_method = "swing_low_D5(×0.99)"
    elif ma5 and ma5 > 0 and ma5 < cur_prc:
        sl_price  = int(ma5 * 0.99)
        sl_method = "MA5(×0.99)"
    else:
        today_low = lows[0] if lows else 0.0
        if today_low > 0 and today_low < cur_prc:
            raw_sl   = int(today_low * 0.995)
            cap_sl   = int(cur_prc * 0.94)              # -6% 캡: 급등일 과대 손절 방지
            sl_price  = max(raw_sl, cap_sl)
            sl_method = f"today_low_cap6%(×0.995,cap=-6%)"
        elif ma20 and ma20 > 0:
            sl_price  = int(ma20 * 0.99)
            sl_method = "MA20(×0.99)"
        else:
            sl_price  = int(cur_prc * 0.97)
            sl_method = "pct_3%_fallback"

    sl_price = max(sl_price, 1)
    if sl_price >= cur_prc:
        sl_price  = int(cur_prc * 0.97)
        sl_method = "pct_3%_fallback"

    # ── 피보나치 기준 레인지 (최근 10봉 저점 ~ 현재가) ────────
    recent_low = min(lows[1:11]) if len(lows) >= 2 else 0.0
    fib_base   = recent_low if recent_low > 0 else sl_price
    _, fib_1272, fib_1618 = calc_fibonacci_extension(fib_base, cur_prc)

    # ── TP: lookback 40 확장 + 3% 미만 스윙 고점 보완 ─────────
    swing_highs = find_swing_highs(highs, cur_prc, lookback=40)   # 20 → 40
    tp2_price   = None

    if swing_highs:
        first_swing = swing_highs[0]
        if (first_swing - cur_prc) / cur_prc >= 0.03:
            # 스윙 고점이 3% 이상 → 직접 사용 (신뢰도 높은 저항)
            tp1_price = int(first_swing)
            tp2_price = int(swing_highs[1]) if len(swing_highs) > 1 else None
            tp_method = "prev_swing_high(D40)"
        else:
            # 스윙 고점이 너무 가까움 → 피보나치로 보완
            tp1_price = int(max(fib_1272, first_swing))
            tp2_price = int(fib_1618) if fib_1618 > tp1_price else (
                int(swing_highs[1]) if len(swing_highs) > 1 else None
            )
            tp_method = "fib_1272(swing_too_close<3%)"
    elif fib_1272 > cur_prc * 1.03:
        tp1_price = int(fib_1272)
        tp2_price = int(fib_1618)
        tp_method = "fib_1272"
    elif atr:
        tp1_price = int(cur_prc + atr * 3.0)
        tp2_price = int(cur_prc + atr * 5.0)
        tp_method = "ATR×3.0"
    else:
        tp1_price = int(cur_prc * 1.05)
        tp_method = "pct_5%_fallback"

    rr_ratio, skip = _calc_rr(cur_prc, tp1_price, sl_price, slip, min_rr)
    return _finalize_swing_result(
        TpSlResult(sl_price=sl_price, tp1_price=tp1_price, tp2_price=tp2_price,
                   sl_method=sl_method, tp_method=tp_method,
                   rr_ratio=rr_ratio, skip_entry=skip),
        cur_prc=cur_prc,
        trailing_pct=1.5,
        trailing_basis="tp1_hit",
        macd_line=macd_line,
        macd_signal=macd_signal,
        macd_hist=macd_hist,
    )


def _tp_sl_oversold(
    cur_prc: float,
    highs:   list[float],
    lows:    list[float],
    ma20:    Optional[float],
    ma60:    Optional[float],
    atr:     Optional[float],
    slip:    float,
    min_rr:  float,
    macd_line: Optional[float] = None,
    macd_signal: Optional[float] = None,
    macd_hist: Optional[float] = None,
) -> TpSlResult:
    """
    S14 과매도 반등 TP/SL  (3~5거래일 반등)

    RSI/Stochastic 과매도 후 반등 전략.
    SL = 반등 실패 확인 = 최근 저점 재이탈
    TP = 반등 목표 = MA60 저항 또는 스윙 고점

    SL 우선순위:
      1. 최근 10봉 스윙 저점 × 0.99  — 과매도 저점 이탈 확인
      2. MA20 × 0.99                  — 추세 지지
      3. ATR × 1.5                    — 데이터 부족 폴백 (×2.0 폐기)

    TP 우선순위:
      1. 최근 40봉 스윙 고점          — 과매도 반등의 자연 목표 저항
      2. MA60                         — 중기 이동평균 저항 (과매도 복귀 목표)
      3. ATR × 3.5                    — 변동성 기반 목표
    """
    # ── SL: 과매도 저점 구조 기반 ─────────────────────────────
    swing_lows = find_swing_lows(lows, cur_prc, lookback=10)
    if swing_lows and swing_lows[0] > cur_prc * 0.90:   # 10% 이내 지지
        sl_price  = int(swing_lows[0] * 0.99)
        sl_method = "swing_low_D10(×0.99)"
    elif ma20 and ma20 > 0 and ma20 < cur_prc:
        sl_price  = int(ma20 * 0.99)
        sl_method = "MA20(×0.99)"
    elif atr:
        sl_price  = int(cur_prc - atr * 1.5)            # ×2.0 → ×1.5
        sl_method = "ATR×1.5"
    else:
        sl_price  = int(cur_prc * 0.95)
        sl_method = "pct_5%_fallback"

    sl_price = max(sl_price, 1)
    if sl_price >= cur_prc:
        sl_price  = int(cur_prc * 0.95)
        sl_method = "pct_5%_fallback"

    # ── TP: 반등 목표 저항 ──────────────────────────────────
    tp2_price   = None
    swing_highs = find_swing_highs(highs, cur_prc, lookback=40)
    if swing_highs:
        tp1_price = int(swing_highs[0])
        tp2_price = int(swing_highs[1]) if len(swing_highs) > 1 else None
        tp_method = "swing_resistance(D40)"
    elif ma60 and ma60 > cur_prc:
        tp1_price = int(ma60)
        tp_method = "MA60_resistance"
    elif atr:
        tp1_price = int(cur_prc + atr * 3.5)
        tp_method = "ATR×3.5"
    else:
        tp1_price = int(cur_prc * 1.08)
        tp_method = "pct_8%_fallback"

    sl_price  = max(sl_price, 1)
    rr_ratio, skip = _calc_rr(cur_prc, tp1_price, sl_price, slip, min_rr)
    return _finalize_swing_result(
        TpSlResult(sl_price=sl_price, tp1_price=tp1_price, tp2_price=tp2_price,
                   sl_method=sl_method, tp_method=tp_method,
                   rr_ratio=rr_ratio, skip_entry=skip),
        cur_prc=cur_prc,
        trailing_pct=1.5,
        trailing_basis="tp1_hit",
        macd_line=macd_line,
        macd_signal=macd_signal,
        macd_hist=macd_hist,
    )


def _tp_sl_day_trading(
    cur_prc: float,
    atr:     Optional[float],   # 5분봉 ATR (get_atr_minute 결과)
    slip:    float,
    min_rr:  float,
) -> TpSlResult:
    """
    데이트레이딩 TP/SL (S1/S2/S4)

    5분봉 ATR 기반 당일 변동성 활용.
    스윙 전략보다 배수를 작게 설정하여 당일 청산 목표에 맞춤:
      SL = cur_prc - ATR_5min × 1.5  (짧은 호흡)
      TP = cur_prc + ATR_5min × 2.5  (최소 R:R ≈ 1.67)
    """
    if atr:
        sl_price  = int(cur_prc - atr * 1.5)
        tp1_price = int(cur_prc + atr * 2.5)
        sl_method = "ATR_5min×1.5"
        tp_method = "ATR_5min×2.5"
    else:
        sl_price  = int(cur_prc * 0.98)
        tp1_price = int(cur_prc * 1.04)
        sl_method = "pct_2%_fallback"
        tp_method = "pct_4%_fallback"

    sl_price = max(sl_price, 1)
    if sl_price >= cur_prc:
        sl_price  = int(cur_prc * 0.98)
        sl_method = "pct_2%_fallback"

    rr_ratio, skip = _calc_rr(cur_prc, tp1_price, sl_price, slip, min_rr)
    return TpSlResult(sl_price=sl_price, tp1_price=tp1_price,
                      sl_method=sl_method, tp_method=tp_method,
                      rr_ratio=rr_ratio, skip_entry=skip)


def _tp_sl_atr_fallback(
    cur_prc: float,
    atr:     Optional[float],
    slip:    float,
    min_rr:  float,
) -> TpSlResult:
    """ATR 기반 범용 폴백 TP/SL"""
    if atr:
        sl_price  = int(cur_prc - atr * 2.0)
        tp1_price = int(cur_prc + atr * 3.0)
        sl_method = "ATR×2.0(fallback)"
        tp_method = "ATR×3.0(fallback)"
    else:
        sl_price  = int(cur_prc * 0.95)
        tp1_price = int(cur_prc * 1.08)
        sl_method = "pct_5%_fallback"
        tp_method = "pct_8%_fallback"

    sl_price  = max(sl_price, 1)
    rr_ratio, skip = _calc_rr(cur_prc, tp1_price, sl_price, slip, min_rr)
    return TpSlResult(sl_price=sl_price, tp1_price=tp1_price,
                      sl_method=sl_method, tp_method=tp_method,
                      rr_ratio=rr_ratio, skip_entry=skip)
