from __future__ import annotations
"""
전술 10: 52주 신고가 돌파 스윙
유형: 스윙 / 보유기간: 5~10거래일
종목 선정: ka10016 신고저가요청 (term=250, 약 1년)

진입 조건 (AND):
  ka10016: 당일 52주(250거래일) 신고가 기록 종목
  ka10023: 전일 대비 거래량 급증률 ≥ 100% (거래량 2배 이상 동반 돌파)
  당일 등락률 2% ~ 15% 범위 (소폭 돌파 ~ 과도한 갭 제외)
  관리종목·ETF 제외
"""

import asyncio
import logging
import os
import httpx
from http_utils import fetch_cntr_strength_cached, fetch_hoga, validate_kiwoom_response, fetch_stk_nm, kiwoom_client
from ma_utils import fetch_daily_candles, _safe_price
from indicator_atr import calc_atr
from tp_sl_engine import calc_tp_sl

logger = logging.getLogger(__name__)
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")
_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))
NEW_HIGH_TERM = os.getenv("S10_NEW_HIGH_TERM", "250")

async def fetch_new_high_stocks_all(token: str, market: str = "000") -> list[dict]:
    """ka10016 신고저가요청 – 전 종목 수집 (연속조회 대응)"""
    all_items = []
    cont_yn, next_key = "N", ""

    async with kiwoom_client() as client:
        while True:
            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/stkinfo",
                headers={
                    "api-id": "ka10016",
                    "authorization": f"Bearer {token}",
                    "cont-yn": cont_yn,
                    "next-key": next_key,
                    "Content-Type": "application/json;charset=UTF-8",
                },
                json={
                    "mrkt_tp": market,
                    "ntl_tp": "1",             # 신고가
                    "high_low_close_tp": "1",  # 고저기준
                    "stk_cnd": "1",            # 관리종목 제외
                    "trde_qty_tp": "00010",    # 만주 이상
                    "crd_cnd": "0",            # 전체
                    "updown_incls": "0",       # 상하한 제외
                    "dt": NEW_HIGH_TERM,
                    "stex_tp": "3",            # KRX
                },
            )
            data = resp.json()
            if not validate_kiwoom_response(data, "ka10016", logger):
                break

            all_items.extend(data.get("ntl_pric", []))

            cont_yn = resp.headers.get("cont-yn", "N")
            next_key = resp.headers.get("next-key", "")
            if cont_yn != "Y" or not next_key:
                break
            await asyncio.sleep(_API_INTERVAL)

    return all_items

async def fetch_volume_surge_map_all(token: str, market: str = "000") -> dict[str, float]:
    """ka10023 거래량급증요청 – 전 종목 수집 (연속조회 대응)"""
    result_map = {}
    cont_yn, next_key = "N", ""

    async with kiwoom_client() as client:
        while True:
            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/rkinfo",
                headers={
                    "api-id": "ka10023",
                    "authorization": f"Bearer {token}",
                    "cont-yn": cont_yn,
                    "next-key": next_key,
                    "Content-Type": "application/json;charset=UTF-8",
                },
                json={
                    "mrkt_tp": market,
                    "sort_tp": "2",      # 급증률 순
                    "tm_tp": "2",        # 전일 대비
                    "trde_qty_tp": "10", # 만주 이상
                    "stk_cnd": "20",     # [고도화] ETF+ETN+스팩 제외 (명세 기준 20번)
                    "pric_tp": "8",      # 1천원 이상
                    "stex_tp": "3",
                },
            )
            data = resp.json()
            if not validate_kiwoom_response(data, "ka10023", logger):
                break

            items = data.get("trde_qty_sdnin", [])
            for item in items:
                stk_cd = item.get("stk_cd")
                if not stk_cd: continue
                try:
                    # 부호 및 콤마 제거 로직 통합
                    raw_rt = str(item.get("sdnin_rt", "0")).replace("+", "").replace(",", "")
                    result_map[stk_cd] = float(raw_rt)
                except: pass

            cont_yn = resp.headers.get("cont-yn", "N")
            next_key = resp.headers.get("next-key", "")
            if cont_yn != "Y" or not next_key:
                break
            await asyncio.sleep(_API_INTERVAL)

    return result_map

async def scan_new_high_swing(token: str, market: str = "000", rdb=None) -> list:
    """52주 신고가 돌파 스윙 전략 메인 스캐너 (Redis 풀 우선 → fallback 직접 조회)"""

    # 1. candidates:s10:{market} 풀 확인 (market="000"이면 001+101 모두 조회)
    pool_codes: list = []
    if rdb:
        try:
            markets_to_check = ["001", "101"] if market == "000" else [market]
            for mkt in markets_to_check:
                codes = await rdb.lrange(f"candidates:s10:{mkt}", 0, -1)
                pool_codes.extend(codes)
            pool_codes = list(dict.fromkeys(pool_codes))  # 중복 제거
            if pool_codes:
                logger.debug("[S10] candidates:s10:* 풀 사용 (%d개)", len(pool_codes))
        except Exception as e:
            logger.debug("[S10] 풀 조회 실패: %s", e)

    # 2. 원천 데이터 확보
    if pool_codes:
        # 풀 기반 경로: ka10016 생략, ws:tick에서 flu_rt 보완
        vol_surge_map = await fetch_volume_surge_map_all(token, market)
        new_high_items = [
            {"stk_cd": cd, "flu_rt": "0", "cur_prc": "0", "stk_nm": ""}
            for cd in pool_codes
        ]
        if rdb:
            for item in new_high_items:
                try:
                    tick = await rdb.hgetall(f"ws:tick:{item['stk_cd']}")
                    if tick:
                        item["flu_rt"]  = tick.get("flu_rt", "0")
                        item["cur_prc"] = tick.get("cur_prc", "0")
                        item["stk_nm"]  = tick.get("stk_nm", "")
                except Exception:
                    pass
    else:
        # fallback: ka10016+ka10023 전수 조회
        logger.debug("[S10] 풀 없음 – ka10016+ka10023 전수 조회")
        new_high_items, vol_surge_map = await asyncio.gather(
            fetch_new_high_stocks_all(token, market),
            fetch_volume_surge_map_all(token, market),
        )

    results = []
    for item in new_high_items:
        stk_cd = item.get("stk_cd")

        # [파싱 고도화] 등락률 및 현재가 추출
        try:
            flu_rt = float(str(item.get("flu_rt", "0")).replace("+", "").replace(",", ""))
            cur_prc = abs(float(str(item.get("cur_prc", "0")).replace("+", "").replace(",", "")))
        except (TypeError, ValueError):
            continue

        # 진입 조건 1: 등락률 2% ~ 15%
        if not (2.0 <= flu_rt <= 15.0):
            continue

        # 진입 조건 2: 거래량 급증 100% 이상 (vol_surge_map 교차 검증)
        sdnin_rt = vol_surge_map.get(stk_cd, 0.0)
        if sdnin_rt < 100.0:
            continue

        # [수급 보완] 체결강도 + 호가 비율 조회 (ka10046, ka10004)
        await asyncio.sleep(_API_INTERVAL)
        cntr_str, _ = await fetch_cntr_strength_cached(token, stk_cd, rdb=rdb)

        await asyncio.sleep(_API_INTERVAL)
        bid_ratio = await fetch_hoga(token, stk_cd, rdb)

        # [리스크 필터 + TP/SL] 일봉 데이터 조회 (MA20 이격도 + 동적 TP/SL 겸용)
        candles = []
        highs_d, lows_d, closes_d = [], [], []
        ma20 = None
        try:
            await asyncio.sleep(_API_INTERVAL)
            candles = await fetch_daily_candles(token, stk_cd)
            closes_d = [_safe_price(c.get("cur_prc")) for c in candles if _safe_price(c.get("cur_prc")) > 0]
            highs_d  = [_safe_price(c.get("high_pric")) for c in candles]
            lows_d   = [_safe_price(c.get("low_pric")) for c in candles]
            if len(closes_d) >= 20:
                ma20 = sum(closes_d[:20]) / 20
                # MA20 이격도 필터 (25% 초과 = 과열 돌파)
                if closes_d[0] > 0 and ma20 > 0:
                    if (closes_d[0] - ma20) / ma20 * 100 > 25.0:
                        continue
        except Exception as e:
            logger.debug("[S10] 일봉 조회 실패 %s: %s", stk_cd, e)

        # 스코어링 (거래량 비중 강화)
        score = (flu_rt * 0.3) + (min(sdnin_rt / 100, 5.0) * 12) + (max(cntr_str - 100, 0) * 0.2)

        # ATR 계산 (SL/TP 폴백 품질 향상)
        atr_val = None
        if len(highs_d) >= 14 and len(lows_d) >= 14 and len(closes_d) >= 14:
            atr_vals = calc_atr(highs_d, lows_d, closes_d, 14)
            atr_val  = atr_vals[0] if atr_vals and atr_vals[0] != 0.0 else None

        # 동적 TP/SL (신고가 돌파 = 이전 52주 고점 기준 피보나치 확장)
        tp_sl = calc_tp_sl("S10_NEW_HIGH", cur_prc, highs_d, lows_d, closes_d,
                           stk_cd=stk_cd, ma20=ma20, atr=atr_val)

        stk_nm = str(item.get("stk_nm", "")).strip() or await fetch_stk_nm(rdb, token, stk_cd)
        results.append({
            "stk_cd": stk_cd,
            "stk_nm": stk_nm,
            "cur_prc": round(cur_prc),
            "strategy": "S10_NEW_HIGH",
            "flu_rt": round(flu_rt, 2),
            "vol_surge_rt": round(sdnin_rt, 1),
            "cntr_strength": round(cntr_str, 1),
            "bid_ratio": round(bid_ratio, 3) if bid_ratio is not None else None,
            "score": round(score, 2),
            **tp_sl.to_signal_fields(),
        })

    # 상위 5개 종목 반환
    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]
