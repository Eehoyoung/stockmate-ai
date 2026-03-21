"""
redis_reader.py
Redis 에서 신호 데이터와 실시간 시세 보조 데이터를 읽는 모듈.
"""

import asyncio
import json
import logging
import os
from typing import Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────
# Redis 재연결 관리자 (지수 백오프)
# ──────────────────────────────────────────────────────────────────

class RedisConnectionManager:
    """
    Redis 연결 오류 시 지수 백오프(1→2→4→8→16→최대 60초)로 재연결을 시도.
    engine.py 의 단순 Redis 객체를 래핑하여 사용 가능.

    사용 예:
        manager = RedisConnectionManager(host="localhost", port=6379)
        rdb = await manager.connect()
    """

    _BACKOFF_BASE = 1       # 초기 대기 시간 (초)
    _BACKOFF_MAX  = 60      # 최대 대기 시간 (초)

    def __init__(self, host: str = "localhost", port: int = 6379,
                 password: Optional[str] = None):
        self.host     = host
        self.port     = port
        self.password = password
        self._client: Optional[aioredis.Redis] = None

    def _make_client(self) -> aioredis.Redis:
        return aioredis.Redis(
            host=self.host,
            port=self.port,
            password=self.password,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )

    async def connect(self) -> aioredis.Redis:
        """초기 연결 – 성공 시 클라이언트 반환"""
        self._client = self._make_client()
        await self._client.ping()
        logger.info("[Redis] 연결 성공 → %s:%d", self.host, self.port)
        return self._client

    async def reconnect(self) -> aioredis.Redis:
        """
        지수 백오프로 재연결 시도.
        성공할 때까지 반복 (1s → 2s → 4s → 8s → 16s → 60s 고정).
        """
        wait = self._BACKOFF_BASE
        attempt = 0
        while True:
            attempt += 1
            logger.warning(
                "[Redis] 재연결 시도 #%d (%.0f초 대기 후) → %s:%d",
                attempt, wait, self.host, self.port,
            )
            await asyncio.sleep(wait)
            try:
                if self._client:
                    try:
                        await self._client.aclose()
                    except Exception:
                        pass
                self._client = self._make_client()
                await self._client.ping()
                logger.info("[Redis] 재연결 성공 (시도 #%d) → %s:%d",
                            attempt, self.host, self.port)
                return self._client
            except Exception as e:
                logger.error("[Redis] 재연결 실패 #%d: %s", attempt, e)
                wait = min(wait * 2, self._BACKOFF_MAX)

    async def get_or_reconnect(self) -> aioredis.Redis:
        """
        현재 클라이언트가 살아있으면 반환, 오류 시 재연결 후 반환.
        """
        if self._client is None:
            return await self.connect()
        try:
            await self._client.ping()
            return self._client
        except Exception as e:
            logger.warning("[Redis] 연결 끊김 감지: %s – 재연결 시작", e)
            return await self.reconnect()

    async def close(self):
        """연결 종료"""
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("[Redis] 연결 종료")


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


async def get_expected_data(rdb, stk_cd: str) -> dict:
    """ws:expected:{stk_cd} Hash 데이터 반환"""
    data = await rdb.hgetall(f"ws:expected:{stk_cd}")
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
