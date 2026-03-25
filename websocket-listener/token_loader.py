"""
Redis 에 Java api-orchestrator 가 저장한 액세스 토큰을 읽어온다.
토큰이 없으면 5초 간격으로 최대 12회 재시도 (1분 대기).
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

REDIS_TOKEN_KEY = "kiwoom:token"  # Java TokenService.REDIS_TOKEN_KEY 와 동일한 키
MAX_RETRIES     = 12
RETRY_INTERVAL  = 5  # seconds


async def load_token(rdb) -> str:
    """Redis 에서 액세스 토큰 반환. 없으면 재시도 후 예외."""
    for attempt in range(1, MAX_RETRIES + 1):
        token = await rdb.get(REDIS_TOKEN_KEY)
        if token:
            logger.info("[Token] Redis 토큰 로드 성공 (시도 %d회)", attempt)
            return token

        logger.warning(
            "[Token] Redis 에 토큰 없음 – Java 서버 기동 대기 (%d/%d)",
            attempt, MAX_RETRIES
        )
        await asyncio.sleep(RETRY_INTERVAL)

    raise RuntimeError(
        f"Redis 키 '{REDIS_TOKEN_KEY}' 없음 – "
        "Java api-orchestrator 를 먼저 기동하고 토큰을 발급하세요."
    )
