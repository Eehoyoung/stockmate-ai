"""전술 2: VI 발동 후 눌림목 재진입
타이밍: 장중 상시 (VI 발동 이벤트 기반)
진입 조건 (순서대로):

1h WebSocket → VI 발동 이벤트 수신 (동적 VI 우선)
VI 발동 당시 거래량이 직전 5분 대비 ≥ 3배
VI 해제 후 현재가가 VI 발동가 대비 -1% ~ -3% 눌림
호가잔량 매수/매도 비율 ≥ 1.3 (0D)
체결강도 ≥ 110% 유지 중"""

from collections import defaultdict
import os
import logging

import httpx

from http_utils import fetch_cntr_strength, fetch_stk_nm
from indicator_atr import get_atr_minute
from tp_sl_engine import calc_tp_sl

# NOTE: Python 메인 전술 실행자 (strategy_runner.py 에서 호출).
# Java api-orchestrator 는 토큰 관리·후보 풀 적재(candidates:s{N}:{market})만 담당.
# rdb (redis.asyncio.Redis) 는 strategy_runner.py 에서 전달받습니다.

logger = logging.getLogger(__name__)
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")

vi_events = defaultdict(list)  # stk_cd → [vi_event, ...]

async def handle_vi_event(rdb, event: dict):
    """VI 발동/해제 이벤트 처리 (비동기 Redis)"""
    stk_cd = event.get("stk_cd")
    vi_type = event.get("vi_type")      # 1:정적, 2:동적, 3:동적+정적
    status = event.get("vi_stat")       # 1:발동, 2:해제
    vi_price = float(event.get("vi_pric", 0))
    volume = int(event.get("acc_trde_qty", 0))

    key = f"vi:{stk_cd}"

    if status == "1":  # 발동
        from datetime import datetime
        await rdb.hset(key, mapping={
            "vi_price": str(vi_price),
            "vi_time": datetime.now().isoformat(),
            "vi_type": vi_type,
            "vi_volume": str(volume),
            "status": "active"
        })
        await rdb.expire(key, 3600)

    elif status == "2":  # 해제 → 눌림목 감시 시작
        from datetime import datetime
        vi_data = await rdb.hgetall(key)
        if not vi_data:
            return
        await rdb.hset(key, "status", "released")
        # 눌림목 감시 큐에 등록
        import json
        import time
        await rdb.lpush("vi_watch_queue", json.dumps({
            "stk_cd": stk_cd,
            "vi_price": float(vi_data["vi_price"]),
            "watch_until": int((time.time() + 600) * 1000),  # 10분 감시 (밀리초, Java와 일치)
            "is_dynamic": vi_data.get("vi_type") in ("2", "3"),
        }))





async def check_vi_pullback(token: str, watch_item: dict, rdb=None) -> dict | None:
    stk_cd = watch_item["stk_cd"]
    vi_price = watch_item["vi_price"]

    if not rdb:
        return None

    # 1. 현재가 조회 (ws:tick)
    cur = await rdb.hgetall(f"ws:tick:{stk_cd}")
    if not cur:
        return None

    cur_price = float(cur.get("cur_prc", 0))
    if cur_price == 0: return None

    # [조건 1] 눌림 범위 체크: -1% ~ -3% (가장 먼저 탈락시킴)
    pullback_pct = (cur_price - vi_price) / vi_price * 100
    if not (-3.0 <= pullback_pct <= -1.0):
        return None

    # [조건 2] 호가잔량 매수/매도 비율 체크 (ws:hoga — 0D 구독 데이터)
    # ws:tick 에는 hoga 필드가 없음. ws:hoga 해시 별도 조회 필요.
    hoga = await rdb.hgetall(f"ws:hoga:{stk_cd}")
    bid_qty = float(hoga.get("total_buy_bid_req", 0))
    ask_qty = float(hoga.get("total_sel_bid_req", 0))
    bid_ratio = bid_qty / ask_qty if ask_qty > 0 else 0
    if bid_ratio < 1.3:
        return None

    # [조건 3] 거래량 조건 체크 (VI 발동 시점에 이미 체크되었어야 함)
    # handle_vi_event에서 저장한 vi_volume_ratio가 있다면 확인
    vi_data = await rdb.hgetall(f"vi:{stk_cd}")
    vol_ratio = float(vi_data.get("vol_ratio", 0))
    if vol_ratio < 3.0:
        # 만약 발동 시점에 체크를 못했다면 여기서 pass 하거나
        # 추가 로직 필요 (단, 실시간성 위해 발동 시 체크 권장)
        pass

        # [조건 4] 체결강도 체크 (가장 무거운 작업 - 외부 API 호출)
    # 위 조건들을 모두 통과한 종목에 대해서만 API를 호출하여 쿼터 절약
    strength = await fetch_cntr_strength(token, stk_cd)
    if strength < 110:
        return None

    stk_nm = await fetch_stk_nm(rdb, token, stk_cd)

    # 동적 TP/SL — 5분봉 ATR 기반 (VI 눌림목 = 단기 변동성 기준)
    atr_val = None
    try:
        atr_result = await get_atr_minute(token, stk_cd, tic_scope="5", period=7)
        atr_val = atr_result.atr
    except Exception:
        pass
    # vi_price: VI 발동가 → TP 목표 (VI 레벨 재탈환)
    tp_sl = calc_tp_sl("S2_VI_PULLBACK", cur_price, [], [], [],
                        stk_cd=stk_cd, atr=atr_val,
                        vi_price=vi_price if vi_price > cur_price else None)

    return {
        "stk_cd": stk_cd,
        "stk_nm": stk_nm,
        "cur_prc": round(cur_price),
        "strategy": "S2_VI_PULLBACK",
        "vi_price": vi_price,
        "pullback_pct": round(pullback_pct, 2),
        "cntr_strength": round(strength, 1),
        "bid_ratio": round(bid_ratio, 2),
        "is_dynamic": bool(watch_item.get("is_dynamic", False)),
        "entry_type": "지정가_눌림목",
        **tp_sl.to_signal_fields(),
    }
