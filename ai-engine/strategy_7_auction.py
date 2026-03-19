"""
전술 7: 장전 예상체결 + 호가잔량 비율 (동시호가 특화)
타이밍: 8:30~9:00 (동시호가 집중)
진입 조건:

0H WebSocket: 예상체결가가 전일 종가 대비 +2% ~ +10% (과도한 갭 제외)
0D WebSocket: 매수/매도 호가잔량 비율 ≥ 2.0 (매수 압도적 우위)
ka10033 거래량 순위: 예상거래량 상위 50위 이내
전일 봉 패턴: 장대양봉 OR 상한가 근접 (3% 이내)
시가총액 ≥ 500억 (소형주 변동성 제거)
"""
from idlelib.multicall import r

import httpx
import os
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL")


async def fetch_volume_rank(token: str, market: str) -> list:
    """ka10033 거래량순위요청 - 예상거래량 상위"""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/rkinfo",
            headers={"api-id": "ka10033", "authorization": f"Bearer {token}",
                     "Content-Type": "application/json;charset=UTF-8"},
            json={
                "mrkt_tp": market,
                "trde_qty_tp": "10",
                "stk_cnd": "1",
                "updown_incls": "0",
                "crd_cnd": "0",
                "stex_tp": "1"
            }
        )
        return resp.json().get("trde_qty_upper", [])

async def scan_auction_signal(token: str, market: str = "000") -> list:
    """장전 동시호가 종목 선별"""
    vol_rank = await fetch_volume_rank(token, market)
    vol_set = {x["stk_cd"]: int(x.get("rank", 999))
               for x in vol_rank[:50]}

    results = []

    for stk_cd, rank in vol_set.items():
        # Redis에서 WebSocket 데이터 조회
        exp = r.hgetall(f"ws:expected:{stk_cd}")
        bid = r.hgetall(f"ws:hoga:{stk_cd}")

        if not exp or not bid:
            continue

        prev_close = float(exp.get("pred_pre_pric", 0))
        exp_price = float(exp.get("exp_cntr_pric", 0))

        if prev_close <= 0 or exp_price <= 0:
            continue

        gap_pct = (exp_price - prev_close) / prev_close * 100

        if not (2.0 <= gap_pct <= 10.0):
            continue

        total_bid = float(bid.get("total_bid_qty", 0))
        total_ask = float(bid.get("total_ask_qty", 1))
        bid_ratio = total_bid / total_ask

        if bid_ratio < 2.0:
            continue

        results.append({
            "stk_cd": stk_cd,
            "strategy": "S7_AUCTION",
            "gap_pct": round(gap_pct, 2),
            "bid_ratio": round(bid_ratio, 2),
            "vol_rank": rank,
            "entry_type": "시초가_시장가",
            "target_pct": min(gap_pct * 0.8, 5.0),
            "stop_pct": -2.0,
        })

    return sorted(results, key=lambda x: (-x["bid_ratio"], x["vol_rank"]))[:5]
