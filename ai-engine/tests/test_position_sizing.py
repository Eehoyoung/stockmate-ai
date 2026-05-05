"""
test_position_sizing.py

position_sizing.calculate_entry_size() 소단위 테스트.
계좌 관련 파라미터 절대 금지 원칙 및 전략별 상한 검증 포함.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import position_sizing
from position_sizing import calculate_entry_size, STRATEGY_SIZE_CAPS


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _default_kwargs(**overrides) -> dict:
    """기준 입력값 — 필요한 항목만 override 해서 사용."""
    base = dict(
        ai_score=75.0,
        rule_score=70.0,
        confidence="HIGH",
        candidate_quality="B",
        quality_score=70.0,
        chase_risk_score=30.0,
        execution_quality="B",
        rr_ratio=2.0,
        rr_quality_bucket="GOOD",
        stop_pct=2.0,
        atr_pct=1.5,
        trde_amt=5_000_000_000,
        spread_pct=0.1,
        strategy_id="S8_GOLDEN_CROSS",
        market_regime="neutral",
        strategy_count=1,
        sector_heat_score=50.0,
        freshness_status="FRESH",
    )
    base.update(overrides)
    return base


# ── Test 1: 낮은 ai_score → SIZE_0 ───────────────────────────────────────────

class TestSize0ForLowAiScore:
    def test_size_0_for_low_ai_score(self):
        """ai_score=30, rule_score=30, poor 조건 → SIZE_0"""
        result = calculate_entry_size(
            ai_score=30.0,
            rule_score=30.0,
            confidence="LOW",
            candidate_quality="REJECT",
            quality_score=20.0,
            chase_risk_score=80.0,
            execution_quality="C",
            rr_ratio=0.5,
            rr_quality_bucket="POOR",
            stop_pct=8.0,
            atr_pct=2.0,
            trde_amt=200_000_000,
            spread_pct=1.0,
            strategy_id="S1_GAP_OPEN",
            market_regime="bear",
            strategy_count=1,
            sector_heat_score=85.0,
            freshness_status="STALE",
        )
        assert result["entry_size_tier"] == "SIZE_0"
        assert result["entry_size_weight"] == 0.00
        assert result["entry_size_score"] < 55.0
        assert result["entry_size_basis"] == "model_relative_not_account"


# ── Test 2: 모든 지표 최고 → SIZE_4 ──────────────────────────────────────────

class TestSize4ForExcellentAll:
    def test_size_4_for_excellent_all(self):
        """모든 지표 최고 + 전략 상한 없음 → SIZE_4"""
        result = calculate_entry_size(
            ai_score=100.0,
            rule_score=100.0,
            confidence="HIGH",
            candidate_quality="A",
            quality_score=100.0,
            chase_risk_score=0.0,
            execution_quality="A",
            rr_ratio=5.0,
            rr_quality_bucket="EXCELLENT",
            stop_pct=0.5,
            atr_pct=1.0,
            trde_amt=50_000_000_000,
            spread_pct=0.01,
            strategy_id="S3_INST_FRGN",   # DEFAULT_CAP = SIZE_4
            market_regime="bull",
            strategy_count=3,
            sector_heat_score=0.0,
            freshness_status="FRESH",
        )
        assert result["entry_size_tier"] == "SIZE_4"
        assert result["entry_size_weight"] == 1.00
        assert result["entry_size_score"] >= 90.0


# ── Test 3: S1 상한 SIZE_3 ───────────────────────────────────────────────────

class TestStrategyCapS1MaxSize3:
    def test_strategy_cap_s1_max_size3(self):
        """S1_GAP_OPEN: 점수가 SIZE_4 에 해당해도 SIZE_3 로 상한 적용."""
        result = calculate_entry_size(
            ai_score=100.0,
            rule_score=100.0,
            confidence="HIGH",
            candidate_quality="A",
            quality_score=100.0,
            chase_risk_score=0.0,
            execution_quality="A",
            rr_ratio=5.0,
            rr_quality_bucket="EXCELLENT",
            stop_pct=0.5,
            atr_pct=1.0,
            trde_amt=50_000_000_000,
            spread_pct=0.01,
            strategy_id="S1_GAP_OPEN",
            market_regime="bull",
            strategy_count=3,
            sector_heat_score=0.0,
            freshness_status="FRESH",
        )
        assert result["entry_size_tier"] == "SIZE_3"
        assert result["entry_size_weight"] == 0.75
        assert "strategy_cap_applied" in result["size_downgrade_flags"]


# ── Test 4: S10 기본 SIZE_2 ──────────────────────────────────────────────────

class TestS10Size2DefaultCap:
    def test_s10_size2_default_cap(self):
        """S10_NEW_HIGH: 기본 상한은 SIZE_2.
        candidate_quality="B" → SIZE_3 예외 조건 미충족."""
        result = calculate_entry_size(**_default_kwargs(
            ai_score=95.0,
            rule_score=90.0,
            candidate_quality="B",       # A 가 아님
            chase_risk_score=20.0,
            strategy_id="S10_NEW_HIGH",
            market_regime="bull",
            strategy_count=3,
            sector_heat_score=0.0,
            trde_amt=50_000_000_000,
            spread_pct=0.01,
            stop_pct=0.5,
            atr_pct=0.5,
        ))
        assert result["entry_size_tier"] == "SIZE_2"
        assert result["entry_size_weight"] == 0.50
        assert "strategy_cap_applied" in result["size_downgrade_flags"]


# ── Test 5: S10 + quality A + 낮은 추격 → SIZE_3 허용 ───────────────────────

class TestS10Size3WithQualityA:
    def test_s10_size3_with_quality_a(self):
        """S10_NEW_HIGH: candidate_quality=A AND chase_risk_score<30 → SIZE_3 허용."""
        result = calculate_entry_size(**_default_kwargs(
            ai_score=95.0,
            rule_score=90.0,
            candidate_quality="A",
            chase_risk_score=20.0,       # < 30
            strategy_id="S10_NEW_HIGH",
            sector_heat_score=0.0,
            trde_amt=50_000_000_000,
            spread_pct=0.01,
            stop_pct=0.5,
        ))
        # 점수가 80 이상이면 SIZE_3 에 매핑, cap 도 SIZE_3 허용
        assert result["entry_size_tier"] == "SIZE_3"
        assert result["entry_size_weight"] == 0.75

    def test_s13_size3_with_quality_a(self):
        """S13_BOX_BREAKOUT: 동일 조건에서 SIZE_3 허용."""
        result = calculate_entry_size(**_default_kwargs(
            ai_score=95.0,
            rule_score=90.0,
            candidate_quality="A",
            chase_risk_score=10.0,
            strategy_id="S13_BOX_BREAKOUT",
            sector_heat_score=0.0,
            trde_amt=50_000_000_000,
            spread_pct=0.01,
            stop_pct=0.5,
        ))
        assert result["entry_size_tier"] == "SIZE_3"


# ── Test 6: 높은 추격 위험 → 낮은 점수 ──────────────────────────────────────

class TestChaseRiskPenalty:
    def test_chase_risk_penalty(self):
        """chase_risk_score=90 → chase_inverse 거의 0 → 전체 점수 하락."""
        low_chase = calculate_entry_size(**_default_kwargs(chase_risk_score=10.0))
        high_chase = calculate_entry_size(**_default_kwargs(chase_risk_score=90.0))
        assert high_chase["entry_size_score"] < low_chase["entry_size_score"]
        assert "high_chase_risk" in high_chase["size_downgrade_flags"]

    def test_low_chase_no_flag(self):
        """chase_risk_score < 70 → high_chase_risk 플래그 없음."""
        result = calculate_entry_size(**_default_kwargs(chase_risk_score=69.0))
        assert "high_chase_risk" not in result["size_downgrade_flags"]


# ── Test 7: 섹터 과열 패널티 ─────────────────────────────────────────────────

class TestSectorOverheatedPenalty:
    def test_sector_overheated_penalty(self):
        """sector_heat_score=90 → 패널티 -10점."""
        normal = calculate_entry_size(**_default_kwargs(sector_heat_score=50.0))
        overheated = calculate_entry_size(**_default_kwargs(sector_heat_score=90.0))
        # 90점 → (90-70)*0.5 = -10점 패널티
        assert overheated["entry_size_score"] < normal["entry_size_score"]
        assert "sector_overheated" in overheated["size_downgrade_flags"]

    def test_sector_under_70_no_penalty(self):
        """sector_heat_score < 70 → 패널티 없음, 플래그 없음."""
        result = calculate_entry_size(**_default_kwargs(sector_heat_score=65.0))
        assert "sector_overheated" not in result["size_downgrade_flags"]

    def test_sector_penalty_formula(self):
        """sector_heat_score=80 → 패널티 = -(80-70)*0.5 = -5점."""
        base = calculate_entry_size(**_default_kwargs(sector_heat_score=50.0))
        penalized = calculate_entry_size(**_default_kwargs(sector_heat_score=80.0))
        delta = base["entry_size_score"] - penalized["entry_size_score"]
        assert abs(delta - 5.0) < 0.5    # 부동소수점 허용


# ── Test 8: 스프레드 넓으면 플래그 ───────────────────────────────────────────

class TestSpreadDowngradeFlag:
    def test_spread_too_wide_flag(self):
        """spread_pct > 0.5 → spread_too_wide 플래그."""
        result = calculate_entry_size(**_default_kwargs(spread_pct=0.8))
        assert "spread_too_wide" in result["size_downgrade_flags"]

    def test_spread_ok_no_flag(self):
        """spread_pct <= 0.5 → 플래그 없음."""
        result = calculate_entry_size(**_default_kwargs(spread_pct=0.5))
        assert "spread_too_wide" not in result["size_downgrade_flags"]

    def test_none_spread_no_flag(self):
        """spread_pct=None → 플래그 없음 (데이터 없음 허용)."""
        result = calculate_entry_size(**_default_kwargs(spread_pct=None))
        assert "spread_too_wide" not in result["size_downgrade_flags"]


# ── Test 9: 계좌 관련 파라미터 절대 금지 확인 ────────────────────────────────

class TestNoAccountFieldsUsed:
    _FORBIDDEN_PARAMS = {
        "account_balance",
        "total_assets",
        "available_amount",
        "account_risk_pct",
        "position_amount",
        "portfolio_value",
        "cash_balance",
        "buying_power",
        "margin",
    }

    def test_no_account_params_in_signature(self):
        """calculate_entry_size 시그니처에 계좌 관련 파라미터가 없어야 한다."""
        sig = inspect.signature(calculate_entry_size)
        param_names = set(sig.parameters.keys())
        forbidden_present = param_names & self._FORBIDDEN_PARAMS
        assert not forbidden_present, (
            f"계좌 관련 파라미터가 시그니처에 존재함: {forbidden_present}"
        )

    def test_entry_size_basis_is_model_relative(self):
        """entry_size_basis 는 항상 'model_relative_not_account' 를 반환한다."""
        result = calculate_entry_size(**_default_kwargs())
        assert result["entry_size_basis"] == "model_relative_not_account"


# ── Test 10: queue_worker 통합 — flag=true 시 payload에 entry_size_tier 포함 ─

def _run(coro):
    return asyncio.run(coro)


def _make_rdb(rpop_value=None):
    rdb = MagicMock()
    rdb.rpop = AsyncMock(return_value=rpop_value)
    rdb.lpush = AsyncMock(return_value=1)
    rdb.expire = AsyncMock(return_value=True)
    rdb.incr = AsyncMock(return_value=1)
    rdb.hgetall = AsyncMock(return_value={})
    rdb.hincrby = AsyncMock(return_value=1)
    rdb.lrange = AsyncMock(return_value=[])
    rdb.get = AsyncMock(return_value=None)
    return rdb


def _base_signal(**overrides):
    base = {
        "id": 999,
        "strategy": "S8_GOLDEN_CROSS",
        "stk_cd": "005930",
        "stk_nm": "Samsung",
        "gap_pct": 2.0,
        "target_pct": 3.0,
        "stop_pct": 2.0,
        "cur_prc": 70000,
        "tp1_price": 73000,
        "sl_price": 68600,
        "rr_ratio": 2.1,
    }
    base.update(overrides)
    return base


def _ctx():
    return {
        "tick": {},
        "hoga": {"total_buy_bid_req": "200", "total_sel_bid_req": "100"},
        "strength": 120.0,
        "vi": {},
        "ws_online": False,
        "freshness": {},
    }


class TestQueueWorkerIntegration:
    def test_queue_worker_integration_flag_true(self):
        """ENABLE_MODEL_RELATIVE_POSITION_SIZE=true → payload에 entry_size_tier 포함."""
        item = _base_signal()
        rdb = _make_rdb(json.dumps(item))
        captured = []

        async def capture_push(_rdb, payload):
            captured.append(payload)

        with patch.dict(os.environ, {"ENABLE_MODEL_RELATIVE_POSITION_SIZE": "true"}), \
             patch("position_sizing.ENABLE_MODEL_RELATIVE_POSITION_SIZE", True), \
             patch("queue_worker.ENABLE_MODEL_RELATIVE_POSITION_SIZE", True), \
             patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
             patch("queue_worker.rule_score", return_value=(75.0, {})), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock, return_value=True), \
             patch("queue_worker.analyze_signal", new_callable=AsyncMock, return_value={
                 "ai_score": 80.0, "action": "ENTER", "confidence": "HIGH",
                 "reason": "ok", "cancel_reason": None,
             }), \
             patch("queue_worker.push_score_only_queue", new_callable=AsyncMock, side_effect=capture_push), \
             patch("queue_worker.fetch_stk_nm", new_callable=AsyncMock, return_value="Samsung"):
            from queue_worker import process_one
            _run(process_one(rdb))

        assert len(captured) >= 1
        main_payload = captured[0]
        assert "entry_size_tier" in main_payload, (
            f"entry_size_tier 누락. payload keys: {list(main_payload.keys())}"
        )
        assert main_payload["entry_size_tier"] in ("SIZE_0", "SIZE_1", "SIZE_2", "SIZE_3", "SIZE_4")
        assert "entry_size_basis" in main_payload
        assert main_payload["entry_size_basis"] == "model_relative_not_account"

    # ── Test 11: flag=false 시 payload에 entry_size_tier 없음 ─────────────────

    def test_queue_worker_disabled_flag_false(self):
        """ENABLE_MODEL_RELATIVE_POSITION_SIZE=false → payload에 entry_size_tier 없음."""
        item = _base_signal()
        rdb = _make_rdb(json.dumps(item))
        captured = []

        async def capture_push(_rdb, payload):
            captured.append(payload)

        with patch.dict(os.environ, {"ENABLE_MODEL_RELATIVE_POSITION_SIZE": "false"}), \
             patch("position_sizing.ENABLE_MODEL_RELATIVE_POSITION_SIZE", False), \
             patch("queue_worker.ENABLE_MODEL_RELATIVE_POSITION_SIZE", False), \
             patch("queue_worker._build_market_ctx", new_callable=AsyncMock, return_value=_ctx()), \
             patch("queue_worker.rule_score", return_value=(75.0, {})), \
             patch("queue_worker.should_skip_ai", return_value=False), \
             patch("queue_worker.check_daily_limit", new_callable=AsyncMock, return_value=True), \
             patch("queue_worker.analyze_signal", new_callable=AsyncMock, return_value={
                 "ai_score": 80.0, "action": "ENTER", "confidence": "HIGH",
                 "reason": "ok", "cancel_reason": None,
             }), \
             patch("queue_worker.push_score_only_queue", new_callable=AsyncMock, side_effect=capture_push), \
             patch("queue_worker.fetch_stk_nm", new_callable=AsyncMock, return_value="Samsung"):
            from queue_worker import process_one
            _run(process_one(rdb))

        assert len(captured) >= 1
        main_payload = captured[0]
        assert "entry_size_tier" not in main_payload, (
            "flag=false 인데 entry_size_tier 가 payload에 포함됨"
        )


# ── 추가: execution_quality=REJECT → 즉시 SIZE_0 ─────────────────────────────

class TestExecutionQualityReject:
    def test_execution_quality_reject_returns_size_0(self):
        """execution_quality=REJECT → 점수 0, SIZE_0."""
        result = calculate_entry_size(**_default_kwargs(execution_quality="REJECT"))
        assert result["entry_size_tier"] == "SIZE_0"
        assert result["entry_size_score"] == 0.0
        assert result["entry_size_weight"] == 0.00
        assert "execution_quality_reject" in result["size_downgrade_flags"]


# ── 추가: STALE 데이터 플래그 및 패널티 ──────────────────────────────────────

class TestStaleDataFlag:
    def test_stale_data_flag_present(self):
        """freshness_status=STALE → stale_data 플래그 존재."""
        result = calculate_entry_size(**_default_kwargs(freshness_status="STALE"))
        assert "stale_data" in result["size_downgrade_flags"]

    def test_stale_reduces_score(self):
        """STALE 은 FRESH 대비 점수가 낮아야 한다."""
        fresh = calculate_entry_size(**_default_kwargs(freshness_status="FRESH"))
        stale = calculate_entry_size(**_default_kwargs(freshness_status="STALE"))
        assert stale["entry_size_score"] < fresh["entry_size_score"]


# ── 추가: low_liquidity 플래그 ───────────────────────────────────────────────

class TestLowLiquidityFlag:
    def test_low_liquidity_flag(self):
        """trde_amt < 10억 → low_liquidity 플래그."""
        result = calculate_entry_size(**_default_kwargs(trde_amt=500_000_000))
        assert "low_liquidity" in result["size_downgrade_flags"]

    def test_no_low_liquidity_flag_when_none(self):
        """trde_amt=None → low_liquidity 플래그 없음."""
        result = calculate_entry_size(**_default_kwargs(trde_amt=None))
        assert "low_liquidity" not in result["size_downgrade_flags"]

    def test_sufficient_liquidity_no_flag(self):
        """trde_amt >= 10억 → low_liquidity 플래그 없음."""
        result = calculate_entry_size(**_default_kwargs(trde_amt=2_000_000_000))
        assert "low_liquidity" not in result["size_downgrade_flags"]


# ── 추가: 출력 스키마 완전성 검증 ────────────────────────────────────────────

class TestOutputSchema:
    _REQUIRED_KEYS = {
        "entry_size_score",
        "entry_size_tier",
        "entry_size_weight",
        "entry_size_basis",
        "size_downgrade_flags",
    }

    def test_all_required_keys_present(self):
        result = calculate_entry_size(**_default_kwargs())
        missing = self._REQUIRED_KEYS - set(result.keys())
        assert not missing, f"출력 스키마 누락 키: {missing}"

    def test_entry_size_score_range(self):
        result = calculate_entry_size(**_default_kwargs())
        assert 0.0 <= result["entry_size_score"] <= 100.0

    def test_tier_is_valid_value(self):
        result = calculate_entry_size(**_default_kwargs())
        assert result["entry_size_tier"] in {"SIZE_0", "SIZE_1", "SIZE_2", "SIZE_3", "SIZE_4"}

    def test_weight_matches_tier(self):
        """entry_size_weight 는 tier 에 대응하는 고정값이어야 한다."""
        tier_weight_map = {
            "SIZE_0": 0.00,
            "SIZE_1": 0.25,
            "SIZE_2": 0.50,
            "SIZE_3": 0.75,
            "SIZE_4": 1.00,
        }
        result = calculate_entry_size(**_default_kwargs())
        expected_weight = tier_weight_map[result["entry_size_tier"]]
        assert result["entry_size_weight"] == expected_weight

    def test_size_downgrade_flags_is_list(self):
        result = calculate_entry_size(**_default_kwargs())
        assert isinstance(result["size_downgrade_flags"], list)
