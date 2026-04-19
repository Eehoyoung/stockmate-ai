from __future__ import annotations
"""
vi_watch_worker.py
──────────────────────────────────────────────────────────────
StockMate AI – VI 눌림목 감시 워커 (S2)

vi_watch_queue (RPOP) 폴링 → S2 눌림목 조건 체크 → telegram_queue 발행.
Java api-orchestrator ViWatchService.processViWatchQueue() 의 Python 이식본.

흐름:
  redis_writer.write_vi() (websocket-listener)
    → vi_watch_queue (LPUSH, VI 해제 시)
      → run_vi_watch_worker()  ← 여기
        → check_vi_pullback()  (strategy_2_vi_pullback.py)
          → 조건 충족 시 telegram_queue (LPUSH)
          → 조건 미충족 시 vi_watch_queue 재삽입 (watch_until 내)

활성화:
  ENABLE_VI_WATCH_WORKER=true (기본 true)
  KIWOOM_API_INTERVAL      : 체결강도 API 호출 간격 (기본 0.25s)
"""

import asyncio
import json
import logging
import os
import time

from strategy_2_vi_pullback import check_vi_pullback

logger = logging.getLogger(__name__)

REDIS_TOKEN_KEY  = "kiwoom:token"
POLL_INTERVAL    = 5.0    # 초: vi_watch_queue 폴링 주기 (Java: 5초)
MAX_BATCH        = 20     # 회당 최대 처리 건수 (Java: 20)
QUEUE_TTL        = 43200  # 12시간
_SUPPLEMENT_INTERVAL = 30.0  # 초: 풀 보완 실행 주기


async def _supplement_from_pool(rdb) -> int:
    """vi_watch_queue 공백 시 candidates:s2:* 풀에서 미처리 VI 종목 보완.

    websocket-listener 가 ws 이벤트로 vi:{stk_cd} 해시를 설정했으나
    vi_watch_queue 에 삽입되지 못한 경우 candidates:s2:* 풀과 교차하여 보완한다.
    vi:{stk_cd} 해시가 없는 종목(WebSocket 이벤트 미수신)은 처리 불가 → skip.
    """
    now_ms = int(time.time() * 1000)
    watch_until = now_ms + 600_000  # 10분 감시 (handle_vi_event 와 동일)
    count = 0

    for market in ("001", "101"):
        try:
            pool = await rdb.lrange(f"candidates:s2:{market}", 0, -1)
        except Exception as e:
            logger.debug("[VI Watch] candidates:s2:%s 조회 실패: %s", market, e)
            continue

        for stk_cd in pool:
            # 이미 신호 발행된 종목 skip
            dedup_key = f"scanner:dedup:S2_VI_PULLBACK:{stk_cd}"
            if await rdb.exists(dedup_key):
                continue

            # WebSocket 이 설정한 vi:{stk_cd} 해시 확인
            vi_data = await rdb.hgetall(f"vi:{stk_cd}")
            if not vi_data or not vi_data.get("vi_price"):
                continue  # VI 이벤트 데이터 없으면 처리 불가

            # vi_watch_queue 에 보완 삽입
            item = {
                "stk_cd": stk_cd,
                "vi_price": float(vi_data.get("vi_price", 0)),
                "watch_until": watch_until,
                "is_dynamic": vi_data.get("vi_type") in ("2", "3"),
            }
            await rdb.lpush("vi_watch_queue", json.dumps(item, ensure_ascii=False))
            await rdb.expire("vi_watch_queue", QUEUE_TTL)
            count += 1

    return count


async def run_vi_watch_worker(rdb):
    logger.info("[VI Watch] 워커 시작")
    _last_supplement = 0.0  # 풀 보완 마지막 실행 시각

    while True:
        try:
            token = await rdb.get(REDIS_TOKEN_KEY)
            if not token:
                await asyncio.sleep(1)
                continue

            # 큐에서 하나씩 꺼내어 처리
            item_raw = await rdb.rpop("vi_watch_queue")
            if not item_raw:
                # vi_watch_queue 공백 시 candidates:s2:* 풀 보완 (30초 주기)
                now_ts = time.time()
                if now_ts - _last_supplement >= _SUPPLEMENT_INTERVAL:
                    supplemented = await _supplement_from_pool(rdb)
                    _last_supplement = now_ts
                    if supplemented:
                        logger.debug("[VI Watch] 풀 보완 %d건 추가", supplemented)
                await asyncio.sleep(POLL_INTERVAL)
                continue

            item = json.loads(item_raw)
            now_ms = int(time.time() * 1000)

            # 1. 감시 시간 만료 체크
            if now_ms > item.get("watch_until", 0):
                continue

            # 2. 조건 체크
            signal = await check_vi_pullback(token, item, rdb)

            if signal:
                # 신호 발생 시 처리 (중복 방지 로직 포함)
                dedup_key = f"scanner:dedup:S2_VI_PULLBACK:{item['stk_cd']}"
                if await rdb.set(dedup_key, "1", nx=True, ex=3600):
                    await rdb.lpush("telegram_queue", json.dumps(signal, ensure_ascii=False))
                    logger.info("🔥 S2 신호 포착: %s", item['stk_cd'])
            else:
                # 3. 조건 미충족 시 다시 큐에 삽입 (단, 약간의 지연 후 재진입 위해 LPUSH 사용 권장)
                # 너무 자주 체크하지 않도록 sleep을 주거나 처리 순서를 뒤로 보냄
                await rdb.lpush("vi_watch_queue", item_raw)
                await asyncio.sleep(0.1) # 과도한 루프 방지

        except Exception as e:
            logger.error("[VI Watch] 에러: %s", e)
            await asyncio.sleep(1)
