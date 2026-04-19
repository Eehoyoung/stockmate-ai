from __future__ import annotations
"""
ai-engine/confirm_gate_redis.py
──────────────────────────────────────────────────────────────
Human Confirm Gate – Redis 헬퍼 함수 모음

ENABLE_CONFIRM_GATE=true 일 때만 사용되는 함수들을 redis_reader.py 에서
분리하여 관심사를 명확히 한다. confirm_worker.py 와 signals.js(Node) 사이의
Redis 키 계약도 이 파일에서 단일 관리한다.

큐 흐름:
  queue_worker → push_human_confirm_queue → human_confirm_queue
  telegram-bot (signals.js) 가 human_confirm_queue 를 표시, 사용자 응답 시
  → confirmed_queue 에 LPUSH
  confirm_worker → pop_confirmed_queue → Claude 2차 분석
"""

import json
import logging

logger = logging.getLogger(__name__)

HUMAN_CONFIRM_QUEUE = "human_confirm_queue"
CONFIRMED_QUEUE     = "confirmed_queue"
CONFIRM_PENDING_PFX = "confirm_pending:"
CONFIRM_TIMEOUT_SEC = 1800  # 30분


async def push_human_confirm_queue(rdb, item: dict) -> None:
    """규칙 점수 통과 신호를 인간 컨펌 대기 큐에 등록"""
    payload = json.dumps(item, ensure_ascii=False, default=str)
    await rdb.lpush(HUMAN_CONFIRM_QUEUE, payload)
    _id = item.get("id")
    if _id:
        sig_id = str(_id)
    else:
        sig_id = f"{item.get('stk_cd', 'unk')}:{item.get('strategy', 'unk')}"
    await rdb.setex(f"{CONFIRM_PENDING_PFX}{sig_id}", CONFIRM_TIMEOUT_SEC, payload)
    logger.debug("[ConfirmGate] human_confirm_queue push [%s]", sig_id)


async def pop_confirmed_queue(rdb) -> dict | None:
    """인간 컨펌 완료 큐에서 항목 꺼내기 (confirm_worker 가 RPOP)"""
    raw = await rdb.rpop(CONFIRMED_QUEUE)
    if not raw:
        return None
    return json.loads(raw)


async def push_confirmed_queue(rdb, payload_str: str) -> None:
    """인간 컨펌 완료 신호를 Claude 처리 큐에 등록 (telegram-bot 에서 호출)"""
    await rdb.lpush(CONFIRMED_QUEUE, payload_str)
    logger.debug("[ConfirmGate] confirmed_queue push")
