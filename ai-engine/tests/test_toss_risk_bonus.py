import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scorer import _toss_risk_bonus


class TestTossRiskBonus:
    def test_no_data_returns_zero(self):
        bonus, info = _toss_risk_bonus("S10_NEW_HIGH", {})
        assert bonus == 0.0
        assert info == {}

    def test_high_short_selling_gives_bonus_for_s10(self):
        ctx = {"toss_risk": {"short_selling": {"shortSellingAmountRate": "0.12", "date": "2026-08-10"}}}
        bonus, info = _toss_risk_bonus("S10_NEW_HIGH", ctx)
        assert bonus == 8.0
        assert info["short_selling_bonus"] == 8.0

    def test_moderate_short_selling_gives_smaller_bonus_for_s13(self):
        ctx = {"toss_risk": {"short_selling": {"shortSellingAmountRate": "0.06"}}}
        bonus, _ = _toss_risk_bonus("S13_BOX_BREAKOUT", ctx)
        assert bonus == 4.0

    def test_low_short_selling_gives_no_bonus(self):
        ctx = {"toss_risk": {"short_selling": {"shortSellingAmountRate": "0.01"}}}
        bonus, info = _toss_risk_bonus("S10_NEW_HIGH", ctx)
        assert bonus == 0.0
        assert info["short_selling_bonus"] == 0.0

    def test_day_strategy_ignores_short_selling(self):
        """데이트레이딩 전략(S1/S2/S4/S6)은 스윙이 아니므로 토스 리스크를 항상 무시한다."""
        ctx = {"toss_risk": {"short_selling": {"shortSellingAmountRate": "0.20"}}}
        bonus, info = _toss_risk_bonus("S1_GAP_OPEN", ctx)
        assert bonus == 0.0
        assert info == {}

    def test_swing_strategy_outside_original_three_now_gets_bonus(self):
        """2026-08-11 스윙 전체 확장 — S8 등도 이제 공매도/신용 데이터를 반영한다."""
        ctx = {
            "toss_risk": {
                "short_selling": {"shortSellingAmountRate": "0.12"},
                "credit_trades": {"marginLoan": {"balanceRate": "0.07"}},
            }
        }
        bonus, info = _toss_risk_bonus("S8_GOLDEN_CROSS", ctx)
        assert bonus == 8.0 - 5.0
        assert info["short_selling_bonus"] == 8.0
        assert info["credit_overhang_penalty"] == -5.0

    def test_s14_combines_short_selling_bonus_and_credit_penalty(self):
        ctx = {
            "toss_risk": {
                "short_selling": {"shortSellingAmountRate": "0.11"},
                "credit_trades": {"marginLoan": {"balanceRate": "0.06"}},
            }
        }
        bonus, info = _toss_risk_bonus("S14_OVERSOLD_BOUNCE", ctx)
        assert bonus == 8.0 - 5.0
        assert info["short_selling_bonus"] == 8.0
        assert info["credit_overhang_penalty"] == -5.0

    def test_s14_low_credit_balance_has_no_penalty(self):
        ctx = {"toss_risk": {"credit_trades": {"marginLoan": {"balanceRate": "0.01"}}}}
        bonus, info = _toss_risk_bonus("S14_OVERSOLD_BOUNCE", ctx)
        assert bonus == 0.0
        assert info["credit_overhang_penalty"] == 0.0

    def test_malformed_rate_is_ignored_safely(self):
        ctx = {"toss_risk": {"short_selling": {"shortSellingAmountRate": None}}}
        bonus, info = _toss_risk_bonus("S10_NEW_HIGH", ctx)
        assert bonus == 0.0
        assert info == {}

    def test_severe_warning_gives_large_penalty(self):
        ctx = {"toss_risk": {"warnings": [{"warningType": "INVESTMENT_WARNING"}]}}
        bonus, info = _toss_risk_bonus("S10_NEW_HIGH", ctx)
        assert bonus == -25.0
        assert info["toss_warning_severe_types"] == ["INVESTMENT_WARNING"]
        assert info["toss_warning_penalty"] == -25.0

    def test_caution_warning_gives_small_penalty(self):
        ctx = {"toss_risk": {"warnings": [{"warningType": "VI_STATIC"}]}}
        bonus, info = _toss_risk_bonus("S13_BOX_BREAKOUT", ctx)
        assert bonus == -6.0
        assert info["toss_warning_caution_types"] == ["VI_STATIC"]

    def test_severe_and_caution_warnings_stack(self):
        ctx = {
            "toss_risk": {
                "warnings": [
                    {"warningType": "LIQUIDATION_TRADING"},
                    {"warningType": "OVERHEATED"},
                ]
            }
        }
        bonus, info = _toss_risk_bonus("S14_OVERSOLD_BOUNCE", ctx)
        assert bonus == -25.0 - 6.0
        assert info["toss_warning_severe_types"] == ["LIQUIDATION_TRADING"]
        assert info["toss_warning_caution_types"] == ["OVERHEATED"]

    def test_empty_warnings_list_gives_no_penalty(self):
        ctx = {"toss_risk": {"warnings": []}}
        bonus, info = _toss_risk_bonus("S10_NEW_HIGH", ctx)
        assert bonus == 0.0
        assert "toss_warning_penalty" not in info

    def test_unknown_warning_type_is_ignored(self):
        ctx = {"toss_risk": {"warnings": [{"warningType": "STOCK_WARRANTS"}]}}
        bonus, info = _toss_risk_bonus("S10_NEW_HIGH", ctx)
        assert bonus == 0.0
        assert "toss_warning_penalty" not in info
