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
import asyncio
import httpx
import logging
import os
from http_utils import validate_kiwoom_response, fetch_stk_nm, kiwoom_client
from indicator_atr import get_atr_minute
from tp_sl_engine import calc_tp_sl

logger = logging.getLogger(__name__)
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")

def clean_num(val) -> float:
    if not val: return 0.0
    # '+' 부호만 제거, '-'는 음수 부호이므로 보존
    return float(str(val).replace("+", "").replace(",", ""))

async def fetch_gap_rank(token: str, market: str) -> dict:
    """ka10029 예상체결등락률상위 - 연속조회로 전체 후보 수집"""
    result = {}
    next_key = ""

    async with kiwoom_client() as client:
        while True:
            headers = {
                "api-id": "ka10029",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8"
            }
            if next_key:
                headers.update({"cont-yn": "Y", "next-key": next_key})

            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/rkinfo",
                headers=headers,
                json={
                    "mrkt_tp": market,
                    "sort_tp": "1",      # 1: 등락률 상위
                    "trde_qty_cnd": "0", # 전체
                    "stk_cnd": "1",      # 1: 관리종목 제외
                    "crd_cnd": "0",
                    "pric_cnd": "0",
                    "stex_tp": "3"       # KRX 고정
                },
            )
            data = resp.json()
            if not validate_kiwoom_response(data, "ka10029", logger):
                break

            items = data.get("exp_cntr_flu_rt_upper", [])
            for i, item in enumerate(items):
                stk_cd = item.get("stk_cd")
                flu_rt = clean_num(item.get("flu_rt"))
                # 갭 2% ~ 10% 사이 종목만 1차 필터링
                if 2.0 <= flu_rt <= 10.0:
                    # 순위(rank)는 전체 조회 결과에서의 순서로 기록
                    result[stk_cd] = {"rank": len(result) + 1, "gap_rt": flu_rt}

            # 헤더에서 연속조회 여부 확인
            cont_yn = resp.headers.get("cont-yn", "N")
            next_key = resp.headers.get("next-key", "").strip()

            # 너무 많은 데이터를 가져오지 않도록 최대 200개 내외에서 끊거나 조건부 종료
            if cont_yn != "Y" or not next_key or len(result) >= 150:
                break

    return result

async def fetch_credit_filter(token: str, market: str = "000", rdb=None) -> set:
    """ka10033 신용비율상위 - Redis 캐시 우선, 없으면 API 호출 후 캐시 저장.

    ka10033은 일일 호출 한도가 낮아 매 스캔마다 호출하면 1700 오류(한도 초과) 발생.
    캐시 TTL 1800s(30분)로 한도 소진 방지.
    """
    CACHE_KEY = f"cache:high_credit:{market}"
    CACHE_TTL = 1800  # 30분

    # 1. Redis 캐시 확인
    if rdb:
        try:
            cached = await rdb.smembers(CACHE_KEY)
            if cached:
                logger.debug("[S7] ka10033 캐시 사용 (%d종목, market=%s)", len(cached), market)
                return set(cached)
        except Exception as e:
            logger.debug("[S7] ka10033 캐시 조회 실패 (API fallback): %s", e)

    high_credit_set = set()
    next_key = ""

    async with kiwoom_client() as client:
        while True:
            headers = {
                "api-id": "ka10033",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8"
            }
            if next_key:
                headers.update({"cont-yn": "Y", "next-key": next_key})

            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/rkinfo",
                headers=headers,
                json={
                    "mrkt_tp": market,
                    "trde_qty_tp": "0",
                    "stk_cnd": "1",
                    "updown_incls": "1",
                    "crd_cnd": "0",
                    "stex_tp": "3"
                }
            )
            data = resp.json()
            if not validate_kiwoom_response(data, "ka10033", logger):
                break

            items = data.get("crd_rt_upper", [])
            for x in items:
                if clean_num(x.get("crd_rt")) >= 8.0:
                    high_credit_set.add(x.get("stk_cd"))

            cont_yn = resp.headers.get("cont-yn", "N")
            next_key = resp.headers.get("next-key", "").strip()

            if cont_yn != "Y" or not next_key:
                break

    # 2. API 조회 성공 시 Redis에 캐시 저장
    if rdb and high_credit_set:
        try:
            pipe = rdb.pipeline()
            pipe.delete(CACHE_KEY)
            pipe.sadd(CACHE_KEY, *high_credit_set)
            pipe.expire(CACHE_KEY, CACHE_TTL)
            await pipe.execute()
            logger.debug("[S7] ka10033 캐시 저장 (%d종목, TTL=%ds)", len(high_credit_set), CACHE_TTL)
        except Exception as e:
            logger.debug("[S7] ka10033 캐시 저장 실패: %s", e)

    return high_credit_set

async def scan_auction_signal(token: str, market: str = "000", rdb=None) -> list:
    """전술 7: 동시호가 최종 스캔 함수"""
    # 1. candidates:s7:{market} 풀 우선 사용
    gap_candidates: dict = {}
    if rdb:
        try:
            pool = await rdb.lrange(f"candidates:s7:{market}", 0, -1)
            if pool:
                for i, stk_cd in enumerate(pool):
                    gap_candidates[stk_cd] = {"rank": i + 1, "gap_rt": 5.0}
                logger.debug("[S7] candidates:s7:%s 풀 사용 (%d개)", market, len(pool))
        except Exception as e:
            logger.debug("[S7] 풀 조회 실패, fallback: %s", e)

    # 풀 없으면 ka10029 직접 조회 (fallback)
    if not gap_candidates:
        logger.debug("[S7] 풀 없음 – ka10029 직접 조회 (fallback)")
        gap_candidates = await fetch_gap_rank(token, market)

    # 신용 리스크 종목 수집 (캐시 우선)
    high_credit_stocks = await fetch_credit_filter(token, market, rdb=rdb)

    results = []

    for stk_cd, info in gap_candidates.items():
        if stk_cd in high_credit_stocks: continue

        # 2. Redis에서 실시간 호가잔량(0D) 데이터 확인
        # ws:hoga 저장 키: total_buy_bid_req(FID125), total_sel_bid_req(FID121)
        try:
            hoga_data = await rdb.hgetall(f"ws:hoga:{stk_cd}") if rdb else {}
        except:
            hoga_data = {}

        if not hoga_data: continue

        total_bid = clean_num(hoga_data.get("total_buy_bid_req", 0))
        total_ask = clean_num(hoga_data.get("total_sel_bid_req", 0))

        # 호가잔량 비율 계산:
        # $$Bid\ Ratio = \frac{Total\ Bid\ Quantity}{Total\ Ask\ Quantity}$$
        bid_ratio = total_bid / total_ask if total_ask > 0 else 0.0
        # FID201(예상체결등락율)은 ws:hoga 미저장 → info['gap_rt'] fallback
        live_gap_pct = info['gap_rt']

        # 최종 진입 조건: 갭 2~10% 유지 & 매수잔량이 매도잔량의 2배 이상
        if (2.0 <= live_gap_pct <= 10.0) and (bid_ratio >= 2.0):
            stk_nm = await fetch_stk_nm(rdb, token, stk_cd)

            # 동적 TP/SL — 5분봉 ATR (동시호가 = 시초가 진입 단기 변동성)
            atr_val = None
            try:
                atr_result = await get_atr_minute(token, stk_cd, tic_scope="5", period=7)
                atr_val = atr_result.atr
            except Exception:
                pass
            # 예상체결가: ws:expected(0H) exp_cntr_pric 우선, 없으면 best bid 호가 사용
            exp_data = await rdb.hgetall(f"ws:expected:{stk_cd}") if rdb else {}
            exp_prc = clean_num(exp_data.get("exp_cntr_pric", 0)) or clean_num(hoga_data.get("buy_bid_pric_1", 0))
            tp_sl = calc_tp_sl("S7_AUCTION", max(exp_prc, 1.0), [], [], [],
                                stk_cd=stk_cd, atr=atr_val)

            results.append({
                "stk_cd": stk_cd,
                "stk_nm": stk_nm,
                "strategy": "S7_AUCTION",
                "gap_pct": round(live_gap_pct, 2),
                "bid_ratio": round(bid_ratio, 2),
                "vol_rank": info['rank'],
                "entry_type": "시초가_시장가",
                **tp_sl.to_signal_fields(),
            })

    # 잔량 비율이 높은 순(수급 강도)으로 정렬
    return sorted(results, key=lambda x: x["bid_ratio"], reverse=True)[:5]
