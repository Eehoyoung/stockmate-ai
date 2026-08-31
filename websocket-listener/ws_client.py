"""
ws_client.py
키움 WebSocket 연결·구독·재연결을 담당하는 모듈.

그룹 할당 (Python 단독 WS 연결 – Java WS 비활성화):
  GRP 1  0B 체결      – 후보 종목 (최대 200)  [pre_market 08:00~ / market]
  GRP 2  0H 예상체결  – 상위 100              [pre_open 07:30~ / pre_market ~09:00]
  GRP 3  1h VI발동해제 – 전체                 [pre_open / pre_market / market]
  GRP 4  0D 호가잔량  – 상위 100              [pre_open / pre_market / market]

장 구분별 구독 전략:
  pre_open   07:30~08:00  GRP2(0H) + GRP3(1h) + GRP4(0D)
  pre_market 08:00~09:00  GRP1(0B) + GRP2(0H) + GRP3(1h) + GRP4(0D)
             ※ 08:00부터 0B 추가 → ws:tick/ws:strength 축적, S1·S7 체결강도 확보
  market     09:00~15:20  GRP1(0B) + GRP3(1h) + GRP4(0D)  [GRP2 해제]
  closed     15:20~       전 그룹 해제

  Kiwoom 은 토큰당 1개 WS 연결만 허용.
  Java api-orchestrator 의 WS 클라이언트(JAVA_WS_ENABLED=false)는 비활성화하고
  Python 이 단독으로 모든 실시간 데이터를 수신하여 Redis 에 기록한다.

환경변수:
  BYPASS_MARKET_HOURS=true  : 장 시간 외에도 연결 시도 (상시 운영 모드)
                              지수 백오프 적용, 최대 MAX_RECONNECTS 회 후 5분 대기 반복
  KIWOOM_MODE=real|mock     : real → wss://api.kiwoom.com, mock → wss://mockapi.kiwoom.com
"""

import asyncio
from collections import defaultdict, deque
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, time as dtime, timedelta, timezone

import websockets
from websockets.exceptions import ConnectionClosed

from health_server import (
    set_ws_connected,
    set_ws_session,
    record_message_received,
    record_subscription_ack,
)
import market_session
from redis_writer import write_tick, write_expected, write_hoga, write_program, write_vi, write_heartbeat, get_runtime_flag
from token_loader import load_token

KST = timezone(timedelta(hours=9))

# 장 운영 시간대 (KST)
_MARKET_OPEN_HOUR   = (7, 30)   # 07:30 – 장전 구독 시작
_MARKET_CLOSE_HOUR  = (20, 10)  # 20:10 – NXT 포함 종료
_WEEKDAYS           = {0, 1, 2, 3, 4}  # Mon=0 … Fri=4

BYPASS_MARKET_HOURS = os.getenv("BYPASS_MARKET_HOURS", "false").lower() in ("1", "true", "yes")


async def _bypass_market_hours(rdb) -> bool:
    """대시보드 flags:bypass_market_hours 오버라이드가 있으면 그 값을, 없으면 env 기본값을 사용."""
    return await get_runtime_flag(rdb, "bypass_market_hours", BYPASS_MARKET_HOURS)


def _now_kst() -> datetime:
    """현재 KST 시각 반환 (timezone-aware)"""
    return datetime.now(KST)


def _is_market_hours() -> bool:
    """Return True while the listener should actively connect/subscribe."""
    return market_session.should_keep_ws_connected(_now_kst())


def _is_early_connect_window() -> bool:
    """Return True during the WebSocket-only early connection window."""
    return market_session.is_early_connect_window(_now_kst())


def _next_market_open() -> datetime:
    """Return the next WebSocket connection start time in KST."""
    return market_session.next_ws_connect_time(_now_kst())


async def _wait_for_market_open():
    """
    장 운영 시간이 아닌 경우 다음 개장 시각까지 대기.
    60초 단위로 깨어나 재확인 (외부에서 취소 가능).
    """
    while True:
        set_ws_session(_get_market_session())
        if _is_market_hours():
            return  # 장 운영 중 → 즉시 반환

        next_open   = _next_market_open()
        now         = _now_kst()
        wait_sec    = (next_open - now).total_seconds()

        if wait_sec <= 0:
            return  # 이미 개장 시간 도달

        sleep_sec = min(60.0, wait_sec)
        logger.info(
            "[WS] 장 종료 시간 외 (현재 KST %02d:%02d) – 다음 개장 %s KST | %.0f분 남음 | %.0f초 대기",
            now.hour, now.minute,
            next_open.strftime("%m/%d %H:%M"),
            wait_sec / 60,
            sleep_sec,
        )
        try:
            await asyncio.sleep(sleep_sec)
        except asyncio.CancelledError:
            raise  # 취소 신호 → 상위로 전파


logger = logging.getLogger(__name__)

WS_PATH              = "/api/dostk/websocket"
MAX_RECONNECTS       = 10
BASE_RECONNECT_MS    = 3000   # ms
MAX_RECONNECT_SEC    = 300    # 최대 재연결 대기 5분
WATCHLIST_POLL_SEC   = 5      # candidates:watchlist 폴링 간격 (/score 호출 후 빠른 구독 반영)
HEARTBEAT_INTERVAL   = 30     # 초 (ws:py_heartbeat Redis 갱신 주기)
MIN_CONNECTED_SEC    = 30     # 이 미만으로 연결이 유지되면 "즉시 종료" 로 간주
WS_SILENCE_TIMEOUT_SEC = 90  # 이 초 이상 메시지 없으면 dead connection 판정 후 강제 종료


WS_CONTROL_MIN_INTERVAL_MS = int(os.getenv("WS_CONTROL_MIN_INTERVAL_MS", "500"))
WS_CONTROL_BACKOFF_SEC = float(os.getenv("WS_CONTROL_BACKOFF_SEC", "30"))
# 그룹당 100종목이 상한이다(키움 프로토콜 제약이라 env로도 못 넘긴다).
#
# 2026-08-14 측정: main_market 세션에서 "후보 200개 중 100개만 구독, 100개 실시간
# 누락" 경고가 92회, "139개 중 100개" 12회 찍혔다. 후보의 정확히 절반이 실시간
# 시세를 못 받는다. 그 여파로 S10은 후보 28개 중 19~23개가 no_realtime_tick으로
# 탈락해 하루 866종목 평가에 신호 0건이었다.
#
# 늘리려면 같은 타입(0B)을 두 그룹에 나눠 걸어야 한다. main_market에서 GRP 2가
# 비어 있어 자리는 있다(_groups_for_session 참고). 다만 지금은 구독 상태 키가
# ws:desired:{ttype} / _get_subscription_codes(ttype)처럼 **타입 단위**라, 두 그룹이
# 같은 0B를 쓰면 desired/current 집합이 충돌해 매 사이클 REG/REMOVE가 반복된다.
# 먼저 이 키들을 (grp_no, ttype) 단위로 바꿔야 하며, 키움 WS가 동일 타입의 다중
# 그룹 등록을 받아주는지도 장중에 확인이 필요하다. 검증 없이 건드리면 실시간
# 수신이 통째로 끊길 수 있어 보류한다.
WS_GROUP_MAX_ITEMS = max(1, min(100, int(os.getenv("WS_GROUP_MAX_ITEMS", "100"))))
WS_DYNAMIC_REG_ENABLED = os.getenv("WS_DYNAMIC_REG_ENABLED", "false").lower() in ("1", "true", "yes")
WS_CONTROL_ACK_TIMEOUT_SEC = max(1.0, float(os.getenv("WS_CONTROL_ACK_TIMEOUT_SEC", "10")))
SUBSCRIPTION_GROUPS = {
    "0B": ("1", "6"),
    "0H": ("2", "9"),
    "1h": ("3",),
    "0D": ("4", "7"),
    "0w": ("5", "8"),
}

_ws_control_lock = asyncio.Lock()
_ws_control_last_sent_at = 0.0
_ws_control_backoff_until = 0.0
_pending_ws_controls = defaultdict(deque)
_ws_control_sequence = 0
_ws_connection_generation = 0


async def _send_ws_control(ws, payload: dict, *, full_snapshot: bool = False):
    """Throttle Kiwoom REG/REMOVE control packets across concurrent tasks."""
    global _ws_control_last_sent_at, _ws_control_sequence
    async with _ws_control_lock:
        now = time.monotonic()
        if _ws_control_backoff_until > now:
            await asyncio.sleep(_ws_control_backoff_until - now)
            now = time.monotonic()
        min_interval = max(0.0, WS_CONTROL_MIN_INTERVAL_MS / 1000.0)
        wait = min_interval - (now - _ws_control_last_sent_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _ws_control_sequence += 1
        operation = {
            "operation_id": _ws_control_sequence,
            "trnm": str(payload.get("trnm", "")),
            "grp_no": str(payload.get("grp_no", "")),
            "data": payload.get("data") or [],
            "full_snapshot": full_snapshot,
            "sent_at_ms": int(time.time() * 1000),
            "generation": _ws_connection_generation,
        }
        operation["item_hash"] = hashlib.sha256(
            json.dumps(operation["data"], sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:16]
        # Kiwoom REG/REMOVE ACK responses always echo grp_no="" (empirically verified
        # across production logs), never the grp_no that was actually sent. Keying the
        # pending queue by (trnm, grp_no) therefore never matches a real ACK and every
        # operation silently times out even when Kiwoom answers immediately. Kiwoom does
        # echo trnm correctly, and responses arrive in the order requests were sent over
        # the single serialized connection (guarded by _ws_control_lock), so FIFO-per-trnm
        # is the only reliable correlation available.
        key = operation["trnm"]
        _pending_ws_controls[key].append(operation)
        try:
            await ws.send(json.dumps(payload))
        except Exception:
            _pending_ws_controls[key].pop()
            if not _pending_ws_controls[key]:
                _pending_ws_controls.pop(key, None)
            raise
        _ws_control_last_sent_at = time.monotonic()
        return operation["operation_id"]


async def _apply_ws_control_ack(rdb, trnm: str, grp_no: str, return_code: str):
    """Commit subscription state only after the matching Kiwoom ACK succeeds.

    Kiwoom's ACK payload never echoes the grp_no we sent (it is always ""), so the
    incoming grp_no cannot be used to key the pending-operation lookup. Match FIFO by
    trnm only; see _send_ws_control for the reasoning.
    """
    key = trnm
    pending = _pending_ws_controls.get(key)
    operation = pending.popleft() if pending else None
    if pending is not None and not pending:
        _pending_ws_controls.pop(key, None)
    if operation is None or return_code != "0":
        return operation

    for entry in operation["data"]:
        items = [str(code) for code in (entry.get("item") or []) if code is not None]
        for ttype in (entry.get("type") or []):
            state_key = f"ws:subscribed:{ttype}"
            group_state_key = f"{state_key}:{operation['grp_no']}"
            if trnm == "REG" and operation["full_snapshot"]:
                await _replace_subscription_set(rdb, group_state_key, items)
            elif trnm == "REG":
                for code in items:
                    await _add_subscription_code(rdb, group_state_key, code)
            elif trnm == "REMOVE":
                for code in items:
                    await _remove_subscription_code(rdb, group_state_key, code)
            await _refresh_subscription_union(rdb, ttype)
    return operation


async def _expire_pending_ws_controls(rdb) -> list[dict]:
    """Expire ACK-less operations without modifying the last acknowledged state."""
    cutoff_ms = int(time.time() * 1000 - WS_CONTROL_ACK_TIMEOUT_SEC * 1000)
    expired: list[dict] = []
    for key in list(_pending_ws_controls.keys()):
        queue = _pending_ws_controls.get(key)
        while queue and queue[0]["sent_at_ms"] <= cutoff_ms:
            operation = queue.popleft()
            expired.append(operation)
            for entry in operation["data"]:
                for ttype in (entry.get("type") or []):
                    status_key = f"status:ws_subscription_rejected:{operation['grp_no']}:{ttype}"
                    try:
                        await rdb.hset(status_key, mapping={
                            "reason": "ACK_TIMEOUT",
                            "operation_id": str(operation["operation_id"]),
                            "generation": str(operation["generation"]),
                            "item_hash": operation["item_hash"],
                            "updated_at_ms": str(int(time.time() * 1000)),
                        })
                        await rdb.expire(status_key, 600)
                    except Exception:
                        pass
            record_subscription_ack(
                operation["trnm"], operation["grp_no"], "ACK_TIMEOUT", "ack deadline exceeded",
                operation_id=operation["operation_id"],
                item_count=sum(len(row.get("item") or []) for row in operation["data"]),
            )
            logger.error(
                "[WS] ACK timeout operation_id=%s generation=%s grp=%s hash=%s",
                operation["operation_id"], operation["generation"], operation["grp_no"], operation["item_hash"],
            )
            _backoff_ws_control(f"ACK_TIMEOUT:{operation['trnm']}:{operation['grp_no']}")
        if queue is not None and not queue:
            _pending_ws_controls.pop(key, None)
    return expired


async def _ack_timeout_watcher(rdb):
    while True:
        try:
            await asyncio.sleep(1.0)
            await _expire_pending_ws_controls(rdb)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[WS] ACK timeout watcher failed: %s", exc)


def _backoff_ws_control(reason: str):
    """Back off future REG/REMOVE sends after Kiwoom request-limit ACKs."""
    global _ws_control_backoff_until
    until = time.monotonic() + WS_CONTROL_BACKOFF_SEC
    if until > _ws_control_backoff_until:
        _ws_control_backoff_until = until
        logger.warning("[WS] control backoff %.1fs reason=%s", WS_CONTROL_BACKOFF_SEC, reason)


async def _replace_subscription_set(rdb, key: str, codes: list[str]):
    """Persist connection-scoped subscription state without a time-based expiry.

    The WS connection explicitly clears these sets on every reconnect. Expiring
    them while the connection is alive loses local state before the 5-minute
    phase refresh and causes duplicate REG requests to accumulate server-side.
    """
    try:
        # An empty item is Kiwoom's valid "all symbols" marker (for example 1h).
        # Persist it so reconciliation does not re-register the wildcard forever.
        uniq = [code for code in dict.fromkeys(codes) if code is not None]
        await rdb.delete(key)
        if uniq:
            await rdb.sadd(key, *uniq)
    except Exception as e:
        logger.debug("[WS] subscription set refresh failed %s: %s", key, e)


async def _add_subscription_code(rdb, key: str, code: str):
    if code is None:
        return
    try:
        await rdb.sadd(key, code)
    except Exception as e:
        logger.debug("[WS] subscription set add failed %s %s: %s", key, code, e)


async def _remove_subscription_code(rdb, key: str, code: str):
    if code is None:
        return
    try:
        await rdb.srem(key, code)
    except Exception as e:
        logger.debug("[WS] subscription set remove failed %s %s: %s", key, code, e)


async def _get_subscription_codes(rdb, ttype: str, grp_no: str | None = None) -> list[str]:
    """Return the locally tracked codes for a realtime type."""
    try:
        suffix = f":{grp_no}" if grp_no is not None else ""
        raw = await rdb.smembers(f"ws:subscribed:{ttype}{suffix}")
    except Exception as e:
        logger.debug("[WS] subscription set read failed %s: %s", ttype, e)
        return []
    codes = [
        c.decode("utf-8") if isinstance(c, bytes) else c
        for c in (raw or [])
        if c is not None
    ]
    return [str(c) for c in codes]


async def _refresh_subscription_union(rdb, ttype: str) -> None:
    """Keep the legacy type-level set equal to the acknowledged group union."""
    union: set[str] = set()
    for grp_no in SUBSCRIPTION_GROUPS.get(ttype, ()):
        union.update(await _get_subscription_codes(rdb, ttype, grp_no))
    await _replace_subscription_set(rdb, f"ws:subscribed:{ttype}", sorted(union))


async def _send_remove(ws, grp_no: str, ttype: str, items: list[str]):
    """Send Kiwoom REMOVE only for concrete tracked items."""
    uniq = [code for code in dict.fromkeys(items) if code is not None]
    if not uniq:
        return False
    for i in range(0, len(uniq), 100):
        batch = uniq[i:i + 100]
        payload = {"trnm": "REMOVE", "grp_no": grp_no, "data": [{"item": batch, "type": [ttype]}]}
        await _send_ws_control(ws, payload)
    return True


async def _clear_subscription_type(ws, rdb, grp_no: str, ttype: str):
    """Idempotently release one realtime type using local subscription state."""
    codes = await _get_subscription_codes(rdb, ttype, grp_no)
    await _replace_subscription_set(rdb, f"ws:desired:{ttype}:{grp_no}", [])
    sent = await _send_remove(ws, grp_no, ttype, codes)
    if sent:
        logger.info("[WS] subscription cleared grp=%s type=%s count=%d", grp_no, ttype, len(codes))
    return sent


async def _reset_local_subscription_sets(rdb):
    """Clear Redis subscription tracking for a freshly established WS connection."""
    global _ws_connection_generation
    _ws_connection_generation += 1
    _pending_ws_controls.clear()
    for ttype, group_numbers in SUBSCRIPTION_GROUPS.items():
        await _replace_subscription_set(rdb, f"ws:subscribed:{ttype}", [])
        await _replace_subscription_set(rdb, f"ws:desired:{ttype}", [])
        for grp_no in group_numbers:
            await _replace_subscription_set(rdb, f"ws:subscribed:{ttype}:{grp_no}", [])
            await _replace_subscription_set(rdb, f"ws:desired:{ttype}:{grp_no}", [])


async def _get_candidates(rdb, market: str = "001") -> list[str]:
    """Redis 후보 종목 캐시 읽기.
    우선순위:
      1. candidates:watchlist (SET) – websocket-listener 전용 통합 풀 (TTL 없음)
      2. candidates:{market}  (LIST) – 구형 호환 (TTL 3분, 만료 시 빈 목록)
    """
    # 1차: candidates:watchlist 전체 (시장 구분 없이)
    try:
        watchlist = await rdb.smembers("candidates:watchlist")
        if watchlist:
            return list(watchlist)[:200]
    except Exception:
        pass
    # 2차: 구형 시장별 LIST (fallback)
    key = f"candidates:{market}"
    items = await rdb.lrange(key, 0, 199)
    return items or []


async def _get_ranked_candidates(rdb) -> tuple[list[str], list[str]]:
    """ZSET 우선순위 후보를 앞에 배치한 전체/상위 100개 목록을 반환한다."""
    hold_codes = await _get_hold_monitor_watchlist(rdb)
    try:
        zset_codes = await rdb.zrevrange("candidates:watchlist:z", 0, 199)
        if zset_codes:
            ranked = [c.decode("utf-8") if isinstance(c, bytes) else c for c in zset_codes if c]
            ranked = _merge_hold_codes(ranked, hold_codes, limit=200)
            return ranked, ranked[:100]
    except Exception:
        pass

    try:
        priority_codes = await rdb.smembers("candidates:watchlist:priority")
    except Exception:
        priority_codes = set()

    try:
        watchlist = await rdb.smembers("candidates:watchlist")
    except Exception:
        watchlist = set()

    if not watchlist:
        combined: list[str] = []
        for market in ("001", "101"):
            combined.extend(await _get_candidates(rdb, market))
        watchlist = set(c for c in combined if c)

    priority_codes = {
        c.decode("utf-8") if isinstance(c, bytes) else c
        for c in priority_codes if c
    }
    watchlist = {
        c.decode("utf-8") if isinstance(c, bytes) else c
        for c in watchlist if c
    }
    priority_list = sorted(c for c in priority_codes if c)
    remaining = sorted(c for c in watchlist if c and c not in priority_codes)
    ranked = _merge_hold_codes(priority_list + remaining, hold_codes, limit=200)
    return ranked, ranked[:100]


async def _get_hold_monitor_watchlist(rdb) -> list[str]:
    try:
        codes = await rdb.smembers("hold_monitor:watchlist")
    except Exception:
        return []
    return [
        c.decode("utf-8") if isinstance(c, bytes) else c
        for c in (codes or [])
        if c
    ]


def _merge_hold_codes(codes: list[str], hold_codes: list[str], *, limit: int) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for code in sorted(hold_codes):
        if code and code not in seen:
            merged.append(code)
            seen.add(code)
    for code in codes:
        if code and code not in seen:
            merged.append(code)
            seen.add(code)
    return merged[:limit]


def _get_market_session() -> str:
    """Return the KST trading session used by subscription and reconnect logic."""
    return market_session.current_session(_now_kst())


def _get_market_phase() -> str:
    """Backward-compatible alias for older tests and callers."""
    return _get_market_session()


def _groups_for_session(session: str, all_cands: list[str], top100: list[str]) -> list[tuple[str, str, list[str]]]:
    tick_groups = [("1", "0B", all_cands[:100]), ("6", "0B", all_cands[100:200])]
    hoga_groups = [("4", "0D", all_cands[:100]), ("7", "0D", all_cands[100:200])]
    program_groups = [("5", "0w", all_cands[:100]), ("8", "0w", all_cands[100:200])]
    if session == "pre_market":
        return tick_groups + hoga_groups + program_groups + [
            ("2", "0H", top100),
            ("3", "1h", [""]),
        ]
    if session == "opening_auction":
        return tick_groups + hoga_groups + program_groups + [
            ("2", "0H", top100),
            ("3", "1h", [""]),
        ]
    if session in {"main_market", "closing_auction", "after_preopen", "after_market"}:
        return tick_groups + hoga_groups + program_groups + [
            ("3", "1h", [""]),
        ]
    return []


def _is_expected_silent_close(session: str, close_code) -> bool:
    return session in {"post_quiet", "closed"} and close_code in {1000, 1001, None}


async def _send_unreg(ws, grp_no: str, ttype: str):
    """단일 그룹/타입 구독 해제 전송"""
    await _send_remove(ws, grp_no, ttype, [])


async def _subscribe_by_phase(ws, rdb, phase: str):
    """장 구분(phase)에 따라 적절한 그룹을 구독/해제한다.

    GRP 1: 0B 체결      – 후보 전체 (최대 200) [pre_market 08:00~ / market]
    GRP 2: 0H 예상체결  – 상위 100             [pre_open / pre_market]
    GRP 3: 1h VI발동해제 – 전종목              [pre_open / pre_market / market]
    GRP 4: 0D 호가잔량  – 상위 100             [pre_open / pre_market / market]
    """
    all_cands, top100 = await _get_ranked_candidates(rdb)
    session = phase
    set_ws_session(session)
    groups = _groups_for_session(session, all_cands, top100)

    if not groups:
        for ttype, group_numbers in SUBSCRIPTION_GROUPS.items():
            for grp_no in group_numbers:
                try:
                    await _clear_subscription_type(ws, rdb, grp_no, ttype)
                    await asyncio.sleep(0.1)
                except Exception:
                    pass
        logger.info("[WS] session=%s, all subscriptions cleared", session)
        return

    # 키움 WS 프로토콜: item 배열에 종목코드 목록, type 배열에 실시간 항목을 담아 전송.
    # 매번 전체 목록을 REG로 재전송하면 Kiwoom 측 그룹당 등록 개수가 중복 누적되어
    # "허용 개수 초과" 거부로 이어지므로, 이미 구독 중인 종목은 다시 보내지 않고
    # 차집합(diff)만 REG/REMOVE 한다.
    subscribed_counts: dict[str, int] = {}
    desired_by_type: dict[str, list[str]] = defaultdict(list)
    for _, ttype, items in groups:
        desired_by_type[ttype].extend(items)
    for ttype, items in desired_by_type.items():
        await _replace_subscription_set(rdb, f"ws:desired:{ttype}", list(dict.fromkeys(items)))
    for grp_no, ttype, items in groups:
        deduped = list(dict.fromkeys(items))
        items = deduped[:WS_GROUP_MAX_ITEMS]
        subscribed_counts[ttype] = subscribed_counts.get(ttype, 0) + len(items)
        # 그룹 상한에 걸려 잘려나간 종목은 실시간 시세를 전혀 받지 못한다.
        # 그 종목을 평가하는 전략(S10 등)은 flu_rt를 0.0으로 읽어 "등락률 범위
        # 초과"로 오탐 제외하게 되므로, 절단이 발생하면 반드시 눈에 띄어야 한다.
        dropped = len(deduped) - len(items)
        if dropped > 0:
            logger.warning(
                "[WS] 구독 상한 초과 – type=%s 후보 %d개 중 %d개만 구독, %d개 실시간 누락 "
                "(WS_GROUP_MAX_ITEMS=%d)",
                ttype, len(deduped), len(items), dropped, WS_GROUP_MAX_ITEMS,
            )
        await _replace_subscription_set(rdb, f"ws:desired:{ttype}:{grp_no}", items)

        current = set(await _get_subscription_codes(rdb, ttype, grp_no))
        desired = set(items)
        if current == desired:
            continue
        if not items:
            await _send_remove(ws, grp_no, ttype, list(current))
            logger.info("[WS] 구독 해제 grp=%s type=%s %d개", grp_no, ttype, len(current))
            await asyncio.sleep(0.3)
            continue
        payload = {
            "trnm": "REG",
            "grp_no": grp_no,
            "refresh": "0",
            "data": [{"item": items, "type": [ttype]}],
        }
        await _send_ws_control(ws, payload, full_snapshot=True)
        logger.info("[WS] 구독 교체 grp=%s type=%s %d개", grp_no, ttype, len(items))
        await asyncio.sleep(0.3)

    # 0H is only valid through opening_auction; make later sessions explicitly release it.
    if phase in {"main_market", "closing_auction", "after_preopen", "after_market"}:
        try:
            removed_0h = await _clear_subscription_type(ws, rdb, "2", "0H")
            logger.info("[WS] 정규장 전환 – 예상체결(0H) 구독 해제")
        except Exception:
            pass

    # len(all_cands)만 찍으면 상한 절단이 보이지 않는다. 실제 구독 수를 함께
    # 남겨야 "후보 200개"가 곧 "실시간 200개"라는 오해가 생기지 않는다.
    tick_subscribed = subscribed_counts.get("0B", 0)
    logger.info(
        "[WS] 구독 설정 완료 (phase=%s, 후보=%d개, 실시간구독=%s, 틱(0B)=%d개)",
        phase,
        len(all_cands),
        ", ".join(f"{t}:{n}" for t, n in sorted(subscribed_counts.items())) or "없음",
        tick_subscribed,
    )


async def _phase_watcher(ws, rdb):
    """30초마다 장 구분 변화를 감지하여 구독을 전환하고,
    5분(30s × 10)마다 후보 종목 구독을 갱신한다.
    Java WebSocketSubscriptionManager.refreshCandidateSubscription() 에 해당.
    """
    current_phase = _get_market_phase()
    refresh_counter = 0
    REFRESH_EVERY = 10  # 30s × 10 = 5분

    while True:
        try:
            await asyncio.sleep(30)
            new_phase = _get_market_phase()
            refresh_counter += 1
            refresh_every = 2 if current_phase in {"pre_market", "opening_auction"} else 10

            if new_phase != current_phase:
                logger.info("[WS] 장 구분 전환 %s → %s", current_phase, new_phase)
                await _subscribe_by_phase(ws, rdb, new_phase)
                current_phase = new_phase
                refresh_counter = 0
            elif refresh_counter >= refresh_every and current_phase not in {"closed", "post_quiet"}:
                logger.info("[WS] 후보 갱신 구독 재전송 (phase=%s)", current_phase)
                await _subscribe_by_phase(ws, rdb, current_phase)
                refresh_counter = 0

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[WS] phase_watcher 오류: %s", e)


async def _handle_message(msg_str: str, ws, rdb, pg_pool=None):
    """수신 메시지 파싱 및 Redis 저장 분기.

    키움 실시간 메시지 형식:
      {"trnm":"REAL","data":[{"type":"0B","item":"005930","values":{"10":"-20800",...}}]}
    """
    try:
        msg  = json.loads(msg_str)
        trnm = msg.get("trnm", "")

        if trnm == "PING":
            await ws.send(msg_str)   # 키움 가이드: 수신값 그대로 송신
            return

        # 키움 실시간 데이터는 trnm="REAL", data 배열 안에 type/item/values 포함
        if trnm in {"REG", "REMOVE"} and "return_code" in msg:
            rc = str(msg.get("return_code", ""))
            grp_no = str(msg.get("grp_no", ""))
            return_msg = str(msg.get("return_msg", ""))
            operation = await _apply_ws_control_ack(rdb, trnm, grp_no, rc)
            record_subscription_ack(
                trnm,
                grp_no,
                rc,
                return_msg,
                operation_id=operation.get("operation_id") if operation else None,
                item_count=sum(len(row.get("item") or []) for row in operation.get("data", [])) if operation else 0,
            )
            status_key = f"status:ws_subscription_ack:{grp_no or 'unknown'}"
            try:
                await rdb.hset(status_key, mapping={
                    "trnm": trnm,
                    "grp_no": grp_no,
                    "return_code": rc,
                    "return_msg": return_msg,
                    "operation_id": str(operation.get("operation_id", "")) if operation else "",
                    "updated_at_ms": str(int(time.time() * 1000)),
                })
                await rdb.expire(status_key, 600)
            except Exception:
                pass
            if rc != "0":
                if rc == "105110":
                    _backoff_ws_control(f"{trnm}:{rc}")
                logger.warning("[WS] %s ACK failed grp=%s return_code=%s msg=%s", trnm, grp_no, rc, return_msg)
            else:
                logger.debug("[WS] %s ACK ok grp=%s", trnm, grp_no)
            return

        if trnm == "REAL":
            data_list = msg.get("data") or []
            for entry in data_list:
                entry_type = entry.get("type", "")
                stk_cd     = entry.get("item", "")
                values     = entry.get("values") or {}
                match entry_type:
                    case "0B": await write_tick(rdb, values, stk_cd, pg_pool)
                    case "0H": await write_expected(rdb, values, stk_cd, pg_pool)
                    case "0D": await write_hoga(rdb, values, stk_cd, pg_pool)
                    case "0w": await write_program(rdb, values, stk_cd, pg_pool)
                    case "1h": await write_vi(rdb, values, stk_cd, pg_pool)
            record_message_received()
            return

    except json.JSONDecodeError:
        logger.debug("[WS] JSON 파싱 실패: %.100s", msg_str)
    except Exception as e:
        logger.warning("[WS] 메시지 처리 오류: %s", e)


async def _watchlist_poller(ws, rdb, subscribed_set: set):
    """
    candidates:watchlist (Redis Set) 을 30초마다 폴링하여
    신규 종목은 REG, 제거 종목은 REMOVE 전송.
    """
    while True:
        try:
            await asyncio.sleep(WATCHLIST_POLL_SEC)
            if not WS_DYNAMIC_REG_ENABLED:
                continue
            watchlist, top100 = await _get_ranked_candidates(rdb)
            if not watchlist:
                continue
            session = _get_market_session()
            groups = _groups_for_session(session, watchlist, top100)
            active_types = {ttype for _, ttype, _ in groups}
            if "0B" not in active_types:
                continue

            watchset = set(watchlist)
            if watchset == subscribed_set:
                continue
            await _subscribe_by_phase(ws, rdb, session)
            subscribed_set.clear()
            subscribed_set.update(watchset)

        except Exception as e:
            logger.warning("[WS] watchlist 폴러 오류: %s", e)


async def _heartbeat_writer(rdb):
    """10초마다 ws:py_heartbeat 갱신 (TTL 30s)"""
    while True:
        try:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            await write_heartbeat(rdb, {
                "grp1": "ok", "grp2": "ok", "grp3": "ok", "grp4": "ok", "grp5": "ok"
            })
        except Exception as e:
            logger.debug("[WS] heartbeat 오류: %s", e)



async def _silence_watchdog(ws, last_msg_holder: list):
    """90초 무메시지 감지 시 ws.close() 로 reconnect 유도.
    Kiwoom 서버가 close frame 없이 TCP를 끊는 경우를 대비한 데드 커넥션 탐지."""
    while True:
        await asyncio.sleep(30)
        elapsed = time.monotonic() - last_msg_holder[0]
        if elapsed > WS_SILENCE_TIMEOUT_SEC:
            logger.warning(
                "[WS] %.0f초 무메시지 — dead connection 판정, 강제 종료하여 재연결 유도", elapsed
            )
            await ws.close()
            return


async def _run_message_loop(ws, rdb, pg_pool=None, last_msg_holder=None):
    """메시지 수신 루프 – 서버 PING 포함 모든 메시지 즉시 처리"""
    async for message in ws:
        if last_msg_holder is not None:
            last_msg_holder[0] = time.monotonic()
        await _handle_message(message, ws, rdb, pg_pool)
    logger.info("[WS] 서버 정상 종료 (clean close)")


async def run_ws_loop(rdb, pg_pool=None):
    """
    WebSocket 메인 루프 – 장 운영 시간 감지 + 지수 백오프 재연결 포함.

    BYPASS_MARKET_HOURS=true 일 때:
      장 시간과 무관하게 연결 시도, 지수 백오프 적용 (최대 5분).
      MAX_RECONNECTS 초과 시 5분 대기 후 카운터 리셋하여 무한 재시도.
    BYPASS_MARKET_HOURS=false 일 때:
      장 시간 외 연결 종료 시 _wait_for_market_open() 으로 개장까지 대기.
    """
    # 실전/모의 환경 분기
    kiwoom_mode = os.getenv("KIWOOM_MODE", "real").lower()
    if kiwoom_mode == "real":
        ws_base_url = os.getenv("KIWOOM_WS_URL", "wss://api.kiwoom.com:10000")
    else:
        ws_base_url = os.getenv("KIWOOM_WS_URL", "wss://mockapi.kiwoom.com:10000")
    url = ws_base_url + WS_PATH

    if BYPASS_MARKET_HOURS:
        logger.warning(
            "[WS] BYPASS_MARKET_HOURS=true keeps the process alive; session rules still control subscriptions"
        )

    # GRP 충돌 방지 검사: JAVA_WS_ENABLED=true 이면 Python과 Java가 동일 GRP 사용 위험
    java_ws_enabled = os.getenv("JAVA_WS_ENABLED", "false").lower() in ("1", "true", "yes")
    if java_ws_enabled:
        logger.error(
            "[WS] ⛔ JAVA_WS_ENABLED=true 감지 – Java api-orchestrator WS 클라이언트가 "
            "GRP 1~4 를 점유 중입니다. Python은 GRP 5~8 을 사용해야 합니다. "
            "두 서비스가 동일 GRP 를 구독하면 Kiwoom 서버에서 킥킹이 발생합니다. "
            "websocket-listener 의 GRP 번호를 5~8 로 수정하거나 "
            "JAVA_WS_ENABLED=false 로 설정하세요."
        )

    reconnect_count = 0
    delay_sec       = BASE_RECONNECT_MS / 1000

    while True:
        # ── 장 운영 시간 외이면 개장까지 대기 ──────────────────────
        bypass_market_hours = await _bypass_market_hours(rdb)
        if not bypass_market_hours:
            await _wait_for_market_open()
        else:
            # bypass 모드: MAX_RECONNECTS 초과 시 5분 대기 후 리셋
            if reconnect_count > MAX_RECONNECTS:
                logger.warning(
                    "[WS] bypass 모드 최대 재연결 %d회 초과 – 5분 대기 후 재시도",
                    MAX_RECONNECTS,
                )
                await asyncio.sleep(MAX_RECONNECT_SEC)
                reconnect_count = 0
                delay_sec       = BASE_RECONNECT_MS / 1000

        connect_time = None
        active_session = _get_market_session()
        set_ws_session(active_session)
        try:
            token = await load_token(rdb)

            logger.info("[WS] 연결 시도 #%d → %s", reconnect_count + 1, url)

            import time as _time
            connect_time = _time.monotonic()

            async with websockets.connect(
                    url,
                    ping_interval=None,   # 키움 앱레벨 PING/PONG 사용 – 라이브러리 ping 비활성화
                    open_timeout=15,
            ) as ws:
                logger.info("[WS] 연결 성공")
                set_ws_connected(True)

                # ── LOGIN 패킷 전송 (키움 WS 프로토콜 필수) ─────────────
                # 연결 후 실시간 데이터 요청 전 반드시 LOGIN 패킷을 보내야 함.
                # 미전송 시 서버가 약 10초 후 code=1000 "Bye" 로 종료.
                login_packet = {"trnm": "LOGIN", "token": token}
                await ws.send(json.dumps(login_packet))
                logger.info("[WS] LOGIN 패킷 전송 완료")

                # LOGIN 응답 수신 (timeout 10초)
                try:
                    login_resp_raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
                    login_resp     = json.loads(login_resp_raw)
                    return_code    = str(login_resp.get("return_code", "-1"))
                    if return_code != "0":
                        logger.error("[WS] LOGIN 실패 – return_code=%s body=%s", return_code, login_resp)
                        raise ConnectionError(f"WS LOGIN 실패 (return_code={return_code})")
                    logger.info("[WS] LOGIN 성공 – return_code=0")
                    await _reset_local_subscription_sets(rdb)
                except asyncio.TimeoutError:
                    logger.error("[WS] LOGIN 응답 타임아웃 (10초)")
                    raise ConnectionError("WS LOGIN 응답 없음")
                except json.JSONDecodeError as e:
                    logger.error("[WS] LOGIN 응답 JSON 파싱 오류: %s", e)
                    raise

                # 연결 직후 즉시 heartbeat 기록 (TTL 소멸 방지)
                await write_heartbeat(rdb, {
                    "grp1": "ok", "grp2": "ok", "grp3": "ok", "grp4": "ok", "grp5": "ok"
                })

                # ── 메시지 루프를 구독보다 먼저 시작 ──────────────────────
                # 구독(REG) 도중 서버가 PING을 보내도 즉시 PONG 응답 가능
                last_msg_holder = [time.monotonic()]
                message_task = asyncio.create_task(_run_message_loop(ws, rdb, pg_pool, last_msg_holder))

                # BYPASS keeps the process alive, but it must not force a trading subscription session.
                initial_phase = _get_market_session()
                await _subscribe_by_phase(ws, rdb, initial_phase)

                # 초기 구독 후보를 subscribed_set 에 등록 (watchlist poller 가 중복 REMOVE 방지)
                initial_ranked, _ = await _get_ranked_candidates(rdb)
                subscribed_set: set = set(initial_ranked)

                # 동적 구독 watchlist 폴러 + heartbeat + 장 구분 전환 감시 시작
                # 키움 공식 가이드: PING 은 서버→클라이언트 방향만 정의됨.
                # 수신한 PING 은 _handle_message 에서 그대로 에코, 클라이언트 주도 PING 은 없음.
                watchlist_task = asyncio.create_task(_watchlist_poller(ws, rdb, subscribed_set))
                heartbeat_task = asyncio.create_task(_heartbeat_writer(rdb))
                phase_task     = asyncio.create_task(_phase_watcher(ws, rdb))
                silence_task   = asyncio.create_task(_silence_watchdog(ws, last_msg_holder))
                ack_timeout_task = asyncio.create_task(_ack_timeout_watcher(rdb))

                try:
                    await message_task  # 서버가 연결을 닫을 때까지 대기
                finally:
                    tasks = [watchlist_task, heartbeat_task, phase_task, silence_task, ack_timeout_task, message_task]
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    set_ws_connected(False)

        except ConnectionClosed as e:
            close_code = e.rcvd.code if e.rcvd else None
            if _is_expected_silent_close(active_session, close_code):
                reason = f"expected_silent_close:{active_session}"
                logger.info("[WS] expected silent close in session=%s code=%s", active_session, close_code)
            else:
                reason = f"ConnectionClosed:{close_code if close_code is not None else 'unknown'}"
                logger.warning("[WS] 연결 끊김 (ConnectionClosed): %s", e,
                               extra={"error_code": reason})
            set_ws_connected(False, reason=reason)
        except OSError as e:
            reason = f"OSError:{type(e).__name__}"
            logger.error("[WS] 네트워크 오류: %s", e,
                         extra={"error_code": reason})
            set_ws_connected(False, reason=reason)
        except RuntimeError as e:
            # load_token 실패: Java api-orchestrator 미기동 (kiwoom:access_token 없음)
            # WS reconnect 카운터를 소모하지 않고 30초 대기 후 재시도
            logger.warning("[WS] 토큰 미발급 – Java 서버 기동 대기: %s | 30초 후 재시도", e)
            set_ws_connected(False, reason="token_not_available")
            await asyncio.sleep(30)
            continue  # reconnect_count 증가 없이 루프 재시작
        except Exception as e:
            reason = f"Exception:{type(e).__name__}"
            logger.error("[WS] 예상치 못한 오류: %s", e,
                         extra={"error_code": reason})
            set_ws_connected(False, reason=reason)

        # 연결이 최소 유지 시간 이상 유지됐다면 종료 경로(정상/ConnectionClosed/
        # OSError/기타 예외)와 무관하게 백오프 카운터를 리셋한다. 키움 WS는
        # close frame 없는 ConnectionClosed 로 끊기는 경우가 대부분이라, 이 리셋을
        # try 블록의 정상 종료 경로에만 두면 사실상 리셋이 거의 발생하지 않아
        # 지수 백오프가 하루 종일 300초 상한까지 누적된 채 유지되는 문제가 있었다.
        if connect_time is not None:
            elapsed = _time.monotonic() - connect_time
            if elapsed >= MIN_CONNECTED_SEC:
                reconnect_count = 0
                delay_sec       = BASE_RECONNECT_MS / 1000
                logger.info("[WS] 연결 %.1f초 유지 후 종료 – 카운터 리셋", elapsed)

        # ── 재연결 전 시장 시간 판단 ──────────────────────────────
        if not bypass_market_hours and not _is_market_hours():
            logger.info("[WS] 장 종료 / 비운영 시간 감지 – 개장 대기 모드로 전환")
            reconnect_count = 0
            delay_sec       = BASE_RECONNECT_MS / 1000
            # 다음 루프 상단의 _wait_for_market_open() 이 처리하므로 continue
            continue

        # ── 지수 백오프 재연결 ────────────────────────────────────
        reconnect_count += 1
        if reconnect_count > MAX_RECONNECTS:
            # bypass 모드 또는 장 운영 중: 프로세스 종료 대신 5분 대기 후 재시도
            if bypass_market_hours or _is_market_hours():
                logger.warning(
                    "[WS] 최대 재연결 %d회 초과 – %.0f분 대기 후 재시도",
                    MAX_RECONNECTS, MAX_RECONNECT_SEC / 60,
                )
                await asyncio.sleep(MAX_RECONNECT_SEC)
                reconnect_count = 0
                delay_sec       = BASE_RECONNECT_MS / 1000
            else:
                logger.critical(
                    "[WS] 최대 재연결 횟수 %d 초과 (장 외 시간) – 프로세스 종료", MAX_RECONNECTS
                )
                sys.exit(1)
            continue

        logger.info("[WS] %.1f초 후 재연결 (%d번째)", delay_sec, reconnect_count)
        await asyncio.sleep(delay_sec)
        delay_sec = min(delay_sec * 2, MAX_RECONNECT_SEC)
