"""
tests/test_scorer_edge_cases.py
scorer.py 의 경계값, 조합, 이상값 처리 테스트.
최소 60개 테스트.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math
import pytest
from scorer import rule_score, _safe_float, should_skip_ai, get_claude_threshold


# ──────────────────────────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────────────────────────

def _ctx(strength=120.0, flu_rt=3.0, bid=2000.0, ask=1000.0):
    return {
        "tick": {"flu_rt": str(flu_rt)},
        "hoga": {
            "total_buy_bid_req": str(bid),
            "total_sel_bid_req": str(ask),
        },
        "strength": strength,
        "vi": {},
    }


def _sig(strategy, **kwargs):
    base = {"strategy": strategy, "stk_cd": "005930", "stk_nm": "삼성전자"}
    base.update(kwargs)
    return base


# ──────────────────────────────────────────────────────────────────
# _safe_float 경계값 및 이상값 테스트
# ──────────────────────────────────────────────────────────────────

class TestSafeFloatEdgeCases:
    def test_empty_string_returns_default(self):
        assert _safe_float("", 0.0) == 0.0

    def test_whitespace_string_returns_default(self):
        assert _safe_float("   ", 0.0) == 0.0

    def test_very_large_number(self):
        result = _safe_float("999999999999.99")
        assert result == pytest.approx(999999999999.99)

    def test_negative_string(self):
        assert _safe_float("-5.0") == -5.0

    def test_negative_with_comma(self):
        assert _safe_float("-1,234.5") == -1234.5

    def test_plus_sign_stripped(self):
        assert _safe_float("+100.0") == 100.0

    def test_list_returns_default(self):
        assert _safe_float([1, 2, 3], -1.0) == -1.0

    def test_dict_returns_default(self):
        assert _safe_float({"a": 1}, -1.0) == -1.0

    def test_bool_true_returns_default(self):
        # str(True) = "True" → ValueError → default 0.0
        assert _safe_float(True) == 0.0

    def test_bool_false_returns_default(self):
        # str(False) = "False" → ValueError → default 0.0
        assert _safe_float(False) == 0.0

    def test_integer_input(self):
        assert _safe_float(42) == 42.0

    def test_zero_integer(self):
        assert _safe_float(0) == 0.0


# ──────────────────────────────────────────────────────────────────
# S1 갭 구간 정확한 경계값 테스트
# ──────────────────────────────────────────────────────────────────

class TestS1GapBoundaries:
    """갭 구간: [3,5) = 20점, [5,8) = 15점, [8,15) = 10점, 15이상 = -10점"""

    def test_gap_exactly_3_gets_20_points(self):
        """갭 정확히 3.0% → 20점"""
        sig = _sig("S1_GAP_OPEN", gap_pct=3.0)
        ctx = _ctx(strength=100, flu_rt=3.0, bid=500, ask=1000)  # bid_ratio=0.5 → 0점
        score, _ = rule_score(sig, ctx)
        assert score == 20.0

    def test_gap_just_below_5_gets_20_points(self):
        """갭 4.99% → 20점 (5% 미만)"""
        sig = _sig("S1_GAP_OPEN", gap_pct=4.99)
        ctx = _ctx(strength=100, flu_rt=4.99, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score == 20.0

    def test_gap_exactly_5_gets_15_points(self):
        """갭 정확히 5.0% → 15점"""
        sig = _sig("S1_GAP_OPEN", gap_pct=5.0)
        ctx = _ctx(strength=100, flu_rt=5.0, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score == 15.0

    def test_gap_just_below_8_gets_15_points(self):
        """갭 7.99% → 15점"""
        sig = _sig("S1_GAP_OPEN", gap_pct=7.99)
        ctx = _ctx(strength=100, flu_rt=7.99, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score == 15.0

    def test_gap_exactly_8_gets_10_points(self):
        """갭 정확히 8.0% → 10점"""
        sig = _sig("S1_GAP_OPEN", gap_pct=8.0)
        ctx = _ctx(strength=100, flu_rt=8.0, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score == 10.0

    def test_gap_just_below_15_gets_10_points(self):
        """갭 14.99% → 10점"""
        sig = _sig("S1_GAP_OPEN", gap_pct=14.99)
        ctx = _ctx(strength=100, flu_rt=5.0, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score == 10.0

    def test_gap_exactly_15_gets_minus_10(self):
        """갭 정확히 15% → -10점 (과열)"""
        sig = _sig("S1_GAP_OPEN", gap_pct=15.0)
        ctx = _ctx(strength=100, flu_rt=5.0, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score == 0.0  # -10점이지만 min(0) 클리핑

    def test_gap_above_15_with_strength_still_clamped(self):
        """갭 20%, 체결강도 강해도 과열 페널티로 스코어 제한"""
        sig = _sig("S1_GAP_OPEN", gap_pct=20.0)
        ctx = _ctx(strength=100, flu_rt=5.0, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        # -10 (갭) + 0 (strength 100) + 0 (bid_ratio 0.5) = -10 → 클리핑 → 0
        assert score == 0.0


# ──────────────────────────────────────────────────────────────────
# S1 체결강도 경계값 테스트
# ──────────────────────────────────────────────────────────────────

class TestS1StrengthBoundaries:
    """체결강도: >150=30점, >130=20점, >110=10점, ≤110=0점"""

    def test_strength_150_exactly_gets_20(self):
        """체결강도 정확히 150 → >130 구간 → 20점"""
        sig = _sig("S1_GAP_OPEN", gap_pct=0)
        ctx = _ctx(strength=150.0, flu_rt=0.5, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        # gap=0 → 0점 (0<3), strength=150 → 20점, bid_ratio=0.5 → 0점 = 20
        assert score == 20.0

    def test_strength_151_gets_30(self):
        """체결강도 151 → >150 구간 → 30점"""
        sig = _sig("S1_GAP_OPEN", gap_pct=0)
        ctx = _ctx(strength=151.0, flu_rt=0.5, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score == 30.0

    def test_strength_130_exactly_gets_10(self):
        """체결강도 130 → >110 구간 → 10점"""
        sig = _sig("S1_GAP_OPEN", gap_pct=0)
        ctx = _ctx(strength=130.0, flu_rt=0.5, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score == 10.0

    def test_strength_131_gets_20(self):
        """체결강도 131 → >130 구간 → 20점"""
        sig = _sig("S1_GAP_OPEN", gap_pct=0)
        ctx = _ctx(strength=131.0, flu_rt=0.5, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score == 20.0

    def test_strength_110_gets_0(self):
        """체결강도 110 → ≤110 → 0점"""
        sig = _sig("S1_GAP_OPEN", gap_pct=0)
        ctx = _ctx(strength=110.0, flu_rt=0.5, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score == 0.0

    def test_strength_111_gets_10(self):
        """체결강도 111 → >110 → 10점"""
        sig = _sig("S1_GAP_OPEN", gap_pct=0)
        ctx = _ctx(strength=111.0, flu_rt=0.5, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score == 10.0


# ──────────────────────────────────────────────────────────────────
# 공통 flu_rt 패널티 경계값
# ──────────────────────────────────────────────────────────────────

class TestFluRtPenaltyBoundaries:
    """flu_rt > 15% → -20점 패널티 / 10~15% → -10점 / < -5% → -15점"""

    def test_flu_rt_15_no_penalty(self):
        """flu_rt = 15.0 (경계) → 패널티 없음 (>15만 패널티)"""
        sig = _sig("S1_GAP_OPEN", gap_pct=4.0)
        ctx = _ctx(strength=160, flu_rt=15.0, bid=4000, ask=1000)
        score_15, _ = rule_score(sig, ctx)
        # flu_rt > 15만 패널티이므로 15.0은 패널티 없음
        ctx2 = _ctx(strength=160, flu_rt=15.1, bid=4000, ask=1000)
        score_151, _ = rule_score(sig, ctx2)
        assert score_15 > score_151  # 15.0 > 15.1

    def test_flu_rt_exactly_15_1_gets_penalty(self):
        """flu_rt = 15.1 → -20점 패널티"""
        sig = _sig("S1_GAP_OPEN", gap_pct=4.0)
        ctx = _ctx(strength=100, flu_rt=15.1, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        # gap=4% → +20, flu_rt>15 → -20, net = 0
        assert score == 0.0

    def test_flu_rt_10_no_penalty(self):
        """flu_rt = 10.0 → 패널티 없음 (>10만 패널티)"""
        sig = _sig("S1_GAP_OPEN", gap_pct=4.0)
        ctx_10 = _ctx(strength=100, flu_rt=10.0, bid=500, ask=1000)
        ctx_10_1 = _ctx(strength=100, flu_rt=10.1, bid=500, ask=1000)
        score_10, _ = rule_score(sig, ctx_10)
        score_10_1, _ = rule_score(sig, ctx_10_1)
        assert score_10 > score_10_1  # 10.0에는 패널티 없음

    def test_flu_rt_10_1_gets_minus_10(self):
        """flu_rt = 10.1 → -10점 패널티"""
        sig = _sig("S1_GAP_OPEN", gap_pct=4.0)
        ctx = _ctx(strength=100, flu_rt=10.1, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        # gap=4% → +20, flu_rt=10.1 → -10, net = 10
        assert score == 10.0

    def test_flu_rt_minus5_no_penalty(self):
        """flu_rt = -5.0 → 패널티 없음 (< -5만 패널티)"""
        sig = _sig("S1_GAP_OPEN", gap_pct=4.0)
        ctx_m5 = _ctx(strength=100, flu_rt=-5.0, bid=500, ask=1000)
        ctx_m5_1 = _ctx(strength=100, flu_rt=-5.1, bid=500, ask=1000)
        score_m5, _ = rule_score(sig, ctx_m5)
        score_m5_1, _ = rule_score(sig, ctx_m5_1)
        assert score_m5 > score_m5_1

    def test_flu_rt_minus6_gets_minus_15(self):
        """flu_rt = -6.0 → -15점 패널티"""
        sig = _sig("S1_GAP_OPEN", gap_pct=4.0)
        ctx = _ctx(strength=100, flu_rt=-6.0, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        # gap=4% → +20, flu_rt < -5 → -15, net = 5
        assert score == 5.0


# ──────────────────────────────────────────────────────────────────
# S2 VI 눌림목 경계값
# ──────────────────────────────────────────────────────────────────

class TestS2Boundaries:
    """pullback: [1,2) = 30점, [2,3) = 20점, 그 외 = 0점"""

    def test_pullback_1_exactly_gets_30(self):
        sig = _sig("S2_VI_PULLBACK", pullback_pct=-1.0)
        ctx = _ctx(strength=100, flu_rt=1.0, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        # pullback=1.0 → abs=1.0 → [1,2) → 30점
        assert score == 30.0

    def test_pullback_just_below_2_gets_30(self):
        sig = _sig("S2_VI_PULLBACK", pullback_pct=-1.99)
        ctx = _ctx(strength=100, flu_rt=1.0, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score == 30.0

    def test_pullback_exactly_2_gets_20(self):
        sig = _sig("S2_VI_PULLBACK", pullback_pct=-2.0)
        ctx = _ctx(strength=100, flu_rt=1.0, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score == 20.0

    def test_pullback_just_below_3_gets_20(self):
        sig = _sig("S2_VI_PULLBACK", pullback_pct=-2.99)
        ctx = _ctx(strength=100, flu_rt=1.0, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score == 20.0

    def test_pullback_exactly_3_gets_0(self):
        sig = _sig("S2_VI_PULLBACK", pullback_pct=-3.0)
        ctx = _ctx(strength=100, flu_rt=1.0, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score == 0.0

    def test_is_dynamic_true_adds_15(self):
        """is_dynamic=True → +15점"""
        sig = _sig("S2_VI_PULLBACK", pullback_pct=-1.5, is_dynamic=True)
        ctx = _ctx(strength=100, flu_rt=1.0, bid=500, ask=1000)
        score_dyn, _ = rule_score(sig, ctx)
        sig2 = _sig("S2_VI_PULLBACK", pullback_pct=-1.5, is_dynamic=False)
        score_static, _ = rule_score(sig2, ctx)
        assert score_dyn - score_static == 15.0

    def test_is_dynamic_1_treated_as_true(self):
        """is_dynamic=1 (int) → True로 처리"""
        sig = _sig("S2_VI_PULLBACK", pullback_pct=-1.5, is_dynamic=1)
        ctx = _ctx(strength=100, flu_rt=1.0, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        # pullback=1.5 → 30점, is_dynamic=1 (bool(1)=True) → +15점
        assert score == 45.0

    def test_is_dynamic_0_treated_as_false(self):
        """is_dynamic=0 (int) → False로 처리"""
        sig = _sig("S2_VI_PULLBACK", pullback_pct=-1.5, is_dynamic=0)
        ctx = _ctx(strength=100, flu_rt=1.0, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score == 30.0


# ──────────────────────────────────────────────────────────────────
# S3 기관/외인 경계값
# ──────────────────────────────────────────────────────────────────

class TestS3Boundaries:
    """cont_days: ≥5=30, ≥3=20, ≥1=10, 0=0 / vol_ratio: ≥3=25, ≥2=20, ≥1.5=10"""

    def test_cont_days_5_gets_30(self):
        sig = _sig("S3_INST_FRGN", net_buy_amt=0, continuous_days=5, vol_ratio=0)
        ctx = _ctx(strength=100, flu_rt=1.0, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score == 30.0

    def test_cont_days_4_gets_20(self):
        sig = _sig("S3_INST_FRGN", net_buy_amt=0, continuous_days=4, vol_ratio=0)
        ctx = _ctx(strength=100, flu_rt=1.0, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score == 20.0

    def test_cont_days_3_gets_20(self):
        sig = _sig("S3_INST_FRGN", net_buy_amt=0, continuous_days=3, vol_ratio=0)
        ctx = _ctx(strength=100, flu_rt=1.0, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score == 20.0

    def test_cont_days_2_gets_10(self):
        sig = _sig("S3_INST_FRGN", net_buy_amt=0, continuous_days=2, vol_ratio=0)
        ctx = _ctx(strength=100, flu_rt=1.0, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score == 10.0

    def test_cont_days_0_gets_0(self):
        sig = _sig("S3_INST_FRGN", net_buy_amt=0, continuous_days=0, vol_ratio=0)
        ctx = _ctx(strength=100, flu_rt=1.0, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score == 0.0

    def test_vol_ratio_3_gets_25(self):
        sig = _sig("S3_INST_FRGN", net_buy_amt=0, continuous_days=0, vol_ratio=3.0)
        ctx = _ctx(strength=100, flu_rt=1.0, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score == 25.0

    def test_vol_ratio_2_gets_20(self):
        sig = _sig("S3_INST_FRGN", net_buy_amt=0, continuous_days=0, vol_ratio=2.0)
        ctx = _ctx(strength=100, flu_rt=1.0, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score == 20.0

    def test_vol_ratio_1_5_gets_10(self):
        sig = _sig("S3_INST_FRGN", net_buy_amt=0, continuous_days=0, vol_ratio=1.5)
        ctx = _ctx(strength=100, flu_rt=1.0, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score == 10.0

    def test_vol_ratio_1_gets_0(self):
        sig = _sig("S3_INST_FRGN", net_buy_amt=0, continuous_days=0, vol_ratio=1.0)
        ctx = _ctx(strength=100, flu_rt=1.0, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score == 0.0

    def test_net_buy_amt_capped_at_25(self):
        """net_buy_amt 점수 최대 25점 제한"""
        # 500억 이상이면 25점 초과지만 min(25, ...)으로 제한
        sig = _sig("S3_INST_FRGN", net_buy_amt=1_000_000_000_000, continuous_days=0, vol_ratio=0)
        ctx = _ctx(strength=100, flu_rt=1.0, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score == 25.0


# ──────────────────────────────────────────────────────────────────
# S7 호가비율 경계값
# ──────────────────────────────────────────────────────────────────

class TestS7Boundaries:
    """호가비율: >3=30점, >2=25점, >1.5=10점"""

    def test_bid_ratio_3_gets_25(self):
        """bid_ratio=3.0 → >2 구간 → 25점"""
        sig = _sig("S7_AUCTION", gap_pct=3.0, vol_rank=5)
        ctx = _ctx(strength=100, flu_rt=3.0, bid=3000, ask=1000)
        score, _ = rule_score(sig, ctx)
        # gap=3% → +25, bid_ratio=3.0 → >2 → 25점
        assert score >= 50  # 최소 25+25=50점

    def test_bid_ratio_just_above_3_gets_30(self):
        """bid_ratio=3.01 → >3 구간 → 30점"""
        sig = _sig("S7_AUCTION", gap_pct=3.0, vol_rank=5)
        ctx = _ctx(strength=100, flu_rt=3.0, bid=3010, ask=1000)
        score, _ = rule_score(sig, ctx)
        # gap=3% → +25, bid_ratio>3 → 30점, vol_rank≤10 → 20점 = 75점
        assert score >= 75


# ──────────────────────────────────────────────────────────────────
# 빈/None 입력 처리
# ──────────────────────────────────────────────────────────────────

class TestEmptyAndNullInputs:
    def test_empty_signal_returns_0(self):
        """빈 딕셔너리 신호 → 0점"""
        score, _ = rule_score({}, _ctx())
        assert score == 0.0

    def test_empty_market_ctx_returns_positive(self):
        """빈 market_ctx → 기본값으로 계산"""
        sig = _sig("S1_GAP_OPEN", gap_pct=4.0)
        score, _ = rule_score(sig, {})
        # ctx 없으면: strength=100, bid=0, ask=0 기본값
        assert isinstance(score, float)
        assert 0 <= score <= 100

    def test_none_gap_pct_treated_as_zero(self):
        """gap_pct=None → 0으로 처리 → 0점"""
        sig = _sig("S1_GAP_OPEN", gap_pct=None)
        score, _ = rule_score(sig, _ctx(flu_rt=1.0))
        # gap=0 < 3 → 0점 (과열아님, flu_rt=1.0 패널티없음)
        # strength=120 → 10점, bid_ratio=2.0 → 20점
        assert score >= 0

    def test_unknown_strategy_returns_0(self):
        """알 수 없는 전략 → 0점"""
        sig = _sig("UNKNOWN_STRATEGY")
        score, _ = rule_score(sig, _ctx())
        # 공통 패널티만 적용 (flu_rt=3.0 → 패널티 없음)
        assert score == 0.0

    def test_missing_stk_cd_still_scores(self):
        """stk_cd 누락 → 스코어링은 가능"""
        sig = {"strategy": "S1_GAP_OPEN", "gap_pct": 4.0}
        score, _ = rule_score(sig, _ctx(flu_rt=1.0))
        assert isinstance(score, float)


# ──────────────────────────────────────────────────────────────────
# 스코어 클리핑 테스트 (0~100)
# ──────────────────────────────────────────────────────────────────

class TestScoreClipping:
    def test_score_never_below_0(self):
        """페널티가 많아도 0 이하로 내려가지 않음"""
        sig = _sig("S1_GAP_OPEN", gap_pct=20.0)  # -10점
        ctx = _ctx(strength=90, flu_rt=16.0, bid=500, ask=1000)  # flu_rt>15 → -20점
        score, _ = rule_score(sig, ctx)
        assert score >= 0.0

    def test_score_never_above_100(self):
        """모든 조건 최대여도 100점 초과 없음"""
        sig = _sig("S7_AUCTION", gap_pct=3.0, vol_rank=1)
        ctx = _ctx(strength=200, flu_rt=1.0, bid=10000, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score <= 100.0

    def test_score_is_rounded_to_1_decimal(self):
        """점수는 소수점 1자리로 반올림"""
        sig = _sig("S1_GAP_OPEN", gap_pct=4.0)
        ctx = _ctx(strength=120, flu_rt=1.0, bid=1500, ask=1000)
        score, _ = rule_score(sig, ctx)
        assert score == round(score, 1)


# ──────────────────────────────────────────────────────────────────
# should_skip_ai 테스트
# ──────────────────────────────────────────────────────────────────

class TestShouldSkipAi:
    def test_skip_when_score_below_strategy_threshold(self):
        """점수가 전략별 임계값 미달 시 True"""
        # S1 임계값 = 70
        assert should_skip_ai(69.9, "S1_GAP_OPEN") is True

    def test_no_skip_when_score_at_threshold(self):
        """점수가 임계값 이상 → False (건너뛰지 않음)"""
        assert should_skip_ai(70.0, "S1_GAP_OPEN") is False

    def test_no_skip_when_above_threshold(self):
        """점수가 임계값 초과 → False"""
        assert should_skip_ai(80.0, "S1_GAP_OPEN") is False

    def test_s2_threshold_65(self):
        """S2 임계값 = 65"""
        assert should_skip_ai(64.9, "S2_VI_PULLBACK") is True
        assert should_skip_ai(65.0, "S2_VI_PULLBACK") is False

    def test_s3_threshold_60(self):
        """S3 임계값 = 60"""
        assert should_skip_ai(59.9, "S3_INST_FRGN") is True
        assert should_skip_ai(60.0, "S3_INST_FRGN") is False

    def test_s4_threshold_75(self):
        """S4 임계값 = 75 (가장 높음)"""
        assert should_skip_ai(74.9, "S4_BIG_CANDLE") is True
        assert should_skip_ai(75.0, "S4_BIG_CANDLE") is False

    def test_unknown_strategy_uses_default(self):
        """알 수 없는 전략 → 기본 임계값 65 사용"""
        assert should_skip_ai(64.9, "UNKNOWN") is True
        assert should_skip_ai(65.0, "UNKNOWN") is False

    def test_no_strategy_uses_min_score(self):
        """전략 미지정 → MIN_SCORE 환경변수 값 (기본 60.0)"""
        # 기본 MIN_SCORE=60.0
        result = should_skip_ai(59.9)
        assert result is True


# ──────────────────────────────────────────────────────────────────
# 조합 테스트
# ──────────────────────────────────────────────────────────────────

class TestCombinationScores:
    def test_s1_all_max_conditions(self):
        """S1 모든 조건 최대 → 최고 점수"""
        sig = _sig("S1_GAP_OPEN", gap_pct=4.0, cntr_strength=160.0)
        ctx = _ctx(strength=160, flu_rt=2.0, bid=3000, ask=1000)
        score, _ = rule_score(sig, ctx)
        # gap=4% → 20, strength=160 → 30, bid_ratio=3 → 25, cntr=160 → 10 = 85점
        assert score == 85.0

    def test_s7_all_max_conditions(self):
        """S7 모든 조건 최대 → 75점"""
        sig = _sig("S7_AUCTION", gap_pct=3.0, vol_rank=5)
        ctx = _ctx(strength=100, flu_rt=1.0, bid=4000, ask=1000)
        score, _ = rule_score(sig, ctx)
        # gap=3% → 25, bid_ratio=4 → 30, vol_rank=5 → 20 = 75점
        assert score == 75.0

    def test_s4_is_new_high_bonus(self):
        """S4 신고가 플래그 +20점"""
        sig_high = _sig("S4_BIG_CANDLE", vol_ratio=8.0, body_ratio=0.85, is_new_high=True)
        sig_no_high = _sig("S4_BIG_CANDLE", vol_ratio=8.0, body_ratio=0.85, is_new_high=False)
        ctx = _ctx(strength=100, flu_rt=1.0, bid=500, ask=1000)
        diff = rule_score(sig_high, ctx)[0] - rule_score(sig_no_high, ctx)[0]
        assert diff == 20.0

    def test_s6_uses_signal_cntr_strength_over_context(self):
        """S6에서 신호 내 cntr_strength가 컨텍스트 strength보다 우선"""
        # 신호 내 강한 체결강도
        sig = _sig("S6_THEME_LAGGARD", gap_pct=2.0, cntr_strength=160.0)
        ctx = _ctx(strength=90, flu_rt=1.0, bid=500, ask=1000)  # 컨텍스트 약함
        score, _ = rule_score(sig, ctx)
        # gap=2% → 25, cntr_sig=160 → effective=160 → >150 → +30, bid_ratio=0.5 → 0 = 55
        assert score == 55.0

    def test_s5_net_buy_amt_max_40_points(self):
        """S5 순매수 금액 점수 최대 40점"""
        sig = _sig("S5_PROG_FRGN", net_buy_amt=200_000_000_000)  # 2000억
        ctx = _ctx(strength=100, flu_rt=1.0, bid=500, ask=1000)
        score, _ = rule_score(sig, ctx)
        # 2000억 / 1000000 * 0.4 = 80 → min(40, 80) = 40점 + 체결강도·호가비율
        assert score >= 40.0
