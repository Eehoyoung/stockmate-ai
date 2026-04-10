"""
db_reader.py
Python ai-engine → PostgreSQL 읽기 모듈 (asyncpg 기반).

전략 스캐너 및 스코어러가 DB 캐시를 먼저 조회하여 API 호출을 최소화한다.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 1. daily_indicators — 기술지표 캐시 조회
# ──────────────────────────────────────────────────────────────────────────────

async def get_daily_indicators(
    pool,
    stk_cd: str,
    target_date: Optional[date] = None,
) -> Optional[dict]:
    """
    daily_indicators 에서 해당 종목·날짜의 기술지표를 조회.
    target_date 미지정 시 오늘 날짜 기준.
    당일 데이터 없으면 None 반환 (호출 측에서 API 재호출 후 UPSERT 해야 함).
    """
    if target_date is None:
        target_date = date.today()
    try:
        row = await pool.fetchrow(
            "SELECT * FROM daily_indicators WHERE stk_cd = $1 AND date = $2",
            stk_cd, target_date,
        )
        return dict(row) if row else None
    except Exception as e:
        logger.error("[DBReader] get_daily_indicators 오류 %s: %s", stk_cd, e)
        return None


async def get_daily_indicators_range(
    pool,
    stk_cd: str,
    days: int = 20,
) -> list[dict]:
    """
    최근 N일치 기술지표 목록 반환 (최신순).
    MA 계산, 스윙포인트 탐색 등에 활용.
    """
    try:
        rows = await pool.fetch(
            """
            SELECT * FROM daily_indicators
            WHERE stk_cd = $1 AND date >= $2
            ORDER BY date DESC
            LIMIT $3
            """,
            stk_cd,
            date.today() - timedelta(days=days + 5),
            days,
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("[DBReader] get_daily_indicators_range 오류 %s: %s", stk_cd, e)
        return []


# ──────────────────────────────────────────────────────────────────────────────
# 2. open_positions — 포지션 상태 조회
# ──────────────────────────────────────────────────────────────────────────────

async def get_active_position(pool, stk_cd: str) -> Optional[dict]:
    """
    특정 종목의 활성 포지션 조회 (이중매수 방지 확인용).
    ACTIVE / PARTIAL_TP / OVERNIGHT 상태만 반환.
    """
    try:
        row = await pool.fetchrow(
            """
            SELECT * FROM open_positions
            WHERE stk_cd = $1 AND status IN ('ACTIVE', 'PARTIAL_TP', 'OVERNIGHT')
            LIMIT 1
            """,
            stk_cd,
        )
        return dict(row) if row else None
    except Exception as e:
        logger.error("[DBReader] get_active_position 오류 %s: %s", stk_cd, e)
        return None


async def count_active_positions(pool) -> int:
    """현재 활성 포지션 수 (최대 포지션 수 제한 체크용)."""
    try:
        return await pool.fetchval(
            "SELECT COUNT(*) FROM open_positions WHERE status IN ('ACTIVE', 'PARTIAL_TP', 'OVERNIGHT')"
        ) or 0
    except Exception as e:
        logger.error("[DBReader] count_active_positions 오류: %s", e)
        return 0


# ──────────────────────────────────────────────────────────────────────────────
# 3. portfolio_config — 설정 조회
# ──────────────────────────────────────────────────────────────────────────────

async def get_portfolio_state(pool) -> dict:
    """
    portfolio_config 싱글턴 행 조회.
    DB 접근 실패 시 안전한 기본값 반환 (서비스 중단 방지).
    """
    defaults = {
        "total_capital":        10_000_000,
        "max_position_pct":     10.0,
        "max_position_count":   5,
        "max_sector_pct":       30.0,
        "daily_loss_limit_pct": 3.0,
        "max_drawdown_pct":     10.0,
        "sl_mandatory":         True,
        "min_rr_ratio":         1.0,
        "sizing_method":        "FIXED_PCT",
    }
    try:
        row = await pool.fetchrow("SELECT * FROM portfolio_config WHERE id = 1")
        if row:
            return dict(row)
        return defaults
    except Exception as e:
        logger.warning("[DBReader] get_portfolio_state 오류, 기본값 사용: %s", e)
        return defaults


# ──────────────────────────────────────────────────────────────────────────────
# 4. daily_pnl — 오늘 손익 상태 (일일 손실 한도 체크용)
# ──────────────────────────────────────────────────────────────────────────────

async def get_today_pnl(pool) -> Optional[dict]:
    """오늘 daily_pnl 행 조회. 없으면 None."""
    try:
        row = await pool.fetchrow(
            "SELECT * FROM daily_pnl WHERE date = $1",
            date.today(),
        )
        return dict(row) if row else None
    except Exception as e:
        logger.error("[DBReader] get_today_pnl 오류: %s", e)
        return None


# ──────────────────────────────────────────────────────────────────────────────
# 5. 전략 성과 조회 (임계값 자동 조정 등에 활용)
# ──────────────────────────────────────────────────────────────────────────────

async def get_strategy_win_rate(pool, strategy: str, days: int = 20) -> Optional[float]:
    """
    최근 N일 특정 전략의 승률 조회.
    청산 완료된 신호 기준: TP_HIT → 승, SL_HIT/FORCE_CLOSE → 패.
    """
    try:
        row = await pool.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE exit_type LIKE 'TP%') AS wins,
                COUNT(*) FILTER (WHERE exit_type IN ('SL_HIT', 'FORCE_CLOSE')) AS losses
            FROM trading_signals
            WHERE strategy = $1
              AND action = 'ENTER'
              AND exited_at >= NOW() - ($2 || ' days')::INTERVAL
              AND exit_type IS NOT NULL
            """,
            strategy,
            str(days),
        )
        if row:
            wins   = row["wins"]   or 0
            losses = row["losses"] or 0
            total  = wins + losses
            if total > 0:
                return round(wins / total * 100, 1)
        return None
    except Exception as e:
        logger.error("[DBReader] get_strategy_win_rate 오류 %s: %s", strategy, e)
        return None
