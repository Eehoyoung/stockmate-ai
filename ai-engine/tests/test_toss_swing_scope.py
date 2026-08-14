import asyncio
import os
import sys
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import queue_worker
import analyzer
from strategy_meta import SWING_STRATEGIES


def _run(coro):
    return asyncio.run(coro)


def _patch_market_ctx_deps(monkeypatch, *, toss_risk_return=None):
    async def _empty(*args, **kwargs):
        return {}

    async def _empty_list(*args, **kwargs):
        return []

    monkeypatch.setattr(queue_worker, "get_tick_data", _empty)
    monkeypatch.setattr(queue_worker, "get_hoga_data", _empty)
    monkeypatch.setattr(queue_worker, "get_avg_cntr_strength", AsyncMock(return_value=0.0))
    monkeypatch.setattr(queue_worker, "get_vi_status", _empty)
    monkeypatch.setattr(queue_worker, "get_market_freshness", _empty)
    monkeypatch.setattr(queue_worker, "get_sector_overheat_count", AsyncMock(return_value=0))
    monkeypatch.setattr(queue_worker, "get_market_index_flu_rt", _empty)
    monkeypatch.setattr(queue_worker, "get_stock_market_cap", AsyncMock(return_value=None))
    monkeypatch.setattr(queue_worker, "get_market_index_exp_flu_rt", _empty)
    monkeypatch.setattr(queue_worker, "get_market_investor_flow", _empty)
    monkeypatch.setattr(queue_worker, "_resolve_signal_market_type", AsyncMock(return_value="001"))

    fetch_mock = AsyncMock(return_value=toss_risk_return or {})
    monkeypatch.setattr(queue_worker, "fetch_stock_risk_context", fetch_mock)
    series_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(queue_worker, "get_market_investor_flow_series", series_mock)
    return fetch_mock, series_mock


class TestQueueWorkerTossScope:
    def test_toss_risk_strategies_equals_swing_strategies(self):
        assert queue_worker._TOSS_RISK_STRATEGIES == SWING_STRATEGIES

    def test_swing_strategy_triggers_toss_fetch(self, monkeypatch):
        fetch_mock, series_mock = _patch_market_ctx_deps(
            monkeypatch, toss_risk_return={"short_selling": {"shortSellingAmountRate": "0.1"}}
        )
        ctx = _run(queue_worker._build_market_ctx(
            object(), "005930", signal={"strategy": "S8_GOLDEN_CROSS"},
        ))
        fetch_mock.assert_called_once()
        assert "toss_risk" in ctx
        # 시장수급 추세도 스윙 전략에서 함께 조회한다 (kospi/kosdaq 2회)
        assert series_mock.await_count == 2

    def test_day_strategy_skips_toss_fetch(self, monkeypatch):
        fetch_mock, series_mock = _patch_market_ctx_deps(monkeypatch)
        ctx = _run(queue_worker._build_market_ctx(
            object(), "005930", signal={"strategy": "S1_GAP_OPEN"},
        ))
        fetch_mock.assert_not_called()
        series_mock.assert_not_called()
        assert "toss_risk" not in ctx
        assert "investor_flow_trend" not in ctx

    def test_swing_strategy_populates_investor_flow_trend_when_series_available(self, monkeypatch):
        fetch_mock, series_mock = _patch_market_ctx_deps(monkeypatch)
        series_mock.side_effect = [
            [{"ts": "t1", "foreigner_net": 100}, {"ts": "t2", "foreigner_net": 300}],  # kospi
            [],  # kosdaq — 표본 부족으로 요약 없음
        ]
        ctx = _run(queue_worker._build_market_ctx(
            object(), "005930", signal={"strategy": "S8_GOLDEN_CROSS"},
        ))
        assert "investor_flow_trend" in ctx
        assert ctx["investor_flow_trend"]["kospi"]["foreigner_net_delta"] == 200
        assert "kosdaq" not in ctx["investor_flow_trend"]


class TestAnalyzerTossScope:
    def test_swing_strategy_fetches_when_missing(self, monkeypatch):
        fetch_mock = AsyncMock(return_value={"short_selling": {"shortSellingAmountRate": "0.1"}})
        monkeypatch.setattr(analyzer, "_toss_fetch_stock_risk_context", fetch_mock)
        monkeypatch.setattr(analyzer, "_get_claude_client", lambda: None)
        monkeypatch.setattr(analyzer, "_build_user_message", lambda signal, ctx, rule_score: "prompt")
        monkeypatch.setattr(analyzer, "_build_system_prompt", lambda signal: "system")

        async def _run_and_check():
            signal = {"strategy": "S8_GOLDEN_CROSS", "stk_cd": "005930"}
            try:
                await analyzer.analyze_signal(signal, {}, 70.0, rdb=None)
            except Exception:
                pass
            fetch_mock.assert_called_once()

        _run(_run_and_check())

    def test_day_strategy_never_fetches(self, monkeypatch):
        fetch_mock = AsyncMock(return_value={"short_selling": {"shortSellingAmountRate": "0.1"}})
        monkeypatch.setattr(analyzer, "_toss_fetch_stock_risk_context", fetch_mock)
        monkeypatch.setattr(analyzer, "_get_claude_client", lambda: None)
        monkeypatch.setattr(analyzer, "_build_user_message", lambda signal, ctx, rule_score: "prompt")
        monkeypatch.setattr(analyzer, "_build_system_prompt", lambda signal: "system")

        async def _run_and_check():
            signal = {"strategy": "S1_GAP_OPEN", "stk_cd": "005930"}
            try:
                await analyzer.analyze_signal(signal, {}, 70.0, rdb=None)
            except Exception:
                pass
            fetch_mock.assert_not_called()

        _run(_run_and_check())


class TestAnalyzerSwingPromptFormatters:
    def test_investor_flow_trend_line_renders_signed_eok(self):
        trend = {"kospi": {"foreigner_net_delta": 1.2e10, "institution_net_delta": -3.0e9}}
        line = analyzer._fmt_investor_flow_trend_line(trend)
        assert "코스피" in line
        assert "+120억" in line
        assert "-30억" in line

    def test_investor_flow_trend_line_empty_when_no_data(self):
        assert analyzer._fmt_investor_flow_trend_line(None) == ""
        assert analyzer._fmt_investor_flow_trend_line({}) == ""

    def test_swing_block_combines_trend_and_risk_under_one_header(self):
        market_ctx = {
            "investor_flow_trend": {"kospi": {"foreigner_net_delta": 5.0e9}},
            "toss_risk": {"short_selling": {"shortSellingAmountRate": "0.1"}},
        }
        combined = (
            analyzer._fmt_investor_flow_trend_line(market_ctx["investor_flow_trend"])
            + analyzer._fmt_toss_risk_line(market_ctx["toss_risk"])
        )
        assert "시장수급추세" in combined
        assert "종목리스크(토스)" in combined

    def test_swing_block_empty_for_day_strategy_ctx(self):
        market_ctx = {}
        combined = (
            analyzer._fmt_investor_flow_trend_line(market_ctx.get("investor_flow_trend"))
            + analyzer._fmt_toss_risk_line(market_ctx.get("toss_risk"))
        )
        assert combined == ""
