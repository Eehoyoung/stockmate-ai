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

from http_utils import fetch_cntr_strength

# NOTE: Python 전술 스캐너 경로 (ENABLE_STRATEGY_SCANNER=true 시 활성화).
# 메인 전술 실행은 api-orchestrator/StrategyService.java에서 이루어집니다.
# rdb (redis.asyncio.Redis) 는 strategy_runner.py 에서 전달받습니다.

logger = logging.getLogger(__name__)
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://mockapi.kiwoom.com")

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

    # 현재가 조회 (Redis 실시간 체결 캐시, 비동기)
    cur = await rdb.hgetall(f"ws:tick:{stk_cd}")
    if not cur:
        return None

    cur_price = float(cur.get("cur_prc", 0))
    pullback_pct = (cur_price - vi_price) / vi_price * 100

    # 눌림 범위 체크: -1% ~ -3%
    if not (-3.0 <= pullback_pct <= -1.0):
        return None

    strength = await fetch_cntr_strength(token, stk_cd)
    if strength < 110:
        return None

    bid_qty = float(cur.get("total_bid_qty", 1))
    ask_qty = float(cur.get("total_ask_qty", 1))
    bid_ratio = bid_qty / ask_qty if ask_qty > 0 else 0

    if bid_ratio < 1.3:
        return None

    return {
        "stk_cd": stk_cd,
        "strategy": "S2_VI_PULLBACK",
        "vi_price": vi_price,
        "cur_price": cur_price,
        "pullback_pct": round(pullback_pct, 2),
        "cntr_strength": round(strength, 1),
        "bid_ratio": round(bid_ratio, 2),
        "entry_type": "지정가_눌림목",
        "target_pct": 3.0,
        "stop_pct": -2.0,
    }
