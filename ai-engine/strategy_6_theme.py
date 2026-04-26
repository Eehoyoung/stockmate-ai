from __future__ import annotations
"""
전술 6: 테마 상위 + 구성종목 연동
타이밍: 9:30~13:00 (테마 모멘텀 집중 시간)
진입 조건:

ka90001 테마그룹 상위 등락률 1위~5위 그룹 추출
ka90002 해당 테마 구성종목 중 등락률 상위 30% 제외 (이미 많이 오른 종목)
구성종목 중 5% 미만 상승 + 체결강도 ≥ 120% + 거래량 급증 종목 선별
테마 내 선도주 이미 강하게 오른 경우 → 후발주 매수
"""

import asyncio
import httpx
import logging
import os
from http_utils import fetch_cntr_strength_cached, validate_kiwoom_response, fetch_stk_nm, kiwoom_client
from ma_utils import fetch_daily_candles, _safe_price
from indicator_atr import calc_atr
from tp_sl_engine import calc_tp_sl
from utils import safe_float as clean_num

logger = logging.getLogger(__name__)

_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")

async def fetch_theme_groups(token: str) -> list:
    """ka90001 테마그룹별 상위 수익률 (연속조회 포함)"""
    results = []
    next_key = ""
    async with kiwoom_client() as client:
        while True:
            headers = {"api-id": "ka90001", "authorization": f"Bearer {token}", "Content-Type": "application/json;charset=UTF-8"}
            if next_key:
                headers.update({"cont-yn": "Y", "next-key": next_key})

            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/thme",
                headers=headers,
                json={
                    "qry_tp": "1",          # 1: 테마검색
                    "date_tp": "1",         # 1일 (당일 테마)
                    "flu_pl_amt_tp": "3",   # 3: 상위등락률 (당일 강한 테마 우선)
                    "stex_tp": "3"          # KRX 고정
                }
            )
            data = resp.json()
            if not validate_kiwoom_response(data, "ka90001", logger): break

            results.extend(data.get("thema_grp", []))

            next_key = resp.headers.get("next-key", "").strip()
            if resp.headers.get("cont-yn") != "Y" or not next_key or len(results) >= 20:
                break
    return results[:10]  # 상위 10개 테마만 분석 대상으로 삼음

async def fetch_theme_stocks(token: str, thema_grp_cd: str) -> list:
    """ka90002 테마구성종목 (연속조회 포함)"""
    results = []
    next_key = ""
    async with kiwoom_client() as client:
        while True:
            headers = {"api-id": "ka90002", "authorization": f"Bearer {token}", "Content-Type": "application/json;charset=UTF-8"}
            if next_key:
                headers.update({"cont-yn": "Y", "next-key": next_key})

            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/thme",
                headers=headers,
                json={
                    "date_tp": "1",
                    "thema_grp_cd": thema_grp_cd,
                    "stex_tp": "3" # KRX 고정
                }
            )
            data = resp.json()
            if not validate_kiwoom_response(data, "ka90002", logger): break

            results.extend(data.get("thema_comp_stk", []))

            next_key = resp.headers.get("next-key", "").strip()
            if resp.headers.get("cont-yn") != "Y" or not next_key:
                break
    return results

async def scan_theme_laggard(token: str, rdb=None) -> list:
    """전술 6: 테마 상위 그룹 내 후발주 매수 스캔 (Redis 풀 우선 → fallback 직접 조회)"""
    # 0. candidates:s6:001 풀 우선 확인 (S6는 시장 무관 동일 풀)
    pool_codes: list = []
    if rdb:
        try:
            pool_codes = await rdb.lrange("candidates:s6:001", 0, -1)
            if pool_codes:
                logger.debug("[S6] candidates:s6:001 풀 사용 (%d개)", len(pool_codes))
        except Exception as e:
            logger.debug("[S6] 풀 조회 실패: %s", e)

    themes = await fetch_theme_groups(token)
    final_candidates = {} # 중복 종목 방지를 위해 dict 사용 (stk_cd: data)
    pool_set = set(pool_codes) if pool_codes else None

    for theme in themes:
        thema_grp_cd = theme.get("thema_grp_cd")
        theme_nm = theme.get("thema_nm")
        theme_flu_rt = clean_num(theme.get("flu_rt"))

        # 테마 자체가 최소 2% 이상은 올라야 에너지가 있다고 판단
        if theme_flu_rt < 2.0: continue

        await asyncio.sleep(_API_INTERVAL)
        stocks = await fetch_theme_stocks(token, thema_grp_cd)
        if len(stocks) < 3: continue # 구성 종목이 너무 적으면 신뢰도 낮음

        # 1. 테마 내 등락률 분포 분석 (상위 30% 선도주 기준선 계산)
        flu_rates = sorted([clean_num(s.get("flu_rt")) for s in stocks])
        # 임계값: $$Threshold_{70\%} = sorted\_flu\_rates[\lfloor N \times 0.7 \rfloor]$$
        p70_idx = int(len(flu_rates) * 0.7)
        p70_threshold = flu_rates[p70_idx]

        for stk in stocks:
            stk_cd = stk.get("stk_cd")
            flu_rt = clean_num(stk.get("flu_rt"))

            # [조건 필터링]
            # - 테마 내 상위 30% 미만 (후발주)
            # - 당일 상승폭 0.5% ~ 7% (너무 낮으면 소외, 너무 높으면 이미 선도주화)
            if not (0.5 <= flu_rt < p70_threshold) or flu_rt >= 7.0:
                continue

            # 이미 다른 테마에서 선정된 종목이라면 패스
            if stk_cd in final_candidates: continue

            # 풀이 있으면 풀 종목만 정밀 검증
            if pool_set and stk_cd not in pool_set:
                continue

            await asyncio.sleep(_API_INTERVAL)
            strength, _ = await fetch_cntr_strength_cached(token, stk_cd, rdb=rdb)
            cur_prc = abs(float(str(stk.get("cur_prc", "0")).replace("+", "").replace(",", "")))
            # 체결강도 115% 이상으로 수급 유입 확인
            if strength >= 115:
                stk_nm = stk.get("stk_nm", "").strip() or await fetch_stk_nm(rdb, token, stk_cd)

                # 동적 TP/SL — 일봉 기반 (테마 단기 저항/지지)
                highs_d, lows_d, closes_d, ma5, atr_val = [], [], [], None, None
                try:
                    await asyncio.sleep(_API_INTERVAL)
                    candles  = await fetch_daily_candles(token, stk_cd)
                    closes_d = [_safe_price(c.get("cur_prc")) for c in candles if _safe_price(c.get("cur_prc")) > 0]
                    highs_d  = [_safe_price(c.get("high_pric")) for c in candles]
                    lows_d   = [_safe_price(c.get("low_pric"))  for c in candles]
                    if len(closes_d) >= 5:
                        ma5 = sum(closes_d[:5]) / 5
                    if len(highs_d) >= 14 and len(lows_d) >= 14 and len(closes_d) >= 14:
                        atr_vals = calc_atr(highs_d, lows_d, closes_d, 14)
                        atr_val  = atr_vals[0] if atr_vals and atr_vals[0] != 0.0 else None
                except Exception as e:
                    logger.debug("[S6] 일봉 조회 실패 %s: %s", stk_cd, e)

                tp_sl = calc_tp_sl("S6_THEME_LAGGARD", cur_prc, highs_d, lows_d, closes_d,
                                    stk_cd=stk_cd, ma5=ma5, atr=atr_val)

                final_candidates[stk_cd] = {
                    "stk_cd": stk_cd,
                    "stk_nm": stk_nm,
                    "cur_prc": cur_prc,
                    "strategy": "S6_THEME_LAGGARD",  # scorer.py case 키와 일치
                    "theme_name": theme_nm,
                    "theme_flu_rt": theme_flu_rt,
                    "flu_rt": flu_rt,
                    "cntr_strength": round(strength, 1),
                    "entry_type": "지정가_1호가",
                    **tp_sl.to_signal_fields(),
                }

    # 체결강도 순으로 정렬하여 상위 5개 반환
    sorted_results = sorted(final_candidates.values(), key=lambda x: x["cntr_strength"], reverse=True)
    return sorted_results[:5]
