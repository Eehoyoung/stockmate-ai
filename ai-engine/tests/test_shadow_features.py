"""
tests/test_shadow_features.py
shadow_features.py Phase 3 단위 테스트.

외부 HTTP / Redis 없이 인메모리 데이터로만 동작한다.
"""
from __future__ import annotations

import pytest

# ── helpers ────────────────────────────────────────────────────────────────────

def _daily_candle(o=10000, h=10500, l=9800, c=10200, vol=100000):
    return {
        "stk_opnpric": str(o),
        "stk_hgpric": str(h),
        "stk_lwpric": str(l),
        "stk_clpr": str(c),
        "acml_vol": str(vol),
    }


def _min_candle(o=10000, h=10500, l=9800, c=10200, vol=50000):
    return _daily_candle(o, h, l, c, vol)


# ── compute_orderbook_imbalance ───────────────────────────────────────────────

class TestOrderbookImbalance:
    def test_buy_dominated(self):
        from shadow_features import compute_orderbook_imbalance
        hoga = {
            "total_buy_bid_req": "1000",
            "total_sel_bid_req": "400",
            "buy_bid_req_1": "200",
            "sel_bid_req_1": "100",
        }
        result = compute_orderbook_imbalance(hoga)
        assert result["imbalance_total"] > 0
        assert result["imbalance_1st_level"] > 0
        assert result["buy_qty_total"] == 1000
        assert result["sell_qty_total"] == 400

    def test_sell_dominated(self):
        from shadow_features import compute_orderbook_imbalance
        hoga = {
            "total_buy_bid_req": "300",
            "total_sel_bid_req": "700",
            "buy_bid_req_1": "50",
            "sel_bid_req_1": "150",
        }
        result = compute_orderbook_imbalance(hoga)
        assert result["imbalance_total"] < 0
        assert result["imbalance_1st_level"] < 0

    def test_empty_hoga_returns_zero(self):
        from shadow_features import compute_orderbook_imbalance
        result = compute_orderbook_imbalance({})
        assert result["imbalance_total"] == 0.0
        assert result["imbalance_1st_level"] == 0.0

    def test_balanced(self):
        from shadow_features import compute_orderbook_imbalance
        hoga = {
            "total_buy_bid_req": "500",
            "total_sel_bid_req": "500",
            "buy_bid_req_1": "100",
            "sel_bid_req_1": "100",
        }
        result = compute_orderbook_imbalance(hoga)
        assert result["imbalance_total"] == 0.0
        assert result["imbalance_1st_level"] == 0.0

    def test_imbalance_range(self):
        from shadow_features import compute_orderbook_imbalance
        hoga = {
            "total_buy_bid_req": "9999",
            "total_sel_bid_req": "1",
            "buy_bid_req_1": "1",
            "sel_bid_req_1": "1",
        }
        result = compute_orderbook_imbalance(hoga)
        assert -1.0 <= result["imbalance_total"] <= 1.0


# ── compute_relative_strength ─────────────────────────────────────────────────

class TestRelativeStrength:
    def test_outperform(self):
        from shadow_features import compute_relative_strength
        signal = {"flu_rt": "3.0"}
        ctx = {"market_type": "001", "kospi_flu_rt": 1.0}
        result = compute_relative_strength(signal, ctx)
        assert result["rs_pct"] == pytest.approx(2.0)
        assert result["rs_trend"] == "outperform"

    def test_underperform(self):
        from shadow_features import compute_relative_strength
        signal = {"flu_rt": "-1.0"}
        ctx = {"market_type": "101", "kosdaq_flu_rt": 0.5}
        result = compute_relative_strength(signal, ctx)
        assert result["rs_pct"] == pytest.approx(-1.5)
        assert result["rs_trend"] == "underperform"

    def test_inline(self):
        from shadow_features import compute_relative_strength
        signal = {"flu_rt": "0.3"}
        ctx = {"market_type": "001", "kospi_flu_rt": 0.0}
        result = compute_relative_strength(signal, ctx)
        assert result["rs_trend"] == "inline"

    def test_missing_idx_returns_unknown(self):
        from shadow_features import compute_relative_strength
        signal = {"flu_rt": "2.0"}
        ctx = {}
        result = compute_relative_strength(signal, ctx)
        assert result["rs_trend"] == "unknown"
        assert result["rs_pct"] is None

    def test_missing_stk_returns_unknown(self):
        from shadow_features import compute_relative_strength
        signal = {}
        ctx = {"kospi_flu_rt": 0.5}
        result = compute_relative_strength(signal, ctx)
        assert result["rs_trend"] == "unknown"


# ── compute_tick_buy_pressure ─────────────────────────────────────────────────

class TestTickBuyPressure:
    def test_strong_label(self):
        from shadow_features import compute_tick_buy_pressure
        tick = {"cntr_str": "130"}
        ctx = {
            "strength": 130,
            "hoga": {"buy_bid_pric_1": "10000", "sel_bid_pric_1": "10010"},
        }
        result = compute_tick_buy_pressure(tick, ctx)
        assert result["buy_pressure_label"] == "strong"
        assert result["cntr_strength"] == pytest.approx(130.0)

    def test_moderate_label(self):
        from shadow_features import compute_tick_buy_pressure
        tick = {}
        ctx = {"strength": 105}
        result = compute_tick_buy_pressure(tick, ctx)
        assert result["buy_pressure_label"] == "moderate"

    def test_weak_label(self):
        from shadow_features import compute_tick_buy_pressure
        tick = {}
        ctx = {"strength": 90}
        result = compute_tick_buy_pressure(tick, ctx)
        assert result["buy_pressure_label"] == "weak"

    def test_spread_computed(self):
        from shadow_features import compute_tick_buy_pressure
        tick = {}
        ctx = {
            "strength": 100,
            "hoga": {"buy_bid_pric_1": "10000", "sel_bid_pric_1": "10050"},
        }
        result = compute_tick_buy_pressure(tick, ctx)
        assert result["spread_pct"] == pytest.approx(0.5, rel=1e-3)

    def test_no_hoga_spread_is_none(self):
        from shadow_features import compute_tick_buy_pressure
        result = compute_tick_buy_pressure({}, {})
        assert result["spread_pct"] is None


# ── compute_cvd_from_candles ──────────────────────────────────────────────────

class TestCVD:
    def _bullish_candles(self, n=10):
        # Close near high → positive CVD
        return [_min_candle(o=10000, h=10500, l=9900, c=10450, vol=100000) for _ in range(n)]

    def _bearish_candles(self, n=10):
        # Close near low → negative CVD
        return [_min_candle(o=10000, h=10500, l=9900, c=9950, vol=100000) for _ in range(n)]

    def test_bullish_cvd_positive(self):
        from shadow_features import compute_cvd_from_candles
        result = compute_cvd_from_candles(self._bullish_candles())
        assert result is not None
        assert result["cvd_total"] > 0
        assert result["aggressive_buy_ratio"] > 0.5

    def test_bearish_cvd_negative(self):
        from shadow_features import compute_cvd_from_candles
        result = compute_cvd_from_candles(self._bearish_candles())
        assert result is not None
        assert result["cvd_total"] < 0
        assert result["aggressive_buy_ratio"] < 0.5

    def test_empty_returns_none(self):
        from shadow_features import compute_cvd_from_candles
        assert compute_cvd_from_candles([]) is None

    def test_slope_computed_for_5plus_bars(self):
        from shadow_features import compute_cvd_from_candles
        result = compute_cvd_from_candles(self._bullish_candles(10))
        assert result is not None
        assert "cvd_slope" in result

    def test_bar_count_matches_input(self):
        from shadow_features import compute_cvd_from_candles
        result = compute_cvd_from_candles(self._bullish_candles(7))
        assert result["bar_count"] == 7

    def test_zero_range_candle_handled(self):
        from shadow_features import compute_cvd_from_candles
        flat = [_min_candle(o=10000, h=10000, l=10000, c=10000, vol=1000)]
        result = compute_cvd_from_candles(flat)
        assert result is not None
        assert result["cvd_total"] == 0.0


# ── compute_anchored_vwap ─────────────────────────────────────────────────────

class TestAnchoredVWAP:
    def _candles(self, n=5):
        return [_min_candle(o=10000, h=10500, l=9800, c=10200, vol=50000) for _ in range(n)]

    def test_vwap_computed(self):
        from shadow_features import compute_anchored_vwap
        result = compute_anchored_vwap(self._candles())
        assert result is not None
        assert result["anchored_vwap"] > 0
        assert result["vwap_total_vol"] == 250000

    def test_price_vs_vwap_above(self):
        from shadow_features import compute_anchored_vwap
        result = compute_anchored_vwap(self._candles(), cur_prc=11000)
        assert result["above_vwap"] is True
        assert result["price_vs_vwap_pct"] > 0

    def test_price_vs_vwap_below(self):
        from shadow_features import compute_anchored_vwap
        result = compute_anchored_vwap(self._candles(), cur_prc=9000)
        assert result["above_vwap"] is False
        assert result["price_vs_vwap_pct"] < 0

    def test_no_cur_prc(self):
        from shadow_features import compute_anchored_vwap
        result = compute_anchored_vwap(self._candles(), cur_prc=None)
        assert result["price_vs_vwap_pct"] is None
        assert result["above_vwap"] is None

    def test_empty_returns_none(self):
        from shadow_features import compute_anchored_vwap
        assert compute_anchored_vwap([]) is None

    def test_zero_volume_candle_excluded(self):
        from shadow_features import compute_anchored_vwap
        candles = [_min_candle(vol=0), _min_candle(vol=50000)]
        result = compute_anchored_vwap(candles)
        assert result is not None
        assert result["vwap_total_vol"] == 50000


# ── compute_adx ───────────────────────────────────────────────────────────────

class TestADX:
    def _trending_data(self, n=35):
        highs  = [10000 + i * 10 for i in range(n)]
        lows   = [9800  + i * 10 for i in range(n)]
        closes = [9900  + i * 10 for i in range(n)]
        return highs, lows, closes

    def _flat_data(self, n=35):
        highs  = [10500] * n
        lows   = [9500]  * n
        closes = [10000] * n
        return highs, lows, closes

    def test_returns_adx_fields(self):
        from shadow_features import compute_adx
        h, l, c = self._trending_data()
        result = compute_adx(h, l, c)
        assert result is not None
        assert "adx" in result
        assert "plus_di" in result
        assert "minus_di" in result
        assert "trend_strength" in result
        assert "trend_direction" in result

    def test_uptrend_has_plus_di_higher(self):
        from shadow_features import compute_adx
        h, l, c = self._trending_data()
        result = compute_adx(h, l, c)
        assert result is not None
        assert result["trend_direction"] == "up"
        assert result["plus_di"] > result["minus_di"]

    def test_insufficient_data_returns_none(self):
        from shadow_features import compute_adx
        h, l, c = self._trending_data(10)
        result = compute_adx(h, l, c)
        assert result is None

    def test_adx_range(self):
        from shadow_features import compute_adx
        h, l, c = self._trending_data(40)
        result = compute_adx(h, l, c)
        assert result is not None
        assert 0 <= result["adx"] <= 100

    def test_trend_strength_label(self):
        from shadow_features import compute_adx
        h, l, c = self._trending_data(50)
        result = compute_adx(h, l, c)
        assert result is not None
        assert result["trend_strength"] in ("strong", "moderate", "weak")


# ── compute_all_shadow_features (orchestrator) ────────────────────────────────

class TestComputeAllShadowFeatures:
    def test_returns_all_keys(self):
        from shadow_features import compute_all_shadow_features
        result = compute_all_shadow_features({}, {})
        assert set(result.keys()) == {
            "orderbook", "relative_strength", "tick_pressure",
            "cvd", "anchored_vwap", "adx",
        }

    def test_without_candles_cvd_vwap_adx_none(self):
        from shadow_features import compute_all_shadow_features
        result = compute_all_shadow_features({}, {})
        assert result["cvd"] is None
        assert result["anchored_vwap"] is None
        assert result["adx"] is None

    def test_with_minute_candles_cvd_vwap_computed(self):
        from shadow_features import compute_all_shadow_features
        candles = [_min_candle() for _ in range(10)]
        result = compute_all_shadow_features({}, {}, minute_candles=candles)
        assert result["cvd"] is not None
        assert result["anchored_vwap"] is not None

    def test_with_few_daily_candles_adx_none(self):
        from shadow_features import compute_all_shadow_features
        daily = [_daily_candle() for _ in range(20)]
        result = compute_all_shadow_features({}, {}, daily_candles=daily)
        assert result["adx"] is None

    def test_with_enough_daily_candles_adx_computed(self):
        from shadow_features import compute_all_shadow_features
        highs  = [10000 + i * 10 for i in range(35)]
        lows   = [9800  + i * 10 for i in range(35)]
        closes = [9900  + i * 10 for i in range(35)]
        daily = [
            {"stk_hgpric": str(h), "stk_lwpric": str(l), "stk_clpr": str(c), "stk_opnpric": str(l), "acml_vol": "10000"}
            for h, l, c in zip(highs, lows, closes)
        ]
        result = compute_all_shadow_features({}, {}, daily_candles=daily)
        assert result["adx"] is not None

    def test_individual_feature_error_does_not_crash(self):
        from shadow_features import compute_all_shadow_features
        broken_candles = [{"stk_hgpric": "BROKEN", "stk_lwpric": None}]
        result = compute_all_shadow_features({}, {}, minute_candles=broken_candles)
        assert isinstance(result, dict)

    def test_full_signal_ctx(self):
        from shadow_features import compute_all_shadow_features
        signal = {"flu_rt": "2.5", "cur_prc": "10500"}
        ctx = {
            "market_type": "001",
            "kospi_flu_rt": 0.8,
            "strength": 115,
            "hoga": {
                "total_buy_bid_req": "800",
                "total_sel_bid_req": "400",
                "buy_bid_req_1": "100",
                "sel_bid_req_1": "60",
                "buy_bid_pric_1": "10490",
                "sel_bid_pric_1": "10510",
            },
            "tick": {"cur_prc": "10500"},
        }
        result = compute_all_shadow_features(signal, ctx)
        assert result["orderbook"]["imbalance_total"] > 0
        assert result["relative_strength"]["rs_trend"] == "outperform"
        assert result["tick_pressure"]["buy_pressure_label"] == "moderate"
