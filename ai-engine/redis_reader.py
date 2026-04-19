from __future__ import annotations
"""
redis_reader.py
Redis 에서 신호 데이터와 실시간 시세 보조 데이터를 읽는 모듈.
"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def pop_telegram_queue(rdb) -> Optional[dict]:
    """
    telegram_queue 에서 항목을 꺼낸다 (RPOP).
    Java SignalService 가 LPUSH 로 넣은 항목을 소비.
    """
    raw = await rdb.rpop("telegram_queue")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("[Reader] telegram_queue JSON 파싱 실패: %s / raw=%.80s", e, raw)
        return None


async def get_tick_data(rdb, stk_cd: str) -> dict:
    """ws:tick:{stk_cd} Hash 데이터 반환"""
    data = await rdb.hgetall(f"ws:tick:{stk_cd}")
    return data or {}


async def get_hoga_data(rdb, stk_cd: str) -> dict:
    """ws:hoga:{stk_cd} Hash 데이터 반환"""
    data = await rdb.hgetall(f"ws:hoga:{stk_cd}")
    return data or {}


async def get_avg_cntr_strength(rdb, stk_cd: str, count: int = 5) -> float:
    """체결강도 최근 N개 평균 반환"""
    values = await rdb.lrange(f"ws:strength:{stk_cd}", 0, count - 1)
    if not values:
        return 100.0
    nums = []
    for v in values:
        try:
            nums.append(float(v.replace(",", "").replace("+", "")))
        except ValueError:
            pass
    return round(sum(nums) / len(nums), 2) if nums else 100.0


async def get_strength_trend(rdb, stk_cd: str, count: int = 10) -> dict:
    """
    ws:strength:{stk_cd} 최근 N개 값에서 추세 정보 반환.
    Returns {
        "avg_all":   float,   # 전체 평균
        "avg_recent": float,  # 최근 3개 평균
        "avg_older":  float,  # 이전 7개 평균
        "declining":  bool,   # avg_recent < avg_older - 5 → 하락 추세
        "count":      int,    # 실제 읽은 값 수
    }
    """
    values = await rdb.lrange(f"ws:strength:{stk_cd}", 0, count - 1)
    nums: list[float] = []
    for v in values:
        try:
            nums.append(float(str(v).replace(",", "").replace("+", "")))
        except ValueError:
            pass
    if not nums:
        return {"avg_all": 100.0, "avg_recent": 100.0, "avg_older": 100.0, "declining": False, "count": 0}
    recent = nums[:3]
    older  = nums[3:] if len(nums) > 3 else nums
    avg_all    = round(sum(nums) / len(nums), 2)
    avg_recent = round(sum(recent) / len(recent), 2)
    avg_older  = round(sum(older)  / len(older),  2)
    declining  = avg_recent < avg_older - 5.0
    return {
        "avg_all":    avg_all,
        "avg_recent": avg_recent,
        "avg_older":  avg_older,
        "declining":  declining,
        "count":      len(nums),
    }


async def get_hoga_ratio(rdb, stk_cd: str) -> float:
    """
    ws:hoga:{stk_cd} 기반 매도/매수 잔량 비율 반환.
    ratio > 1.0 → 매도 우위 (하락 압력)
    데이터 없으면 1.0 반환 (중립).
    """
    data = await rdb.hgetall(f"ws:hoga:{stk_cd}")
    if not data:
        return 1.0
    try:
        sell = float(str(data.get("total_sel_bid_req", 0)).replace(",", "") or 0)
        buy  = float(str(data.get("total_buy_bid_req", 1)).replace(",", "") or 1)
        if buy <= 0:
            return 2.0
        return round(sell / buy, 3)
    except (TypeError, ValueError):
        return 1.0


async def get_vi_status(rdb, stk_cd: str) -> dict:
    """vi:{stk_cd} Hash 데이터 반환"""
    data = await rdb.hgetall(f"vi:{stk_cd}")
    return data or {}


async def push_score_only_queue(rdb, payload: dict):
    """
    스코어만 업데이트한 신호를 ai_scored_queue 에 저장
    (텔레그램 봇이 별도 폴링하는 큐)
    """
    try:
        serialized = json.dumps(payload, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error("[Reader] ai_scored_queue 직렬화 실패: %s", e)
        return
    await rdb.lpush("ai_scored_queue", serialized)
    await rdb.expire("ai_scored_queue", 43200)


# ─── Human Confirm Gate (confirm_gate_redis.py 로 이관) ───────
# 하위 호환을 위해 재수출만 유지 – 새 코드는 confirm_gate_redis 를 직접 import할 것
from confirm_gate_redis import (  # noqa: E402, F401
    HUMAN_CONFIRM_QUEUE,
    CONFIRMED_QUEUE,
    CONFIRM_PENDING_PFX,
    CONFIRM_TIMEOUT_SEC,
    push_human_confirm_queue,
    pop_confirmed_queue,
    push_confirmed_queue,
)
