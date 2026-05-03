
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from scorer import rule_score, get_claude_threshold, should_skip_ai, _safe_float


# ??????????????????????????????????????????????????????????????????
# 怨듯넻 ?ы띁
# ??????????????????????????????????????????????????????????????????

def _ctx(strength=120.0, flu_rt=3.0, bid_ratio=1.5):
    total_buy = bid_ratio * 1000
    return {
        "tick": {"flu_rt": str(flu_rt)},
        "hoga": {
            "total_buy_bid_req": str(total_buy),
            "total_sel_bid_req": "1000",
        },
        "strength": strength,
        "vi": {},
    }


def _signal(strategy, **kwargs):
    base = {"strategy": strategy, "stk_cd": "005930", "stk_nm": "?쇱꽦?꾩옄"}
    base.update(kwargs)
    return base


# ??????????????????????????????????????????????????????????????????
# _safe_float ?좏떥 ?뚯뒪??
# ??????????????????????????????????????????????????????????????????

class TestSafeFloat:
    def test_normal_float(self):
        assert _safe_float(3.5) == 3.5

    def test_string_with_comma(self):
        assert _safe_float("1,234.5") == 1234.5

    def test_string_with_plus(self):
        assert _safe_float("+5.0") == 5.0

    def test_none_returns_default(self):
        assert _safe_float(None, 0.0) == 0.0

    def test_invalid_string_returns_default(self):
        assert _safe_float("N/A", -1.0) == -1.0

    def test_zero_string(self):
        assert _safe_float("0") == 0.0


# ??????????????????????????????????????????????????????????????????
# S1_GAP_OPEN ?뚯뒪??
# ??????????????????????????????????????????????????????????????????

class TestS1GapOpen:

    def test_optimal_conditions_high_score(self):
        signal = _signal("S1_GAP_OPEN", gap_pct=4.0, cntr_strength=160)
        ctx = _ctx(strength=160, flu_rt=4.0, bid_ratio=2.5)
        score, _ = rule_score(signal, ctx)
        assert score >= 70, f"Expected >=70 but got {score}"

    def test_minimal_conditions_low_score(self):
        signal = _signal("S1_GAP_OPEN", gap_pct=0.5)
        ctx = _ctx(strength=90, flu_rt=0.5, bid_ratio=1.0)
        score, _ = rule_score(signal, ctx)
        assert score < 50, f"Expected <50 but got {score}"

    def test_gap_3_to_5_gets_20_points(self):
        signal = _signal("S1_GAP_OPEN", gap_pct=4.0)
        ctx = _ctx(strength=100, flu_rt=4.0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        # gap=4%硫?20?? strength=100 ??0?? bid_ratio=0.5 ??0????珥?20??
        assert score == 20.0

    def test_gap_5_to_8_gets_15_points(self):
        signal = _signal("S1_GAP_OPEN", gap_pct=6.0)
        ctx = _ctx(strength=100, flu_rt=6.0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        assert score == 15.0

    def test_strategy_raw_score_boost_used(self):
        signal = _signal("S7_ICHIMOKU_BREAKOUT", gap_pct=3.0, vol_rank=999, score=40)
        ctx = _ctx(strength=100, flu_rt=0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        assert score == 35.0

    def test_overheat_penalty_above_15pct(self):
        signal = _signal("S1_GAP_OPEN", gap_pct=4.0)
        ctx = _ctx(strength=160, flu_rt=16.0, bid_ratio=2.5)
        score_overheat, _ = rule_score(signal, ctx)
        ctx_normal = _ctx(strength=160, flu_rt=4.0, bid_ratio=2.5)
        score_normal, _ = rule_score(signal, ctx_normal)
        assert score_overheat < score_normal

    def test_penalty_10_to_15pct(self):
        signal = _signal("S1_GAP_OPEN", gap_pct=4.0)
        ctx_11 = _ctx(strength=100, flu_rt=11.0, bid_ratio=0.5)
        ctx_4 = _ctx(strength=100, flu_rt=4.0, bid_ratio=0.5)
        score_penalty, _ = rule_score(signal, ctx_11)
        score_normal, _ = rule_score(signal, ctx_4)
        assert score_penalty == score_normal - 10

    def test_decline_penalty_below_minus5pct(self):
        signal = _signal("S1_GAP_OPEN", gap_pct=4.0)
        ctx = _ctx(strength=100, flu_rt=-6.0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        assert score == max(0.0, 20.0 - 15.0)

    def test_cntr_strength_bonus(self):
        signal_with = _signal("S1_GAP_OPEN", gap_pct=4.0, cntr_strength=160)
        signal_without = _signal("S1_GAP_OPEN", gap_pct=4.0)
        ctx = _ctx(strength=100, flu_rt=4.0, bid_ratio=0.5)
        score_with, _ = rule_score(signal_with, ctx)
        score_without, _ = rule_score(signal_without, ctx)
        assert score_with == score_without + 10

    def test_zero_values(self):
        signal = _signal("S1_GAP_OPEN", gap_pct=0, cntr_strength=0)
        ctx = _ctx(strength=0, flu_rt=0, bid_ratio=0)
        score, _ = rule_score(signal, ctx)
        assert score >= 0.0

    def test_score_clamped_0_to_100(self):
        signal = _signal("S1_GAP_OPEN", gap_pct=4.0, cntr_strength=200)
        ctx = _ctx(strength=200, flu_rt=4.0, bid_ratio=5.0)
        score, _ = rule_score(signal, ctx)
        assert 0.0 <= score <= 100.0

    def test_missing_gap_pct_defaults_zero(self):
        signal = _signal("S1_GAP_OPEN")  # gap_pct ?놁쓬
        ctx = _ctx()
        score, _ = rule_score(signal, ctx)
        assert isinstance(score, float)

    def test_signal_bid_ratio_fallback_used_when_hoga_missing(self):
        signal = _signal("S1_GAP_OPEN", gap_pct=4.0, bid_ratio=2.5)
        ctx = {
            "tick": {"flu_rt": "4.0"},
            "hoga": {},
            "strength": 100.0,
            "vi": {},
        }
        score, _ = rule_score(signal, ctx)
        assert score == 45.0

    def test_strategy_raw_score_boost_used(self):
        signal = _signal("S1_GAP_OPEN", gap_pct=4.0, score=100)
        ctx = _ctx(strength=100, flu_rt=4.0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        assert score == 40.0


# ??????????????????????????????????????????????????????????????????
# S2_VI_PULLBACK ?뚯뒪??
# ??????????????????????????????????????????????????????????????????

class TestS2ViPullback:

    def test_optimal_conditions_high_score(self):
        signal = _signal("S2_VI_PULLBACK", pullback_pct=-1.5, is_dynamic=True)
        ctx = _ctx(strength=130, flu_rt=3.0, bid_ratio=1.8)
        score, _ = rule_score(signal, ctx)
        assert score >= 70, f"Expected >=70 but got {score}"

    def test_minimal_conditions_low_score(self):
        signal = _signal("S2_VI_PULLBACK", pullback_pct=0, is_dynamic=False)
        ctx = _ctx(strength=100, flu_rt=3.0, bid_ratio=1.0)
        score, _ = rule_score(signal, ctx)
        assert score < 50, f"Expected <50 but got {score}"

    def test_is_dynamic_true_bool(self):
        signal_dyn = _signal("S2_VI_PULLBACK", pullback_pct=-1.5, is_dynamic=True)
        signal_static = _signal("S2_VI_PULLBACK", pullback_pct=-1.5, is_dynamic=False)
        ctx = _ctx(strength=100, flu_rt=3.0, bid_ratio=0.5)
        score_dyn, _ = rule_score(signal_dyn, ctx)
        score_static, _ = rule_score(signal_static, ctx)
        assert score_dyn == score_static + 15

    def test_is_dynamic_int_1(self):
        signal = _signal("S2_VI_PULLBACK", pullback_pct=-1.5, is_dynamic=1)
        ctx = _ctx(strength=100, flu_rt=3.0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        # pullback 1~2% ??30?? is_dynamic=1(truthy) ??+15??
        assert score == 45.0

    def test_is_dynamic_int_0(self):
        signal = _signal("S2_VI_PULLBACK", pullback_pct=-1.5, is_dynamic=0)
        ctx = _ctx(strength=100, flu_rt=3.0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        assert score == 30.0

    def test_pullback_1_to_2pct_max_score(self):
        signal = _signal("S2_VI_PULLBACK", pullback_pct=-1.5, is_dynamic=False)
        ctx = _ctx(strength=100, flu_rt=3.0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        assert score == 30.0

    def test_pullback_2_to_3pct_medium_score(self):
        signal = _signal("S2_VI_PULLBACK", pullback_pct=-2.5, is_dynamic=False)
        ctx = _ctx(strength=100, flu_rt=3.0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        assert score == 20.0

    def test_pullback_over_3pct_zero_score(self):
        signal = _signal("S2_VI_PULLBACK", pullback_pct=-4.0, is_dynamic=False)
        ctx = _ctx(strength=100, flu_rt=3.0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        assert score == 0.0

    def test_none_pullback_defaults(self):
        signal = _signal("S2_VI_PULLBACK", pullback_pct=None, is_dynamic=False)
        ctx = _ctx(strength=100, flu_rt=3.0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        # pullback=0 < 3.0 ??20??(1~2% 踰붿쐞 ?꾨땲誘濡?20??遺꾧린)
        assert score == 20.0

    def test_missing_is_dynamic(self):
        signal = _signal("S2_VI_PULLBACK", pullback_pct=-1.5)
        ctx = _ctx(strength=100, flu_rt=3.0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        assert score == 30.0

    def test_strength_bonus_120(self):
        signal = _signal("S2_VI_PULLBACK", pullback_pct=-1.5, is_dynamic=False)
        ctx = _ctx(strength=125, flu_rt=3.0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        assert score == 50.0  # 30 + 20


# ??????????????????????????????????????????????????????????????????
# S3_INST_FRGN ?뚯뒪??
# ??????????????????????????????????????????????????????????????????

class TestS3InstFrgn:

    def test_optimal_conditions_high_score(self):
        signal = _signal(
            "S3_INST_FRGN",
            net_buy_amt=50_000_000_000,  # 500??
            continuous_days=5,
            vol_ratio=3.5
        )
        ctx = _ctx()
        score, _ = rule_score(signal, ctx)
        assert score >= 70, f"Expected >=70 but got {score}"

    def test_minimal_conditions_low_score(self):
        signal = _signal(
            "S3_INST_FRGN",
            net_buy_amt=1_000_000,  # 100留???
            continuous_days=0,
            vol_ratio=1.0
        )
        ctx = _ctx()
        score, _ = rule_score(signal, ctx)
        assert score < 30, f"Expected <30 but got {score}"

    def test_continuous_days_5_plus_gets_30(self):
        signal = _signal("S3_INST_FRGN", net_buy_amt=0, continuous_days=5, vol_ratio=0)
        ctx = _ctx()
        score, _ = rule_score(signal, ctx)
        assert score == 30.0

    def test_continuous_days_3_gets_20(self):
        signal = _signal("S3_INST_FRGN", net_buy_amt=0, continuous_days=3, vol_ratio=0)
        ctx = _ctx()
        score, _ = rule_score(signal, ctx)
        assert score == 20.0

    def test_continuous_days_1_gets_10(self):
        signal = _signal("S3_INST_FRGN", net_buy_amt=0, continuous_days=1, vol_ratio=0)
        ctx = _ctx()
        score, _ = rule_score(signal, ctx)
        assert score == 10.0

    def test_continuous_days_0_gets_0(self):
        signal = _signal("S3_INST_FRGN", net_buy_amt=0, continuous_days=0, vol_ratio=0)
        ctx = _ctx()
        score, _ = rule_score(signal, ctx)
        assert score == 0.0

    def test_vol_ratio_thresholds(self):
        base = {"net_buy_amt": 0, "continuous_days": 0}
        ctx = _ctx()

        signal_3x = _signal("S3_INST_FRGN", **base, vol_ratio=3.0)
        assert rule_score(signal_3x, ctx)[0] == 25.0

        signal_2x = _signal("S3_INST_FRGN", **base, vol_ratio=2.0)
        assert rule_score(signal_2x, ctx)[0] == 20.0

        signal_15x = _signal("S3_INST_FRGN", **base, vol_ratio=1.5)
        assert rule_score(signal_15x, ctx)[0] == 10.0

        signal_1x = _signal("S3_INST_FRGN", **base, vol_ratio=1.0)
        assert rule_score(signal_1x, ctx)[0] == 0.0

    def test_net_buy_amt_capped_at_25(self):
        signal = _signal(
            "S3_INST_FRGN",
            net_buy_amt=999_999_999_999,  # 留ㅼ슦 ??媛?
            continuous_days=0,
            vol_ratio=0
        )
        ctx = _ctx()
        score, _ = rule_score(signal, ctx)
        assert score == 25.0

    def test_flu_rt_positive_adds_bonus(self):
        signal = _signal("S3_INST_FRGN", net_buy_amt=0, continuous_days=0, vol_ratio=0, flu_rt=2.0)
        ctx = _ctx()
        score, _ = rule_score(signal, ctx)
        assert score == 10.0

    def test_missing_continuous_days_defaults(self):
        signal = _signal("S3_INST_FRGN", net_buy_amt=0, vol_ratio=0)
        ctx = _ctx()
        score, _ = rule_score(signal, ctx)
        assert score == 0.0

    def test_none_continuous_days(self):
        signal = _signal("S3_INST_FRGN", net_buy_amt=0, continuous_days=None, vol_ratio=0)
        ctx = _ctx()
        score, _ = rule_score(signal, ctx)
        assert score == 0.0


# ??????????????????????????????????????????????????????????????????
# S4_BIG_CANDLE ?뚯뒪??
# ??????????????????????????????????????????????????????????????????

class TestS4BigCandle:

    def test_optimal_conditions_high_score(self):
        signal = _signal("S4_BIG_CANDLE", vol_ratio=12, body_ratio=0.85, is_new_high=True)
        ctx = _ctx(strength=155, flu_rt=5.0, bid_ratio=2.0)
        score, _ = rule_score(signal, ctx)
        assert score >= 75, f"Expected >=75 but got {score}"

    def test_minimal_conditions_low_score(self):
        signal = _signal("S4_BIG_CANDLE", vol_ratio=2, body_ratio=0.5, is_new_high=False)
        ctx = _ctx(strength=100, flu_rt=3.0, bid_ratio=1.0)
        score, _ = rule_score(signal, ctx)
        assert score < 30, f"Expected <30 but got {score}"

    def test_vol_ratio_over_10_gets_30(self):
        signal = _signal("S4_BIG_CANDLE", vol_ratio=11, body_ratio=0, is_new_high=False)
        ctx = _ctx(strength=100, flu_rt=3.0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        assert score == 30.0

    def test_vol_ratio_5_to_10_gets_25(self):
        signal = _signal("S4_BIG_CANDLE", vol_ratio=7, body_ratio=0, is_new_high=False)
        ctx = _ctx(strength=100, flu_rt=3.0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        assert score == 25.0

    def test_body_ratio_over_0_8_gets_20(self):
        signal = _signal("S4_BIG_CANDLE", vol_ratio=0, body_ratio=0.8, is_new_high=False)
        ctx = _ctx(strength=100, flu_rt=3.0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        assert score == 20.0

    def test_body_ratio_0_65_to_0_69_gets_10(self):
        signal = _signal("S4_BIG_CANDLE", vol_ratio=0, body_ratio=0.66, is_new_high=False)
        ctx = _ctx(strength=100, flu_rt=3.0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        assert score == 10.0

    def test_is_new_high_adds_20(self):
        signal_high = _signal("S4_BIG_CANDLE", vol_ratio=0, body_ratio=0, is_new_high=True)
        signal_no = _signal("S4_BIG_CANDLE", vol_ratio=0, body_ratio=0, is_new_high=False)
        ctx = _ctx(strength=100, flu_rt=3.0, bid_ratio=0.5)
        assert rule_score(signal_high, ctx)[0] == rule_score(signal_no, ctx)[0] + 20

    def test_missing_is_new_high(self):
        signal = _signal("S4_BIG_CANDLE", vol_ratio=0, body_ratio=0)
        ctx = _ctx(strength=100, flu_rt=3.0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        assert score == 0.0

    def test_strength_150_plus_gets_20(self):
        signal = _signal("S4_BIG_CANDLE", vol_ratio=0, body_ratio=0, is_new_high=False)
        ctx = _ctx(strength=155, flu_rt=3.0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        assert score == 20.0

    def test_gain_pct_3_5_plus_gets_10(self):
        signal = _signal("S4_BIG_CANDLE", vol_ratio=0, body_ratio=0, gain_pct=3.6, is_new_high=False)
        ctx = _ctx(strength=100, flu_rt=3.0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        assert score == 10.0

# ??????????????????????????????????????????????????????????????????
# S5_PROG_FRGN ?뚯뒪??
# ??????????????????????????????????????????????????????????????????

class TestS5ProgFrgn:

    def test_optimal_conditions_high_score(self):
        signal = _signal("S5_PROG_FRGN", net_buy_amt=100_000_000_000)
        ctx = _ctx(strength=135, flu_rt=3.0, bid_ratio=2.5)
        score, _ = rule_score(signal, ctx)
        assert score >= 65, f"Expected >=65 but got {score}"

    def test_minimal_conditions_low_score(self):
        signal = _signal("S5_PROG_FRGN", net_buy_amt=1_000_000)
        ctx = _ctx(strength=90, flu_rt=3.0, bid_ratio=1.0)
        score, _ = rule_score(signal, ctx)
        assert score == 0.0

    def test_net_buy_amt_capped_at_40(self):
        signal = _signal("S5_PROG_FRGN", net_buy_amt=999_999_999_999)
        ctx = _ctx(strength=100, flu_rt=3.0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        assert score == 40.0

    def test_strength_above_130_gets_25(self):
        signal = _signal("S5_PROG_FRGN", net_buy_amt=0)
        ctx = _ctx(strength=135, flu_rt=3.0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        assert score == 25.0

    def test_strength_120_to_130_gets_20(self):
        signal = _signal("S5_PROG_FRGN", net_buy_amt=0)
        ctx = _ctx(strength=125, flu_rt=3.0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        assert score == 20.0

    def test_bid_ratio_above_2_gets_20(self):
        signal = _signal("S5_PROG_FRGN", net_buy_amt=0)
        ctx = _ctx(strength=100, flu_rt=3.0, bid_ratio=2.5)
        score, _ = rule_score(signal, ctx)
        assert score == 20.0

    def test_signal_strength_and_bid_ratio_fallback_used(self):
        signal = _signal("S5_PROG_FRGN", net_buy_amt=0, cntr_strength=135, bid_ratio=2.5)
        ctx = {
            "tick": {"flu_rt": "3.0"},
            "hoga": {},
            "strength": 100.0,
            "vi": {},
            "ws_online": True,
        }
        score, _ = rule_score(signal, ctx)
        assert score == 45.0

    def test_zero_net_buy_amt(self):
        signal = _signal("S5_PROG_FRGN", net_buy_amt=0)
        ctx = _ctx(strength=100, flu_rt=3.0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        assert score == 0.0

    def test_missing_net_buy_amt(self):
        signal = _signal("S5_PROG_FRGN")
        ctx = _ctx(strength=100, flu_rt=3.0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        assert score == 0.0


# ??????????????????????????????????????????????????????????????????
# S6_THEME_LAGGARD ?뚯뒪??
# ??????????????????????????????????????????????????????????????????

class TestS6ThemeLaggard:

    def test_optimal_conditions_high_score(self):
        signal = _signal("S6_THEME_LAGGARD", gap_pct=2.0, cntr_strength=160, theme_name="AI")
        ctx = _ctx(strength=155, flu_rt=2.0, bid_ratio=2.0)
        score, _ = rule_score(signal, ctx)
        assert score >= 60, f"Expected >=60 but got {score}"

    def test_minimal_conditions_low_score(self):
        signal = _signal("S6_THEME_LAGGARD", gap_pct=0, cntr_strength=0)
        ctx = _ctx(strength=90, flu_rt=0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        assert score == 15.0

    def test_gap_1_to_3_gets_25(self):
        signal = _signal("S6_THEME_LAGGARD", gap_pct=2.0, cntr_strength=0)
        ctx = _ctx(strength=100, flu_rt=2.0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        assert score == 25.0

    def test_gap_3_to_5_gets_15(self):
        signal = _signal("S6_THEME_LAGGARD", gap_pct=4.0, cntr_strength=0)
        ctx = _ctx(strength=100, flu_rt=4.0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        assert score == 15.0

    def test_cntr_strength_takes_priority_over_ctx(self):
        signal_high_cntr = _signal("S6_THEME_LAGGARD", gap_pct=0, cntr_strength=160)
        signal_no_cntr = _signal("S6_THEME_LAGGARD", gap_pct=0, cntr_strength=0)
        ctx_low = _ctx(strength=90, flu_rt=0, bid_ratio=0.5)

        score_high_cntr, _ = rule_score(signal_high_cntr, ctx_low)
        score_no_cntr, _ = rule_score(signal_no_cntr, ctx_low)

        # cntr_strength=160 ??30?? cntr_strength=0 ??strength=90 ??0??
        assert score_high_cntr > score_no_cntr

    def test_bid_ratio_above_1_5_gets_20_plus_gap(self):
        signal = _signal("S6_THEME_LAGGARD", gap_pct=0, cntr_strength=0)
        ctx = _ctx(strength=100, flu_rt=0, bid_ratio=2.0)
        score, _ = rule_score(signal, ctx)
        # gap=0 < 5 ??15?? cntr_strength=0 ??effective=100 ??120 ??0?? bid_ratio=2.0 ??20??
        assert score == 35.0

    def test_bid_ratio_1_2_to_1_5_gets_10(self):
        signal = _signal("S6_THEME_LAGGARD", gap_pct=6.0, cntr_strength=0)
        ctx = _ctx(strength=100, flu_rt=6.0, bid_ratio=1.3)
        score, _ = rule_score(signal, ctx)
        # gap=6.0 ??5 ??0?? effective_strength=100 ??120 ??0?? bid_ratio=1.3 > 1.2 ??10??
        assert score == 10.0

    def test_none_gap_pct(self):
        signal = _signal("S6_THEME_LAGGARD", gap_pct=None, cntr_strength=0)
        ctx = _ctx(strength=100, flu_rt=0, bid_ratio=0.5)
        score, _ = rule_score(signal, ctx)
        # gap=0 < 5 ??15?? cntr_strength=0 ??effective=100 ??120 ??0?? bid_ratio=0.5 ??1.2 ??0??
        assert score == 15.0


# S7_ICHIMOKU_BREAKOUT tests

class TestS7IchimokuBreakout:

    def test_optimal_conditions_high_score(self):
        signal = _signal("S7_ICHIMOKU_BREAKOUT", cloud_thickness_pct=0.8, chikou_above=True, vol_ratio=2.0, rsi=55, cond_count=3)
        score, _ = rule_score(signal, _ctx(strength=100, flu_rt=3.0))
        assert score >= 90

    def test_minimal_conditions_low_score(self):
        signal = _signal("S7_ICHIMOKU_BREAKOUT", cloud_thickness_pct=4.0, chikou_above=False, vol_ratio=1.0, rsi=80, cond_count=0)
        score, _ = rule_score(signal, _ctx(strength=100, flu_rt=0.0))
        assert score == 0.0

    def test_cloud_thickness_below_1_gets_20(self):
        signal = _signal("S7_ICHIMOKU_BREAKOUT", cloud_thickness_pct=0.8, chikou_above=False, vol_ratio=1.0, rsi=80, cond_count=0)
        score, _ = rule_score(signal, _ctx())
        assert score == 20.0

    def test_chikou_above_adds_20(self):
        signal = _signal("S7_ICHIMOKU_BREAKOUT", cloud_thickness_pct=4.0, chikou_above=True, vol_ratio=1.0, rsi=80, cond_count=0)
        score, _ = rule_score(signal, _ctx())
        assert score == 20.0

    def test_vol_ratio_2_gets_25(self):
        signal = _signal("S7_ICHIMOKU_BREAKOUT", cloud_thickness_pct=4.0, chikou_above=False, vol_ratio=2.0, rsi=80, cond_count=0)
        score, _ = rule_score(signal, _ctx())
        assert score == 25.0

    def test_rsi_in_range_gets_15(self):
        signal = _signal("S7_ICHIMOKU_BREAKOUT", cloud_thickness_pct=4.0, chikou_above=False, vol_ratio=1.0, rsi=55, cond_count=0)
        score, _ = rule_score(signal, _ctx())
        assert score == 15.0

    def test_condition_count_adds_five_each(self):
        signal = _signal("S7_ICHIMOKU_BREAKOUT", cloud_thickness_pct=4.0, chikou_above=False, vol_ratio=1.0, rsi=80, cond_count=3)
        score, _ = rule_score(signal, _ctx())
        assert score == 20.0


class TestThresholdAndSkipAi:
    def test_known_strategy_thresholds(self):
        assert get_claude_threshold("S1_GAP_OPEN") == 55
        assert get_claude_threshold("S2_VI_PULLBACK") == 65
        assert get_claude_threshold("S3_INST_FRGN") == 60
        assert get_claude_threshold("S4_BIG_CANDLE") == 65
        assert get_claude_threshold("S5_PROG_FRGN") == 65
        assert get_claude_threshold("S6_THEME_LAGGARD") == 60
        assert get_claude_threshold("S7_ICHIMOKU_BREAKOUT") == 62
        assert get_claude_threshold("S8_GOLDEN_CROSS") == 50
        assert get_claude_threshold("S9_PULLBACK_SWING") == 55
        assert get_claude_threshold("S10_NEW_HIGH") == 55
        assert get_claude_threshold("S11_FRGN_CONT") == 58
        assert get_claude_threshold("S12_CLOSING") == 60
        assert get_claude_threshold("S13_BOX_BREAKOUT") == 55
        assert get_claude_threshold("S14_OVERSOLD_BOUNCE") == 58
        assert get_claude_threshold("S15_MOMENTUM_ALIGN") == 65

    def test_unknown_strategy_default_threshold(self):
        threshold = get_claude_threshold("UNKNOWN")
        assert threshold == 65.0

    def test_should_skip_ai_below_threshold(self):
        assert should_skip_ai(50.0, "S1_GAP_OPEN") is True

    def test_should_not_skip_ai_above_threshold(self):
        assert should_skip_ai(75.0, "S1_GAP_OPEN") is False

    def test_should_skip_ai_no_strategy(self):
        import os
        min_score = float(os.getenv("AI_SCORE_THRESHOLD", "60.0"))
        assert should_skip_ai(min_score - 1, "") is True
        assert should_skip_ai(min_score + 1, "") is False


# ??????????????????????????????????????????????????????????????????
# 怨듯넻 ?⑤꼸??/ ?ｌ?耳?댁뒪 ?뚯뒪??
# ??????????????????????????????????????????????????????????????????

class TestCommonPenalties:
    def test_unknown_strategy_zero_score(self):
        signal = _signal("UNKNOWN_STRATEGY")
        ctx = _ctx()
        score, _ = rule_score(signal, ctx)
        assert score == 0.0

    def test_score_not_negative(self):
        signal = _signal("S1_GAP_OPEN", gap_pct=0)
        ctx = _ctx(strength=0, flu_rt=16.0, bid_ratio=0)  # 怨쇱뿴 ?⑤꼸??-20
        score, _ = rule_score(signal, ctx)
        assert score >= 0.0

    def test_empty_signal(self):
        score, _ = rule_score({}, {})
        assert score == 0.0

    def test_empty_market_ctx(self):
        signal = _signal("S1_GAP_OPEN", gap_pct=4.0)
        score, _ = rule_score(signal, {})
        assert isinstance(score, float)
        assert 0.0 <= score <= 100.0


class TestSwingScoreBoosts:
    def test_s8_strategy_score_bonus_is_applied(self):
        signal = _signal(
            "S8_GOLDEN_CROSS",
            flu_rt=2.0,
            cntr_strength=125,
            vol_ratio=2.0,
            score=40,
            rsi=58,
            gap_pct=1.5,
            is_today_cross=True,
            is_macd_accel=True,
        )
        score, _ = rule_score(signal, _ctx(strength=120, flu_rt=2.0, bid_ratio=1.4))
        assert score >= 70.0

    def test_s13_strategy_payload_is_reflected_in_score(self):
        signal = _signal(
            "S13_BOX_BREAKOUT",
            flu_rt=4.0,
            cntr_strength=135,
            vol_ratio=2.5,
            score=55,
            rsi=62,
            bollinger_squeeze=True,
            mfi_confirmed=True,
        )
        score, _ = rule_score(signal, _ctx(strength=130, flu_rt=4.0, bid_ratio=1.6))
        assert score >= 70.0

    def test_s14_single_reversal_signal_can_still_score(self):
        signal = _signal(
            "S14_OVERSOLD_BOUNCE",
            rsi=28,
            atr_pct=1.8,
            cntr_strength=112,
            vol_ratio=1.6,
            cond_count=1,
            score=42,
        )
        score, _ = rule_score(signal, _ctx(strength=110, flu_rt=-1.0, bid_ratio=1.3))
        assert score >= 50.0
