"""
ws_client.py
키움 WebSocket 연결·구독·재연결을 담당하는 모듈.

그룹 할당 (Java GRP 1~4 와 충돌 방지):
  GRP 5  0B 체결      – 후보 종목
  GRP 6  0H 예상체결  – 장전용
  GRP 7  1h VI발동해제 – 전체
  GRP 8  0D 호가잔량  – 상위 100

환경변수:
  BYPASS_MARKET_HOURS=true  : 장 시간 외에도 연결 시도 (모의 테스트용)
                              지수 백오프 적용, 최대 MAX_RECONNECTS 회 후 5분 대기 반복
  KIWOOM_MODE=real|mock     : real → wss://api.kiwoom.com, mock → wss://mockapi.kiwoom.com
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

# 장 시간 외 재연결 허용 여부 (모의 테스트용)
BYPASS_MARKET_HOURS = os.getenv("BYPASS_MARKET_HOURS", "false").lower() in ("1", "true", "yes")


def _now_kst() -> datetime:
    """현재 KST 시각 반환 (timezone-aware)"""
    return datetime.now(KST)


def _is_market_hours() -> bool:
    """현재 KST 시각이 장 운영 시간 (평일 07:30~15:35) 인지 확인"""
    now = _now_kst()
    if now.weekday() not in _WEEKDAYS:
        return False
    t = dtime(now.hour, now.minute, now.second)
    return dtime(*_MARKET_OPEN_HOUR) <= t < dtime(*_MARKET_CLOSE_HOUR)


def _next_market_open() -> datetime:
    """다음 장 개장 datetime (KST, timezone-aware) 반환"""
    now = _now_kst()
    wd  = now.weekday()
    t   = dtime(now.hour, now.minute, now.second)
    open_t = dtime(*_MARKET_OPEN_HOUR)

    # 오늘 개장 전이면 오늘 07:30
    if wd in _WEEKDAYS and t < open_t:
        return now.replace(hour=open_t.hour, minute=open_t.minute,
                           second=0, microsecond=0)

    # 오늘 이미 개장했거나 주말 → 다음 평일 07:30
    days_ahead = 1
    if wd >= 4:          # 금=4 → 토=1일 후(6 아님), 일=2일 후
        days_ahead = 7 - wd
    base = now.replace(hour=open_t.hour, minute=open_t.minute,
                       second=0, microsecond=0)
    return base + timedelta(days=days_ahead)


async def _wait_for_market_open():
    """
    장 운영 시간이 아닌 경우 다음 개장 시각까지 대기.
    60초 단위로 깨어나 재확인 (외부에서 취소 가능).
    """
    while True:
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
WATCHLIST_POLL_SEC   = 30     # candidates:watchlist 폴링 간격
HEARTBEAT_INTERVAL   = 10     # 초
MIN_CONNECTED_SEC    = 30     # 이 미만으로 연결이 유지되면 "즉시 종료" 로 간주


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


async def _ws_ping_sender(ws):
    """30초마다 애플리케이션 레벨 PING 전송 (키움 프로토콜 keepalive)"""
    while True:
        try:
            await asyncio.sleep(30)
            await ws.send('{"trnm":"PING"}')
            logger.debug("[WS] PING 전송")
        except Exception as e:
            logger.debug("[WS] PING 전송 오류: %s", e)
            break


async def _run_message_loop(ws, rdb):
    """메시지 수신 루프 – 서버 PING 포함 모든 메시지 즉시 처리"""
    async for message in ws:
        await _handle_message(message, ws, rdb)
    logger.info("[WS] 서버 정상 종료 (clean close)")


async def run_ws_loop(rdb):
    """
    WebSocket 메인 루프 – 장 운영 시간 감지 + 지수 백오프 재연결 포함.

    BYPASS_MARKET_HOURS=true 일 때:
      장 시간과 무관하게 연결 시도, 지수 백오프 적용 (최대 5분).
      MAX_RECONNECTS 초과 시 5분 대기 후 카운터 리셋하여 무한 재시도.
    BYPASS_MARKET_HOURS=false (기본):
      장 시간 외 연결 종료 시 _wait_for_market_open() 으로 개장까지 대기.
    """
    # 실전/모의 환경 분기
    kiwoom_mode = os.getenv("KIWOOM_MODE", "mock").lower()
    if kiwoom_mode == "real":
        ws_base_url = os.getenv("KIWOOM_WS_URL", "wss://api.kiwoom.com:10000")
    else:
        ws_base_url = os.getenv("KIWOOM_WS_URL", "wss://mockapi.kiwoom.com:10000")
    url = ws_base_url + WS_PATH

    if BYPASS_MARKET_HOURS:
        logger.warning(
            "[WS] ⚠️  BYPASS_MARKET_HOURS=true – 장 시간 외 연결 허용 (모의 테스트 모드)"
        )

    reconnect_count = 0
    delay_sec       = BASE_RECONNECT_MS / 1000

    while True:
        # ── 장 운영 시간 외이면 개장까지 대기 ──────────────────────
        if not BYPASS_MARKET_HOURS:
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
        try:
            token = await load_token(rdb)
            headers = {"authorization": f"Bearer {token}"}

            logger.info("[WS] 연결 시도 #%d → %s", reconnect_count + 1, url)

            import time as _time
            connect_time = _time.monotonic()

            async with websockets.connect(
                    url,
                    additional_headers=headers,
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
                    return_code    = str(login_resp.get("return_code", login_resp.get("returnCode", "-1")))
                    if return_code != "0":
                        logger.error("[WS] LOGIN 실패 – return_code=%s body=%s", return_code, login_resp)
                        raise ConnectionError(f"WS LOGIN 실패 (return_code={return_code})")
                    logger.info("[WS] LOGIN 성공 – return_code=0")
                except asyncio.TimeoutError:
                    logger.error("[WS] LOGIN 응답 타임아웃 (10초)")
                    raise ConnectionError("WS LOGIN 응답 없음")
                except json.JSONDecodeError as e:
                    logger.error("[WS] LOGIN 응답 JSON 파싱 오류: %s", e)
                    raise

                # 연결 직후 즉시 heartbeat 기록 (TTL 소멸 방지)
                await write_heartbeat(rdb, {
                    "grp5": "ok", "grp6": "ok", "grp7": "ok", "grp8": "ok"
                })

                # ── 메시지 루프를 구독보다 먼저 시작 ──────────────────────
                # 구독(REG) 도중 서버가 PING을 보내도 즉시 PONG 응답 가능
                message_task = asyncio.create_task(_run_message_loop(ws, rdb))

                await _subscribe_all(ws, rdb)

                # 초기 구독 후보를 subscribed_set 에 등록 (watchlist poller 가 중복 UNREG 방지)
                kospi  = await _get_candidates(rdb, "001")
                kosdaq = await _get_candidates(rdb, "101")
                subscribed_set: set = set(dict.fromkeys(kospi + kosdaq))

                # 동적 구독 watchlist 폴러 + heartbeat + 앱레벨 PING 시작
                watchlist_task  = asyncio.create_task(_watchlist_poller(ws, rdb, subscribed_set))
                heartbeat_task  = asyncio.create_task(_heartbeat_writer(rdb))
                ws_ping_task    = asyncio.create_task(_ws_ping_sender(ws))

                try:
                    await message_task  # 서버가 연결을 닫을 때까지 대기
                finally:
                    watchlist_task.cancel()
                    heartbeat_task.cancel()
                    ws_ping_task.cancel()
                    message_task.cancel()
                    set_ws_connected(False)

            # 연결이 최소 유지 시간 이상 유지된 경우에만 카운터 리셋
            elapsed = _time.monotonic() - connect_time
            if elapsed >= MIN_CONNECTED_SEC:
                reconnect_count = 0
                delay_sec       = BASE_RECONNECT_MS / 1000
                logger.info("[WS] 연결 %.1f초 유지 후 종료 – 카운터 리셋", elapsed)

        except ConnectionClosed as e:
            logger.warning("[WS] 연결 끊김 (ConnectionClosed): %s", e)
            set_ws_connected(False)
        except OSError as e:
            logger.error("[WS] 네트워크 오류: %s", e)
            set_ws_connected(False)
        except Exception as e:
            logger.error("[WS] 예상치 못한 오류: %s", e)
            set_ws_connected(False)

        # ── 재연결 전 시장 시간 판단 ──────────────────────────────
        if not BYPASS_MARKET_HOURS and not _is_market_hours():
            logger.info("[WS] 장 종료 / 비운영 시간 감지 – 개장 대기 모드로 전환")
            reconnect_count = 0
            delay_sec       = BASE_RECONNECT_MS / 1000
            # 다음 루프 상단의 _wait_for_market_open() 이 처리하므로 continue
            continue

        # ── 지수 백오프 재연결 ────────────────────────────────────
        reconnect_count += 1
        if reconnect_count > MAX_RECONNECTS:
            # bypass 모드 또는 장 운영 중: 프로세스 종료 대신 5분 대기 후 재시도
            if BYPASS_MARKET_HOURS or _is_market_hours():
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
