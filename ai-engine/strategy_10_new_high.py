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
from http_utils import fetch_cntr_strength, validate_kiwoom_response

logger = logging.getLogger(__name__)
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://mockapi.kiwoom.com")
_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))
NEW_HIGH_TERM = os.getenv("S10_NEW_HIGH_TERM", "250")

async def fetch_new_high_stocks_all(token: str, market: str = "000") -> list[dict]:
    """ka10016 신고저가요청 – 전 종목 수집 (연속조회 대응)"""
    all_items = []
    cont_yn, next_key = "N", ""

    async with httpx.AsyncClient(timeout=10.0) as client:
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
                    "stex_tp": "1",            # KRX
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

    async with httpx.AsyncClient(timeout=10.0) as client:
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
                    "stex_tp": "1",
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
    """52주 신고가 돌파 스윙 전략 메인 스캐너"""
    # 1. 두 API 데이터를 전체 페이지로 수집 (동시 실행)
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

        # [수급 보완] 체결강도 확인
        cntr_str = None
        if rdb:
            # Redis 우선 조회 (생략 가능하지만 성능상 유리)
            pass

        if cntr_str is None:
            await asyncio.sleep(_API_INTERVAL)
            cntr_str = await fetch_cntr_strength(token, stk_cd)

        # [리스크 필터] MA20 이격도 검사
        try:
            from ma_utils import get_ma_context
            ma_ctx = await get_ma_context(token, stk_cd)
            if ma_ctx.valid and ma_ctx.is_overextended(threshold_pct=25.0):
                continue
        except: pass

        # 스코어링 (거래량 비중 강화)
        score = (flu_rt * 0.3) + (min(sdnin_rt / 100, 5.0) * 12) + (max(cntr_str - 100, 0) * 0.2)

        results.append({
            "stk_cd": stk_cd,
            "stk_nm": str(item.get("stk_nm", "")).strip(),
            "cur_prc": round(cur_prc),
            "strategy": "신고가 돌파 스윙",
            "flu_rt": round(flu_rt, 2),
            "vol_surge_rt": round(sdnin_rt, 1),
            "cntr_strength": round(cntr_str, 1),
            "score": round(score, 2),
            "target_pct": 12.0,
            "stop_pct": -5.0,
        })

    # 상위 5개 종목 반환
    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]
