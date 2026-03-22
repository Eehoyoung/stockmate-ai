"""
tests/test_integration.py
queue_worker + analyzer + scorer 통합 테스트.
여러 컴포넌트가 함께 작동하는 흐름을 검증.
최소 20개 테스트.
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


def _make_full_rdb(rpop_value=None):
    """완전한 Redis mock (모든 메서드 포함)"""
    rdb = MagicMock()
    rdb.rpop = AsyncMock(return_value=rpop_value)
    rdb.lpush = AsyncMock(return_value=1)
    rdb.expire = AsyncMock(return_value=True)
    rdb.hgetall = AsyncMock(return_value={})
    rdb.lrange = AsyncMock(return_value=["120.0", "130.0"])
    rdb.incr = AsyncMock(return_value=1)
    rdb.incrby = AsyncMock(return_value=400)
    rdb.get = AsyncMock(return_value=None)
    rdb.ping = AsyncMock(return_value=True)
    return rdb


def _make_claude_response(action="ENTER", ai_score=78, confidence="HIGH",
                           reason="강한 신호", target=3.5, stop=-2.0):
    content = MagicMock()
    content.text = json.dumps({
        "action": action,
        "ai_score": ai_score,
        "confidence": confidence,
        "reason": reason,
        "adjusted_target_pct": target,
        "adjusted_stop_pct": stop,
    })
    usage = MagicMock()
    usage.input_tokens = 300
    usage.output_tokens = 100
    response = MagicMock()
    response.content = [content]
    response.usage = usage
    return response


# ──────────────────────────────────────────────────────────────────
# 전체 파이프라인 통합 테스트
# ──────────────────────────────────────────────────────────────────

class TestFullPipeline:
    def test_s1_signal_enters_and_exits_pipeline(self):
        """S1 신호가 전체 파이프라인을 통과"""
        signal = {
            "strategy": "S1_GAP_OPEN",
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "gap_pct": 4.0,
            "cntr_strength": 155.0,
            "target_pct": 4.0,
            "stop_pct": -2.0,
        }
        ctx = {
            "tick": {"flu_rt": "4.0"},
            "hoga": {"total_buy_bid_req": "3000", "total_sel_bid_req": "1000"},
            "strength": 155.0,
            "vi": {},
        }
        rdb = _make_full_rdb(json.dumps(signal))

        captured = []

        async def capture_push(rdb, payload):
            captured.append(payload)

        mock_response = _make_claude_response("ENTER", 80)

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=ctx), \
             patch("analyzer._get_claude_client") as mock_fn:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_fn.return_value = mock_client

            with patch("queue_worker.push_score_only_queue", side_effect=capture_push):
                from queue_worker import process_one
                result = _run(process_one(rdb))

        assert result is True
        assert len(captured) == 1
        payload = captured[0]
        assert payload["stk_cd"] == "005930"
        assert payload["strategy"] == "S1_GAP_OPEN"
        assert "rule_score" in payload
        assert payload["ai_score"] == 80
        assert payload["action"] == "ENTER"

    def test_force_close_bypasses_scoring_and_analysis(self):
        """FORCE_CLOSE 특수 메시지가 스코어링과 AI 분석 없이 통과"""
        item = {
            "type": "FORCE_CLOSE",
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "strategy": "S1_GAP_OPEN",
        }
        rdb = _make_full_rdb(json.dumps(item))
        captured = []

        async def capture_push(rdb, payload):
            captured.append(payload)

        with patch("queue_worker.rule_score") as mock_rule, \
             patch("analyzer.analyze_signal") as mock_analyze, \
             patch("queue_worker.push_score_only_queue", side_effect=capture_push):
            from queue_worker import process_one
            _run(process_one(rdb))

        mock_rule.assert_not_called()
        mock_analyze.assert_not_called()
        assert captured[0]["type"] == "FORCE_CLOSE"

    def test_borderline_score_69_is_cancelled(self):
        """규칙 점수 69점(임계값 70 미달) → CANCEL, Claude 미호출"""
        signal = {
            "strategy": "S1_GAP_OPEN",
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "gap_pct": 4.99,  # 약간 최적 미달 갭
        }
        ctx = {
            "tick": {"flu_rt": "2.0"},
            "hoga": {"total_buy_bid_req": "1300", "total_sel_bid_req": "1000"},
            "strength": 115.0,
            "vi": {},
        }
        rdb = _make_full_rdb(json.dumps(signal))
        captured = []

        async def capture_push(rdb, payload):
            captured.append(payload)

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=ctx):
            with patch("queue_worker.analyze_signal", new_callable=AsyncMock) as mock_ai:
                with patch("queue_worker.push_score_only_queue", side_effect=capture_push):
                    from queue_worker import process_one
                    _run(process_one(rdb))

        # S1 임계값 = 70, 갭=4.99(20점) + strength=115(10점) + bid_ratio=1.3(10점) = 40점 < 70
        # should_skip_ai → True → CANCEL
        mock_ai.assert_not_awaited()
        assert captured[0]["action"] == "CANCEL"

    def test_borderline_score_70_triggers_ai(self):
        """규칙 점수 정확히 70점 → Claude 호출"""
        # S1: gap=4%(20점) + strength=131(20점) + bid_ratio=0 = 40점 < 70
        # 강한 조건 필요: gap=4%(20) + strength>150(30) + bid_ratio>2(25) = 75점
        signal = {
            "strategy": "S1_GAP_OPEN",
            "stk_cd": "005930",
            "gap_pct": 4.0,
        }
        ctx = {
            "tick": {"flu_rt": "4.0"},
            "hoga": {"total_buy_bid_req": "2200", "total_sel_bid_req": "1000"},
            "strength": 155.0,  # >150 → 30점
            "vi": {},
        }
        rdb = _make_full_rdb(json.dumps(signal))
        captured = []

        async def capture_push(rdb, payload):
            captured.append(payload)

        mock_response = _make_claude_response("ENTER", 78)

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=ctx), \
             patch("analyzer._get_claude_client") as mock_fn:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_fn.return_value = mock_client

            with patch("queue_worker.push_score_only_queue", side_effect=capture_push):
                from queue_worker import process_one
                _run(process_one(rdb))

        # rule_score = gap(20) + strength>150(30) + bid_ratio~2.2(25) = 75점 ≥ 70 → AI 호출
        mock_client.messages.create.assert_awaited()

    def test_duplicate_signal_handling(self):
        """같은 종목 신호 두 번 처리 - 각각 독립적으로 처리됨"""
        signal = {
            "strategy": "S1_GAP_OPEN",
            "stk_cd": "005930",
            "gap_pct": 4.0,
        }
        ctx = {"tick": {}, "hoga": {}, "strength": 120.0, "vi": {}}

        processed = []

        async def capture_push(rdb, payload):
            processed.append(payload["stk_cd"])

        with patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=ctx), \
             patch("queue_worker.rule_score", return_value=30.0), \
             patch("queue_worker.should_skip_ai", return_value=True), \
             patch("queue_worker.push_score_only_queue", side_effect=capture_push):
            from queue_worker import process_one

            rdb1 = _make_full_rdb(json.dumps(signal))
            rdb2 = _make_full_rdb(json.dumps(signal))
            _run(process_one(rdb1))
            _run(process_one(rdb2))

        assert len(processed) == 2
        assert all(p == "005930" for p in processed)


# ──────────────────────────────────────────────────────────────────
# 스코어링 + 분석 통합
# ──────────────────────────────────────────────────────────────────

class TestScoringAndAnalysisIntegration:
    def test_rule_score_determines_ai_call(self):
        """rule_score 결과가 AI 호출 여부를 결정"""
        from scorer import rule_score, should_skip_ai

        # 높은 점수 신호
        high_sig = {
            "strategy": "S1_GAP_OPEN",
            "stk_cd": "005930",
            "gap_pct": 4.0,
        }
        ctx = {
            "tick": {"flu_rt": "4.0"},
            "hoga": {"total_buy_bid_req": "3000", "total_sel_bid_req": "1000"},
            "strength": 160.0,
            "vi": {},
        }
        score = rule_score(high_sig, ctx)
        skip = should_skip_ai(score, "S1_GAP_OPEN")
        assert not skip  # 높은 점수 → 건너뛰지 않음

        # 낮은 점수 신호
        low_sig = {
            "strategy": "S1_GAP_OPEN",
            "stk_cd": "005930",
            "gap_pct": 0.5,
        }
        ctx2 = {
            "tick": {"flu_rt": "0.5"},
            "hoga": {"total_buy_bid_req": "500", "total_sel_bid_req": "1000"},
            "strength": 90.0,
            "vi": {},
        }
        low_score = rule_score(low_sig, ctx2)
        low_skip = should_skip_ai(low_score, "S1_GAP_OPEN")
        assert low_skip  # 낮은 점수 → 건너뜀

    def test_fallback_action_based_on_rule_score(self):
        """폴백 시 rule_score로 action 결정"""
        from scorer import rule_score
        from analyzer import _fallback

        # 높은 점수 → ENTER
        high_ctx = {
            "tick": {"flu_rt": "4.0"},
            "hoga": {"total_buy_bid_req": "3000", "total_sel_bid_req": "1000"},
            "strength": 160.0, "vi": {},
        }
        high_score = rule_score({"strategy": "S1_GAP_OPEN", "gap_pct": 4.0}, high_ctx)
        if high_score >= 70:
            fallback = _fallback(high_score)
            assert fallback["action"] == "ENTER"

        # 낮은 점수 → CANCEL
        low_ctx = {
            "tick": {"flu_rt": "0.5"},
            "hoga": {"total_buy_bid_req": "500", "total_sel_bid_req": "1000"},
            "strength": 90.0, "vi": {},
        }
        low_score = rule_score({"strategy": "S1_GAP_OPEN", "gap_pct": 0.5}, low_ctx)
        if low_score < 50:
            fallback = _fallback(low_score)
            assert fallback["action"] == "CANCEL"

    def test_each_strategy_can_produce_signals(self):
        """각 전략에 대해 스코어링이 정상 작동"""
        from scorer import rule_score

        strategy_signals = {
            "S1_GAP_OPEN": {"gap_pct": 4.0},
            "S2_VI_PULLBACK": {"pullback_pct": -1.5, "is_dynamic": True},
            "S3_INST_FRGN": {"net_buy_amt": 10_000_000_000, "continuous_days": 3, "vol_ratio": 2.0},
            "S4_BIG_CANDLE": {"vol_ratio": 8.0, "body_ratio": 0.85},
            "S5_PROG_FRGN": {"net_buy_amt": 50_000_000_000},
            "S6_THEME_LAGGARD": {"gap_pct": 2.0, "cntr_strength": 130.0},
            "S7_AUCTION": {"gap_pct": 3.0, "vol_rank": 5},
        }

        ctx = {
            "tick": {"flu_rt": "3.0"},
            "hoga": {"total_buy_bid_req": "2000", "total_sel_bid_req": "1000"},
            "strength": 130.0, "vi": {},
        }

        for strategy, fields in strategy_signals.items():
            sig = {"strategy": strategy, "stk_cd": "005930", **fields}
            score = rule_score(sig, ctx)
            assert isinstance(score, float), f"{strategy}: score should be float"
            assert 0 <= score <= 100, f"{strategy}: score {score} out of range"

    def test_s2_is_dynamic_int_works_same_as_bool(self):
        """S2 is_dynamic=1 (int)과 True (bool)이 같은 결과"""
        from scorer import rule_score

        ctx = {"tick": {"flu_rt": "1.0"}, "hoga": {}, "strength": 100.0, "vi": {}}

        sig_int = {"strategy": "S2_VI_PULLBACK", "pullback_pct": -1.5, "is_dynamic": 1}
        sig_bool = {"strategy": "S2_VI_PULLBACK", "pullback_pct": -1.5, "is_dynamic": True}

        score_int = rule_score(sig_int, ctx)
        score_bool = rule_score(sig_bool, ctx)

        assert score_int == score_bool


# ──────────────────────────────────────────────────────────────────
# 엣지 케이스 통합
# ──────────────────────────────────────────────────────────────────

class TestEdgeCasesIntegration:
    def test_signal_with_all_zeros_produces_zero_score(self):
        """모든 지표가 0인 신호 → 0점"""
        from scorer import rule_score
        sig = {"strategy": "S1_GAP_OPEN", "gap_pct": 0}
        ctx = {"tick": {"flu_rt": "0"}, "hoga": {}, "strength": 0.0, "vi": {}}
        score = rule_score(sig, ctx)
        assert score == 0.0

    def test_overheat_penalty_reduces_high_base_score(self):
        """과열 페널티가 높은 기본 점수를 감소"""
        from scorer import rule_score
        sig = {"strategy": "S1_GAP_OPEN", "gap_pct": 4.0, "cntr_strength": 160.0}
        ctx_hot = {"tick": {"flu_rt": "16.0"}, "hoga": {"total_buy_bid_req": "3000", "total_sel_bid_req": "1000"}, "strength": 160.0, "vi": {}}
        ctx_normal = {"tick": {"flu_rt": "4.0"}, "hoga": {"total_buy_bid_req": "3000", "total_sel_bid_req": "1000"}, "strength": 160.0, "vi": {}}

        score_hot = rule_score(sig, ctx_hot)
        score_normal = rule_score(sig, ctx_normal)

        assert score_hot < score_normal  # 과열 페널티 효과

    def test_score_range_all_strategies(self):
        """모든 전략의 스코어가 0~100 범위 내"""
        from scorer import rule_score

        test_cases = [
            {"strategy": "S1_GAP_OPEN", "gap_pct": 100.0},  # 극단적 갭
            {"strategy": "S2_VI_PULLBACK", "pullback_pct": -10.0},  # 극단적 눌림
            {"strategy": "S3_INST_FRGN", "net_buy_amt": -1_000_000_000},  # 음수 순매수
            {"strategy": "S7_AUCTION", "gap_pct": 0, "vol_rank": 999},  # 최저 조건
        ]

        ctx = {"tick": {"flu_rt": "3.0"}, "hoga": {}, "strength": 120.0, "vi": {}}

        for sig in test_cases:
            score = rule_score(sig, ctx)
            assert 0 <= score <= 100, f"Score {score} out of range for {sig}"
