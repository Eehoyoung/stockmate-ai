from __future__ import annotations
"""
전술 5: 프로그램 순매수 + 외인 동반 상위
수정 사항: ka90003 URI 변경 및 ka10044/ka10001 필터 로직 추가
"""
import asyncio
import httpx
import logging
import os
from datetime import datetime, timedelta, timezone
from statistics import mean

from http_utils import fetch_cntr_strength_cached, fetch_hoga, validate_kiwoom_response, fetch_stk_nm, kiwoom_client
from ma_utils import fetch_daily_candles, _safe_price
from indicator_atr import calc_atr
from tp_sl_engine import calc_tp_sl
from utils import safe_float as clean_val
from strategy_perf import perf_timer
from strategy_shared_cache import cache_get_json, cache_set_json, flag_enabled

logger = logging.getLogger(__name__)
KST    = timezone(timedelta(hours=9))
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")
_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))
_S5_CACHE_TTL = int(os.getenv("S5_SHARED_CACHE_TTL", "60"))
_S5_OVERLAP_LIMIT = int(os.getenv("S5_OVERLAP_LIMIT", "15"))
_S5_TWO_STAGE_LIMIT = int(os.getenv("S5_TWO_STAGE_LIMIT", "8"))

async def fetch_progra_netbuy(token: str, market: str, rdb=None) -> dict:
    """ka90003 프로그램순매수상위50 조회 (연속조회 포함)"""
    cache_key = f"strategy:s5:ka90003:{market}"
    if flag_enabled("S5_SHARED_CACHE_ENABLED") and rdb is not None:
        cached = await cache_get_json(rdb, cache_key)
        if isinstance(cached, dict):
            return cached

    market_map = {"KOSPI": "P00101", "KOSDAQ": "P10102", "001": "P00101", "101": "P10102", "000": "P00101"}
    kiwoom_mrkt = market_map.get(market.upper(), "P00101")

    result = {}
    next_key = ""

    async with kiwoom_client() as client:
        while True:
            headers = {
                "api-id": "ka90003",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8"
            }
            if next_key:
                headers["cont-yn"] = "Y"
                headers["next-key"] = next_key

            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/stkinfo",
                headers=headers,
                json={
                    "trde_upper_tp": "2",  # 2: 순매수상위
                    "amt_qty_tp": "1",     # 1: 금액
                    "mrkt_tp": kiwoom_mrkt,
                    "stex_tp": "3"         # KRX 고정
                }
            )
            resp.raise_for_status()
            data = resp.json()

            if not validate_kiwoom_response(data, "ka90003", logger):
                break

            items = data.get("prm_netprps_upper_50", [])
            for x in items:
                stk_cd = x.get("stk_cd")
                if stk_cd:
                    try:
                        cur_prc = abs(int(float(
                            str(x.get("cur_prc", "0")).replace("+", "").replace(",", "").replace("-", "") or "0"
                        )))
                    except (TypeError, ValueError):
                        cur_prc = 0
                    result[stk_cd] = {
                        "net_buy_amt": int(clean_val(x.get("prm_netprps_amt", 0))),
                        "stk_nm": str(x.get("stk_nm", "")).strip(),
                        "cur_prc": cur_prc,
                        "flu_rt": clean_val(x.get("flu_rt", "0")),
                    }

            cont_yn = resp.headers.get("cont-yn", "N")
            next_key = resp.headers.get("next-key", "").strip()
            if cont_yn != "Y" or not next_key:
                break
    if flag_enabled("S5_SHARED_CACHE_ENABLED") and rdb is not None:
        await cache_set_json(rdb, cache_key, result, _S5_CACHE_TTL)
    return result

async def fetch_frgn_inst_upper(token: str, market: str, rdb=None) -> set:
    """ka90009 외국인기관매매상위 - 외인 순매수 종목 코드 추출 (연속조회 포함)"""
    cache_key = f"strategy:s5:ka90009:{market}"
    if flag_enabled("S5_SHARED_CACHE_ENABLED") and rdb is not None:
        cached = await cache_get_json(rdb, cache_key)
        if isinstance(cached, list):
            return set(cached)

    # ka90009는 시장코드가 001, 101 형태를 따름
    mrkt = "001" if market in ["KOSPI", "001", "000"] else "101"

    result_set = set()
    next_key = ""

    async with kiwoom_client() as client:
        while True:
            headers = {
                "api-id": "ka90009",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8"
            }
            if next_key:
                headers["cont-yn"] = "Y"
                headers["next-key"] = next_key

            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/rkinfo",
                headers=headers,
                json={
                    "mrkt_tp": mrkt,
                    "amt_qty_tp": "1",
                    "qry_dt_tp": "0",
                    "stex_tp": "3" # KRX 고정
                }
            )
            resp.raise_for_status()
            data = resp.json()
            if not validate_kiwoom_response(data, "ka90009", logger):
                break

            items = data.get("frgnr_orgn_trde_upper", [])
            for x in items:
                # 외인 순매수 종목코드 필드 (명세서 확인 필요: 보통 for_netprps_stk_cd)
                cd = x.get("for_netprps_stk_cd")
                if cd:
                    result_set.add(cd)

            cont_yn = resp.headers.get("cont-yn", "N")
            next_key = resp.headers.get("next-key", "").strip()
            if cont_yn != "Y" or not next_key:
                break
    if flag_enabled("S5_SHARED_CACHE_ENABLED") and rdb is not None:
        await cache_set_json(rdb, cache_key, sorted(result_set), _S5_CACHE_TTL)
    return result_set

async def check_extra_conditions(token: str, stk_cd: str, market: str = "001", rdb=None) -> bool:
    """전일 기관 순매수 여부 및 5분봉 5이평선 상단 확인"""
    cache_key = f"strategy:s5:extra:{market}:{stk_cd}"
    if flag_enabled("S5_EXTRA_CACHE_ENABLED") and rdb is not None:
        cached = await cache_get_json(rdb, cache_key)
        if isinstance(cached, bool):
            return cached

    async def finish(value: bool) -> bool:
        if flag_enabled("S5_EXTRA_CACHE_ENABLED") and rdb is not None:
            await cache_set_json(rdb, cache_key, value, _S5_CACHE_TTL)
        return value

    try:
        # 전일 날짜 (단, 장 종료 후 호출 시 로직에 따라 당일/전일 조정 필요)
        yesterday = (datetime.now(KST) - timedelta(days=1)).strftime("%Y%m%d")
        mrkt = "001" if market in ["KOSPI", "001", "000"] else "101"

        async with kiwoom_client() as client:
            # 1. ka10044 전일 기관 순매수 리스트 확인
            inst_resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/mrkcond",
                headers={"api-id": "ka10044", "authorization": f"Bearer {token}", "Content-Type": "application/json;charset=UTF-8"},
                json={"strt_dt": yesterday, "end_dt": yesterday, "trde_tp": "2", "mrkt_tp": mrkt, "stex_tp": "3"}
            )
            inst_data = inst_resp.json()
            if validate_kiwoom_response(inst_data, "ka10044", logger):
                netbuy_list = inst_data.get("daly_orgn_trde_stk", [])
                if not any(item.get("stk_cd") == stk_cd for item in netbuy_list):
                    return await finish(False)
            else:
                return await finish(False)

            # 2. ka10080 5분봉 5이평선 확인
            chart_resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/chart",
                headers={"api-id": "ka10080", "authorization": f"Bearer {token}", "Content-Type": "application/json;charset=UTF-8"},
                json={"stk_cd": stk_cd, "tic_scope": "5", "upd_stkpc_tp": "1"}
            )
            chart_data = chart_resp.json()
            if validate_kiwoom_response(chart_data, "ka10080", logger):
                candles = chart_data.get("stk_min_pole_chart_qry", [])
                if len(candles) >= 5:
                    cur_prc = clean_val(candles[0].get("cur_prc", 0))
                    ma5 = mean([clean_val(c.get("cur_prc", 0)) for c in candles[:5]])
                    return await finish(cur_prc >= ma5)
            return await finish(False)
    except Exception as e:
        logger.debug(f"[S5_Extra] {stk_cd} 필터 제외: {e}")
        return False

async def scan_program_buy(token: str, market: str = "000", rdb=None) -> list:
    """전술 5 메인 스캔 함수"""
    # 0. candidates:s5:{market} 풀 우선 확인
    pool_codes: list = []
    if rdb:
        try:
            pool_codes = await rdb.lrange(f"candidates:s5:{market}", 0, -1)
            if pool_codes:
                logger.debug("[S5] candidates:s5:%s 풀 사용 (%d개)", market, len(pool_codes))
        except Exception as e:
            logger.debug("[S5] 풀 조회 실패: %s", e)

    # 1. 기초 데이터 동시 수집
    async with perf_timer("s5_base_fetch", rdb=rdb, fields={"market": market}):
        prog_map, frgn_set = await asyncio.gather(
            fetch_progra_netbuy(token, market, rdb=rdb),
            fetch_frgn_inst_upper(token, market, rdb=rdb)
        )

    # 2. 프로그램 순매수 & 외인 순매수 교집합 추출 (순매수 금액 상위 15종목으로 제한)
    overlap_raw = set(prog_map.keys()) & frgn_set
    # 풀이 있으면 풀 종목으로 추가 필터
    if pool_codes:
        pool_set = set(pool_codes)
        overlap_raw = overlap_raw & pool_set
        logger.debug("[S5] 풀 필터 후 교집합 %d개", len(overlap_raw))
    else:
        logger.debug("[S5] 풀 없음 – ka90003 전수 조회")
    overlap_limit = _S5_TWO_STAGE_LIMIT if flag_enabled("S5_TWO_STAGE_ENABLED") else _S5_OVERLAP_LIMIT
    overlap = sorted(overlap_raw, key=lambda c: prog_map[c]["net_buy_amt"], reverse=True)[:overlap_limit]
    if flag_enabled("S5_TWO_STAGE_SHADOW"):
        shadow = sorted(overlap_raw, key=lambda c: prog_map[c]["net_buy_amt"], reverse=True)[:_S5_TWO_STAGE_LIMIT]
        logger.info("[S5] two-stage shadow current=%d shadow=%d", len(overlap), len(shadow))
    results = []

    # 3. 교집합 종목들에 대해 정밀 필터 적용 (ka10044+ka10080 × 15 = 30 calls max)
    for stk_cd in overlap:
        await asyncio.sleep(_API_INTERVAL) # 과부하 방지
        async with perf_timer("s5_extra", rdb=rdb, fields={"market": market, "stk_cd": stk_cd}):
            extra_ok = await check_extra_conditions(token, stk_cd, market, rdb=rdb)
        if extra_ok:
            info = prog_map[stk_cd]
            # ka90003 응답에서 직접 수집한 stk_nm/cur_prc 우선 사용
            stk_nm  = info.get("stk_nm") or await fetch_stk_nm(rdb, token, stk_cd)
            cur_prc = info.get("cur_prc", 0)
            cntr_strength, _ = await fetch_cntr_strength_cached(token, stk_cd, rdb=rdb)
            bid_ratio = await fetch_hoga(token, stk_cd, rdb=rdb)

            # 동적 TP/SL — 일봉 기반 (프로그램+외인 수급 스윙 목표)
            highs_d, lows_d, closes_d, ma20, atr_val = [], [], [], None, None
            try:
                await asyncio.sleep(_API_INTERVAL)
                candles  = await fetch_daily_candles(token, stk_cd)
                closes_d = [_safe_price(c.get("cur_prc")) for c in candles if _safe_price(c.get("cur_prc")) > 0]
                highs_d  = [_safe_price(c.get("high_pric")) for c in candles]
                lows_d   = [_safe_price(c.get("low_pric"))  for c in candles]
                if len(closes_d) >= 20:
                    ma20 = sum(closes_d[:20]) / 20
                if len(highs_d) >= 14 and len(lows_d) >= 14 and len(closes_d) >= 14:
                    atr_vals = calc_atr(highs_d, lows_d, closes_d, 14)
                    atr_val  = atr_vals[0] if atr_vals and atr_vals[0] != 0.0 else None
            except Exception as e:
                logger.debug("[S5] 일봉 조회 실패 %s: %s", stk_cd, e)

            tp_sl = calc_tp_sl("S5_PROG_FRGN", cur_prc, highs_d, lows_d, closes_d,
                                stk_cd=stk_cd, ma20=ma20, atr=atr_val)

            results.append({
                "stk_cd": stk_cd,
                "stk_nm": stk_nm,
                "cur_prc": cur_prc,
                "strategy": "S5_PROG_FRGN",  # scorer.py case 키와 일치
                "net_buy_amt": info["net_buy_amt"],
                "flu_rt": info.get("flu_rt", 0.0),
                "cntr_strength": round(cntr_strength, 1),
                "bid_ratio": round(bid_ratio, 2) if bid_ratio is not None else None,
                "entry_type": "지정가_1호가",
                **tp_sl.to_signal_fields(),
            })

    # 순매수 금액 상위 5개 반환
    return sorted(results, key=lambda x: x["net_buy_amt"], reverse=True)[:5]
