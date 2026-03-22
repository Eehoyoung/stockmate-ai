"""
ws_client.py
키움 WebSocket 연결·구독·재연결을 담당하는 모듈.

그룹 할당 (Java GRP 1~4 와 충돌 방지):
  GRP 5  0B 체결      – 후보 종목
  GRP 6  0H 예상체결  – 장전용
  GRP 7  1h VI발동해제 – 전체
  GRP 8  0D 호가잔량  – 상위 100
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, time as dtime, timedelta, timezone

import websockets
from websockets.exceptions import ConnectionClosed

from health_server import set_ws_connected
from redis_writer import write_tick, write_expected, write_hoga, write_vi, write_heartbeat
from token_loader import load_token

KST = timezone(timedelta(hours=9))

# 장 운영 시간대 (KST)
_MARKET_OPEN_HOUR   = (7, 30)   # 07:30 – 장전 구독 시작
_MARKET_CLOSE_HOUR  = (15, 35)  # 15:35 – 장 완전 종료
_WEEKDAYS           = {0, 1, 2, 3, 4}  # Mon=0 … Fri=4


def _is_market_hours() -> bool:
    """현재 KST 시각이 장 운영 시간 (평일 07:30~15:35) 인지 확인"""
    now = datetime.now(KST)
    if now.weekday() not in _WEEKDAYS:
        return False
    t = dtime(now.hour, now.minute, now.second)
    open_t  = dtime(*_MARKET_OPEN_HOUR)
    close_t = dtime(*_MARKET_CLOSE_HOUR)
    return open_t <= t < close_t


async def _wait_for_market_open():
    """
    장 운영 시간이 아닌 경우 다음 개장 시각까지 대기.
    평일 07:30 KST, 주말이면 다음 월요일 07:30 까지 대기.
    """
    now = datetime.now(KST)
    wd  = now.weekday()
    t   = dtime(now.hour, now.minute, now.second)

    open_t  = dtime(*_MARKET_OPEN_HOUR)
    close_t = dtime(*_MARKET_CLOSE_HOUR)

    # 평일 장 시간 내이면 즉시 반환
    if wd in _WEEKDAYS and open_t <= t < close_t:
        return

    # 다음 개장 시각 계산
    target = now.replace(
        hour=_MARKET_OPEN_HOUR[0], minute=_MARKET_OPEN_HOUR[1],
        second=0, microsecond=0
    )
    if wd in _WEEKDAYS and t < open_t:
        # 오늘 아직 개장 전
        pass
    else:
        # 오늘 장 종료 또는 주말 → 다음 평일 07:30
        days_ahead = 1
        if wd >= 4:  # 금요일(4) 이후 → 다음 월요일
            days_ahead = 7 - wd  # 토=2, 일=1
        target += timedelta(days=days_ahead)

    wait_sec = (target - now).total_seconds()
    logger.info(
        "[WS] 장 종료 시간 외 (현재 KST %02d:%02d, 평일 %02d:%02d 개장) – %.0f초 대기",
        now.hour, now.minute, *_MARKET_OPEN_HOUR, wait_sec
    )
    # 최대 60초 단위로 체크하며 대기 (외부에서 취소 가능)
    while wait_sec > 0:
        await asyncio.sleep(min(60, wait_sec))
        wait_sec = (_wait_next_open() - datetime.now(KST)).total_seconds()
        if wait_sec <= 0:
            break


def _wait_next_open() -> datetime:
    """다음 장 개장 datetime 반환"""
    now = datetime.now(KST)
    wd  = now.weekday()
    t   = dtime(now.hour, now.minute, now.second)
    open_t = dtime(*_MARKET_OPEN_HOUR)
    target = now.replace(
        hour=_MARKET_OPEN_HOUR[0], minute=_MARKET_OPEN_HOUR[1],
        second=0, microsecond=0
    )
    if wd in _WEEKDAYS and t < open_t:
        return target
    days_ahead = 1
    if wd >= 4:
        days_ahead = 7 - wd
    return target + timedelta(days=days_ahead)

logger = logging.getLogger(__name__)

WS_PATH              = "/api/dostk/websocket"
MAX_RECONNECTS       = 10
BASE_RECONNECT_MS    = 3000   # ms
WATCHLIST_POLL_SEC   = 30     # candidates:watchlist 폴링 간격
HEARTBEAT_INTERVAL   = 10     # 초


async def _get_candidates(rdb, market: str = "001") -> list[str]:
    """Redis 후보 종목 캐시 읽기 (Java CandidateService 가 저장)"""
    key = f"candidates:{market}"
    items = await rdb.lrange(key, 0, 199)
    return items or []


async def _subscribe_all(ws, rdb):
    """장 구분에 따른 전체 구독 설정"""
    kospi  = await _get_candidates(rdb, "001")
    kosdaq = await _get_candidates(rdb, "101")
    all_cands = list(dict.fromkeys(kospi + kosdaq))[:200]
    top100 = all_cands[:100]

    groups = [
        ("5", "0B", all_cands),    # 체결 – 전체 후보
        ("6", "0H", top100),       # 예상체결 – 상위 100
        ("7", "1h", [""]),         # VI – 전종목
        ("8", "0D", top100),       # 호가잔량 – 상위 100
    ]

    for grp_no, ttype, items in groups:
        if not items:
            continue
        # 100개 단위 배치 구독
        for i in range(0, len(items), 100):
            batch = items[i:i + 100]
            payload = {
                "trnm":    "REG",
                "grp_no":  grp_no,
                "refresh": "1",
                "data":    [{"item": it, "type": ttype} for it in batch],
            }
            await ws.send(json.dumps(payload))
            logger.info("[WS] 구독 grp=%s type=%s %d개", grp_no, ttype, len(batch))
            await asyncio.sleep(0.3)


async def _handle_message(msg_str: str, ws, rdb):
    """수신 메시지 파싱 및 Redis 저장 분기"""
    try:
        msg   = json.loads(msg_str)
        trnm  = msg.get("trnm", "")

        if trnm == "PING":
            await ws.send(json.dumps({"trnm": "PONG"}))
            return

        data   = msg.get("data") or {}
        stk_cd = msg.get("item") or (data.get("stk_cd", "") if isinstance(data, dict) else "")

        match trnm:
            case "0B": await write_tick(rdb, data, stk_cd)
            case "0H": await write_expected(rdb, data, stk_cd)
            case "0D": await write_hoga(rdb, data, stk_cd)
            case "1h": await write_vi(rdb, data, stk_cd)
            case _:    pass

    except json.JSONDecodeError:
        logger.debug("[WS] JSON 파싱 실패: %.100s", msg_str)
    except Exception as e:
        logger.warning("[WS] 메시지 처리 오류: %s", e)


async def _watchlist_poller(ws, rdb, subscribed_set: set):
    """
    candidates:watchlist (Redis Set) 을 30초마다 폴링하여
    신규 종목은 REG, 제거 종목은 UNREG 전송.
    """
    while True:
        try:
            await asyncio.sleep(WATCHLIST_POLL_SEC)
            watchlist = await rdb.smembers("candidates:watchlist")
            if not watchlist:
                continue

            new_codes     = watchlist - subscribed_set
            removed_codes = subscribed_set - watchlist

            for code in new_codes:
                for grp_no, ttype in [("5", "0B"), ("6", "0H"), ("8", "0D")]:
                    payload = {"trnm": "REG", "grp_no": grp_no, "refresh": "0",
                               "data": [{"item": code, "type": ttype}]}
                    await ws.send(json.dumps(payload))
                subscribed_set.add(code)
                logger.info("[WS] 동적 구독 추가 [%s]", code)

            for code in removed_codes:
                for grp_no, ttype in [("5", "0B"), ("6", "0H"), ("8", "0D")]:
                    payload = {"trnm": "UNREG", "grp_no": grp_no,
                               "data": [{"item": code, "type": ttype}]}
                    await ws.send(json.dumps(payload))
                subscribed_set.discard(code)
                logger.info("[WS] 동적 구독 해제 [%s]", code)

        except Exception as e:
            logger.warning("[WS] watchlist 폴러 오류: %s", e)


async def _heartbeat_writer(rdb):
    """10초마다 ws:heartbeat 갱신 (TTL 30s)"""
    while True:
        try:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            await write_heartbeat(rdb, {
                "grp5": "ok", "grp6": "ok", "grp7": "ok", "grp8": "ok"
            })
        except Exception as e:
            logger.debug("[WS] heartbeat 오류: %s", e)


async def run_ws_loop(rdb):
    """WebSocket 메인 루프 – 장 운영 시간 감지 + 지수 백오프 재연결 포함"""
    # 실전/모의 환경 분기
    kiwoom_mode = os.getenv("KIWOOM_MODE", "mock").lower()
    if kiwoom_mode == "real":
        ws_base_url = os.getenv("KIWOOM_WS_URL", "wss://api.kiwoom.com:10000")
    else:
        ws_base_url = os.getenv("KIWOOM_WS_URL", "wss://mockapi.kiwoom.com:10000")
    url = ws_base_url + WS_PATH

    reconnect_count = 0
    delay_sec       = BASE_RECONNECT_MS / 1000

    # 연결 성공 후 최소 유지 시간 – 이 미만이면 연결이 즉시 종료된 것으로 간주
    MIN_CONNECTED_SEC = 30

    while True:
        # ── 장 운영 시간 외이면 개장까지 대기 ──────────────────────
        await _wait_for_market_open()

        connect_time = None
        try:
            token = await load_token(rdb)
            headers = {"authorization": f"Bearer {token}"}

            logger.info("[WS] 연결 시도 #%d → %s", reconnect_count + 1, url)

            import time as _time
            connect_time = _time.monotonic()

            async with websockets.connect(
                    url,
                    additional_headers=headers,
                    ping_interval=30,
                    ping_timeout=10,
                    open_timeout=15,
            ) as ws:
                logger.info("[WS] 연결 성공")
                set_ws_connected(True)

                # 연결 직후 즉시 heartbeat 기록 (TTL 소멸 방지)
                await write_heartbeat(rdb, {
                    "grp5": "ok", "grp6": "ok", "grp7": "ok", "grp8": "ok"
                })

                await _subscribe_all(ws, rdb)

                # 초기 구독 후보를 subscribed_set 에 등록 (watchlist poller 가 중복 UNREG 방지)
                kospi  = await _get_candidates(rdb, "001")
                kosdaq = await _get_candidates(rdb, "101")
                subscribed_set: set = set(dict.fromkeys(kospi + kosdaq))

                # 동적 구독 watchlist 폴러 + heartbeat 시작
                watchlist_task  = asyncio.create_task(_watchlist_poller(ws, rdb, subscribed_set))
                heartbeat_task  = asyncio.create_task(_heartbeat_writer(rdb))

                try:
                    async for message in ws:
                        await _handle_message(message, ws, rdb)
                finally:
                    watchlist_task.cancel()
                    heartbeat_task.cancel()
                    set_ws_connected(False)

            # 연결이 최소 유지 시간 이상 유지된 경우에만 카운터 리셋
            elapsed = _time.monotonic() - connect_time
            if elapsed >= MIN_CONNECTED_SEC:
                reconnect_count = 0
                delay_sec       = BASE_RECONNECT_MS / 1000

        except ConnectionClosed as e:
            logger.warning("[WS] 연결 끊김: %s", e)
            set_ws_connected(False)
        except Exception as e:
            logger.error("[WS] 오류: %s", e)
            set_ws_connected(False)

        # 장 종료 후 서버가 닫은 경우 재시도 대신 개장 대기
        if not _is_market_hours():
            logger.info("[WS] 장 종료 또는 비운영 시간 – 개장 대기 모드로 전환")
            reconnect_count = 0
            delay_sec       = BASE_RECONNECT_MS / 1000
            continue

        reconnect_count += 1
        if reconnect_count > MAX_RECONNECTS:
            logger.critical("[WS] 최대 재연결 횟수 %d 초과 – 프로세스 종료", MAX_RECONNECTS)
            sys.exit(1)

        logger.info("[WS] %.1f초 후 재연결 (%d번째)", delay_sec, reconnect_count)
        await asyncio.sleep(delay_sec)
        delay_sec = min(delay_sec * 2, 60)
