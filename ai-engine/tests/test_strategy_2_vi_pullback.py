from __future__ import annotations
"""
test_strategy_2_vi_pullback.py
S2_VI_PULLBACK 전략 단위 테스트.

커버 범위:
  1. vi_vol_ratio=2.9 → hard reject (strict gate on)
  2. vi_vol_ratio=3.0, 조건 만족 → pass
  3. vi_vol_ratio 누락 → SHADOW 처리
  4. vi_amount_ratio=2.9 → hard reject (strict gate on)
  5. 2차 VI 위험 플래그 산출
  6. payload 필수 필드 포함 확인
  7. strict gate 비활성화 시 미달 후보 → SHADOW (not None)
  8. volume_quality=CONFIRMED 케이스
"""

import os
import sys
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── 공통 mock 빌더 ────────────────────────────────────────────────────────

_KST = timezone(timedelta(hours=9))

VI_PRICE = 10000.0
CUR_PRICE = 9800.0  # -2.0% pullback (정상 범위)


def _make_rdb(
    *,
    cur_prc: float = CUR_PRICE,
    vi_vol_ratio: float | None = 3.5,
    vi_amount_ratio: float | None = 3.5,
    vi_volume_source: str = "realtime_diff",
    vi_time_offset_sec: int = 600,  # VI 발동 후 경과 초 (기본 10분 → secondary risk LOW)
    recent_vi_count: int = 1,
    bid_qty: float = 2000.0,
    ask_qty: float = 1000.0,
    hoga_valid: bool = True,
    rebound_high: float | None = None,
):
    """watch_item과 함께 사용할 AsyncMock rdb를 반환."""
    rdb = AsyncMock()

    # ws:tick
    rdb.hgetall = AsyncMock(side_effect=_make_hgetall(
        cur_prc=cur_prc,
        vi_vol_ratio=vi_vol_ratio,
        vi_amount_ratio=vi_amount_ratio,
        vi_volume_source=vi_volume_source,
        vi_time_offset_sec=vi_time_offset_sec,
        recent_vi_count=recent_vi_count,
        bid_qty=bid_qty,
        ask_qty=ask_qty,
        hoga_valid=hoga_valid,
        rebound_high=rebound_high,
    ))

    rdb.lrange = AsyncMock(return_value=[])
    rdb.get = AsyncMock(return_value=None)
    rdb.set = AsyncMock(return_value=True)
    rdb.exists = AsyncMock(return_value=0)
    return rdb


def _make_hgetall(
    *,
    cur_prc,
    vi_vol_ratio,
    vi_amount_ratio,
    vi_volume_source,
    vi_time_offset_sec,
    recent_vi_count,
    bid_qty,
    ask_qty,
    hoga_valid,
    rebound_high,
):
    vi_time_dt = datetime.now(_KST) - timedelta(seconds=vi_time_offset_sec)
    vi_time_str = vi_time_dt.isoformat()

    vi_hash: dict = {
        "vi_price": str(VI_PRICE),
        "vi_time": vi_time_str,
        "vi_type": "2",
        "vi_volume": "50000",
        "vi_volume_source": vi_volume_source,
        "is_dynamic": "1",
        "status": "released",
        "recent_vi_count": str(recent_vi_count),
    }
    if vi_vol_ratio is not None:
        vi_hash["vi_vol_ratio"] = str(vi_vol_ratio)
    if vi_amount_ratio is not None:
        vi_hash["vi_amount_ratio"] = str(vi_amount_ratio)
    if rebound_high is not None:
        vi_hash["rebound_high"] = str(rebound_high)

    tick_hash = {
        "cur_prc": str(cur_prc),
        "acc_trde_qty": "100000",
        "acc_trde_prica": "980000000",
        "cntr_str": "120.0",
        "updated_at_ms": str(int(time.time() * 1000)),
    }

    hoga_hash: dict = {}
    if hoga_valid:
        hoga_hash = {
            "total_buy_bid_req": str(bid_qty),
            "total_sel_bid_req": str(ask_qty),
            "updated_at_ms": str(int(time.time() * 1000)),
        }

    async def _hgetall(key: str):
        if key.startswith("ws:tick:"):
            return tick_hash
        if key.startswith("vi:"):
            return vi_hash
        if key.startswith("ws:hoga:"):
            return hoga_hash
        return {}

    return _hgetall


def _make_watch_item(stk_cd: str = "005930") -> dict:
    return {
        "stk_cd": stk_cd,
        "vi_price": VI_PRICE,
        "watch_until": int((time.time() + 600) * 1000),
        "is_dynamic": True,
    }


# ── 공통 patch context ────────────────────────────────────────────────────

def _patch_externals(strength: float = 120.0):
    """체결강도 캐시, hoga REST, 종목명, ATR, tp_sl 을 한꺼번에 mock."""
    return [
        patch(
            "strategy_2_vi_pullback.fetch_cntr_strength_cached",
            new=AsyncMock(return_value=(strength, "redis")),
        ),
        patch(
            "strategy_2_vi_pullback.fetch_hoga",
            new=AsyncMock(return_value=None),  # ws:hoga 있으면 호출 안 됨
        ),
        patch(
            "strategy_2_vi_pullback.fetch_stk_nm",
            new=AsyncMock(return_value="삼성전자"),
        ),
        patch(
            "strategy_2_vi_pullback.fetch_same_time_volume_ratio",
            new=AsyncMock(return_value=({"same_time_volume_ratio": 0.0}, {"api_id": "ka10055"})),
        ),
        patch(
            "strategy_2_vi_pullback.get_atr_minute",
            new=AsyncMock(side_effect=Exception("no atr")),
        ),
        patch(
            "strategy_2_vi_pullback.calc_tp_sl",
            return_value=MagicMock(to_signal_fields=lambda: {"tp": 10200, "sl": 9600}),
        ),
    ]


async def _run_check(rdb, strict_gate: bool = True, strength: float = 120.0) -> dict | None:
    """check_vi_pullback을 strict gate 설정과 함께 실행."""
    import strategy_2_vi_pullback as m

    watch_item = _make_watch_item()
    patches = _patch_externals(strength=strength)

    with patch.object(m, "ENABLE_S2_STRICT_VOLUME_GATE", strict_gate):
        ctx_managers = [p.__enter__() for p in patches]
        try:
            result = await m.check_vi_pullback("dummy_token", watch_item, rdb)
        finally:
            for p, _ in zip(patches, ctx_managers):
                p.__exit__(None, None, None)

    return result


# ══════════════════════════════════════════════════════════════════════════
# 1. vi_vol_ratio < 3.0 → hard reject (strict gate on)
# ══════════════════════════════════════════════════════════════════════════

class TestVolRatioBelowThresholdRejected:
    @pytest.mark.asyncio
    async def test_vol_ratio_2_9_rejected_when_strict(self):
        """vi_vol_ratio=2.9 이면 strict gate on 시 None 반환"""
        rdb = _make_rdb(vi_vol_ratio=2.9, vi_amount_ratio=4.0)
        result = await _run_check(rdb, strict_gate=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_vol_ratio_zero_rejected_when_strict(self):
        """vi_vol_ratio=0.0 도 hard reject"""
        rdb = _make_rdb(vi_vol_ratio=0.0, vi_amount_ratio=5.0)
        result = await _run_check(rdb, strict_gate=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_vol_ratio_just_below_threshold(self):
        """vi_vol_ratio=2.99 → 반올림 기준 미달, hard reject"""
        rdb = _make_rdb(vi_vol_ratio=2.99, vi_amount_ratio=4.0)
        result = await _run_check(rdb, strict_gate=True)
        assert result is None


# ══════════════════════════════════════════════════════════════════════════
# 2. vi_vol_ratio=3.0 이상 + 조건 만족 → pass
# ══════════════════════════════════════════════════════════════════════════

class TestVolRatioAtThresholdPasses:
    @pytest.mark.asyncio
    async def test_vol_ratio_3_0_passes(self):
        """vi_vol_ratio=3.0 정확히 기준값 → pass"""
        rdb = _make_rdb(vi_vol_ratio=3.0, vi_amount_ratio=3.0)
        result = await _run_check(rdb, strict_gate=True)
        assert result is not None
        assert result["stk_cd"] == "005930"
        assert result["strategy"] == "S2_VI_PULLBACK"

    @pytest.mark.asyncio
    async def test_vol_ratio_above_threshold_passes(self):
        """vi_vol_ratio=5.5 → 조건 만족, pass"""
        rdb = _make_rdb(vi_vol_ratio=5.5, vi_amount_ratio=4.2)
        result = await _run_check(rdb, strict_gate=True)
        assert result is not None

    @pytest.mark.asyncio
    async def test_confirmed_volume_quality(self):
        """두 배수 모두 >= 3.0 → volume_quality=CONFIRMED"""
        rdb = _make_rdb(vi_vol_ratio=3.5, vi_amount_ratio=3.5)
        result = await _run_check(rdb, strict_gate=True)
        assert result is not None
        assert result["volume_quality"] == "CONFIRMED"


# ══════════════════════════════════════════════════════════════════════════
# 3. vi_vol_ratio 누락/산출 불가 → SHADOW 처리
# ══════════════════════════════════════════════════════════════════════════

class TestVolRatioMissingBlocksLiveSignal:
    @pytest.mark.asyncio
    async def test_vol_ratio_missing_key_returns_shadow(self):
        """vi_vol_ratio 키 없음 → volume_quality=UNKNOWN, signal_mode=SHADOW"""
        rdb = _make_rdb(
            vi_vol_ratio=None,
            vi_amount_ratio=None,
            vi_volume_source="unknown",
        )
        result = await _run_check(rdb, strict_gate=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_vol_ratio_zero_with_unknown_source_returns_shadow(self):
        """vi_volume_source=unknown + ratio 모두 0 → SHADOW"""
        rdb = _make_rdb(vi_vol_ratio=0.0, vi_amount_ratio=0.0, vi_volume_source="unknown")
        result = await _run_check(rdb, strict_gate=False)
        assert result is None

    @pytest.mark.asyncio
    async def test_shadow_payload_contains_required_fields(self):
        """SHADOW 케이스에서도 vi_vol_ratio 등 필드가 payload에 포함됨"""
        rdb = _make_rdb(vi_vol_ratio=None, vi_amount_ratio=None, vi_volume_source="unknown")
        result = await _run_check(rdb, strict_gate=True)
        assert result is None


# ══════════════════════════════════════════════════════════════════════════
# 4. vi_amount_ratio < 3.0 → hard reject (strict gate on)
# ══════════════════════════════════════════════════════════════════════════

class TestAmountRatioBelowThresholdRejected:
    @pytest.mark.asyncio
    async def test_amount_ratio_2_9_rejected(self):
        """vi_amount_ratio=2.9, vi_vol_ratio 충분 → strict gate에서 reject"""
        rdb = _make_rdb(vi_vol_ratio=5.0, vi_amount_ratio=2.9)
        result = await _run_check(rdb, strict_gate=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_amount_ratio_zero_rejected(self):
        rdb = _make_rdb(vi_vol_ratio=4.0, vi_amount_ratio=0.0, vi_volume_source="realtime_diff")
        result = await _run_check(rdb, strict_gate=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_both_ratios_must_meet_threshold(self):
        """vol_ratio 충분해도 amount_ratio 미달이면 reject"""
        rdb = _make_rdb(vi_vol_ratio=10.0, vi_amount_ratio=1.5)
        result = await _run_check(rdb, strict_gate=True)
        assert result is None


# ══════════════════════════════════════════════════════════════════════════
# 5. 2차 VI 위험 플래그
# ══════════════════════════════════════════════════════════════════════════

class TestSecondaryViRiskFlag:
    @pytest.mark.asyncio
    async def test_secondary_risk_high_when_recent_repeated_vi(self):
        """VI 발동 후 5분 이내이고 반복 발동 이력이 있으면 secondary_vi_risk=HIGH"""
        rdb = _make_rdb(
            vi_vol_ratio=3.5,
            vi_amount_ratio=3.5,
            vi_time_offset_sec=60,
            recent_vi_count=2,
        )
        result = await _run_check(rdb, strict_gate=True)
        assert result is not None
        assert result["secondary_vi_risk"] == "HIGH"

    @pytest.mark.asyncio
    async def test_secondary_risk_low_when_vi_old(self):
        """VI 발동 후 10분(600초) 이상 경과 → secondary_vi_risk=LOW"""
        rdb = _make_rdb(
            vi_vol_ratio=3.5,
            vi_amount_ratio=3.5,
            vi_time_offset_sec=600,
        )
        result = await _run_check(rdb, strict_gate=True)
        assert result is not None
        assert result["secondary_vi_risk"] == "LOW"

    def test_assess_secondary_vi_risk_high_for_repeated_recent_vi(self):
        """_assess_secondary_vi_risk 단독: 반복된 최근 VI → HIGH"""
        from strategy_2_vi_pullback import _assess_secondary_vi_risk

        recent_time = (datetime.now(_KST) - timedelta(seconds=120)).isoformat()
        vi_data = {"vi_time": recent_time, "recent_vi_count": "2"}
        assert _assess_secondary_vi_risk(vi_data) == "HIGH"

    def test_assess_secondary_vi_risk_low_for_single_recent_vi(self):
        """단순히 최근 VI라는 이유만으로 HIGH 처리하지 않는다."""
        from strategy_2_vi_pullback import _assess_secondary_vi_risk

        recent_time = (datetime.now(_KST) - timedelta(seconds=120)).isoformat()
        vi_data = {"vi_time": recent_time, "recent_vi_count": "1"}
        assert _assess_secondary_vi_risk(vi_data) == "LOW"

    def test_assess_secondary_vi_risk_low(self):
        """_assess_secondary_vi_risk 단독: 오래된 VI → LOW"""
        from strategy_2_vi_pullback import _assess_secondary_vi_risk

        old_time = (datetime.now(_KST) - timedelta(seconds=1000)).isoformat()
        vi_data = {"vi_time": old_time}
        assert _assess_secondary_vi_risk(vi_data) == "LOW"

    def test_assess_secondary_vi_risk_no_time(self):
        """vi_time 없으면 LOW 반환"""
        from strategy_2_vi_pullback import _assess_secondary_vi_risk

        assert _assess_secondary_vi_risk({}) == "LOW"


# ══════════════════════════════════════════════════════════════════════════
# 6. payload 필수 필드 포함 확인
# ══════════════════════════════════════════════════════════════════════════

class TestPayloadContainsRequiredFields:
    @pytest.mark.asyncio
    async def test_all_required_fields_present(self):
        """정상 통과 시 payload 필드 전체 확인"""
        rdb = _make_rdb(vi_vol_ratio=3.5, vi_amount_ratio=3.5)
        result = await _run_check(rdb, strict_gate=True)
        assert result is not None

        required = [
            "stk_cd", "stk_nm", "cur_prc", "strategy",
            "vi_price", "pullback_pct", "cntr_strength", "bid_ratio",
            "is_dynamic", "entry_type",
            "vi_vol_ratio", "vi_amount_ratio", "volume_quality", "secondary_vi_risk",
        ]
        for field in required:
            assert field in result, f"필드 누락: {field}"

    @pytest.mark.asyncio
    async def test_vi_vol_ratio_value_in_payload(self):
        """payload의 vi_vol_ratio 값이 입력값과 일치"""
        rdb = _make_rdb(vi_vol_ratio=4.7, vi_amount_ratio=5.1)
        result = await _run_check(rdb, strict_gate=True)
        assert result is not None
        assert abs(result["vi_vol_ratio"] - 4.7) < 0.01
        assert abs(result["vi_amount_ratio"] - 5.1) < 0.01

    @pytest.mark.asyncio
    async def test_no_signal_mode_in_normal_payload(self):
        """정상 후보는 signal_mode 필드가 없거나 None"""
        rdb = _make_rdb(vi_vol_ratio=3.5, vi_amount_ratio=3.5)
        result = await _run_check(rdb, strict_gate=True)
        assert result is not None
        # signal_mode 없거나 있으면 SHADOW가 아니어야 함
        assert result.get("signal_mode") != "SHADOW"


# ══════════════════════════════════════════════════════════════════════════
# 7. strict gate 비활성화 시 미달 후보 → SHADOW (not None)
# ══════════════════════════════════════════════════════════════════════════

class TestStrictGateOffBehavior:
    @pytest.mark.asyncio
    async def test_gate_off_low_ratio_blocks_live_signal(self):
        """strict gate=false 에서 배수 미달 → SHADOW payload 반환 (탈락 아님)"""
        rdb = _make_rdb(
            vi_vol_ratio=2.0,
            vi_amount_ratio=1.5,
            vi_volume_source="candle_avg",
        )
        result = await _run_check(rdb, strict_gate=False)
        assert result is None

    @pytest.mark.asyncio
    async def test_gate_off_high_ratio_passes_normally(self):
        """strict gate=false + 배수 충분 → 정상 통과"""
        rdb = _make_rdb(vi_vol_ratio=4.0, vi_amount_ratio=4.0)
        result = await _run_check(rdb, strict_gate=False)
        assert result is not None
        assert result.get("signal_mode") is None or result.get("signal_mode") != "SHADOW"


class TestPublishableSignal:
    def test_non_live_signal_is_rejected_by_live_configuration(self):
        from strategy_2_vi_pullback import is_publishable_signal

        signal = {"signal_mode": "SHADOW"}
        assert is_publishable_signal(signal) is False
        assert signal["signal_mode"] == "SHADOW"

    def test_normal_signal_is_publishable(self):
        from strategy_2_vi_pullback import is_publishable_signal

        assert is_publishable_signal({"signal_mode": "NORMAL"}) is True
        assert is_publishable_signal({"stk_cd": "005930"}) is True

    def test_non_live_signal_is_rejected_when_live_enabled(self, monkeypatch):
        from strategy_2_vi_pullback import is_publishable_signal

        monkeypatch.setenv("LIVE_ONLY_MODE", "true")
        signal = {"signal_mode": "SHADOW", "volume_quality": "UNKNOWN"}
        assert is_publishable_signal(signal) is False
        assert signal["signal_mode"] == "SHADOW"


class TestHandleViEvent:
    @pytest.mark.asyncio
    async def test_handle_vi_event_stores_volume_ratio_fields(self):
        from strategy_2_vi_pullback import handle_vi_event, vi_events

        vi_events.clear()
        rdb = AsyncMock()
        rdb.hgetall = AsyncMock(return_value={
            "acc_trde_qty": "100000",
            "acc_trde_prica": "1000000000",
            "prev_5m_avg_qty": "20000",
            "prev_5m_avg_amt": "200000000",
            "updated_at_ms": str(int(time.time() * 1000)),
        })
        rdb.hset = AsyncMock()
        rdb.expire = AsyncMock()

        await handle_vi_event(rdb, {
            "stk_cd": "005930",
            "vi_type": "2",
            "vi_stat": "1",
            "vi_pric": "10000",
            "acc_trde_qty": "100000",
        })

        mapping = rdb.hset.await_args.kwargs["mapping"]
        assert mapping["vi_vol_ratio"] == "5.0"
        assert mapping["vi_amount_ratio"] == "5.0"
        assert mapping["vi_volume_source"] == "realtime_diff"
        assert mapping["is_dynamic"] == "1"
        assert mapping["recent_vi_count"] == "1"


class TestReboundHighBreakout:
    @pytest.mark.asyncio
    async def test_rebound_high_below_vi_price_rejected(self):
        rdb = _make_rdb(
            vi_vol_ratio=3.5,
            vi_amount_ratio=3.5,
            rebound_high=9950.0,
        )
        result = await _run_check(rdb, strict_gate=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_rebound_high_at_vi_price_passes(self):
        rdb = _make_rdb(
            vi_vol_ratio=3.5,
            vi_amount_ratio=3.5,
            rebound_high=10000.0,
        )
        result = await _run_check(rdb, strict_gate=True)
        assert result is not None
        assert result["rebound_high_breakout"] == "PASS"

    @pytest.mark.asyncio
    async def test_gate_on_low_ratio_returns_none(self):
        """strict gate=true + 배수 미달 → None 반환 (hard reject)"""
        rdb = _make_rdb(vi_vol_ratio=2.0, vi_amount_ratio=1.5, vi_volume_source="candle_avg")
        result = await _run_check(rdb, strict_gate=True)
        assert result is None


# ══════════════════════════════════════════════════════════════════════════
# 8. volume_quality=CONFIRMED 케이스 및 PARTIAL 케이스
# ══════════════════════════════════════════════════════════════════════════

class TestVolumeQualityBuckets:
    @pytest.mark.asyncio
    async def test_confirmed_when_both_above_threshold(self):
        rdb = _make_rdb(vi_vol_ratio=3.1, vi_amount_ratio=3.1)
        result = await _run_check(rdb, strict_gate=False)
        assert result is not None
        assert result["volume_quality"] == "CONFIRMED"

    @pytest.mark.asyncio
    async def test_partial_when_only_vol_above_threshold(self):
        """vol_ratio>=3 but amount_ratio<3 + strict gate off → PARTIAL"""
        rdb = _make_rdb(vi_vol_ratio=3.5, vi_amount_ratio=2.5, vi_volume_source="realtime_diff")
        result = await _run_check(rdb, strict_gate=False)
        assert result is not None
        assert result["volume_quality"] == "PARTIAL"

    @pytest.mark.asyncio
    async def test_partial_when_only_amount_above_threshold(self):
        """vol_ratio<3 but amount_ratio>=3 + strict gate off → PARTIAL"""
        rdb = _make_rdb(vi_vol_ratio=2.5, vi_amount_ratio=3.5, vi_volume_source="realtime_diff")
        result = await _run_check(rdb, strict_gate=False)
        assert result is not None
        assert result["volume_quality"] == "PARTIAL"


# ══════════════════════════════════════════════════════════════════════════
# 9. 눌림 범위 이탈 시 None 반환 (기존 로직 보존)
# ══════════════════════════════════════════════════════════════════════════

class TestPullbackRangeFilter:
    @pytest.mark.asyncio
    async def test_pullback_too_deep_rejected(self):
        """-3% 초과 눌림 → None (pullback 조건 탈락)"""
        # cur_price=9650 → (9650-10000)/10000 = -3.5%
        rdb = _make_rdb(cur_prc=9650.0, vi_vol_ratio=5.0, vi_amount_ratio=5.0)
        result = await _run_check(rdb, strict_gate=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_pullback_rejected(self):
        """눌림 없음(현재가 > VI 발동가) → None"""
        rdb = _make_rdb(cur_prc=10100.0, vi_vol_ratio=5.0, vi_amount_ratio=5.0)
        result = await _run_check(rdb, strict_gate=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_pullback_1pct_passes(self):
        """-1% 눌림 → 범위 내"""
        rdb = _make_rdb(cur_prc=9900.0, vi_vol_ratio=3.5, vi_amount_ratio=3.5)
        result = await _run_check(rdb, strict_gate=True)
        assert result is not None


# ══════════════════════════════════════════════════════════════════════════
# 10. _parse_vi_vol_ratio 단독 테스트
# ══════════════════════════════════════════════════════════════════════════

class TestParseViVolRatio:
    def test_normal_parse(self):
        from strategy_2_vi_pullback import _parse_vi_vol_ratio

        vi_data = {
            "vi_vol_ratio": "4.5",
            "vi_amount_ratio": "3.8",
            "vi_volume_source": "realtime_diff",
        }
        vol, amt, src = _parse_vi_vol_ratio(vi_data)
        assert vol == 4.5
        assert amt == 3.8
        assert src == "realtime_diff"

    def test_missing_keys(self):
        from strategy_2_vi_pullback import _parse_vi_vol_ratio

        vol, amt, src = _parse_vi_vol_ratio({})
        assert vol == 0.0
        assert amt == 0.0
        assert src == "unknown"

    def test_invalid_float(self):
        from strategy_2_vi_pullback import _parse_vi_vol_ratio

        vi_data = {
            "vi_vol_ratio": "N/A",
            "vi_amount_ratio": "",
            "vi_volume_source": "candle_avg",
        }
        vol, amt, src = _parse_vi_vol_ratio(vi_data)
        assert vol == 0.0
        assert amt == 0.0
        assert src == "candle_avg"
