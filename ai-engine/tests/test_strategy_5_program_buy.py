import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _MockResponse:
    def __init__(self, payload_key, items, cont_yn="N", next_key=""):
        self._payload_key = payload_key
        self._items = items
        self.headers = {"cont-yn": cont_yn, "next-key": next_key}

    def json(self):
        return {self._payload_key: self._items, "return_code": 0}

    def raise_for_status(self):
        return None


class _MockClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.post = AsyncMock(side_effect=self._post)

    async def _post(self, url, headers=None, json=None):
        if not self._responses:
            raise AssertionError("No mock response left")
        return self._responses.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


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
    def test_default_uses_expanded_candidate_extra_check_limit(self, monkeypatch):
        from strategy_5_program_buy import scan_program_buy

        monkeypatch.delenv("S5_TWO_STAGE_ENABLED", raising=False)
        check_extra = AsyncMock(return_value=(False, "ma5_failed"))

        with patch("strategy_5_program_buy.fetch_progra_netbuy", AsyncMock(return_value=_prog_map())), \
             patch("strategy_5_program_buy.fetch_frgn_inst_upper", AsyncMock(return_value=set(_prog_map().keys()))), \
             patch("strategy_5_program_buy.check_extra_conditions", check_extra), \
             patch("strategy_5_program_buy.asyncio.sleep", new=AsyncMock()):
            result = _run(scan_program_buy("token"))

        assert result == []
        assert check_extra.await_count == 20

    def test_two_stage_flag_uses_runtime_env_limit(self, monkeypatch):
        from strategy_5_program_buy import scan_program_buy

        monkeypatch.setenv("S5_TWO_STAGE_ENABLED", "1")
        monkeypatch.setenv("S5_TWO_STAGE_LIMIT", "8")
        check_extra = AsyncMock(return_value=(False, "ma5_failed"))

        with patch("strategy_5_program_buy.fetch_progra_netbuy", AsyncMock(return_value=_prog_map())), \
             patch("strategy_5_program_buy.fetch_frgn_inst_upper", AsyncMock(return_value=set(_prog_map().keys()))), \
             patch("strategy_5_program_buy.check_extra_conditions", check_extra), \
             patch("strategy_5_program_buy.asyncio.sleep", new=AsyncMock()):
            result = _run(scan_program_buy("token"))

        assert result == []
        assert check_extra.await_count == 8


class TestStockCodeNormalization:
    """ka90003/ka90009 응답의 '_AL' 접미사를 정규화하지 않으면 두 세트의 교집합이
    항상 비게 되는 회귀 방지 테스트 (S5가 몇 달간 신호를 하나도 못 낸 원인)."""

    def test_fetch_progra_netbuy_strips_kiwoom_suffix(self):
        from strategy_5_program_buy import fetch_progra_netbuy

        client = _MockClient([
            _MockResponse("prm_netprps_upper_50", [
                {"stk_cd": "000660_AL", "stk_nm": "SK하이닉스", "cur_prc": "+150000",
                 "prm_netprps_amt": "1000", "flu_rt": "+5.0"},
            ]),
        ])

        with patch("strategy_5_program_buy.kiwoom_client", return_value=client):
            result = _run(fetch_progra_netbuy("token", "001"))

        assert "000660_AL" not in result
        assert "000660" in result
        assert result["000660"]["net_buy_amt"] == 1_000_000_000

    def test_fetch_frgn_inst_upper_strips_kiwoom_suffix(self):
        from strategy_5_program_buy import fetch_frgn_inst_upper

        client = _MockClient([
            _MockResponse("frgnr_orgn_trde_upper", [
                {"for_netprps_stk_cd": "000660_AL"},
            ]),
        ])

        with patch("strategy_5_program_buy.kiwoom_client", return_value=client):
            result = _run(fetch_frgn_inst_upper("token", "001"))

        assert result == {"000660"}

    def test_program_and_foreign_overlap_after_normalization(self, monkeypatch):
        """두 소스가 접미사 유무만 다르게 같은 종목을 반환해도 교집합이 정상 도출되는지 확인."""
        from strategy_5_program_buy import scan_program_buy

        monkeypatch.delenv("S5_TWO_STAGE_ENABLED", raising=False)
        prog_map = {"000660": {"net_buy_amt": 100, "stk_nm": "SK하이닉스", "cur_prc": 150000, "flu_rt": 5.0}}
        check_extra = AsyncMock(return_value=(False, "ma5_failed"))

        with patch("strategy_5_program_buy.fetch_progra_netbuy", AsyncMock(return_value=prog_map)), \
             patch("strategy_5_program_buy.fetch_frgn_inst_upper", AsyncMock(return_value={"000660"})), \
             patch("strategy_5_program_buy.check_extra_conditions", check_extra), \
             patch("strategy_5_program_buy.asyncio.sleep", new=AsyncMock()):
            _run(scan_program_buy("token"))

        assert check_extra.await_count == 1
        assert check_extra.await_args.args[1] == "000660"


class TestCheckExtraConditionsReasons:
    """check_extra_conditions()가 실패 사유(inst_netbuy_failed/ma5_failed/api_error)를
    구분해서 반환하는지, 그리고 ka10044 stk_cd 접미사를 정규화해서 비교하는지 검증."""

    def _chart_response(self, prices):
        return _MockResponse(
            "stk_min_pole_chart_qry",
            [{"cur_prc": str(p)} for p in prices],
        )

    def test_inst_netbuy_failed_when_stock_not_in_ka10044_list(self):
        from strategy_5_program_buy import check_extra_conditions

        client = _MockClient([
            _MockResponse("daly_orgn_trde_stk", [{"stk_cd": "999999"}]),
        ])

        with patch("strategy_5_program_buy.kiwoom_client", return_value=client):
            ok, reason = _run(check_extra_conditions("token", "000660", "001"))

        assert ok is False
        assert reason == "inst_netbuy_failed"

    def test_ka10044_stk_cd_suffix_is_normalized_before_comparison(self):
        """ka90003/ka90009와 동일하게 ka10044 응답도 '_AL' 접미사가 붙을 수 있다.
        정규화 없이 비교하면 항상 inst_netbuy_failed로 오탈락한다 (회귀 방지)."""
        from strategy_5_program_buy import check_extra_conditions

        client = _MockClient([
            _MockResponse("daly_orgn_trde_stk", [{"stk_cd": "000660_AL"}]),
            self._chart_response([1000, 900, 900, 900, 900]),  # cur_prc >= ma5
        ])

        with patch("strategy_5_program_buy.kiwoom_client", return_value=client):
            ok, reason = _run(check_extra_conditions("token", "000660", "001"))

        assert ok is True
        assert reason is None

    def test_ma5_failed_when_price_below_ma5(self):
        from strategy_5_program_buy import check_extra_conditions

        client = _MockClient([
            _MockResponse("daly_orgn_trde_stk", [{"stk_cd": "000660"}]),
            self._chart_response([800, 900, 900, 900, 900]),  # cur_prc < ma5
        ])

        with patch("strategy_5_program_buy.kiwoom_client", return_value=client):
            ok, reason = _run(check_extra_conditions("token", "000660", "001"))

        assert ok is False
        assert reason == "ma5_failed"

    def test_api_error_when_ka10044_response_invalid(self):
        from strategy_5_program_buy import check_extra_conditions

        class _ErrorResponse(_MockResponse):
            def json(self):
                return {"return_code": 900, "return_msg": "internal error"}

        client = _MockClient([_ErrorResponse("daly_orgn_trde_stk", [])])

        with patch("strategy_5_program_buy.kiwoom_client", return_value=client):
            ok, reason = _run(check_extra_conditions("token", "000660", "001"))

        assert ok is False
        assert reason == "api_error"

    def test_reject_reason_flows_into_scan_summary(self, monkeypatch):
        """scan_program_buy가 check_extra_conditions의 세분화된 사유를 reject 집계에 반영하는지 확인."""
        from strategy_5_program_buy import scan_program_buy

        monkeypatch.delenv("S5_TWO_STAGE_ENABLED", raising=False)
        prog_map = {"000660": {"net_buy_amt": 100, "stk_nm": "SK하이닉스", "cur_prc": 150000, "flu_rt": 5.0}}
        check_extra = AsyncMock(return_value=(False, "ma5_failed"))

        with patch("strategy_5_program_buy.fetch_progra_netbuy", AsyncMock(return_value=prog_map)), \
             patch("strategy_5_program_buy.fetch_frgn_inst_upper", AsyncMock(return_value={"000660"})), \
             patch("strategy_5_program_buy.check_extra_conditions", check_extra), \
             patch("strategy_5_program_buy.asyncio.sleep", new=AsyncMock()), \
             patch("strategy_5_program_buy.logger") as mock_logger:
            result = _run(scan_program_buy("token"))

        assert result == []
        summary_calls = [
            c for c in mock_logger.info.call_args_list
            if c.args and "[S5][scan_summary]" in c.args[0]
        ]
        assert summary_calls, "scan_summary 로그가 호출되지 않음"
        # rejects=%s 인자에 세분화된 사유(ma5_failed)가 담겨 있어야 한다
        assert "ma5_failed" in str(summary_calls[-1].args)


class TestCheckExtraConditionsBusinessDayOffset:
    """영업일 보정 로직(월=3, 일=2, 그 외=1)이 정상 동작하는지 확인."""

    def _run_and_capture_strt_dt(self, fixed_now, monkeypatch):
        import strategy_5_program_buy as s5

        class _FixedDatetime(s5.datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_now

        monkeypatch.setattr(s5, "datetime", _FixedDatetime)

        client = _MockClient([
            _MockResponse("daly_orgn_trde_stk", [{"stk_cd": "000660"}]),
            self._chart_response([1000, 900, 900, 900, 900]),
        ])

        with patch("strategy_5_program_buy.kiwoom_client", return_value=client):
            _run(s5.check_extra_conditions("token", "000660", "001"))

        first_call = client.post.await_args_list[0]
        return first_call.kwargs["json"]["strt_dt"]

    def _chart_response(self, prices):
        return _MockResponse(
            "stk_min_pole_chart_qry",
            [{"cur_prc": str(p)} for p in prices],
        )

    def test_wednesday_2026_08_05_uses_previous_day(self, monkeypatch):
        from datetime import datetime as real_datetime, timezone, timedelta

        kst = timezone(timedelta(hours=9))
        fixed_now = real_datetime(2026, 8, 5, 10, 0, 0, tzinfo=kst)  # Wednesday
        assert fixed_now.weekday() == 2

        strt_dt = self._run_and_capture_strt_dt(fixed_now, monkeypatch)
        assert strt_dt == "20260804"  # 화요일 (직전 영업일)

    def test_monday_uses_previous_friday(self, monkeypatch):
        from datetime import datetime as real_datetime, timezone, timedelta

        kst = timezone(timedelta(hours=9))
        fixed_now = real_datetime(2026, 8, 3, 10, 0, 0, tzinfo=kst)  # Monday
        assert fixed_now.weekday() == 0

        strt_dt = self._run_and_capture_strt_dt(fixed_now, monkeypatch)
        assert strt_dt == "20260731"  # 직전 금요일
