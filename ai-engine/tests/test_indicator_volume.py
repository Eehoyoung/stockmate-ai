"""
tests/test_indicator_volume.py
indicator_volume.py 순수 계산(calc_mfi, calc_vwap) 및 get_vwap_minute 배선 테스트.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _min_candle(cntr_tm: str, cur_prc: float, high: float, low: float, vol: float) -> dict:
    return {
        "cntr_tm": cntr_tm,
        "cur_prc": str(cur_prc),
        "high_pric": str(high),
        "low_pric": str(low),
        "trde_qty": str(vol),
    }


class TestCalcMfi:
    def test_insufficient_data_returns_zero_filled_list(self):
        from indicator_volume import calc_mfi

        closes = [100.0, 101.0, 102.0]
        mfi = calc_mfi(closes, closes, closes, [1000.0] * 3, period=14)
        assert mfi == [0.0, 0.0, 0.0]

    def test_mfi_bounded_between_0_and_100(self):
        from indicator_volume import calc_mfi

        n = 20
        closes = [float(100 + (i % 5) * 3) for i in range(n)]
        highs = [c + 2 for c in closes]
        lows = [c - 2 for c in closes]
        vols = [1000.0 + i * 10 for i in range(n)]
        mfi = calc_mfi(highs, lows, closes, vols, period=14)
        for v in mfi:
            assert 0.0 <= v <= 100.0

    def test_all_positive_flow_yields_mfi_hundred(self):
        """전형가(TP)가 매 봉 상승하면(음의 자금흐름=0) MFI=100."""
        from indicator_volume import calc_mfi

        n = 20
        # newest-first: index 0이 가장 큼(최신이 최고가) -> 시간순으로는 계속 상승
        closes = [float(119 - i) for i in range(n)]
        vols = [1000.0] * n
        mfi = calc_mfi(closes, closes, closes, vols, period=14)
        assert mfi[0] == 100.0

    def test_all_negative_flow_yields_mfi_zero(self):
        """전형가(TP)가 매 봉 하락하면(양의 자금흐름=0) MFI=0."""
        from indicator_volume import calc_mfi

        n = 20
        # newest-first: index 0이 가장 작음(최신이 최저가) -> 시간순으로는 계속 하락
        closes = [float(100 + i) for i in range(n)]
        vols = [1000.0] * n
        mfi = calc_mfi(closes, closes, closes, vols, period=14)
        assert mfi[0] == 0.0


class TestBuildMfiResult:
    """_build_mfi_result: RSI/Stochastic/ATR와 동일한 근거로 구현된 0.0-보존 로직 검증."""

    def test_genuine_mfi_zero_is_not_nulled_out(self):
        from indicator_volume import _build_mfi_result

        n = 20
        closes = [float(100 + i) for i in range(n)]  # 최신이 최저(계속 하락)
        candles = [
            {"cur_prc": str(c), "high_pric": str(c), "low_pric": str(c),
             "trde_qty": "1000"}
            for c in closes
        ]
        result = _build_mfi_result("005930", candles, period=14)
        assert result.mfi == 0.0
        assert result.mfi is not None
        assert result.is_oversold is True

    def test_insufficient_candles_returns_none(self):
        from indicator_volume import _build_mfi_result

        candles = [
            {"cur_prc": "100", "high_pric": "101", "low_pric": "99", "trde_qty": "1000"}
            for _ in range(5)
        ]
        result = _build_mfi_result("005930", candles, period=14)
        assert result.mfi is None
        assert result.mfi_prev is None


class TestGetMfiDaily:
    def test_wires_fetch_daily_candles_into_build_result(self):
        from indicator_volume import get_mfi_daily

        n = 20
        closes = [float(119 - i) for i in range(n)]  # 최신이 최고(계속 상승)
        candles = [
            {"cur_prc": str(c), "high_pric": str(c), "low_pric": str(c),
             "trde_qty": "1000"}
            for c in closes
        ]
        with patch("indicator_volume.fetch_daily_candles", new=AsyncMock(return_value=candles)):
            result = _run(get_mfi_daily("token", "005930", period=14))

        assert result.mfi == 100.0


class TestCalcVwap:
    def test_zero_volume_returns_zero(self):
        from indicator_volume import calc_vwap

        assert calc_vwap([100.0], [100.0], [100.0], [0.0]) == 0.0

    def test_vwap_between_low_and_high(self):
        from indicator_volume import calc_vwap

        highs = [105.0, 106.0, 104.0]
        lows = [95.0, 96.0, 94.0]
        closes = [100.0, 101.0, 99.0]
        vols = [100.0, 200.0, 150.0]
        vwap = calc_vwap(highs, lows, closes, vols)
        assert min(lows) <= vwap <= max(highs)

    def test_vwap_weights_toward_higher_volume_bar(self):
        from indicator_volume import calc_vwap

        # 저가/거래량이 큰 봉 쪽으로 VWAP이 쏠려야 함
        highs = [100.0, 200.0]
        lows = [100.0, 200.0]
        closes = [100.0, 200.0]
        vols = [1_000_000.0, 1.0]
        vwap = calc_vwap(highs, lows, closes, vols)
        assert vwap < 101.0


class TestGetVwapMinute:
    def test_uses_only_today_session_candles(self):
        from indicator_volume import get_vwap_minute

        today = datetime.now().strftime("%Y%m%d")
        candles = [
            _min_candle(f"{today}150000", 110.0, 111.0, 109.0, 100.0),
            _min_candle(f"{today}093000", 100.0, 101.0, 99.0, 50.0),
            _min_candle("20200101090000", 999.0, 999.0, 999.0, 999.0),  # 과거 세션(제외 대상)
        ]
        with patch("indicator_volume.fetch_minute_candles", new=AsyncMock(return_value=candles)), \
             patch("indicator_volume.filter_closed_minute_candles", side_effect=lambda c, _: c):
            result = _run(get_vwap_minute("token", "005930", tic_scope="1"))

        assert result.vwap is not None
        assert result.cur_prc == 110.0  # 최신순 index0

    def test_no_candles_returns_empty_result(self):
        from indicator_volume import get_vwap_minute

        with patch("indicator_volume.fetch_minute_candles", new=AsyncMock(return_value=[])), \
             patch("indicator_volume.filter_closed_minute_candles", side_effect=lambda c, _: c):
            result = _run(get_vwap_minute("token", "005930", tic_scope="1"))

        assert result.vwap is None


class TestMfiResultProperties:
    def test_is_oversold_and_turning_up(self):
        from indicator_volume import MFIResult

        r = MFIResult(mfi=25.0, mfi_prev=15.0)
        assert r.is_turning_up() is True

        oversold = MFIResult(mfi=15.0)
        assert oversold.is_oversold is True


class TestVwapResultProperties:
    def test_pct_from_vwap(self):
        from indicator_volume import VWAPResult

        r = VWAPResult(vwap=100.0, cur_prc=105.0)
        assert r.is_above_vwap is True
        assert r.pct_from_vwap() == 5.0
