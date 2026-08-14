import asyncio
from unittest.mock import AsyncMock, patch

from claude_analyst import _extract_json_block, _normalize_action_response


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _daily_candle(cur_prc: float) -> dict:
    return {"cur_prc": str(cur_prc), "high_pric": str(cur_prc + 5),
            "low_pric": str(cur_prc - 5), "trde_qty": "10000"}


def test_extract_json_block_from_fenced_text():
    payload = """```json
    {"action":"ENTER","confidence":"HIGH","reasons":["a"]}
    ```"""
    parsed = _extract_json_block(payload)
    assert parsed["action"] == "ENTER"
    assert parsed["confidence"] == "HIGH"


def test_extract_json_block_repairs_missing_comma_between_fields():
    payload = """{
      "action": "HOLD",
      "confidence": "LOW",
      "reasons": ["체결강도 미달"]
      "risk_factors": ["분봉 모멘텀 약화"],
      "action_guide": ["재평가 필요"],
      "tp_sl": {"take_profit": 10000, "stop_loss": 9300}
      "summary": "관망 우세"
    }"""

    parsed = _extract_json_block(payload)

    assert parsed["action"] == "HOLD"
    assert parsed["risk_factors"] == ["분봉 모멘텀 약화"]
    assert parsed["summary"] == "관망 우세"


def test_normalize_action_response_defaults_and_sanitizes():
    parsed = _normalize_action_response({
        "action": "watch",
        "confidence": "strong",
        "reasons": "momentum",
        "risk_factors": ["volatility", ""],
        "action_guide": None,
        "tp_sl": {"take_profit": "88000", "stop_loss": "83000"},
    })

    assert parsed["action"] == "HOLD"
    assert parsed["confidence"] == "LOW"
    assert parsed["reasons"] == ["momentum"]
    assert parsed["risk_factors"] == ["volatility"]
    assert parsed["tp_sl"]["take_profit"] == 88000.0
    assert parsed["tp_sl"]["stop_loss"] == 83000.0
    assert parsed["portfolio_not_linked"] is True


def test_build_daily_indicators_includes_daily_stochastic():
    """2026-08-06: 일봉 스토캐스틱을 daily_indicators에 배선했는지 회귀 검증.

    RSI/MACD/Bollinger/ATR은 원래부터 일봉으로 조회되는데 Stochastic만
    분봉 전용이었던 비대칭을 해소한 변경. get_stochastic_daily가 실제로
    호출되고 그 결과가 stoch_k/stoch_d로 반영되는지 확인한다.
    """
    from claude_analyst import _build_daily_indicators
    from indicator_stochastic import StochasticResult

    candles = [_daily_candle(100 + i) for i in range(120)]
    stoch_result = StochasticResult(k=42.0, d=38.0, k_prev=40.0, d_prev=37.0)

    with patch("claude_analyst.fetch_daily_candles", new=AsyncMock(return_value=candles)), \
         patch("claude_analyst.get_rsi_daily", new=AsyncMock(return_value=None)), \
         patch("claude_analyst.get_macd_daily", new=AsyncMock(return_value=None)), \
         patch("claude_analyst.get_bollinger_daily", new=AsyncMock(return_value=None)), \
         patch("claude_analyst.get_atr_daily", new=AsyncMock(return_value=None)), \
         patch("claude_analyst.get_stochastic_daily", new=AsyncMock(return_value=stoch_result)) as mocked_stoch:
        result, _ = _run(_build_daily_indicators("token", "005930", fallback_price=100.0))

    mocked_stoch.assert_awaited_once_with("token", "005930")
    assert result["stoch_k"] == 42.0
    assert result["stoch_d"] == 38.0


def test_build_daily_indicators_stoch_none_when_no_token():
    from claude_analyst import _build_daily_indicators

    result, _ = _run(_build_daily_indicators("", "005930", fallback_price=100.0))

    assert result["stoch_k"] is None
    assert result["stoch_d"] is None
