import asyncio
import logging
import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _gainer(stk_cd, flu_rt="+5.0", cntr_str="120", cur_prc="10000"):
    return {
        "stk_cd": stk_cd,
        "stk_nm": f"stock{stk_cd}",
        "flu_rt": flu_rt,
        "cntr_str": cntr_str,
        "cur_prc": cur_prc,
        "buy_req": "100",
        "sel_req": "50",
    }


class TestScanClosingBuy:
    def test_no_gainers_logs_summary_and_returns_empty(self, caplog):
        from strategy_12_closing import scan_closing_buy

        with patch("strategy_12_closing.fetch_top_gainers_paged", AsyncMock(return_value=[])), \
             patch("strategy_12_closing.fetch_inst_netbuy_set", AsyncMock(return_value=set())), \
             caplog.at_level(logging.INFO, logger="strategy_12_closing"):
            result = _run(scan_closing_buy("token"))

        assert result == []
        summary_logs = [r for r in caplog.records if "[S12][scan_summary]" in r.message]
        assert len(summary_logs) == 1
        assert "candidate_count=0" in summary_logs[0].message

    def test_all_rejected_still_logs_summary_with_reasons(self, caplog):
        """운영 관측성 회귀 테스트: pass=0이어도 [S12][scan_summary] INFO 로그가
        항상 찍히고, 어떤 사유로 탈락했는지 구분되어야 한다."""
        from strategy_12_closing import scan_closing_buy

        gainers = [_gainer("005930"), _gainer("068270")]

        with patch("strategy_12_closing.fetch_top_gainers_paged", AsyncMock(return_value=gainers)), \
             patch("strategy_12_closing.fetch_inst_netbuy_set", AsyncMock(return_value=set())), \
             caplog.at_level(logging.INFO, logger="strategy_12_closing"):
            result = _run(scan_closing_buy("token"))

        assert result == []
        summary_logs = [r for r in caplog.records if "[S12][scan_summary]" in r.message]
        assert len(summary_logs) == 1
        msg = summary_logs[0].message
        assert "candidate_count=2" in msg
        assert "evaluated=2" in msg
        assert "pass=0" in msg
        assert "inst_netbuy_failed" in msg

    def test_flu_rt_or_cntr_str_out_of_range_reason_recorded(self, caplog):
        from strategy_12_closing import scan_closing_buy

        gainers = [_gainer("005930", flu_rt="+1.0", cntr_str="120")]  # flu_rt < MIN_FLU_RT(4.0)

        with patch("strategy_12_closing.fetch_top_gainers_paged", AsyncMock(return_value=gainers)), \
             patch("strategy_12_closing.fetch_inst_netbuy_set", AsyncMock(return_value={"005930"})), \
             caplog.at_level(logging.INFO, logger="strategy_12_closing"):
            result = _run(scan_closing_buy("token"))

        assert result == []
        summary_logs = [r for r in caplog.records if "[S12][scan_summary]" in r.message]
        assert "flu_rt_or_cntr_str_out_of_range" in summary_logs[0].message

    def test_pool_filter_reason_recorded(self, monkeypatch, caplog):
        from strategy_12_closing import scan_closing_buy

        gainers = [_gainer("005930")]
        rdb = AsyncMock()

        async def lrange(key, start, end):
            if key == "candidates:s12:001":
                return ["999999"]
            return []

        rdb.lrange = AsyncMock(side_effect=lrange)

        with patch("strategy_12_closing.fetch_top_gainers_paged", AsyncMock(return_value=gainers)), \
             patch("strategy_12_closing.fetch_inst_netbuy_set", AsyncMock(return_value={"005930"})), \
             caplog.at_level(logging.INFO, logger="strategy_12_closing"):
            result = _run(scan_closing_buy("token", market="001", rdb=rdb))

        assert result == []
        summary_logs = [r for r in caplog.records if "[S12][scan_summary]" in r.message]
        assert "not_in_pool" in summary_logs[0].message
