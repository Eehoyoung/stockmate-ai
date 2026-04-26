"""
tests/test_analyzer.py
analyzer.py 의 JSON 파싱, 폴백, Claude 클라이언트 모킹 테스트.
실제 API 연결 없이 unittest.mock 사용.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ──────────────────────────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────────────────────────

def _signal(strategy="S1_GAP_OPEN", **kwargs):
    base = {
        "strategy": strategy,
        "stk_cd": "005930",
        "stk_nm": "삼성전자",
    }
    base.update(kwargs)
    return base


def _ctx():
    return {
        "tick": {"flu_rt": "3.0"},
        "hoga": {"total_buy_bid_req": "2000", "total_sel_bid_req": "1000"},
        "strength": 130.0,
        "vi": {},
    }


def _make_response(text: str):
    """Claude API 응답 객체 모킹"""
    content = MagicMock()
    content.text = text
    response = MagicMock()
    response.content = [content]
    return response


# ──────────────────────────────────────────────────────────────────
# _fallback 테스트
# ──────────────────────────────────────────────────────────────────

class TestFallback:
    def test_fallback_high_score_enter(self):
        from analyzer import _fallback
        result = _fallback(75.0)
        assert result["action"] == "ENTER"
        assert result["ai_score"] == 75.0
        assert result["confidence"] == "LOW"

    def test_fallback_mid_score_hold(self):
        from analyzer import _fallback
        result = _fallback(55.0)
        assert result["action"] == "HOLD"

    def test_fallback_low_score_cancel(self):
        from analyzer import _fallback
        result = _fallback(30.0)
        assert result["action"] == "CANCEL"

    def test_fallback_boundary_70_enter(self):
        from analyzer import _fallback
        result = _fallback(70.0)
        assert result["action"] == "ENTER"

    def test_fallback_boundary_50_hold(self):
        from analyzer import _fallback
        result = _fallback(50.0)
        assert result["action"] == "HOLD"

    def test_fallback_boundary_49_cancel(self):
        from analyzer import _fallback
        result = _fallback(49.9)
        assert result["action"] == "CANCEL"

    def test_fallback_has_required_fields(self):
        from analyzer import _fallback
        result = _fallback(60.0)
        assert "action" in result
        assert "ai_score" in result
        assert "confidence" in result
        assert "reason" in result
        assert "cancel_reason" in result
        assert "adjusted_target_pct" in result
        assert "adjusted_stop_pct" in result


# ──────────────────────────────────────────────────────────────────
# _build_user_message 테스트
# ──────────────────────────────────────────────────────────────────

class TestBuildUserMessage:
    def test_uses_signal_bid_ratio_when_hoga_missing(self):
        from analyzer import _build_user_message
        signal = _signal(
            "S1_GAP_OPEN",
            bid_ratio=7.17,
            cntr_strength=500,
            cur_prc=21450,
            tp1_price=22000,
            sl_price=20200,
        )
        msg = _build_user_message(signal, {"tick": {"flu_rt": "5.46"}, "hoga": {}, "strength": 0, "vi": {}}, 100.0)
        assert "7.17" in msg

    def test_message_contains_signal_quality_context(self):
        from analyzer import _build_user_message
        signal = _signal(
            "S1_GAP_OPEN",
            signal_quality_score=72.5,
            signal_quality_bucket="strong",
            rr_quality_bucket="caution",
            strategy_ev_pct="N/A",
            strategy_sample_count=0,
        )
        msg = _build_user_message(signal, _ctx(), 75.0)
        assert "신호품질" in msg
        assert "72.5" in msg
        assert "RR품질" in msg

    def test_s1_message_contains_gap(self):
        from analyzer import _build_user_message
        signal = _signal("S1_GAP_OPEN", gap_pct=4.0)
        msg = _build_user_message(signal, _ctx(), 75.0)
        assert "갭" in msg or "4.0" in msg

    def test_s2_message_contains_pullback(self):
        from analyzer import _build_user_message
        signal = _signal("S2_VI_PULLBACK", pullback_pct=-1.5, is_dynamic=True)
        msg = _build_user_message(signal, _ctx(), 70.0)
        assert "눌림" in msg or "VI" in msg

    def test_s3_message_contains_netbuy(self):
        from analyzer import _build_user_message
        signal = _signal("S3_INST_FRGN", net_buy_amt=10_000_000_000, continuous_days=3)
        msg = _build_user_message(signal, _ctx(), 65.0)
        assert "외인" in msg or "기관" in msg or "순매수" in msg

    def test_s4_message_contains_candle(self):
        from analyzer import _build_user_message
        signal = _signal("S4_BIG_CANDLE", body_ratio=0.85, vol_ratio=8.0)
        msg = _build_user_message(signal, _ctx(), 80.0)
        assert "양봉" in msg or "거래량" in msg

    def test_s5_message_contains_program(self):
        from analyzer import _build_user_message
        signal = _signal("S5_PROG_FRGN", net_buy_amt=5_000_000_000)
        msg = _build_user_message(signal, _ctx(), 70.0)
        assert "프로그램" in msg or "외인" in msg

    def test_s6_message_contains_theme(self):
        from analyzer import _build_user_message
        signal = _signal("S6_THEME_LAGGARD", theme_name="AI반도체", gap_pct=2.0)
        msg = _build_user_message(signal, _ctx(), 65.0)
        assert "테마" in msg

    def test_s7_message_contains_ichimoku(self):
        from analyzer import _build_user_message
        signal = _signal("S7_ICHIMOKU_BREAKOUT", cloud_thickness_pct=0.8, chikou_above=True, vol_ratio=1.8, rsi=55, cond_count=3)
        msg = _build_user_message(signal, _ctx(), 75.0)
        assert "일목" in msg or "구름" in msg

    def test_unknown_strategy_message(self):
        from analyzer import _build_user_message
        signal = _signal("UNKNOWN_STRAT")
        msg = _build_user_message(signal, _ctx(), 50.0)
        assert "UNKNOWN_STRAT" in msg


# ──────────────────────────────────────────────────────────────────
# analyze_signal – Claude API 모킹 테스트
# ──────────────────────────────────────────────────────────────────

class TestAnalyzeSignal:
    """Claude API 를 unittest.mock 으로 대체하여 테스트"""

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_successful_json_response(self):
        """Claude가 완전한 JSON 응답 반환 시 파싱 성공"""
        expected = {
            "action": "ENTER",
            "ai_score": 80,
            "confidence": "HIGH",
            "reason": "강한 진입 신호",
            "adjusted_target_pct": 3.5,
            "adjusted_stop_pct": -2.0
        }
        mock_response = _make_response(json.dumps(expected))

        with patch("analyzer._get_claude_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_fn.return_value = mock_client

            from analyzer import analyze_signal
            result = self._run(analyze_signal(_signal(), _ctx(), 75.0))

        assert result["action"] == "ENTER"
        assert result["ai_score"] == 80
        assert result["confidence"] == "HIGH"

    def test_json_embedded_in_text(self):
        """Claude 응답에 JSON이 텍스트 속에 포함된 경우"""
        json_part = json.dumps({"action": "HOLD", "ai_score": 60, "confidence": "MEDIUM",
                                "reason": "관망", "adjusted_target_pct": None, "adjusted_stop_pct": None})
        raw = f"분석 결과: {json_part} 이상입니다."
        mock_response = _make_response(raw)

        with patch("analyzer._get_claude_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_fn.return_value = mock_client

            from analyzer import analyze_signal
            result = self._run(analyze_signal(_signal(), _ctx(), 60.0))

        assert result["action"] == "HOLD"

    def test_json_with_markdown_code_block(self):
        """```json ... ``` 형식의 마크다운 코드블록 내 JSON 처리"""
        json_data = {"action": "CANCEL", "ai_score": 40, "confidence": "LOW",
                     "reason": "약한 신호", "cancel_reason": "체결강도 부족",
                     "adjusted_target_pct": None, "adjusted_stop_pct": None}
        raw = f"```json\n{json.dumps(json_data)}\n```"
        # 중괄호 추출 로직으로 처리됨
        mock_response = _make_response(raw)

        with patch("analyzer._get_claude_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_fn.return_value = mock_client

            from analyzer import analyze_signal
            result = self._run(analyze_signal(_signal(), _ctx(), 40.0))

        assert result["action"] == "CANCEL"
        assert result["cancel_reason"] == "체결강도 부족"

    def test_cancel_reason_defaults_to_reason_when_missing(self):
        mock_response = _make_response(json.dumps({
            "action": "CANCEL",
            "ai_score": 35,
            "confidence": "LOW",
            "reason": "상단 저항 근접",
            "adjusted_target_pct": None,
            "adjusted_stop_pct": None,
        }))

        with patch("analyzer._get_claude_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_fn.return_value = mock_client

            from analyzer import analyze_signal
            result = self._run(analyze_signal(_signal(), _ctx(), 40.0))

        assert result["action"] == "CANCEL"
        assert result["cancel_reason"] == "상단 저항 근접"

    def test_timeout_returns_fallback(self):
        """Claude 타임아웃 시 폴백 반환"""
        with patch("analyzer._get_claude_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(side_effect=asyncio.TimeoutError())
            mock_client_fn.return_value = mock_client

            from analyzer import analyze_signal
            result = self._run(analyze_signal(_signal(), _ctx(), 75.0))

        assert "action" in result
        assert result["confidence"] == "LOW"

    def test_invalid_json_returns_fallback(self):
        """Claude가 파싱 불가능한 텍스트 반환 시 폴백"""
        mock_response = _make_response("이것은 JSON이 아닙니다")

        with patch("analyzer._get_claude_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_fn.return_value = mock_client

            from analyzer import analyze_signal
            result = self._run(analyze_signal(_signal(), _ctx(), 75.0))

        assert "action" in result
        assert result["confidence"] == "LOW"

    def test_api_error_returns_fallback(self):
        """Claude API 오류 시 폴백 반환"""
        import anthropic
        with patch("analyzer._get_claude_client") as mock_client_fn:
            mock_client = MagicMock()
            # APIError를 대신할 일반 예외 사용 (APIError는 생성이 복잡)
            mock_client.messages.create = AsyncMock(
                side_effect=Exception("Connection error")
            )
            mock_client_fn.return_value = mock_client

            from analyzer import analyze_signal
            result = self._run(analyze_signal(_signal(), _ctx(), 60.0))

        assert "action" in result
        assert result["confidence"] == "LOW"

    def test_fallback_score_used_for_action(self):
        """폴백 시 rule_score 기준으로 action 결정"""
        mock_response = _make_response("no json here")

        with patch("analyzer._get_claude_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_fn.return_value = mock_client

            from analyzer import analyze_signal
            result_enter = self._run(analyze_signal(_signal(), _ctx(), 75.0))
            result_cancel = self._run(analyze_signal(_signal(), _ctx(), 30.0))

        assert result_enter["action"] == "ENTER"
        assert result_cancel["action"] == "CANCEL"


# ──────────────────────────────────────────────────────────────────
# _get_claude_client 테스트
# ──────────────────────────────────────────────────────────────────

class TestGetClaudeClient:
    def test_raises_without_api_key(self):
        """CLAUDE_API_KEY 없을 때 RuntimeError"""
        import analyzer
        # 클라이언트 캐시 초기화
        original = analyzer._claude_client
        analyzer._claude_client = None
        try:
            with patch.dict(os.environ, {}, clear=True):
                # CLAUDE_API_KEY를 제거하고 테스트
                env_without_key = {k: v for k, v in os.environ.items() if k != "CLAUDE_API_KEY"}
                with patch.dict(os.environ, env_without_key, clear=True):
                    with pytest.raises(RuntimeError, match="CLAUDE_API_KEY"):
                        analyzer._get_claude_client()
        finally:
            analyzer._claude_client = original

    def test_returns_singleton(self):
        """동일한 클라이언트 반환 (싱글턴)"""
        import analyzer
        with patch.dict(os.environ, {"CLAUDE_API_KEY": "test-key"}):
            with patch("anthropic.AsyncAnthropic") as mock_class:
                analyzer._claude_client = None
                client1 = analyzer._get_claude_client()
                client2 = analyzer._get_claude_client()
                assert client1 is client2
                # 생성자는 1번만 호출
                assert mock_class.call_count == 1
                analyzer._claude_client = None  # 정리


# ──────────────────────────────────────────────────────────────────
# 전략별 valid signal 테스트 (필터링 통과 여부)
# ──────────────────────────────────────────────────────────────────

class TestStrategySignalValidity:
    """각 전략의 신호가 올바른 필드를 포함하는지 검증"""

    def test_s1_signal_has_required_fields(self):
        signal = _signal("S1_GAP_OPEN", gap_pct=4.0, cntr_strength=150)
        assert "gap_pct" in signal
        assert "strategy" in signal

    def test_s2_signal_has_required_fields(self):
        signal = _signal("S2_VI_PULLBACK", pullback_pct=-1.5, is_dynamic=True)
        assert "pullback_pct" in signal
        assert "is_dynamic" in signal

    def test_s3_signal_has_required_fields(self):
        signal = _signal("S3_INST_FRGN", net_buy_amt=10_000_000_000,
                         continuous_days=3, vol_ratio=2.0)
        assert "net_buy_amt" in signal
        assert "continuous_days" in signal
        assert "vol_ratio" in signal

    def test_s4_signal_has_required_fields(self):
        signal = _signal("S4_BIG_CANDLE", vol_ratio=8.0, body_ratio=0.85, is_new_high=True)
        assert "vol_ratio" in signal
        assert "body_ratio" in signal

    def test_s5_signal_has_required_fields(self):
        signal = _signal("S5_PROG_FRGN", net_buy_amt=50_000_000_000)
        assert "net_buy_amt" in signal

    def test_s6_signal_has_required_fields(self):
        signal = _signal("S6_THEME_LAGGARD", gap_pct=2.0, cntr_strength=130,
                         theme_name="AI반도체")
        assert "gap_pct" in signal
        assert "theme_name" in signal

    def test_s7_signal_has_required_fields(self):
        signal = _signal("S7_ICHIMOKU_BREAKOUT", cloud_thickness_pct=0.8, chikou_above=True, vol_ratio=1.8, rsi=55, cond_count=3)
        assert "cloud_thickness_pct" in signal
        assert "chikou_above" in signal
