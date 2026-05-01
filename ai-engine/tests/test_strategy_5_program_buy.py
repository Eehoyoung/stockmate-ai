import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _prog_map(size=20):
    return {
        f"{idx:06d}": {
            "net_buy_amt": size - idx,
            "stk_nm": f"stock{idx}",
            "cur_prc": 1000,
            "flu_rt": 0.0,
        }
        for idx in range(size)
    }


class TestScanProgramBuy:
    def test_default_keeps_existing_15_candidate_extra_check_limit(self, monkeypatch):
        from strategy_5_program_buy import scan_program_buy

        monkeypatch.delenv("S5_TWO_STAGE_ENABLED", raising=False)
        check_extra = AsyncMock(return_value=False)

        with patch("strategy_5_program_buy.fetch_progra_netbuy", AsyncMock(return_value=_prog_map())), \
             patch("strategy_5_program_buy.fetch_frgn_inst_upper", AsyncMock(return_value=set(_prog_map().keys()))), \
             patch("strategy_5_program_buy.check_extra_conditions", check_extra), \
             patch("strategy_5_program_buy.asyncio.sleep", new=AsyncMock()):
            result = _run(scan_program_buy("token"))

        assert result == []
        assert check_extra.await_count == 15

    def test_two_stage_flag_reduces_extra_check_limit(self, monkeypatch):
        from strategy_5_program_buy import scan_program_buy

        monkeypatch.setenv("S5_TWO_STAGE_ENABLED", "1")
        monkeypatch.setenv("S5_TWO_STAGE_LIMIT", "8")
        check_extra = AsyncMock(return_value=False)

        with patch("strategy_5_program_buy.fetch_progra_netbuy", AsyncMock(return_value=_prog_map())), \
             patch("strategy_5_program_buy.fetch_frgn_inst_upper", AsyncMock(return_value=set(_prog_map().keys()))), \
             patch("strategy_5_program_buy.check_extra_conditions", check_extra), \
             patch("strategy_5_program_buy.asyncio.sleep", new=AsyncMock()):
            result = _run(scan_program_buy("token"))

        assert result == []
        assert check_extra.await_count == 8
