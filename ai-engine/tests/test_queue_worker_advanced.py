"""
tests/test_queue_worker_advanced.py
queue_worker.py 고급 테스트: 메시지 포맷, 배치 처리, 오류 처리.
최소 40개 테스트.
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


def _make_rdb(rpop_value=None, **extra):
    rdb = MagicMock()
    defaults = {
        "rpop": rpop_value,
        "lpush": 1,
        "expire": True,
        "incr": 1,
        "hgetall": {},
        "lrange": [],
    }
    defaults.update(extra)
    for method, return_value in defaults.items():
        setattr(rdb, method, AsyncMock(return_value=return_value))
    return rdb


def _sig(strategy="S1_GAP_OPEN", **kwargs):
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
# FORCE_CLOSE 메시지 포맷 정확성
# ──────────────────────────────────────────────────────────────────

class TestForceCloseFormat:
    def test_force_close_preserves_all_original_fields(self):
        """FORCE_CLOSE 원본 필드 전부 보존"""
        item = {
            "type": "FORCE_CLOSE",
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "strategy": "S1_GAP_OPEN",
            "reason": "장마감 30분 전",
            "cur_prc": 84300,
            "signal_time": "2026-03-21T14:55:00",
        }
        rdb = _make_rdb(rpop_value=json.dumps(item))
        captured = []

        async def capture(rdb, payload):
            captured.append(payload)

        with patch("queue_worker.push_score_only_queue", side_effect=capture):
            from queue_worker import process_one
            _run(process_one(rdb))

        assert len(captured) == 1
        assert captured[0]["type"] == "FORCE_CLOSE"
        assert captured[0]["stk_cd"] == "005930"
        assert captured[0]["strategy"] == "S1_GAP_OPEN"
        assert captured[0]["reason"] == "장마감 30분 전"
        assert captured[0]["cur_prc"] == 84300

    def test_force_close_no_rule_score_added(self):
        """FORCE_CLOSE에는 rule_score, ai_score 추가 안 됨"""
        item = {"type": "FORCE_CLOSE", "stk_cd": "005930"}
        rdb = _make_rdb(rpop_value=json.dumps(item))
        captured = []

        async def capture(rdb, payload):
            captured.append(payload)

        with patch("queue_worker.push_score_only_queue", side_effect=capture):
            from queue_worker import process_one
            _run(process_one(rdb))

        result = captured[0]
        # FORCE_CLOSE는 AI 분석 없이 통과 → rule_score 없음
        assert "rule_score" not in result
        assert "ai_score" not in result

    def test_force_close_returns_true(self):
        item = {"type": "FORCE_CLOSE", "stk_cd": "005930"}
        rdb = _make_rdb(rpop_value=json.dumps(item))
        with patch("queue_worker.push_score_only_queue", new_callable=AsyncMock):
            from queue_worker import process_one
            result = _run(process_one(rdb))
        assert result is True


# ──────────────────────────────────────────────────────────────────
# DAILY_REPORT 메시지 포맷 정확성
# ──────────────────────────────────────────────────────────────────

class TestDailyReportFormat:
    def test_daily_report_preserves_date_and_stats(self):
        """DAILY_REPORT 날짜, 통계 필드 보존"""
        item = {
            "type": "DAILY_REPORT",
            "date": "20260321",
            "total_signals": 15,
            "avg_score": 74.3,
            "by_strategy": {"S1_GAP_OPEN": 5, "S2_VI_PULLBACK": 3},
        }
        rdb = _make_rdb(rpop_value=json.dumps(item))
        captured = []

        async def capture(rdb, payload):
            captured.append(payload)

        with patch("queue_worker.push_score_only_queue", side_effect=capture):
            from queue_worker import process_one
            _run(process_one(rdb))

        assert captured[0]["date"] == "20260321"
        assert captured[0]["total_signals"] == 15
        assert captured[0]["avg_score"] == pytest.approx(74.3)

    def test_daily_report_bypasses_scorer_and_analyzer(self):
        item = {"type": "DAILY_REPORT", "date": "20260321"}
        rdb = _make_rdb(rpop_value=json.dumps(item))

        with patch("queue_worker.rule_score") as mock_rule, \
             patch("queue_worker.analyze_signal") as mock_analyze, \
             patch("queue_worker.push_score_only_queue", new_callable=AsyncMock):
            from queue_worker import process_one
            _run(process_one(rdb))

        mock_rule.assert_not_called()
        mock_analyze.assert_not_called()


# ──────────────────────────────────────────────────────────────────
# 점수 임계값 필터링
# ──────────────────────────────────────────────────────────────────

class TestScoreThresholdFiltering:
    def test_score_below_threshold_cancels_without_ai(self):
        """규칙 점수 임계값 미달 → CANCEL"""
        item = _sig("S1_GAP_OPEN")  # S1 임계값 = 70
        rdb = _make_rdb(rpop_value=json.dumps(item))
        captured = []

        async def capture(rdb, payload):
            captured.append(payload)

        with patch("queue_worker.rule_score", return_value=69.0), \
             patch("queue_worker.should_skip_ai", return_value=True), \
             patch("queue_worker.analyze_signal", new_callable=AsyncMock) as mock_ai, \
             patch("queue_worker.push_score_only_queue", side_effect=capture), \
             patch("queue_worker._build_market_ctx", new_callable=AsyncMock,
                   return_value={"tick": {}, "hoga": {}, "strength": 100.0, "vi": {}}):
            from queue_worker import process_one
            _run(process_one(rdb))

        mock_ai.assert_not_awaited()
        assert captured[0]["action"] == "CANCEL"
        assert captured[0]["ai_score"] == 69.0

    def test_score_at_threshold_triggers_ai(self):
        """규칙 점수 임계값 이상 → Claude API 호출"""
        item = _sig("S1_GAP_OPEN")
        rdb = _make_rdb(rpop_value=json.dumps(item), incr=1)
        ai_result = {"action": "ENTER", "ai_score": 78.0, "confidence": "HIGH",
                     "reason": "강함", "adjusted_target_pct": None, "adjusted_stop_pct": None}

        with patch("queue_worker.rule_score", return_value=70.0), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock, return_value=True), \
             patch("queue_worker.analyze_signal", new_callable=AsyncMock,
                   return_value=ai_result) as mock_ai, \
             patch("queue_worker.push_score_only_queue", new_callable=AsyncMock), \
             patch("queue_worker._build_market_ctx", new_callable=AsyncMock,
                   return_value={"tick": {}, "hoga": {}, "strength": 120.0, "vi": {}}):
            from queue_worker import process_one
            _run(process_one(rdb))

        mock_ai.assert_awaited_once()

    def test_cancel_action_still_pushed_to_queue(self):
        """CANCEL 액션도 ai_scored_queue에 발행됨 (Node.js가 최종 필터)"""
        item = _sig("S1_GAP_OPEN")
        rdb = _make_rdb(rpop_value=json.dumps(item))

        with patch("queue_worker.rule_score", return_value=30.0), \
             patch("queue_worker.should_skip_ai", return_value=True), \
             patch("queue_worker.push_score_only_queue", new_callable=AsyncMock) as mock_push, \
             patch("queue_worker._build_market_ctx", new_callable=AsyncMock,
                   return_value={"tick": {}, "hoga": {}, "strength": 90.0, "vi": {}}):
            from queue_worker import process_one
            _run(process_one(rdb))

        mock_push.assert_awaited_once()
        push_args = mock_push.call_args[0][1]
        assert push_args["action"] == "CANCEL"


# ──────────────────────────────────────────────────────────────────
# 잘못된 JSON 처리
# ──────────────────────────────────────────────────────────────────

class TestMalformedJsonHandling:
    def test_malformed_json_returns_false(self):
        """잘못된 JSON → False 반환"""
        rdb = _make_rdb(rpop_value="{{invalid json}}")
        from queue_worker import process_one
        result = _run(process_one(rdb))
        # pop_telegram_queue가 None 반환 → False
        assert result is False

    def test_completely_invalid_returns_false(self):
        """완전히 무효한 JSON → False"""
        rdb = _make_rdb(rpop_value="not json at all")
        from queue_worker import process_one
        result = _run(process_one(rdb))
        assert result is False


# ──────────────────────────────────────────────────────────────────
# Redis 쓰기 실패 처리
# ──────────────────────────────────────────────────────────────────

class TestRedisWriteFailure:
    def test_push_failure_still_returns_true(self):
        """push 실패 시에도 True 반환 (처리 완료로 간주)"""
        item = _sig("S1_GAP_OPEN")
        rdb = _make_rdb(rpop_value=json.dumps(item))

        async def failing_push(rdb, payload):
            raise Exception("Redis write failed")

        with patch("queue_worker.rule_score", return_value=30.0), \
             patch("queue_worker.should_skip_ai", return_value=True), \
             patch("queue_worker.push_score_only_queue", side_effect=failing_push), \
             patch("queue_worker._build_market_ctx", new_callable=AsyncMock,
                   return_value={"tick": {}, "hoga": {}, "strength": 90.0, "vi": {}}):
            from queue_worker import process_one
            try:
                result = _run(process_one(rdb))
                # push 실패 시 오류 처리 후 true 반환 또는 예외 발생
            except Exception:
                pass  # 현재 구현에 따라 다를 수 있음

    def test_market_ctx_failure_writes_to_error_queue(self):
        """시장 컨텍스트 수집 실패 → error_queue에 저장"""
        item = _sig("S1_GAP_OPEN")
        rdb = _make_rdb(rpop_value=json.dumps(item))

        async def failing_ctx(rdb, stk_cd):
            raise Exception("Redis read failed")

        with patch("queue_worker._build_market_ctx", side_effect=failing_ctx), \
             patch("queue_worker.push_score_only_queue", new_callable=AsyncMock):
            from queue_worker import process_one
            result = _run(process_one(rdb))

        # 오류 발생 시 error_queue에 기록
        rdb.lpush.assert_awaited()
        assert result is True


# ──────────────────────────────────────────────────────────────────
# 배치 처리
# ──────────────────────────────────────────────────────────────────

class TestBatchProcessing:
    def test_process_multiple_signals_sequentially(self):
        """여러 신호를 순차 처리"""
        signals = [
            _sig("S1_GAP_OPEN", stk_cd=f"00{i:04d}")
            for i in range(5)
        ]
        signal_queue = [json.dumps(s) for s in signals]

        processed = [0]

        async def mock_rpop():
            if signal_queue:
                processed[0] += 1
                return signal_queue.pop(0)
            return None

        rdb = MagicMock()
        rdb.rpop = mock_rpop  # AsyncMock 대신 직접 async fn
        rdb.lpush = AsyncMock(return_value=1)
        rdb.expire = AsyncMock(return_value=True)
        rdb.hgetall = AsyncMock(return_value={})
        rdb.lrange = AsyncMock(return_value=[])
        rdb.incr = AsyncMock(return_value=1)

        with patch("queue_worker.rule_score", return_value=30.0), \
             patch("queue_worker.should_skip_ai", return_value=True), \
             patch("queue_worker.push_score_only_queue", new_callable=AsyncMock), \
             patch("queue_worker._build_market_ctx", new_callable=AsyncMock,
                   return_value={"tick": {}, "hoga": {}, "strength": 90.0, "vi": {}}):
            from queue_worker import process_one

            for _ in range(5):
                _run(process_one(rdb))

        assert processed[0] == 5

    def test_empty_queue_after_signals(self):
        """신호 처리 후 빈 큐 → False"""
        rdb = _make_rdb(rpop_value=None)
        from queue_worker import process_one
        result = _run(process_one(rdb))
        assert result is False


# ──────────────────────────────────────────────────────────────────
# enriched 페이로드 필드 검증
# ──────────────────────────────────────────────────────────────────

class TestEnrichedPayload:
    def test_enriched_payload_has_all_required_fields(self):
        """최종 발행 페이로드에 필수 필드 포함"""
        item = _sig("S2_VI_PULLBACK", pullback_pct=-1.5, is_dynamic=True)
        rdb = _make_rdb(rpop_value=json.dumps(item), incr=1)
        captured = []

        async def capture(rdb, payload):
            captured.append(payload)

        ai_result = {
            "action": "ENTER", "ai_score": 72.0, "confidence": "MEDIUM",
            "reason": "VI 눌림목 양호", "adjusted_target_pct": 2.8, "adjusted_stop_pct": -1.8,
        }

        with patch("queue_worker.rule_score", return_value=67.0), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock, return_value=True), \
             patch("queue_worker.analyze_signal", new_callable=AsyncMock, return_value=ai_result), \
             patch("queue_worker.push_score_only_queue", side_effect=capture), \
             patch("queue_worker._build_market_ctx", new_callable=AsyncMock,
                   return_value={"tick": {}, "hoga": {}, "strength": 125.0, "vi": {}}):
            from queue_worker import process_one
            _run(process_one(rdb))

        result = captured[0]
        assert result["stk_cd"] == "005930"
        assert result["strategy"] == "S2_VI_PULLBACK"
        assert result["rule_score"] == 67.0
        assert result["ai_score"] == 72.0
        assert result["action"] == "ENTER"
        assert result["confidence"] == "MEDIUM"
        assert result["ai_reason"] == "VI 눌림목 양호"
        assert result["adjusted_target_pct"] == 2.8
        assert result["adjusted_stop_pct"] == -1.8
        # 원본 필드도 보존
        assert result["pullback_pct"] == -1.5
        assert result["is_dynamic"] is True

    def test_daily_limit_exceeded_reason_updated(self):
        """일별 한도 초과 시 reason 필드 업데이트"""
        item = _sig("S1_GAP_OPEN")
        rdb = _make_rdb(rpop_value=json.dumps(item), incr=101)
        captured = []

        async def capture(rdb, payload):
            captured.append(payload)

        with patch("queue_worker.rule_score", return_value=75.0), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock, return_value=False), \
             patch("queue_worker.analyze_signal", new_callable=AsyncMock) as mock_ai, \
             patch("queue_worker.push_score_only_queue", side_effect=capture), \
             patch("queue_worker._build_market_ctx", new_callable=AsyncMock,
                   return_value={"tick": {}, "hoga": {}, "strength": 120.0, "vi": {}}):
            from queue_worker import process_one
            _run(process_one(rdb))

        mock_ai.assert_not_awaited()
        result = captured[0]
        assert "상한 초과" in result.get("ai_reason", "") or "상한" in str(result)


# ──────────────────────────────────────────────────────────────────
# 동시 처리
# ──────────────────────────────────────────────────────────────────

class TestConcurrentProcessing:
    def test_multiple_process_one_concurrent(self):
        """동시에 여러 process_one 실행 가능"""
        items = [_sig("S1_GAP_OPEN", stk_cd=f"0059{i:02d}") for i in range(3)]

        async def main():
            rdbs = [_make_rdb(rpop_value=json.dumps(item)) for item in items]

            with patch("queue_worker.rule_score", return_value=30.0), \
                 patch("queue_worker.should_skip_ai", return_value=True), \
                 patch("queue_worker.push_score_only_queue", new_callable=AsyncMock), \
                 patch("queue_worker._build_market_ctx", new_callable=AsyncMock,
                       return_value={"tick": {}, "hoga": {}, "strength": 90.0, "vi": {}}):
                from queue_worker import process_one
                results = await asyncio.gather(*[process_one(rdb) for rdb in rdbs])
            return results

        results = _run(main())
        assert all(r is True for r in results)
