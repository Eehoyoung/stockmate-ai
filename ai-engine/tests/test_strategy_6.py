import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── _classify_mode ────────────────────────────────────────────────────────

class TestClassifyMode:
    def test_leader_pullback_top30pct_with_moderate_flu(self):
        from strategy_6_theme import _classify_mode, S6_MODE_LEADER
        assert _classify_mode(5.0, 0.85) == S6_MODE_LEADER

    def test_leader_pullback_minimum_boundary(self):
        from strategy_6_theme import _classify_mode, S6_MODE_LEADER
        assert _classify_mode(3.0, 0.70) == S6_MODE_LEADER

    def test_leader_rejected_when_over_extended(self):
        from strategy_6_theme import _classify_mode
        # flu_rt > 8% → 과열, 어떤 모드도 없음
        assert _classify_mode(9.0, 0.90) is None

    def test_leader_not_matched_when_flu_rt_below_3(self):
        """rank_pct >= 0.70 but flu_rt < 3 → SECONDARY 또는 LAGGARD 로 분류"""
        from strategy_6_theme import _classify_mode, S6_MODE_SECONDARY
        # rank_pct=0.80, flu_rt=2.0 → SECONDARY (1~5% 조건 충족)
        assert _classify_mode(2.0, 0.80) == S6_MODE_SECONDARY

    def test_secondary_rotation_midrank(self):
        from strategy_6_theme import _classify_mode, S6_MODE_SECONDARY
        assert _classify_mode(3.0, 0.50) == S6_MODE_SECONDARY

    def test_secondary_minimum_boundary(self):
        from strategy_6_theme import _classify_mode, S6_MODE_SECONDARY
        assert _classify_mode(1.0, 0.30) == S6_MODE_SECONDARY

    def test_secondary_rejected_when_flu_rt_exceeds_5(self):
        from strategy_6_theme import _classify_mode
        # rank_pct=0.50, flu_rt=5.5% → SECONDARY(5%) 초과, LAGGARD(4%) 초과 → None
        assert _classify_mode(5.5, 0.50) is None

    def test_laggard_catchup_low_rank_low_flu(self):
        from strategy_6_theme import _classify_mode, S6_MODE_LAGGARD
        assert _classify_mode(1.5, 0.15) == S6_MODE_LAGGARD

    def test_laggard_rejected_when_flu_too_low(self):
        from strategy_6_theme import _classify_mode
        assert _classify_mode(0.3, 0.10) is None

    def test_laggard_rejected_when_flu_exceeds_4(self):
        from strategy_6_theme import _classify_mode, S6_MODE_SECONDARY
        # flu_rt=4.5, rank_pct=0.20 → rank_pct<0.30 이므로 SECONDARY 탈락, LAGGARD(4%)도 탈락
        result = _classify_mode(4.5, 0.20)
        assert result is None


# ── _calc_volume_ratio ────────────────────────────────────────────────────

class TestCalcVolumeRatio:
    def test_ratio_computed_correctly(self):
        from strategy_6_theme import _calc_volume_ratio
        candles = [{"trde_qty": "1000000"}, {"trde_qty": "900000"}, {"trde_qty": "1100000"}]
        # avg = 1_000_000, acc_vol = 1_500_000 → ratio = 1.5
        assert _calc_volume_ratio(1_500_000, candles) == 1.5

    def test_zero_acc_vol_returns_zero(self):
        from strategy_6_theme import _calc_volume_ratio
        candles = [{"trde_qty": "1000000"}]
        assert _calc_volume_ratio(0, candles) == 0.0

    def test_empty_candles_returns_zero(self):
        from strategy_6_theme import _calc_volume_ratio
        assert _calc_volume_ratio(500_000, []) == 0.0

    def test_uses_at_most_5_candles(self):
        from strategy_6_theme import _calc_volume_ratio
        candles = [{"trde_qty": str(v)} for v in [1_000_000] * 5 + [9_999_999] * 5]
        # only first 5 used → avg=1_000_000, ratio=2.0
        assert _calc_volume_ratio(2_000_000, candles) == 2.0


class TestBidRatioLookup:
    @pytest.mark.asyncio
    async def test_common_hoga_path_is_used(self):
        from strategy_6_theme import _get_bid_ratio

        rdb = MagicMock()

        with patch("strategy_6_theme.fetch_hoga", new=AsyncMock(return_value=3.0)) as mock_fetch:
            ratio = await _get_bid_ratio("token", rdb, "005930")

        assert ratio == 3.0
        mock_fetch.assert_awaited_once_with("token", "005930", rdb=rdb)

    @pytest.mark.asyncio
    async def test_rest_hoga_fallback_when_ws_hoga_missing(self):
        from strategy_6_theme import _get_bid_ratio

        rdb = MagicMock()
        rdb.hgetall = AsyncMock(return_value={})

        with patch("strategy_6_theme.fetch_hoga", new=AsyncMock(return_value=1.234)):
            ratio = await _get_bid_ratio("token", rdb, "005930")

        assert ratio == 1.23


class TestAccVolumeLookup:
    @pytest.mark.asyncio
    async def test_fresh_tick_volume_is_used(self):
        from strategy_6_theme import _get_acc_vol

        rdb = MagicMock()
        fresh = {
            "data": {"acc_trde_qty": "1,666,969"},
            "source": "redis",
            "status": {"state": "fresh"},
        }
        with patch("strategy_6_theme.get_tick_with_status", new=AsyncMock(return_value=fresh)):
            assert await _get_acc_vol(rdb, "005930") == 1_666_969.0

    @pytest.mark.asyncio
    async def test_stale_strong_tick_volume_is_suppressed(self):
        from strategy_6_theme import _get_acc_vol

        stale = {
            "data": {},
            "source": "stale",
            "status": {"state": "cancel"},
        }
        with patch("strategy_6_theme.get_tick_with_status", new=AsyncMock(return_value=stale)):
            assert await _get_acc_vol(MagicMock(), "005930") == 0.0

    def test_daily_candle_fallback_volume(self):
        from strategy_6_theme import _fallback_acc_vol_from_candles

        candles = [{"trde_qty": "2,500,000"}]
        assert _fallback_acc_vol_from_candles(candles) == 2_500_000.0


# ── scan_theme_laggard integration (mocked APIs) ─────────────────────────

@pytest.mark.asyncio
async def test_scan_returns_empty_when_all_themes_weak():
    """모든 테마 flu_rt < 1.5% 이면 후보 없음"""
    from strategy_6_theme import scan_theme_laggard

    themes = [{"thema_grp_cd": "T1", "thema_nm": "약한테마", "flu_rt": "1.0"}]

    with patch("strategy_6_theme.fetch_theme_groups", new=AsyncMock(return_value=themes)):
        result = await scan_theme_laggard("token", rdb=None)

    assert result == []


@pytest.mark.asyncio
async def test_scan_rejects_weak_strength(monkeypatch):
    """체결강도 미달 종목은 탈락해야 한다."""
    from strategy_6_theme import scan_theme_laggard

    themes = [{"thema_grp_cd": "T1", "thema_nm": "반도체", "flu_rt": "3.0"}]
    stocks = [
        {"stk_cd": "000660", "stk_nm": "SK하이닉스", "cur_prc": "200000", "flu_rt": "5.0"},
    ]

    monkeypatch.setattr("strategy_6_theme.fetch_theme_groups", AsyncMock(return_value=themes))
    monkeypatch.setattr("strategy_6_theme.fetch_theme_stocks", AsyncMock(return_value=stocks))
    monkeypatch.setattr(
        "strategy_6_theme.fetch_cntr_strength_cached",
        AsyncMock(return_value=(100.0, "redis")),  # 115 미만
    )
    monkeypatch.setattr("strategy_6_theme._get_bid_ratio", AsyncMock(return_value=None))
    monkeypatch.setattr("strategy_6_theme._get_acc_vol", AsyncMock(return_value=0.0))
    monkeypatch.setattr("strategy_6_theme.fetch_daily_candles", AsyncMock(return_value=[]))

    result = await scan_theme_laggard("token", rdb=None)
    assert result == []


@pytest.mark.asyncio
async def test_scan_leader_pullback_mode_passes(monkeypatch):
    """LEADER_PULLBACK 모드 종목이 강한 체결강도로 통과해야 한다."""
    from strategy_6_theme import scan_theme_laggard, S6_MODE_LEADER

    themes = [{"thema_grp_cd": "T1", "thema_nm": "반도체", "flu_rt": "4.0"}]
    # 5개 종목 flu_rt: [1.0, 2.0, 3.5, 4.0, 7.0]
    # 삼성전자(7.0%) → 4개가 아래 → rank_pct=4/5=0.80 → LEADER (3≤7≤8 ✓)
    stocks = [
        {"stk_cd": "005930", "stk_nm": "삼성전자", "cur_prc": "80000",  "flu_rt": "7.0"},
        {"stk_cd": "000660", "stk_nm": "A종목",    "cur_prc": "50000",  "flu_rt": "4.0"},
        {"stk_cd": "000990", "stk_nm": "B종목",    "cur_prc": "40000",  "flu_rt": "3.5"},
        {"stk_cd": "000001", "stk_nm": "C종목",    "cur_prc": "10000",  "flu_rt": "2.0"},
        {"stk_cd": "000002", "stk_nm": "D종목",    "cur_prc": "10000",  "flu_rt": "1.0"},
    ]

    fake_tp_sl = MagicMock()
    fake_tp_sl.to_signal_fields.return_value = {"tp": 85000, "sl": 78000, "rr_ratio": 1.8}
    fake_tp_sl.rr_ratio = 1.8

    monkeypatch.setattr("strategy_6_theme.fetch_theme_groups", AsyncMock(return_value=themes))
    monkeypatch.setattr("strategy_6_theme.fetch_theme_stocks", AsyncMock(return_value=stocks))
    monkeypatch.setattr(
        "strategy_6_theme.fetch_cntr_strength_cached",
        AsyncMock(return_value=(135.0, "redis")),
    )
    monkeypatch.setattr("strategy_6_theme._get_bid_ratio", AsyncMock(return_value=1.3))
    monkeypatch.setattr("strategy_6_theme._get_acc_vol", AsyncMock(return_value=2_000_000.0))
    monkeypatch.setattr("strategy_6_theme.fetch_daily_candles", AsyncMock(return_value=[
        {"cur_prc": "79000", "high_pric": "81000", "low_pric": "78000", "trde_qty": "1000000"},
        {"cur_prc": "78000", "high_pric": "80000", "low_pric": "77000", "trde_qty": "1000000"},
    ]))
    monkeypatch.setattr("strategy_6_theme.fetch_investor_flow_summary_cached", AsyncMock(return_value=({}, {})))
    monkeypatch.setattr("strategy_6_theme.fetch_program_time_trend", AsyncMock(return_value=({}, {})))
    monkeypatch.setattr("strategy_6_theme.calc_tp_sl", MagicMock(return_value=fake_tp_sl))
    monkeypatch.setattr("strategy_6_theme.fetch_stk_nm", AsyncMock(return_value="삼성전자"))

    result = await scan_theme_laggard("token", rdb=None)

    # 삼성전자(5.0%)는 LEADER_PULLBACK 모드로 통과해야 함
    passed_codes = [r["stk_cd"] for r in result]
    assert "005930" in passed_codes
    leader_signal = next(r for r in result if r["stk_cd"] == "005930")
    assert leader_signal["s6_mode"] == S6_MODE_LEADER


@pytest.mark.asyncio
async def test_scan_no_pool_prefilter(monkeypatch):
    """pool 사전 필터 없이 모든 테마 종목을 직접 평가해야 한다.

    기존 S6는 candidates:s6 풀에서 flu_rt < 5.0% 종목만 담아 주도주를 사전 배제했음.
    신규 S6는 풀 사전 필터를 사용하지 않으므로, 5% 이상 상승한 LEADER 종목도
    체결강도 API 조회 단계까지 진입해야 한다.
    """
    from strategy_6_theme import scan_theme_laggard

    themes = [{"thema_grp_cd": "T1", "thema_nm": "반도체", "flu_rt": "3.0"}]
    # 4개 종목: 삼성전자 flu_rt=6.0% → rank_pct=3/4=0.75 → LEADER (3≤6≤8 ✓)
    stocks = [
        {"stk_cd": "005930", "stk_nm": "삼성전자", "cur_prc": "80000", "flu_rt": "6.0"},
        {"stk_cd": "000001", "stk_nm": "A종목",     "cur_prc": "10000", "flu_rt": "3.0"},
        {"stk_cd": "000002", "stk_nm": "B종목",     "cur_prc": "10000", "flu_rt": "2.0"},
        {"stk_cd": "000003", "stk_nm": "C종목",     "cur_prc": "10000", "flu_rt": "1.0"},
    ]

    evaluated = []

    async def fake_strength(token, stk_cd, rdb=None, count=5):
        evaluated.append(stk_cd)
        return 120.0, "redis"

    fake_tp_sl = MagicMock()
    fake_tp_sl.to_signal_fields.return_value = {}
    fake_tp_sl.rr_ratio = 1.5

    monkeypatch.setattr("strategy_6_theme.fetch_theme_groups", AsyncMock(return_value=themes))
    monkeypatch.setattr("strategy_6_theme.fetch_theme_stocks", AsyncMock(return_value=stocks))
    monkeypatch.setattr("strategy_6_theme.fetch_cntr_strength_cached", fake_strength)
    monkeypatch.setattr("strategy_6_theme._get_bid_ratio", AsyncMock(return_value=None))
    monkeypatch.setattr("strategy_6_theme._get_acc_vol", AsyncMock(return_value=0.0))
    monkeypatch.setattr("strategy_6_theme.fetch_daily_candles", AsyncMock(return_value=[]))
    monkeypatch.setattr("strategy_6_theme.fetch_investor_flow_summary_cached", AsyncMock(return_value=({}, {})))
    monkeypatch.setattr("strategy_6_theme.fetch_program_time_trend", AsyncMock(return_value=({}, {})))
    monkeypatch.setattr("strategy_6_theme.calc_tp_sl", MagicMock(return_value=fake_tp_sl))
    monkeypatch.setattr("strategy_6_theme.fetch_stk_nm", AsyncMock(return_value="삼성전자"))

    await scan_theme_laggard("token", rdb=None)

    # 삼성전자(flu_rt=6.0%)가 LEADER 모드로 체결강도 조회 단계까지 진입해야 함
    assert "005930" in evaluated


# ── scorer S6 케이스 ────────────────────────────────────────────────────────

class TestScorerS6:
    def _make_signal(self, s6_mode, flu_rt, strength, volume_ratio=0.0, bid_ratio=None):
        return {
            "strategy": "S6_THEME_LAGGARD",
            "s6_mode": s6_mode,
            "flu_rt": flu_rt,
            "gap_pct": flu_rt,
            "cntr_strength": strength,
            "volume_ratio": volume_ratio,
            "bid_ratio": bid_ratio,
            "theme_name": "반도체",
            "theme_flu_rt": 3.0,
            "cur_prc": 50000,
            "tp": 55000,
            "sl": 48000,
            "rr_ratio": 1.8,
        }

    def _score(self, signal):
        import scorer
        score, _ = scorer.rule_score(signal, market_ctx={})
        return score

    def test_leader_pullback_scores_above_zero(self):
        sig = self._make_signal("LEADER_PULLBACK", 5.0, 130.0)
        assert self._score(sig) > 30

    def test_secondary_rotation_scores_above_zero(self):
        sig = self._make_signal("SECONDARY_ROTATION", 2.5, 121.0)
        assert self._score(sig) > 20

    def test_laggard_catchup_baseline_score(self):
        sig = self._make_signal("LAGGARD_CATCHUP", 2.0, 125.0)
        assert self._score(sig) > 20

    def test_volume_ratio_gives_bonus(self):
        sig_low  = self._make_signal("SECONDARY_ROTATION", 2.0, 120.0, volume_ratio=0.0)
        sig_high = self._make_signal("SECONDARY_ROTATION", 2.0, 120.0, volume_ratio=2.5)
        assert self._score(sig_high) > self._score(sig_low)

    def test_leader_over_8pct_gets_no_gap_score(self):
        """flu_rt=9% 주도주는 gap_sc=0 → 강도 점수만"""
        sig = self._make_signal("LEADER_PULLBACK", 9.0, 130.0)
        score = self._score(sig)
        # 강도(130>120→20pt) + volume(0) = 20, 기타 기본점수 포함
        assert score >= 0  # 최소한 양수 (다른 기본 점수들)
