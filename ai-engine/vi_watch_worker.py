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
from datetime import time as dtime

from market_session import is_market_open_day, now_kst
from strategy_2_vi_pullback import check_vi_pullback, is_publishable_signal

logger = logging.getLogger(__name__)

REDIS_TOKEN_KEY  = "kiwoom:token"
POLL_INTERVAL    = 5.0    # 초: vi_watch_queue 폴링 주기 (Java: 5초)
MAX_BATCH        = 20     # 회당 최대 처리 건수 (Java: 20)
QUEUE_TTL        = 43200  # 12시간
S2_WINDOW_START  = dtime(9, 0)
S2_WINDOW_END    = dtime(14, 50)
_FUND_PRODUCT_NAME_MARKERS = (
    "ETF", "ETN", "레버리지", "인버스", "2X", "곱버스", "선물", "합성", "액티브",
)


def _is_etf_or_etn_item(item: dict) -> bool:
    normalized = str(item.get("stk_nm") or "").upper()
    return any(marker in normalized for marker in _FUND_PRODUCT_NAME_MARKERS)


def _is_s2_window_open(date_time=None) -> bool:
    target = date_time or now_kst()
    return (
        is_market_open_day(target.date())
        and S2_WINDOW_START <= target.time() < S2_WINDOW_END
    )


async def _is_stale_release_item(rdb, item: dict) -> bool:
    """Return True when a newer VI release superseded this queued watch."""
    stk_cd = str(item.get("stk_cd") or "").strip()
    if not stk_cd:
        return True
    latest = await rdb.hgetall(f"vi:{stk_cd}")
    if not latest:
        return False
    try:
        queued_price = float(item.get("vi_price") or 0)
        latest_price = float(latest.get("vi_price") or 0)
    except (TypeError, ValueError):
        return False
    return queued_price > 0 and latest_price > 0 and queued_price != latest_price
_SUPPLEMENT_INTERVAL = 30.0  # 초: 풀 보완 실행 주기
_SUPPLEMENT_RELEASE_MAX_AGE_MS = int(os.getenv("VI_SUPPLEMENT_RELEASE_MAX_AGE_MS", "60000"))
_SUPPLEMENT_DEDUP_SEC = int(os.getenv("VI_SUPPLEMENT_DEDUP_SEC", "660"))
STRATEGY_NAME = "S2_VI_PULLBACK"
STATUS_SIGNAL_TTL_SEC = 600
WORKER_STATUS_TTL_SEC = 600


async def _record_worker_metric(rdb, event: str, stk_cd: str | None = None) -> None:
    """Record lightweight S2 worker health without affecting signal processing."""
    try:
        now_ts = str(int(time.time()))
        key = "status:s2_vi_watch_worker"
        mapping = {
            "last_event": event,
            "updated_at": now_ts,
        }
        if stk_cd:
            mapping["last_stk_cd"] = str(stk_cd)
        await rdb.hset(key, mapping=mapping)
        await rdb.hincrby(key, f"{event}_count", 1)
        await rdb.expire(key, WORKER_STATUS_TTL_SEC)
    except Exception as status_err:
        logger.debug("[VI Watch] status metric failed event=%s: %s", event, status_err)


async def _record_signal_metric(rdb, signal: dict) -> None:
    """Mirror strategy_runner status metrics for S2 signals published by VI worker."""
    try:
        status_key = f"status:signals_10m:{STRATEGY_NAME}"
        await rdb.incr(status_key)
        await rdb.expire(status_key, STATUS_SIGNAL_TTL_SEC)
        await rdb.hset(
            f"status:last_signal:{STRATEGY_NAME}",
            mapping={
                "stk_cd": str(signal.get("stk_cd", "")),
                "score": str(signal.get("score", "")),
                "updated_at": str(int(time.time())),
            },
        )
        await rdb.expire(f"status:last_signal:{STRATEGY_NAME}", STATUS_SIGNAL_TTL_SEC)
    except Exception as status_err:
        logger.debug("[VI Watch] signal status metric failed: %s", status_err)


async def _requeue_watch_item(rdb, item_raw: str, stk_cd: str | None = None) -> None:
    """Requeue one unresolved VI watch at the configured worker cadence."""
    await rdb.lpush("vi_watch_queue", item_raw)
    await _record_worker_metric(rdb, "requeued", stk_cd)
    await asyncio.sleep(POLL_INTERVAL)


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
            dedup_key = f"scanner:dedup:{STRATEGY_NAME}:{stk_cd}"
            if await rdb.exists(dedup_key):
                continue

            # WebSocket 이 설정한 vi:{stk_cd} 해시 확인
            vi_data = await rdb.hgetall(f"vi:{stk_cd}")
            if not vi_data or not vi_data.get("vi_price"):
                continue  # VI 이벤트 데이터 없으면 처리 불가

            # 구독 갱신 시 과거 VI 스냅샷이 재전송될 수 있다. 풀 보완은
            # 큐 기록을 놓친 최근 해제 이벤트만 복구해야 한다.
            if str(vi_data.get("status") or "").lower() != "released":
                continue
            try:
                released_at_ms = int(float(vi_data.get("released_at_ms") or 0))
            except (TypeError, ValueError):
                continue
            release_age_ms = now_ms - released_at_ms
            if release_age_ms < 0 or release_age_ms > _SUPPLEMENT_RELEASE_MAX_AGE_MS:
                continue
            try:
                vi_price_key = float(str(vi_data.get("vi_price") or "0").replace(",", ""))
            except (TypeError, ValueError):
                continue
            supplement_key = f"vi:release:queue_dedup:{stk_cd}:{vi_price_key}"
            if not await rdb.set(supplement_key, "1", nx=True, ex=_SUPPLEMENT_DEDUP_SEC):
                continue

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
                if _is_s2_window_open() and now_ts - _last_supplement >= _SUPPLEMENT_INTERVAL:
                    supplemented = await _supplement_from_pool(rdb)
                    _last_supplement = now_ts
                    if supplemented:
                        logger.debug("[VI Watch] 풀 보완 %d건 추가", supplemented)
                await asyncio.sleep(POLL_INTERVAL)
                continue

            item = json.loads(item_raw)
            now_ms = int(time.time() * 1000)

            # S2 is live only during 09:00 <= KST < 14:50. Drain queued
            # releases outside that window without REST calls or publication.
            if not _is_s2_window_open():
                await _record_worker_metric(rdb, "blocked_after_window", item.get("stk_cd"))
                logger.info(
                    "[VI Watch] item discarded outside S2 window stk=%s",
                    item.get("stk_cd"),
                )
                continue

            # Defense in depth for stale queue entries created before the
            # websocket producer-side ETF/ETN filter was deployed.
            if _is_etf_or_etn_item(item):
                await _record_worker_metric(rdb, "blocked_etf_etn", item.get("stk_cd"))
                logger.info(
                    "[VI Watch] ETF/ETN item discarded stk=%s name=%s",
                    item.get("stk_cd"),
                    item.get("stk_nm"),
                )
                continue

            if await _is_stale_release_item(rdb, item):
                await _record_worker_metric(rdb, "stale_release", item.get("stk_cd"))
                logger.info(
                    "[VI Watch] superseded release discarded stk=%s price=%s",
                    item.get("stk_cd"),
                    item.get("vi_price"),
                )
                continue

            # 1. 감시 시간 만료 체크
            if now_ms > item.get("watch_until", 0):
                await _record_worker_metric(rdb, "expired", item.get("stk_cd"))
                continue

            # 2. 조건 체크
            signal = await check_vi_pullback(token, item, rdb)

            if signal and not is_publishable_signal(signal):
                await _record_worker_metric(rdb, "blocked_non_live", item.get("stk_cd"))
                logger.warning("[VI Watch] blocked non-live S2 payload: %s", item.get("stk_cd"))
                continue

            if signal:
                # 신호 발생 시 처리 (중복 방지 로직 포함)
                dedup_key = f"scanner:dedup:{STRATEGY_NAME}:{item['stk_cd']}"
                if await rdb.set(dedup_key, "1", nx=True, ex=3600):
                    await rdb.lpush("telegram_queue", json.dumps(signal, ensure_ascii=False))
                    await rdb.expire("telegram_queue", QUEUE_TTL)
                    await _record_signal_metric(rdb, signal)
                    await _record_worker_metric(rdb, "published", item.get("stk_cd"))
                    logger.info("🔥 S2 신호 포착: %s", item['stk_cd'])
                else:
                    await _record_worker_metric(rdb, "duplicate", item.get("stk_cd"))
            else:
                # 3. 조건 미충족 시 다시 큐에 삽입 (단, 약간의 지연 후 재진입 위해 LPUSH 사용 권장)
                # 너무 자주 체크하지 않도록 sleep을 주거나 처리 순서를 뒤로 보냄
                await _requeue_watch_item(rdb, item_raw, item.get("stk_cd"))

        except Exception as e:
            try:
                await _record_worker_metric(rdb, "error")
            except Exception:
                pass
            logger.error("[VI Watch] 에러: %s", e)
            await asyncio.sleep(1)
