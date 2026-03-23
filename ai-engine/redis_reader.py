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
