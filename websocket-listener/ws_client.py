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

import websockets
from websockets.exceptions import ConnectionClosed

from redis_writer import write_tick, write_expected, write_hoga, write_vi, write_heartbeat
from token_loader import load_token

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
                for grp_no, ttype in [("5", "0B"), ("6", "0D"), ("7", "0H")]:
                    payload = {"trnm": "REG", "grp_no": grp_no, "refresh": "0",
                               "data": [{"item": code, "type": ttype}]}
                    await ws.send(json.dumps(payload))
                subscribed_set.add(code)
                logger.info("[WS] 동적 구독 추가 [%s]", code)

            for code in removed_codes:
                for grp_no, ttype in [("5", "0B"), ("6", "0D"), ("7", "0H")]:
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
    """WebSocket 메인 루프 – 지수 백오프 재연결 포함"""
    # 실전/모의 환경 분기
    kiwoom_mode = os.getenv("KIWOOM_MODE", "mock").lower()
    if kiwoom_mode == "real":
        ws_base_url = os.getenv("KIWOOM_WS_URL", "wss://api.kiwoom.com:10000")
    else:
        ws_base_url = os.getenv("KIWOOM_WS_URL", "wss://mockapi.kiwoom.com:10000")
    url = ws_base_url + WS_PATH

    reconnect_count = 0
    delay_sec       = BASE_RECONNECT_MS / 1000

    while True:
        try:
            token = await load_token(rdb)
            headers = {"authorization": f"Bearer {token}"}

            logger.info("[WS] 연결 시도 #%d → %s", reconnect_count + 1, url)

            async with websockets.connect(
                    url,
                    additional_headers=headers,
                    ping_interval=30,
                    ping_timeout=10,
                    open_timeout=15,
            ) as ws:
                reconnect_count = 0
                delay_sec       = BASE_RECONNECT_MS / 1000
                logger.info("[WS] 연결 성공")

                await _subscribe_all(ws, rdb)

                # 동적 구독 watchlist 폴러 + heartbeat 시작
                subscribed_set: set = set()
                watchlist_task  = asyncio.create_task(_watchlist_poller(ws, rdb, subscribed_set))
                heartbeat_task  = asyncio.create_task(_heartbeat_writer(rdb))

                try:
                    async for message in ws:
                        await _handle_message(message, ws, rdb)
                finally:
                    watchlist_task.cancel()
                    heartbeat_task.cancel()

        except ConnectionClosed as e:
            logger.warning("[WS] 연결 끊김: %s", e)
        except Exception as e:
            logger.error("[WS] 오류: %s", e)

        reconnect_count += 1
        if reconnect_count > MAX_RECONNECTS:
            logger.critical("[WS] 최대 재연결 횟수 %d 초과 – 프로세스 종료", MAX_RECONNECTS)
            sys.exit(1)

        logger.info("[WS] %.1f초 후 재연결 (%d번째)", delay_sec, reconnect_count)
        await asyncio.sleep(delay_sec)
        delay_sec = min(delay_sec * 2, 60)
