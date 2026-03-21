"""
tests/test_queue_worker.py
queue_worker.py 의 process_one 메시지 라우팅 테스트.
FORCE_CLOSE, DAILY_REPORT 는 AI 없이 통과,
일반 신호는 전체 파이프라인(스코어링 + Claude) 경유.
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


def _make_rdb(**kwargs):
    """비동기 Redis 모킹"""
    rdb = MagicMock()
    defaults = {
        "rpop": None,
        "lpush": 1,
        "expire": True,
        "incr": 1,
        "hgetall": {},
        "lrange": [],
    }
    defaults.update(kwargs)
    for method, return_value in defaults.items():
        setattr(rdb, method, AsyncMock(return_value=return_value))
    return rdb


def _signal(strategy="S1_GAP_OPEN", **kwargs):
    base = {
        "strategy": strategy,
        "stk_cd": "005930",
        "stk_nm": "삼성전자",
        "gap_pct": 4.0,
        "target_pct": 3.5,
        "stop_pct": -2.0,
    }
    base.update(kwargs)
    return base


# ──────────────────────────────────────────────────────────────────
# FORCE_CLOSE 특수 타입 테스트
# ──────────────────────────────────────────────────────────────────

class TestForceCloseBypass:
    def test_force_close_bypasses_ai_scoring(self):
        """FORCE_CLOSE 타입은 AI 분석 없이 ai_scored_queue 에 직접 전달"""
        force_close_item = {
            "type": "FORCE_CLOSE",
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "strategy": "S1_GAP_OPEN",
        }

        rdb = _make_rdb(rpop=json.dumps(force_close_item))

        with patch("queue_worker.analyze_signal") as mock_analyze, \
             patch("queue_worker.rule_score") as mock_rule_score, \
             patch("queue_worker.push_score_only_queue", new_callable=AsyncMock) as mock_push:
            from queue_worker import process_one
            result = _run(process_one(rdb))

        assert result is True
        mock_push.assert_awaited_once()
        mock_analyze.assert_not_called()
        mock_rule_score.assert_not_called()

    def test_force_close_payload_preserved(self):
        """FORCE_CLOSE 타입 원본 페이로드가 그대로 전달"""
        force_close_item = {
            "type": "FORCE_CLOSE",
            "stk_cd": "005930",
            "strategy": "S1_GAP_OPEN",
            "reason": "장마감 30분 전",
        }

        rdb = _make_rdb(rpop=json.dumps(force_close_item))

        captured = []
        async def capture_push(rdb, payload):
            captured.append(payload)

        with patch("queue_worker.push_score_only_queue", side_effect=capture_push):
            from queue_worker import process_one
            _run(process_one(rdb))

        assert len(captured) == 1
        assert captured[0]["type"] == "FORCE_CLOSE"
        assert captured[0]["reason"] == "장마감 30분 전"


# ──────────────────────────────────────────────────────────────────
# DAILY_REPORT 특수 타입 테스트
# ──────────────────────────────────────────────────────────────────

class TestDailyReportBypass:
    def test_daily_report_bypasses_ai_scoring(self):
        """DAILY_REPORT 타입은 AI 분석 없이 ai_scored_queue 에 직접 전달"""
        daily_report_item = {
            "type": "DAILY_REPORT",
            "date": "20260321",
            "total_signals": 15,
            "avg_score": 72.5,
        }

        rdb = _make_rdb(rpop=json.dumps(daily_report_item))

        with patch("queue_worker.analyze_signal") as mock_analyze, \
             patch("queue_worker.rule_score") as mock_rule_score, \
             patch("queue_worker.push_score_only_queue", new_callable=AsyncMock) as mock_push:
            from queue_worker import process_one
            result = _run(process_one(rdb))

        assert result is True
        mock_push.assert_awaited_once()
        mock_analyze.assert_not_called()
        mock_rule_score.assert_not_called()

    def test_daily_report_payload_preserved(self):
        """DAILY_REPORT 원본 데이터 보존"""
        daily_report_item = {
            "type": "DAILY_REPORT",
            "date": "20260321",
            "total_signals": 15,
            "by_strategy": {"S1_GAP_OPEN": 5, "S2_VI_PULLBACK": 3},
        }

        rdb = _make_rdb(rpop=json.dumps(daily_report_item))

        captured = []
        async def capture_push(rdb, payload):
            captured.append(payload)

        with patch("queue_worker.push_score_only_queue", side_effect=capture_push):
            from queue_worker import process_one
            _run(process_one(rdb))

        assert captured[0]["total_signals"] == 15


# ──────────────────────────────────────────────────────────────────
# 일반 신호 처리 테스트
# ──────────────────────────────────────────────────────────────────

class TestNormalSignalPipeline:
    def test_normal_signal_goes_through_full_pipeline(self):
        """일반 신호는 rule_score → Claude → push_score_only_queue 전체 경유"""
        item = _signal("S1_GAP_OPEN")
        rdb = _make_rdb(rpop=json.dumps(item))

        mock_ai_result = {
            "action": "ENTER",
            "ai_score": 80.0,
            "confidence": "HIGH",
            "reason": "강한 갭 신호",
            "adjusted_target_pct": 3.5,
            "adjusted_stop_pct": -2.0,
        }

        with patch("queue_worker.rule_score", return_value=75.0) as mock_rule, \
             patch("queue_worker.should_skip_ai", return_value=False) as mock_skip, \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock, return_value=True), \
             patch("queue_worker.analyze_signal", new_callable=AsyncMock,
                   return_value=mock_ai_result) as mock_analyze, \
             patch("queue_worker.push_score_only_queue", new_callable=AsyncMock) as mock_push, \
             patch("queue_worker._build_market_ctx", new_callable=AsyncMock,
                   return_value={"tick": {}, "hoga": {}, "strength": 120.0, "vi": {}}):
            from queue_worker import process_one
            result = _run(process_one(rdb))

        assert result is True
        mock_rule.assert_called_once()
        mock_analyze.assert_awaited_once()
        mock_push.assert_awaited_once()

    def test_low_score_cancels_without_ai(self):
        """규칙 스코어 미달 시 Claude API 호출 없이 CANCEL"""
        item = _signal("S1_GAP_OPEN")
        rdb = _make_rdb(rpop=json.dumps(item))

        with patch("queue_worker.rule_score", return_value=30.0), \
             patch("queue_worker.should_skip_ai", return_value=True), \
             patch("queue_worker.analyze_signal", new_callable=AsyncMock) as mock_analyze, \
             patch("queue_worker.push_score_only_queue", new_callable=AsyncMock) as mock_push, \
             patch("queue_worker._build_market_ctx", new_callable=AsyncMock,
                   return_value={"tick": {}, "hoga": {}, "strength": 90.0, "vi": {}}):
            from queue_worker import process_one
            result = _run(process_one(rdb))

        assert result is True
        mock_analyze.assert_not_awaited()
        mock_push.assert_awaited_once()
        # CANCEL 액션이 포함되어야 함
        push_args = mock_push.call_args[0][1]
        assert push_args["action"] == "CANCEL"

    def test_enriched_result_contains_original_fields(self):
        """최종 발행 페이로드에 원본 신호 필드가 포함"""
        item = _signal("S1_GAP_OPEN", entry_type="시초가", target_pct=3.5)
        rdb = _make_rdb(rpop=json.dumps(item))

        captured = []
        async def capture_push(rdb, payload):
            captured.append(payload)

        mock_ai_result = {
            "action": "ENTER", "ai_score": 80.0, "confidence": "HIGH",
            "reason": "good", "adjusted_target_pct": None, "adjusted_stop_pct": None,
        }

        with patch("queue_worker.rule_score", return_value=75.0), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock, return_value=True), \
             patch("queue_worker.analyze_signal", new_callable=AsyncMock,
                   return_value=mock_ai_result), \
             patch("queue_worker.push_score_only_queue", side_effect=capture_push), \
             patch("queue_worker._build_market_ctx", new_callable=AsyncMock,
                   return_value={"tick": {}, "hoga": {}, "strength": 120.0, "vi": {}}):
            from queue_worker import process_one
            _run(process_one(rdb))

        assert len(captured) == 1
        result = captured[0]
        assert result["stk_cd"] == "005930"
        assert result["strategy"] == "S1_GAP_OPEN"
        assert result["entry_type"] == "시초가"
        assert result["rule_score"] == 75.0
        assert result["ai_score"] == 80.0
        assert result["action"] == "ENTER"

    def test_daily_limit_exceeded_uses_fallback(self):
        """일별 Claude 호출 상한 초과 시 폴백 사용"""
        item = _signal("S1_GAP_OPEN")
        rdb = _make_rdb(rpop=json.dumps(item))

        captured = []
        async def capture_push(rdb, payload):
            captured.append(payload)

        with patch("queue_worker.rule_score", return_value=75.0), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock, return_value=False), \
             patch("queue_worker.analyze_signal", new_callable=AsyncMock) as mock_analyze, \
             patch("queue_worker.push_score_only_queue", side_effect=capture_push), \
             patch("queue_worker._build_market_ctx", new_callable=AsyncMock,
                   return_value={"tick": {}, "hoga": {}, "strength": 120.0, "vi": {}}):
            from queue_worker import process_one
            _run(process_one(rdb))

        mock_analyze.assert_not_awaited()
        assert len(captured) == 1

    def test_claude_error_falls_back_gracefully(self):
        """Claude API 오류 시 폴백으로 정상 처리"""
        item = _signal("S1_GAP_OPEN")
        rdb = _make_rdb(rpop=json.dumps(item))

        captured = []
        async def capture_push(rdb, payload):
            captured.append(payload)

        with patch("queue_worker.rule_score", return_value=75.0), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock, return_value=True), \
             patch("queue_worker.analyze_signal",
                   new_callable=AsyncMock, side_effect=Exception("API Error")), \
             patch("queue_worker.push_score_only_queue", side_effect=capture_push), \
             patch("queue_worker._build_market_ctx", new_callable=AsyncMock,
                   return_value={"tick": {}, "hoga": {}, "strength": 120.0, "vi": {}}):
            from queue_worker import process_one
            result = _run(process_one(rdb))

        assert result is True
        assert len(captured) == 1
        # 폴백은 여전히 action을 결정해야 함
        assert "action" in captured[0]


# ──────────────────────────────────────────────────────────────────
# 빈 큐 테스트
# ──────────────────────────────────────────────────────────────────

class TestEmptyQueue:
    def test_empty_queue_returns_false(self):
        """큐가 비어있을 때 False 반환"""
        rdb = _make_rdb(rpop=None)

        from queue_worker import process_one
        result = _run(process_one(rdb))

        assert result is False

    def test_empty_queue_does_not_push(self):
        """빈 큐일 때 ai_scored_queue에 아무것도 넣지 않음"""
        rdb = _make_rdb(rpop=None)

        with patch("queue_worker.push_score_only_queue", new_callable=AsyncMock) as mock_push:
            from queue_worker import process_one
            _run(process_one(rdb))

        mock_push.assert_not_awaited()


# ──────────────────────────────────────────────────────────────────
# _build_market_ctx 테스트
# ──────────────────────────────────────────────────────────────────

class TestBuildMarketCtx:
    def test_builds_ctx_with_all_components(self):
        """market_ctx 가 tick, hoga, strength, vi 를 모두 포함"""
        tick_data = {"cur_prc": "50000", "flu_rt": "3.5"}
        hoga_data = {"total_buy_bid_req": "2000", "total_sel_bid_req": "1000"}
        vi_data = {"vi_price": "48000", "status": "released"}

        rdb = MagicMock()
        rdb.hgetall = AsyncMock(side_effect=[tick_data, hoga_data, vi_data])
        rdb.lrange = AsyncMock(return_value=["120.0", "130.0"])

        from queue_worker import _build_market_ctx
        ctx = _run(_build_market_ctx(rdb, "005930"))

        assert ctx["tick"] == tick_data
        assert ctx["hoga"] == hoga_data
        assert isinstance(ctx["strength"], float)
        assert ctx["vi"] == vi_data
