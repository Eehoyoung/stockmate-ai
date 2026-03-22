"""
monitor_worker.py
Feature 5 – 데이터 품질 모니터링 비동기 태스크.

60초마다 Redis 상태를 확인하여 이상 징후 발견 시 ai_scored_queue 에 SYSTEM_ALERT 발행.
  - telegram_queue 적체 (> QUEUE_DEPTH_WARN)
  - error_queue 누적 (> ERROR_QUEUE_WARN)
  - Redis 메모리 사용률 (> MEMORY_WARN_PCT)
"""

import asyncio
import json
import logging
import os
from datetime import datetime

logger = logging.getLogger("monitor_worker")

MONITOR_INTERVAL_SEC = int(os.getenv("MONITOR_INTERVAL_SEC", "60"))
QUEUE_DEPTH_WARN     = int(os.getenv("MONITOR_QUEUE_DEPTH_WARN", "50"))
ERROR_QUEUE_WARN     = int(os.getenv("MONITOR_ERROR_QUEUE_WARN", "5"))
MEMORY_WARN_PCT      = float(os.getenv("MONITOR_MEMORY_WARN_PCT", "80.0"))


async def run_monitor(rdb):
    """메인 모니터링 루프 – engine.py에서 asyncio.create_task(run_monitor(rdb)) 로 등록"""
    logger.info("[Monitor] 데이터 품질 모니터링 시작 (interval=%ds)", MONITOR_INTERVAL_SEC)

    while True:
        try:
            await asyncio.sleep(MONITOR_INTERVAL_SEC)
            await _check_once(rdb)
        except asyncio.CancelledError:
            logger.info("[Monitor] 모니터링 태스크 종료")
            break
        except Exception as e:
            logger.error("[Monitor] 모니터링 루프 오류: %s", e)
            await asyncio.sleep(10)


async def _check_once(rdb):
    alerts = []

    # 1. telegram_queue 적체 체크
    try:
        q_depth = await rdb.llen("telegram_queue")
        if q_depth > QUEUE_DEPTH_WARN:
            alerts.append(f"⚠️ telegram_queue 적체: {q_depth}건")
            logger.warning("[Monitor] telegram_queue 적체 %d건", q_depth)
    except Exception as e:
        logger.debug("[Monitor] 큐 깊이 체크 오류: %s", e)

    # 2. error_queue 누적 체크
    try:
        err_count = await rdb.llen("error_queue")
        if err_count > ERROR_QUEUE_WARN:
            alerts.append(f"🔴 AI 엔진 에러 큐: {err_count}건 누적")
            logger.warning("[Monitor] error_queue 누적 %d건", err_count)
    except Exception as e:
        logger.debug("[Monitor] error_queue 체크 오류: %s", e)

    # 3. Redis 메모리 사용률 체크
    try:
        info = await rdb.info("memory")
        used = info.get("used_memory", 0)
        max_mem = info.get("maxmemory", 0)
        if max_mem and max_mem > 0:
            usage_pct = used / max_mem * 100.0
            if usage_pct > MEMORY_WARN_PCT:
                alerts.append(f"🔴 Redis 메모리 {usage_pct:.0f}% 사용 중")
                logger.warning("[Monitor] Redis 메모리 %.1f%%", usage_pct)
    except Exception as e:
        logger.debug("[Monitor] Redis 메모리 체크 오류: %s", e)

    # 4. 알림 발행
    if alerts:
        await _publish_system_alert(rdb, alerts)


async def _publish_system_alert(rdb, alert_messages: list):
    try:
        joined = "\n".join(alert_messages)
        payload = json.dumps({
            "type":    "SYSTEM_ALERT",
            "alerts":  alert_messages,
            "message": f"🔧 <b>[시스템 경고]</b>\n{joined}",
            "timestamp": datetime.now().isoformat(),
        }, ensure_ascii=False)
        await rdb.lpush("ai_scored_queue", payload)
        await rdb.expire("ai_scored_queue", 43200)
        logger.info("[Monitor] SYSTEM_ALERT 발행: %d건 경고", len(alert_messages))
    except Exception as e:
        logger.error("[Monitor] SYSTEM_ALERT 발행 실패: %s", e)
