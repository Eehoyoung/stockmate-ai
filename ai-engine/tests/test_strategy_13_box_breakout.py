"""
tests/test_strategy_13_box_breakout.py

회귀 테스트 (2026-08-13 트레이더 리뷰에서 발견한 버그 수정):
S13은 예전에 detect_box_breakout() 내부에서 "오늘 누적거래량(장중 계속
불어나는 값) >= 15일 평균 *하루 전체* 거래량 x 2.0"을 하드게이트로 걸었다.
이건 시간대 편향이 있다 — 이른 시간에 스캔하면 오늘 누적거래량이 하루치의
일부에 불과해서, 실제로 강한 돌파가 나와도 게이트를 통과하기 어렵다.

수정 후에는 S7/S8/S9와 동일하게 ka10055 전일 동시간대 비교
(resolve_effective_volume_ratio)를 우선 사용하고, 실패/불완전 시에만
기존 당일누적/15일평균 비율로 폴백한다. 이 파일은 그 전환이 실제로
동작하는지 검증한다.

실행:
  cd ai-engine
  python -m pytest tests/test_strategy_13_box_breakout.py -v
"""

import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _s13_candles():
    """62개 일봉: [0]=오늘(박스 상단 돌파 + 양봉, 거래량은 낮게),
    [1:16]=박스권(4% 폭), [16:62]=나머지 채움용."""
    candles = []
    for idx in range(62):
        if idx == 0:
            candles.append({
                "cur_prc": "110", "open_pric": "100",
                "high_pric": "112", "low_pric": "98", "trde_qty": "400",
            })
        else:
            candles.append({
                "cur_prc": "100", "open_pric": "100",
                "high_pric": "102", "low_pric": "98", "trde_qty": "1000",
            })
    return candles


async def _scan_s13_with_volume_meta(monkeypatch, meta):
    import strategy_13_box_breakout as s13

    rdb = AsyncMock()

    async def lrange(key, start, end):
        if key == "candidates:s13:001":
            return ["005930"]
        return []

    rdb.lrange = AsyncMock(side_effect=lrange)

    tp_sl = MagicMock()
    tp_sl.to_signal_fields.return_value = {"rr_ratio": 1.8}

    eq_result = {
        "spread_pct": 0.1, "depth_score": 1.0, "sell_wall_score": 0.0,
        "vwap_position": "above", "first_low_break": False,
        "breakout_line_break": False, "upper_shadow_pct": 1.0,
        "close_position_pct": 90.0, "chase_risk_score": 0.1,
        "execution_quality": "NORMAL", "reject_reason": None,
    }

    monkeypatch.setattr(s13.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(s13, "fetch_daily_candles", AsyncMock(return_value=_s13_candles()))
    monkeypatch.setattr(s13, "calc_bollinger", lambda *a, **k: [(105.0, 100.0, 95.0)])
    monkeypatch.setattr(s13, "calc_mfi", lambda *a, **k: [60.0])
    monkeypatch.setattr(s13, "calc_rsi", lambda *a, **k: [50.0])
    monkeypatch.setattr(s13, "calc_atr", lambda *a, **k: [5.0])
    monkeypatch.setattr(
        s13, "get_tick_with_status",
        AsyncMock(return_value={"data": {"flu_rt": "5.0", "cntr_str": "130"}}),
    )
    monkeypatch.setattr(s13, "calc_tp_sl", MagicMock(return_value=tp_sl))
    monkeypatch.setattr(s13, "_fetch_hoga_raw_s13", AsyncMock(return_value={}))
    monkeypatch.setattr(s13, "_fetch_minute_chart_raw_s13", AsyncMock(return_value={}))
    monkeypatch.setattr(s13, "assess_execution_quality", lambda *a, **k: eq_result)
    monkeypatch.setattr(s13, "should_hard_reject", lambda *a, **k: False)
    monkeypatch.setattr(s13, "fetch_stk_nm", AsyncMock(return_value="테스트종목"))
    monkeypatch.setattr(s13, "fetch_program_snapshot", AsyncMock(return_value={}))
    monkeypatch.setattr(s13, "program_drop_reason", lambda *a, **k: None)
    monkeypatch.setattr(s13, "fetch_volume_profile", AsyncMock(return_value=({}, {})))
    monkeypatch.setattr(s13, "apply_volume_profile_rr", lambda signal, profile: signal)
    monkeypatch.setattr(
        s13,
        "fetch_same_time_volume_ratio_cached",
        AsyncMock(return_value=({"same_time_volume_ratio": 2.5}, meta)),
    )

    return await s13.scan_box_breakout("token", rdb=rdb)


@pytest.mark.asyncio
async def test_s13_uses_same_time_ratio_even_when_daily_partial_ratio_is_weak(monkeypatch):
    """핵심 회귀: 당일누적/15일평균 비율(0.4)은 예전 게이트(>=2.0)를 통과하지
    못했을 값이지만, 전일 동시간대 비율(2.5)이 완전하면 이를 우선 사용해
    신호를 통과시켜야 한다."""
    result = await _scan_s13_with_volume_meta(
        monkeypatch,
        {"api_id": "ka10055", "complete": True},
    )

    assert len(result) == 1
    assert result[0]["daily_volume_ratio"] == 0.4
    assert result[0]["vol_ratio"] == 2.5
    assert result[0]["volume_ratio_source"] == "ka10055_same_time"


@pytest.mark.asyncio
async def test_s13_falls_back_to_daily_ratio_when_same_time_incomplete(monkeypatch):
    """ka10055가 불완전/실패하면 기존 당일누적/15일평균 비율로 폴백하고,
    그 값이 임계값(2.0) 미만이면 정상적으로 거절해야 한다(안전망 유지)."""
    result = await _scan_s13_with_volume_meta(
        monkeypatch,
        {"api_id": "ka10055", "complete": False},
    )

    assert result == []


@pytest.mark.asyncio
async def test_s13_reads_strategy_owned_candidate_pool(monkeypatch):
    import strategy_13_box_breakout as s13

    rdb = AsyncMock()
    rdb.lrange = AsyncMock(side_effect=[[], []])

    result = await s13.scan_box_breakout("token", rdb=rdb)

    assert result == []
    assert rdb.lrange.await_args_list[0].args == ("candidates:s13:001", 0, s13._POOL_READ_LIMIT - 1)
    assert rdb.lrange.await_args_list[1].args == ("candidates:s13:101", 0, s13._POOL_READ_LIMIT - 1)
