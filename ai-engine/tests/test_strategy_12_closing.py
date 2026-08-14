import asyncio
import logging
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

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


def _tp_sl_mock():
    tp_sl = MagicMock()
    tp_sl.to_signal_fields.return_value = {"rr_ratio": 2.0}
    return tp_sl


class TestScanClosingBuy:
    def test_no_gainers_logs_summary_and_returns_empty(self, caplog):
        from strategy_12_closing import scan_closing_buy

        with patch("strategy_12_closing.fetch_top_gainers_paged", AsyncMock(return_value=[])), \
             patch("strategy_12_closing.fetch_inst_netbuy_set", AsyncMock(return_value=(set(), True))), \
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
             patch("strategy_12_closing.fetch_inst_netbuy_set", AsyncMock(return_value=(set(), True))), \
             caplog.at_level(logging.INFO, logger="strategy_12_closing"):
            result = _run(scan_closing_buy("token"))

        assert result == []
        summary_logs = [r for r in caplog.records if "[S12][scan_summary]" in r.message]
        assert len(summary_logs) == 1
        msg = summary_logs[0].message
        assert "candidate_count=2" in msg
        assert "evaluated=2" in msg
        assert "pass=0" in msg
        assert "not_inst_netbuy" in msg

    def test_inst_fetch_failure_skips_scan_instead_of_rejecting_all(self, caplog):
        """ka10063 조회 실패를 '기관 미매수'로 위장하지 않는다.

        실패 시 전 종목을 not_inst_netbuy로 떨구면 스캔이 정상 동작한 것처럼
        보인다. 별도 사유로 남기고 사이클을 건너뛰어야 한다."""
        from strategy_12_closing import scan_closing_buy

        gainers = [_gainer("005930"), _gainer("068270")]

        with patch("strategy_12_closing.fetch_top_gainers_paged", AsyncMock(return_value=gainers)), \
             patch("strategy_12_closing.fetch_inst_netbuy_set", AsyncMock(return_value=(set(), False))), \
             caplog.at_level(logging.INFO, logger="strategy_12_closing"):
            result = _run(scan_closing_buy("token"))

        assert result == []
        summary_logs = [r for r in caplog.records if "[S12][scan_summary]" in r.message]
        assert len(summary_logs) == 1
        msg = summary_logs[0].message
        assert "inst_netbuy_fetch_failed" in msg
        assert "not_inst_netbuy" not in msg

    def test_flu_rt_or_cntr_str_out_of_range_reason_recorded(self, caplog):
        from strategy_12_closing import scan_closing_buy

        gainers = [_gainer("005930", flu_rt="+1.0", cntr_str="120")]  # flu_rt < MIN_FLU_RT(4.0)

        with patch("strategy_12_closing.fetch_top_gainers_paged", AsyncMock(return_value=gainers)), \
             patch("strategy_12_closing.fetch_inst_netbuy_set", AsyncMock(return_value=({"005930"}, True))), \
             caplog.at_level(logging.INFO, logger="strategy_12_closing"):
            result = _run(scan_closing_buy("token"))

        assert result == []
        summary_logs = [r for r in caplog.records if "[S12][scan_summary]" in r.message]
        assert "flu_rt_or_cntr_str_out_of_range" in summary_logs[0].message

    def test_stock_outside_pool_is_no_longer_hard_rejected(self, caplog):
        """핵심 회귀 (2026-08-14): 풀(ka10032 거래대금상위)은 gainers(ka10027
        등락률상위)와 유니버스가 달라서, AND로 걸면 기관 필터를 통과한 종목이
        전부 여기서 잘렸다(하루 28,000평가 0통과). 풀 밖 종목도 신호가 나와야
        한다."""
        from strategy_12_closing import scan_closing_buy

        gainers = [_gainer("005930")]
        rdb = AsyncMock()

        async def lrange(key, start, end):
            if key == "candidates:s12:001":
                return ["999999"]  # 005930은 풀에 없음
            return []

        rdb.lrange = AsyncMock(side_effect=lrange)

        with patch("strategy_12_closing.fetch_top_gainers_paged", AsyncMock(return_value=gainers)), \
             patch("strategy_12_closing.fetch_inst_netbuy_set", AsyncMock(return_value=({"005930"}, True))), \
             patch("strategy_12_closing.fetch_daily_candles", AsyncMock(return_value=[])), \
             patch("strategy_12_closing.calc_tp_sl", MagicMock(return_value=_tp_sl_mock())), \
             patch("strategy_12_closing.fetch_stk_nm", AsyncMock(return_value="삼성전자")), \
             caplog.at_level(logging.INFO, logger="strategy_12_closing"):
            result = _run(scan_closing_buy("token", market="001", rdb=rdb))

        assert len(result) == 1
        assert result[0]["stk_cd"] == "005930"
        summary_logs = [r for r in caplog.records if "[S12][scan_summary]" in r.message]
        assert "not_in_pool" not in summary_logs[0].message

    def test_pool_membership_adds_score_bonus(self):
        """풀은 하드 게이트에서 빠졌지만 유동성 근거로서 가점은 남는다."""
        import strategy_12_closing as s12

        gainers = [_gainer("005930")]

        def _scan(pool_codes):
            rdb = AsyncMock()

            async def lrange(key, start, end):
                if key == "candidates:s12:001":
                    return pool_codes
                return []

            rdb.lrange = AsyncMock(side_effect=lrange)

            with patch("strategy_12_closing.fetch_top_gainers_paged", AsyncMock(return_value=gainers)), \
                 patch("strategy_12_closing.fetch_inst_netbuy_set", AsyncMock(return_value=({"005930"}, True))), \
                 patch("strategy_12_closing.fetch_daily_candles", AsyncMock(return_value=[])), \
                 patch("strategy_12_closing.calc_tp_sl", MagicMock(return_value=_tp_sl_mock())), \
                 patch("strategy_12_closing.fetch_stk_nm", AsyncMock(return_value="삼성전자")):
                return _run(s12.scan_closing_buy("token", market="001", rdb=rdb))

        in_pool = _scan(["005930"])
        out_pool = _scan(["999999"])

        assert len(in_pool) == 1 and len(out_pool) == 1
        assert in_pool[0]["score"] - out_pool[0]["score"] == s12.POOL_BONUS
