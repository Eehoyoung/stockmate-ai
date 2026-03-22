"""
tests/conftest.py
pytest 공유 픽스처 모음.
모든 테스트 파일에서 자동으로 사용 가능.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import pytest
from unittest.mock import AsyncMock, MagicMock


# ──────────────────────────────────────────────────────────────────
# 기본 신호(signal) 픽스처들
# ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_s1_signal():
    """S1 갭상승 신호 – 규칙 스코어가 높게 나오도록 설정"""
    return {
        "strategy": "S1_GAP_OPEN",
        "stk_cd": "005930",
        "stk_nm": "삼성전자",
        "gap_pct": 4.0,
        "cntr_strength": 155.0,
        "entry_type": "시초가_시장가",
        "target_pct": 4.0,
        "stop_pct": -2.0,
        "signal_time": "2026-03-21T09:00:05",
        "cur_prc": 84300,
    }


@pytest.fixture
def sample_s2_signal():
    """S2 VI 눌림목 신호"""
    return {
        "strategy": "S2_VI_PULLBACK",
        "stk_cd": "000660",
        "stk_nm": "SK하이닉스",
        "pullback_pct": -1.5,
        "is_dynamic": True,
        "cntr_strength": 125.0,
        "bid_ratio": 1.6,
        "vi_price": 130000,
        "cur_price": 127950,
        "entry_type": "지정가_눌림목",
        "target_pct": 3.0,
        "stop_pct": -2.0,
        "signal_time": "2026-03-21T10:30:00",
        "cur_prc": 127950,
    }


@pytest.fixture
def sample_s3_signal():
    """S3 기관/외인 순매수 신호"""
    return {
        "strategy": "S3_INST_FRGN",
        "stk_cd": "005380",
        "stk_nm": "현대차",
        "net_buy_amt": 50_000_000_000,
        "continuous_days": 5,
        "vol_ratio": 3.2,
        "entry_type": "지정가_1호가",
        "target_pct": 3.5,
        "stop_pct": -2.0,
        "signal_time": "2026-03-21T11:00:00",
        "cur_prc": 250000,
    }


@pytest.fixture
def sample_s4_signal():
    """S4 장대양봉 신호"""
    return {
        "strategy": "S4_BIG_CANDLE",
        "stk_cd": "035720",
        "stk_nm": "카카오",
        "gain_pct": 4.5,
        "body_ratio": 0.85,
        "vol_ratio": 8.2,
        "cntr_strength": 155.0,
        "is_new_high": True,
        "entry_type": "추격_시장가",
        "target_pct": 4.0,
        "stop_pct": -2.5,
        "signal_time": "2026-03-21T11:30:00",
        "cur_prc": 55000,
    }


@pytest.fixture
def sample_s5_signal():
    """S5 프로그램매수 신호"""
    return {
        "strategy": "S5_PROG_FRGN",
        "stk_cd": "000270",
        "stk_nm": "기아",
        "net_buy_amt": 80_000_000_000,
        "entry_type": "지정가_1호가",
        "target_pct": 3.0,
        "stop_pct": -2.0,
        "signal_time": "2026-03-21T12:00:00",
        "cur_prc": 105000,
    }


@pytest.fixture
def sample_s6_signal():
    """S6 테마 후발주 신호"""
    return {
        "strategy": "S6_THEME_LAGGARD",
        "stk_cd": "003490",
        "stk_nm": "대한항공",
        "theme_name": "AI반도체",
        "theme_flu_rt": 4.5,
        "stk_flu_rt": 2.1,
        "gap_pct": 2.1,
        "cntr_strength": 135.0,
        "entry_type": "지정가_1호가",
        "target_pct": 2.7,
        "stop_pct": -2.0,
        "signal_time": "2026-03-21T10:00:00",
        "cur_prc": 28000,
    }


@pytest.fixture
def sample_s7_signal():
    """S7 동시호가 신호"""
    return {
        "strategy": "S7_AUCTION",
        "stk_cd": "028260",
        "stk_nm": "삼성물산",
        "gap_pct": 3.5,
        "bid_ratio": 2.8,
        "vol_rank": 8,
        "entry_type": "시초가_시장가",
        "target_pct": 2.8,
        "stop_pct": -2.0,
        "signal_time": "2026-03-21T08:55:00",
        "cur_prc": 180000,
    }


# ──────────────────────────────────────────────────────────────────
# 시장 컨텍스트 픽스처
# ──────────────────────────────────────────────────────────────────

@pytest.fixture
def default_market_ctx():
    """기본 시장 컨텍스트"""
    return {
        "tick": {"flu_rt": "3.0", "cur_prc": "84300"},
        "hoga": {
            "total_buy_bid_req": "2000",
            "total_sel_bid_req": "1000",
        },
        "strength": 130.0,
        "vi": {},
    }


@pytest.fixture
def strong_market_ctx():
    """강한 매수 시장 컨텍스트 – 높은 스코어 유도"""
    return {
        "tick": {"flu_rt": "4.0", "cur_prc": "84300"},
        "hoga": {
            "total_buy_bid_req": "4000",
            "total_sel_bid_req": "1000",
        },
        "strength": 160.0,
        "vi": {},
    }


@pytest.fixture
def weak_market_ctx():
    """약한 시장 컨텍스트 – 낮은 스코어 유도"""
    return {
        "tick": {"flu_rt": "1.0", "cur_prc": "84300"},
        "hoga": {
            "total_buy_bid_req": "800",
            "total_sel_bid_req": "1000",
        },
        "strength": 90.0,
        "vi": {},
    }


# ──────────────────────────────────────────────────────────────────
# 높은/낮은 점수 신호 픽스처
# ──────────────────────────────────────────────────────────────────

@pytest.fixture
def high_score_signal():
    """높은 스코어 신호 (S1 기준, ≥ 70점 유도)"""
    return {
        "strategy": "S1_GAP_OPEN",
        "stk_cd": "005930",
        "stk_nm": "삼성전자",
        "gap_pct": 4.0,         # 최적 갭 구간 (+20점)
        "cntr_strength": 160.0, # 매우 강한 체결강도 (+10점)
        "entry_type": "시초가_시장가",
        "target_pct": 4.0,
        "stop_pct": -2.0,
    }


@pytest.fixture
def low_score_signal():
    """낮은 스코어 신호 (S1 기준, < 70점)"""
    return {
        "strategy": "S1_GAP_OPEN",
        "stk_cd": "005930",
        "stk_nm": "삼성전자",
        "gap_pct": 0.5,    # 갭 없음 → 0점
        "entry_type": "시초가_시장가",
        "target_pct": 4.0,
        "stop_pct": -2.0,
    }


# ──────────────────────────────────────────────────────────────────
# Redis 모킹 픽스처
# ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_redis():
    """비동기 Redis 클라이언트 모킹"""
    rdb = MagicMock()
    rdb.rpop = AsyncMock(return_value=None)
    rdb.lpush = AsyncMock(return_value=1)
    rdb.expire = AsyncMock(return_value=True)
    rdb.hgetall = AsyncMock(return_value={})
    rdb.lrange = AsyncMock(return_value=[])
    rdb.incr = AsyncMock(return_value=1)
    rdb.incrby = AsyncMock(return_value=100)
    rdb.get = AsyncMock(return_value=None)
    rdb.set = AsyncMock(return_value=True)
    rdb.ping = AsyncMock(return_value=True)
    rdb.aclose = AsyncMock(return_value=None)
    return rdb


@pytest.fixture
def mock_redis_with_signal(sample_s1_signal):
    """S1 신호가 들어있는 Redis 모킹"""
    rdb = MagicMock()
    rdb.rpop = AsyncMock(return_value=json.dumps(sample_s1_signal, ensure_ascii=False))
    rdb.lpush = AsyncMock(return_value=1)
    rdb.expire = AsyncMock(return_value=True)
    rdb.hgetall = AsyncMock(return_value={})
    rdb.lrange = AsyncMock(return_value=["120.0", "130.0"])
    rdb.incr = AsyncMock(return_value=1)
    rdb.incrby = AsyncMock(return_value=100)
    rdb.ping = AsyncMock(return_value=True)
    return rdb


# ──────────────────────────────────────────────────────────────────
# Claude API 모킹 픽스처
# ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_anthropic_client():
    """Anthropic 클라이언트 모킹"""
    client = MagicMock()

    def _make_response(action="ENTER", ai_score=78, confidence="HIGH",
                       reason="강한 매수 신호", target=3.5, stop=-2.0):
        content = MagicMock()
        content.text = json.dumps({
            "action": action,
            "ai_score": ai_score,
            "confidence": confidence,
            "reason": reason,
            "adjusted_target_pct": target,
            "adjusted_stop_pct": stop,
        })
        response = MagicMock()
        response.content = [content]
        response.usage = MagicMock()
        response.usage.input_tokens = 300
        response.usage.output_tokens = 100
        return response

    client.messages.create = AsyncMock(return_value=_make_response())
    client._make_response = _make_response
    return client


# ──────────────────────────────────────────────────────────────────
# 특수 메시지 픽스처
# ──────────────────────────────────────────────────────────────────

@pytest.fixture
def force_close_item():
    """FORCE_CLOSE 특수 메시지"""
    return {
        "type": "FORCE_CLOSE",
        "stk_cd": "005930",
        "stk_nm": "삼성전자",
        "strategy": "S1_GAP_OPEN",
        "reason": "장마감 30분 전 강제청산",
    }


@pytest.fixture
def daily_report_item():
    """DAILY_REPORT 특수 메시지"""
    return {
        "type": "DAILY_REPORT",
        "date": "20260321",
        "total_signals": 15,
        "avg_score": 74.3,
        "by_strategy": {
            "S1_GAP_OPEN": 5,
            "S2_VI_PULLBACK": 3,
            "S4_BIG_CANDLE": 4,
            "S7_AUCTION": 3,
        },
    }
