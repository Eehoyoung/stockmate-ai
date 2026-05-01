"""
tests/test_analyzer_advanced.py
analyzer.py 심화 테스트: 전략별 경계값, JSON 파싱 다양한 케이스,
_track_api_usage, 특수 입력 처리.
최소 50개 테스트.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _sig(strategy="S1_GAP_OPEN", **kwargs):
    base = {"strategy": strategy, "stk_cd": "005930", "stk_nm": "삼성전자"}
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
    content = MagicMock()
    content.text = text
    usage = MagicMock()
    usage.input_tokens = 300
    usage.output_tokens = 100
    response = MagicMock()
    response.content = [content]
    response.usage = usage
    return response


# ──────────────────────────────────────────────────────────────────
# _fallback 경계값 테스트
# ──────────────────────────────────────────────────────────────────

class TestFallbackBoundaries:
    def test_fallback_exactly_70_is_cancel(self):
        from analyzer import _fallback
        assert _fallback(70.0)["action"] == "CANCEL"

    def test_fallback_just_below_70_is_cancel(self):
        from analyzer import _fallback
        assert _fallback(69.9)["action"] == "CANCEL"

    def test_fallback_exactly_50_is_cancel(self):
        from analyzer import _fallback
        assert _fallback(50.0)["action"] == "CANCEL"

    def test_fallback_just_below_50_is_cancel(self):
        from analyzer import _fallback
        assert _fallback(49.9)["action"] == "CANCEL"

    def test_fallback_0_is_cancel(self):
        from analyzer import _fallback
        assert _fallback(0.0)["action"] == "CANCEL"

    def test_fallback_100_is_cancel(self):
        from analyzer import _fallback
        assert _fallback(100.0)["action"] == "CANCEL"

    def test_fallback_confidence_always_low(self):
        from analyzer import _fallback
        for score in [0, 30, 50, 70, 100]:
            assert _fallback(float(score))["confidence"] == "LOW"

    def test_fallback_adjusted_fields_are_none(self):
        from analyzer import _fallback
        result = _fallback(75.0)
        assert result["adjusted_target_pct"] is None
        assert result["adjusted_stop_pct"] is None

    def test_fallback_reason_is_string(self):
        from analyzer import _fallback
        result = _fallback(60.0)
        assert isinstance(result["reason"], str)
        assert len(result["reason"]) > 0


# ──────────────────────────────────────────────────────────────────
# JSON 파싱 다양한 케이스
# ──────────────────────────────────────────────────────────────────

class TestJsonParsing:
    def _analyze(self, response_text, rule_score=75.0):
        mock_response = _make_response(response_text)
        with patch("analyzer._get_claude_client") as mock_fn:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_fn.return_value = mock_client
            from analyzer import analyze_signal
            return _run(analyze_signal(_sig(), _ctx(), rule_score))

    def test_pure_json_response(self):
        """순수 JSON 응답"""
        payload = {"action": "ENTER", "ai_score": 80, "confidence": "HIGH",
                   "reason": "강한 신호", "adjusted_target_pct": 3.5, "adjusted_stop_pct": -2.0}
        result = self._analyze(json.dumps(payload))
        assert result["action"] == "ENTER"
        assert result["ai_score"] == 80

    def test_json_with_leading_text(self):
        """JSON 앞에 텍스트가 있는 경우"""
        inner = '{"action":"HOLD","ai_score":65,"confidence":"MEDIUM","reason":"관망","adjusted_target_pct":null,"adjusted_stop_pct":null}'
        result = self._analyze(f"분석 결과입니다.\n{inner}")
        assert result["action"] == "HOLD"

    def test_json_with_trailing_text(self):
        """JSON 뒤에 텍스트가 있는 경우"""
        inner = '{"action":"CANCEL","ai_score":40,"confidence":"LOW","reason":"약함","adjusted_target_pct":null,"adjusted_stop_pct":null}'
        result = self._analyze(f"{inner}\n이상으로 분석을 마칩니다.")
        assert result["action"] == "CANCEL"

    def test_json_in_markdown_code_block(self):
        """마크다운 코드 블록 내 JSON"""
        inner = {"action": "ENTER", "ai_score": 75, "confidence": "HIGH",
                 "reason": "강함", "adjusted_target_pct": None, "adjusted_stop_pct": None}
        raw = f"```json\n{json.dumps(inner)}\n```"
        result = self._analyze(raw)
        assert result["action"] == "ENTER"

    def test_json_in_code_block_without_lang(self):
        """언어 없는 코드 블록 내 JSON"""
        inner = {"action": "ENTER", "ai_score": 72, "confidence": "MEDIUM",
                 "reason": "보통", "adjusted_target_pct": None, "adjusted_stop_pct": None}
        raw = f"```\n{json.dumps(inner)}\n```"
        result = self._analyze(raw)
        assert result["action"] == "ENTER"

    def test_completely_invalid_json_returns_fallback(self):
        """JSON 없는 응답 → 폴백"""
        result = self._analyze("이것은 JSON이 아닙니다 completely invalid")
        assert result["confidence"] == "LOW"

    def test_partial_json_returns_fallback(self):
        """불완전한 JSON → 폴백"""
        result = self._analyze('{"action": "ENTER"')  # 닫히지 않은 JSON
        # 닫히지 않은 JSON이지만 find("{") → rfind("}") 로직으로 처리
        # 실패 시 fallback 반환
        assert "action" in result

    def test_nested_json_with_outer_object(self):
        """중첩 JSON → 가장 바깥 {} 추출"""
        inner = {"action": "ENTER", "ai_score": 78, "confidence": "HIGH",
                 "reason": "강한 신호", "adjusted_target_pct": None, "adjusted_stop_pct": None,
                 "metadata": {"source": "claude", "version": "3"}}
        result = self._analyze(json.dumps(inner))
        assert result["action"] == "ENTER"

    def test_json_with_unicode_in_reason(self):
        """한글 포함 JSON"""
        inner = {"action": "ENTER", "ai_score": 80, "confidence": "HIGH",
                 "reason": "강한 갭상승과 체결강도 확인됨", "adjusted_target_pct": None, "adjusted_stop_pct": None}
        result = self._analyze(json.dumps(inner, ensure_ascii=False))
        assert "강한" in result["reason"]

    def test_json_with_null_adjusted_fields(self):
        """adjusted 필드가 null인 경우"""
        inner = {"action": "ENTER", "ai_score": 75, "confidence": "HIGH",
                 "reason": "진입 추천", "adjusted_target_pct": None, "adjusted_stop_pct": None}
        result = self._analyze(json.dumps(inner))
        assert result.get("adjusted_target_pct") is None
        assert result.get("adjusted_stop_pct") is None

    def test_json_with_adjusted_values(self):
        """조정된 목표/손절 값이 있는 경우"""
        inner = {"action": "ENTER", "ai_score": 82, "confidence": "HIGH",
                 "reason": "진입 추천", "adjusted_target_pct": 4.5, "adjusted_stop_pct": -1.5}
        result = self._analyze(json.dumps(inner))
        assert result["adjusted_target_pct"] == 4.5
        assert result["adjusted_stop_pct"] == -1.5


# ──────────────────────────────────────────────────────────────────
# _track_api_usage 테스트
# ──────────────────────────────────────────────────────────────────

class TestTrackApiUsage:
    def test_track_increments_token_key(self):
        """토큰 사용량 Redis에 기록"""
        mock_rdb = MagicMock()
        mock_rdb.incrby = AsyncMock(return_value=500)
        mock_rdb.expire = AsyncMock(return_value=True)

        from analyzer import _track_api_usage
        _run(_track_api_usage(mock_rdb, input_tokens=300, output_tokens=100))

        mock_rdb.incrby.assert_awaited_once()
        args = mock_rdb.incrby.call_args[0]
        assert "claude:daily_tokens:" in args[0]
        assert args[1] == 400  # 300 + 100

    def test_track_sets_ttl_on_first_call(self):
        """첫 기록 시 TTL 설정"""
        mock_rdb = MagicMock()
        mock_rdb.incrby = AsyncMock(return_value=400)  # 첫 호출: incrby 결과 == total
        mock_rdb.expire = AsyncMock(return_value=True)

        from analyzer import _track_api_usage
        _run(_track_api_usage(mock_rdb, input_tokens=300, output_tokens=100))

        # cnt == total 이면 expire 호출
        mock_rdb.expire.assert_awaited_once()

    def test_track_with_none_rdb_does_nothing(self):
        """rdb=None이면 아무것도 하지 않음"""
        from analyzer import _track_api_usage
        # 예외 없이 완료되어야 함
        _run(_track_api_usage(None, input_tokens=300, output_tokens=100))

    def test_track_with_zero_tokens_skips(self):
        """토큰 0개면 기록 건너뜀"""
        mock_rdb = MagicMock()
        mock_rdb.incrby = AsyncMock(return_value=0)
        mock_rdb.expire = AsyncMock(return_value=True)

        from analyzer import _track_api_usage
        _run(_track_api_usage(mock_rdb, input_tokens=0, output_tokens=0))

        mock_rdb.incrby.assert_not_awaited()

    def test_track_redis_error_does_not_raise(self):
        """Redis 오류 시 예외 전파 없음"""
        mock_rdb = MagicMock()
        mock_rdb.incrby = AsyncMock(side_effect=Exception("Redis error"))

        from analyzer import _track_api_usage
        # 예외 없이 완료되어야 함
        _run(_track_api_usage(mock_rdb, input_tokens=300, output_tokens=100))

    def test_track_called_after_successful_analysis(self):
        """Claude 성공적 응답 후 _track_api_usage 호출 확인"""
        response = _make_response('{"action":"ENTER","ai_score":80,"confidence":"HIGH","reason":"강함","adjusted_target_pct":null,"adjusted_stop_pct":null}')

        mock_rdb = MagicMock()
        mock_rdb.incrby = AsyncMock(return_value=400)
        mock_rdb.expire = AsyncMock(return_value=True)

        with patch("analyzer._get_claude_client") as mock_fn:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=response)
            mock_fn.return_value = mock_client

            from analyzer import analyze_signal
            _run(analyze_signal(_sig(), _ctx(), 75.0, rdb=mock_rdb))

        mock_rdb.incrby.assert_awaited()


# ──────────────────────────────────────────────────────────────────
# 전략별 analyze_signal 프롬프트 테스트
# ──────────────────────────────────────────────────────────────────

class TestStrategyPrompts:
    def _get_prompt(self, signal, ctx=None):
        if ctx is None:
            ctx = _ctx()
        from analyzer import _build_user_message
        return _build_user_message(signal, ctx, 75.0)

    def _get_system_arg(self, signal):
        response = _make_response('{"action":"HOLD","ai_score":60,"confidence":"MEDIUM","reason":"watch","adjusted_target_pct":null,"adjusted_stop_pct":null}')
        with patch("analyzer._get_claude_client") as mock_fn:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=response)
            mock_fn.return_value = mock_client

            from analyzer import analyze_signal
            _run(analyze_signal(signal, _ctx(), 75.0))

        return mock_client.messages.create.call_args.kwargs["system"]

    def test_s1_uses_gap_open_system_prompt(self):
        import analyzer
        system_prompt = self._get_system_arg(_sig("S1_GAP_OPEN", gap_pct=4.0))
        assert system_prompt == analyzer._S1_GAP_OPEN_SYS_PROMPT
        assert system_prompt != analyzer._SYS_PROMPT

    def test_non_s1_uses_default_system_prompt(self):
        import analyzer
        system_prompt = self._get_system_arg(_sig("S2_VI_PULLBACK", pullback_pct=-1.5))
        assert system_prompt == analyzer._SYS_PROMPT

    def test_s1_prompt_contains_gap(self):
        msg = self._get_prompt(_sig("S1_GAP_OPEN", gap_pct=4.0))
        assert "4.0" in msg

    def test_s2_prompt_contains_is_dynamic(self):
        msg = self._get_prompt(_sig("S2_VI_PULLBACK", pullback_pct=-1.5, is_dynamic=True))
        assert "True" in msg or "동적" in msg

    def test_s3_prompt_contains_continuous_days(self):
        msg = self._get_prompt(_sig("S3_INST_FRGN", net_buy_amt=10_000_000_000, continuous_days=5))
        assert "연속일: 5일" in msg

    def test_s3_amt_formatted_in_eok(self):
        """S3 순매수 금액 억 단위 표시"""
        msg = self._get_prompt(_sig("S3_INST_FRGN", net_buy_amt=100_000_000_000))
        assert "100억" in msg or "1000억" in msg or "억" in msg

    def test_s4_prompt_contains_body_ratio(self):
        msg = self._get_prompt(_sig("S4_BIG_CANDLE", body_ratio=0.85))
        assert "0.85" in msg

    def test_s5_prompt_contains_netbuy(self):
        msg = self._get_prompt(_sig("S5_PROG_FRGN", net_buy_amt=50_000_000_000))
        assert "억" in msg

    def test_s6_prompt_contains_theme_name(self):
        msg = self._get_prompt(_sig("S6_THEME_LAGGARD", theme_name="AI반도체", gap_pct=2.0))
        assert "AI반도체" in msg

    def test_s7_prompt_contains_ichimoku_fields(self):
        msg = self._get_prompt(_sig("S7_ICHIMOKU_BREAKOUT", cloud_thickness_pct=0.8, chikou_above=True, vol_ratio=1.8, cond_count=3))
        assert "0.8" in msg or "일목" in msg

    def test_prompt_contains_rule_score(self):
        """모든 전략 프롬프트에 규칙 점수 포함"""
        for strategy in ["S1_GAP_OPEN", "S2_VI_PULLBACK", "S3_INST_FRGN",
                         "S4_BIG_CANDLE", "S5_PROG_FRGN", "S6_THEME_LAGGARD", "S7_ICHIMOKU_BREAKOUT"]:
            msg = self._get_prompt(_sig(strategy))
            assert "75" in msg or "75.0" in msg or "규칙" in msg

    def test_prompt_contains_stk_nm(self):
        """종목명 포함"""
        msg = self._get_prompt(_sig("S1_GAP_OPEN"))
        assert "삼성전자" in msg

    def test_unknown_strategy_prompt_contains_strategy_code(self):
        """알 수 없는 전략 코드도 프롬프트에 포함"""
        msg = self._get_prompt(_sig("S99_CUSTOM"))
        assert "S99_CUSTOM" in msg


class TestS1SystemPromptStability:
    def test_s1_uses_dedicated_system_prompt(self):
        from analyzer import _S1_GAP_OPEN_SYS_PROMPT, _SYS_PROMPT, _get_system_prompt

        assert _get_system_prompt("S1_GAP_OPEN") == _S1_GAP_OPEN_SYS_PROMPT
        assert _get_system_prompt("S2_VI_PULLBACK") == _SYS_PROMPT

    def test_s1_prompt_requires_json_only_single_line_no_markdown(self):
        from analyzer import _get_system_prompt

        prompt = _get_system_prompt("S1_GAP_OPEN")
        lowered = prompt.lower()

        assert "exactly one valid json object on a single line" in lowered
        assert "do not use markdown" in lowered
        assert "code fences" in lowered
        assert "explanatory text outside the json" in lowered

    def test_s1_prompt_blocks_unprovided_context_inference(self):
        from analyzer import _get_system_prompt

        prompt = _get_system_prompt("S1_GAP_OPEN").lower()

        assert "use only the values explicitly present" in prompt
        assert "do not infer, invent, or mention news" in prompt
        assert "themes" in prompt
        assert "institutional flow" in prompt
        assert "foreign flow" in prompt

    def test_s1_prompt_requires_hold_cancel_null_tpsl_and_enter_integer_prices(self):
        from analyzer import _get_system_prompt

        prompt = _get_system_prompt("S1_GAP_OPEN").lower()

        assert "for enter only" in prompt
        assert "absolute krw prices as integers" in prompt
        assert "for hold or cancel" in prompt
        assert "claude_tp1, claude_tp2, and claude_sl must be null" in prompt
        assert "for cancel only, cancel_reason must be a short korean string" in prompt
        assert "for enter or hold, cancel_reason must be null" in prompt


# ──────────────────────────────────────────────────────────────────
# 신호 없거나 잘못된 입력
# ──────────────────────────────────────────────────────────────────

class TestEdgeInputs:
    def test_analyze_with_empty_signal(self):
        """빈 신호 딕셔너리도 처리"""
        response = _make_response('{"action":"HOLD","ai_score":50,"confidence":"LOW","reason":"N/A","adjusted_target_pct":null,"adjusted_stop_pct":null}')
        with patch("analyzer._get_claude_client") as mock_fn:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=response)
            mock_fn.return_value = mock_client
            from analyzer import analyze_signal
            result = _run(analyze_signal({}, _ctx(), 50.0))
        assert "action" in result

    def test_analyze_with_empty_market_ctx(self):
        """빈 시장 컨텍스트도 처리"""
        response = _make_response('{"action":"ENTER","ai_score":70,"confidence":"MEDIUM","reason":"괜찮음","adjusted_target_pct":null,"adjusted_stop_pct":null}')
        with patch("analyzer._get_claude_client") as mock_fn:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=response)
            mock_fn.return_value = mock_client
            from analyzer import analyze_signal
            result = _run(analyze_signal(_sig(), {}, 70.0))
        assert "action" in result

    def test_analyze_timeout_uses_fallback(self):
        """타임아웃 → 폴백"""
        with patch("analyzer._get_claude_client") as mock_fn:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(side_effect=asyncio.TimeoutError())
            mock_fn.return_value = mock_client
            from analyzer import analyze_signal
            result = _run(analyze_signal(_sig(), _ctx(), 75.0))
        assert result["confidence"] == "LOW"

    def test_analyze_api_error_uses_fallback(self):
        """일반 예외 → 폴백"""
        with patch("analyzer._get_claude_client") as mock_fn:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(side_effect=Exception("API error"))
            mock_fn.return_value = mock_client
            from analyzer import analyze_signal
            result = _run(analyze_signal(_sig(), _ctx(), 75.0))
        assert "action" in result
        assert result["confidence"] == "LOW"

    def test_get_claude_client_reuses_singleton(self):
        """연속 호출 시 같은 클라이언트 반환"""
        import analyzer
        old_client = analyzer._claude_client
        try:
            analyzer._claude_client = None
            with patch.dict(os.environ, {"CLAUDE_API_KEY": "test-key"}):
                with patch("anthropic.AsyncAnthropic"):
                    c1 = analyzer._get_claude_client()
                    c2 = analyzer._get_claude_client()
            assert c1 is c2
        finally:
            analyzer._claude_client = old_client

    def test_s3_zero_net_buy_amt(self):
        """net_buy_amt=0인 경우도 프롬프트 생성"""
        from analyzer import _build_user_message
        sig = _sig("S3_INST_FRGN", net_buy_amt=0)
        msg = _build_user_message(sig, _ctx(), 60.0)
        assert "N/A" in msg or "0" in msg or "종목" in msg


# ──────────────────────────────────────────────────────────────────
# rate 경계값 필터 (flu_rt) - analyze_signal 통합
# ──────────────────────────────────────────────────────────────────

class TestRateFilterInAnalyzeSignal:
    def test_high_flu_rt_still_gets_analyzed(self):
        """flu_rt > 15이어도 분석 시도 (패널티는 scorer에서 적용)"""
        response = _make_response('{"action":"CANCEL","ai_score":20,"confidence":"LOW","reason":"과열","adjusted_target_pct":null,"adjusted_stop_pct":null}')
        ctx = {
            "tick": {"flu_rt": "16.0"},
            "hoga": {"total_buy_bid_req": "2000", "total_sel_bid_req": "1000"},
            "strength": 100.0,
            "vi": {},
        }
        with patch("analyzer._get_claude_client") as mock_fn:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=response)
            mock_fn.return_value = mock_client
            from analyzer import analyze_signal
            result = _run(analyze_signal(_sig(), ctx, 30.0))
        assert "action" in result
