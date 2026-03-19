"""전술 2: VI 발동 후 눌림목 재진입
타이밍: 장중 상시 (VI 발동 이벤트 기반)
진입 조건 (순서대로):

1h WebSocket → VI 발동 이벤트 수신 (동적 VI 우선)
VI 발동 당시 거래량이 직전 5분 대비 ≥ 3배
VI 해제 후 현재가가 VI 발동가 대비 -1% ~ -3% 눌림
호가잔량 매수/매도 비율 ≥ 1.3 (0D)
체결강도 ≥ 110% 유지 중"""

from collections import defaultdict
from idlelib.multicall import r
import os

import httpx

KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL")

vi_events = defaultdict(list)  # stk_cd → [vi_event, ...]

async def handle_vi_event(event: dict):
    """Java WebSocket → 1h VI발동/해제 이벤트 처리"""
    stk_cd = event.get("stk_cd")
    vi_type = event.get("vi_type")      # 1:정적, 2:동적, 3:동적+정적
    status = event.get("vi_stat")       # 1:발동, 2:해제
    vi_price = float(event.get("vi_pric", 0))
    volume = int(event.get("acc_trde_qty", 0))

    key = f"vi:{stk_cd}"

    if status == "1":  # 발동
        from datetime import datetime
        r.hset(key, mapping={
            "vi_price": vi_price,
            "vi_time": datetime.now().isoformat(),
            "vi_type": vi_type,
            "vi_volume": volume,
            "status": "active"
        })
        r.expire(key, 3600)

    elif status == "2":  # 해제 → 눌림목 감시 시작
        from datetime import datetime
        vi_data = r.hgetall(key)
        if not vi_data:
            return
        r.hset(key, "status", "released")
        # 눌림목 감시 큐에 등록
        import json
        r.lpush("vi_watch_queue", json.dumps({
            "stk_cd": stk_cd,
            "vi_price": float(vi_data["vi_price"]),
            "watch_until": (datetime.now().timestamp() + 600)  # 10분 감시
        }))


async def fetch_cntr_strength(token: str, stk_cd: str) -> float:
    """
    체결강도 조회 (ka10003 체결정보요청)
    - 종목코드(stk_cd)를 입력받아 최근 체결정보의 cntr_str 반환
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/stkinfo",
            headers={
                "api-id": "ka10003",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8"
            },
            json={"stk_cd": stk_cd}
        )

    data = resp.json()
    cntr_infr = data.get("cntr_infr", [])
    if not cntr_infr:
        return 0.0

    # 가장 최근 체결정보의 cntr_str 사용
    latest = cntr_infr[0]
    strength = latest.get("cntr_str", "0")
    try:
        return float(strength)
    except ValueError:
        return 0.0



async def check_vi_pullback(token: str, watch_item: dict) -> dict | None:
    stk_cd = watch_item["stk_cd"]
    vi_price = watch_item["vi_price"]

    # 현재가 조회 (Redis 실시간 체결 캐시)
    cur = r.hgetall(f"ws:tick:{stk_cd}")
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
