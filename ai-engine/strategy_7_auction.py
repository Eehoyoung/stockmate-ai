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
import os
import logging
import httpx

logger = logging.getLogger(__name__)

# NOTE: Python 전술 스캐너 경로 (ENABLE_STRATEGY_SCANNER=true 시 활성화).
# 메인 전술 실행은 api-orchestrator/StrategyService.java에서 이루어집니다.
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://mockapi.kiwoom.com")


async def fetch_gap_rank(token: str, market: str) -> list:
    """ka10029 예상체결등락률상위 – 갭 2~10% 후보"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/rkinfo",
                headers={"api-id": "ka10029", "authorization": f"Bearer {token}",
                         "Content-Type": "application/json;charset=UTF-8"},
                json={"mrkt_tp": market, "sort_tp": "1", "trde_qty_cnd": "10",
                      "stk_cnd": "1", "crd_cnd": "0", "pric_cnd": "8", "stex_tp": "1"},
            )
            items = resp.json().get("exp_cntr_flu_rt_upper", [])
            result = {}
            for i, item in enumerate(items[:50]):
                try:
                    flu_rt = float(str(item.get("flu_rt", "0")).replace("+", "").replace(",", ""))
                    if 2.0 <= flu_rt <= 10.0:
                        result[item.get("stk_cd")] = i + 1
                except Exception:
                    pass
            return result
    except Exception as e:
        logger.warning("[S7] ka10029 호출 실패: %s", e)
        return {}


async def scan_auction_signal(token: str, market: str = "000", rdb=None) -> list:
    """장전 동시호가 종목 선별 (ka10029 기반, 비동기 Redis)"""
    vol_set = await fetch_gap_rank(token, market)

    results = []

    for stk_cd, rank in vol_set.items():
        # Redis에서 WebSocket 데이터 조회 (비동기)
        try:
            exp = await rdb.hgetall(f"ws:expected:{stk_cd}") if rdb else {}
            bid = await rdb.hgetall(f"ws:hoga:{stk_cd}") if rdb else {}
        except Exception:
            exp, bid = {}, {}

        if not exp or not bid:
            continue

        prev_close = float(exp.get("pred_pre_pric", 0))
        exp_price = float(exp.get("exp_cntr_pric", 0))

        if prev_close <= 0 or exp_price <= 0:
            continue

        gap_pct = (exp_price - prev_close) / prev_close * 100

        if not (2.0 <= gap_pct <= 10.0):
            continue

        total_bid = float(bid.get("total_buy_bid_req", 0) or 0)
        total_ask = float(bid.get("total_sel_bid_req", 1) or 1)
        bid_ratio = total_bid / total_ask

        if bid_ratio < 1.5:   # 2.0 → 1.5 유연화 (갭 자체가 수급 필터 역할)
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
