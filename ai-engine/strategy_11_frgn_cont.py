from __future__ import annotations
"""
전술 11: 외국인 연속 순매수 스윙
유형: 스윙 / 보유기간: 5~7거래일
종목 선정: ka10035 외인연속순매매상위요청

진입 조건 (AND):
  ka10035: 외국인 D-1·D-2·D-3 모두 순매수 양수 (3거래일 연속 매수 확인)
  tot(누적 순매수 수량) > 0 (누적 방향 확인)
  당일 등락률 > 0 (하락 당일 제외) — ws:tick Redis에서 조회
  당일 등락률 ≤ 10% (과도한 갭 이미 오른 종목 제외)
  체결강도 ≥ 100% — ws:tick Redis에서 조회

API 실제 스펙 (docs/api_new/ka10035.md 기준):
  - 파라미터: mrkt_tp, trde_tp(2=순매수), base_dt_tp(1=전일기준), stex_tp
  - 응답키: for_cont_nettrde_upper
  - 응답 필드: stk_cd, cur_prc, dm1(D-1), dm2(D-2), dm3(D-3), tot(누적합계), limit_exh_rt
  - ※ cont_days, flu_rt 필드 없음 → flu_rt는 ws:tick Redis에서 조회
"""

import logging
import os
import asyncio
import httpx

from http_utils import validate_kiwoom_response, fetch_stk_nm, kiwoom_client, fetch_cntr_strength_cached
from ma_utils import fetch_daily_candles, _safe_price
from indicator_bollinger import calc_bollinger
from tp_sl_engine import calc_tp_sl

# NOTE: Python 메인 전술 실행자 (strategy_runner.py 에서 호출).
# Java api-orchestrator 는 토큰 관리·후보 풀 적재(candidates:s{N}:{market})만 담당.

logger = logging.getLogger(__name__)
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")


def _parse_qty(val: str) -> int:
    """'+34396981', '-140' 형식의 수량 문자열 → 정수 변환"""
    try:
        return int(str(val).replace("+", "").replace(",", ""))
    except (TypeError, ValueError):
        return 0


async def fetch_frgn_cont_buy(token: str, market: str = "000", max_pages: int = 2) -> list[dict]:
    """ka10035 외인연속순매매상위요청 – 연속조회 지원 버전"""
    all_items = []
    cont_yn = "N"
    next_key = ""

    async with kiwoom_client() as client:
        for _ in range(max_pages):
            headers = {
                "api-id": "ka10035",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
                "cont-yn": cont_yn,
                "next-key": next_key
            }

            body = {
                "mrkt_tp": market,
                "trde_tp": "2",       # 2: 연속순매수
                "base_dt_tp": "1",    # 1: 전일기준
                "stex_tp": "3",       # KRX
            }

            try:
                resp = await client.post(
                    f"{KIWOOM_BASE_URL}/api/dostk/rkinfo",
                    headers=headers,
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()

                if not validate_kiwoom_response(data, "ka10035", logger):
                    break

                items = data.get("for_cont_nettrde_upper", [])
                if not items:
                    break

                all_items.extend(items)

                # 헤더에서 다음 페이지 정보 추출
                cont_yn = resp.headers.get("cont-yn", "N")
                next_key = resp.headers.get("next-key", "")

                if cont_yn != "Y" or not next_key:
                    break

                # API 호출 부하 조절
                await asyncio.sleep(0.2)

            except Exception as e:
                logger.error(f"[S11] ka10035 호출 오류: {e}")
                break

    return all_items


async def scan_frgn_cont_swing(token: str, market: str = "000", rdb=None) -> list:
    """외국인 연속 순매수 스윙 전략 스캔 (Redis 풀 우선 → fallback 직접 조회)"""

    # 1. candidates:s11:{market} 풀 우선 확인
    pool_codes: list = []
    if rdb:
        try:
            pool_codes = await rdb.lrange(f"candidates:s11:{market}", 0, -1)
            if pool_codes:
                logger.debug("[S11] candidates:s11:%s 풀 사용 (%d개)", market, len(pool_codes))
        except Exception as e:
            logger.debug("[S11] 풀 조회 실패: %s", e)

    # 2. 원천 데이터 확보 (연속조회 적용)
    raw_items = await fetch_frgn_cont_buy(token, market, max_pages=2)
    if not raw_items:
        return []

    # 풀이 있으면 풀 종목만 필터
    if pool_codes:
        pool_set = set(pool_codes)
        raw_items = [it for it in raw_items if it.get("stk_cd") in pool_set]
        logger.debug("[S11] 풀 필터 후 %d개", len(raw_items))
    else:
        logger.debug("[S11] 풀 없음 – ka10035 전수 조회")

    results = []
    for item in raw_items:
        stk_cd = item.get("stk_cd")
        if not stk_cd: continue

        # 2. 순매수 연속성 검증 (D-1, D-2, D-3)
        dm1 = _parse_qty(item.get("dm1", "0"))
        dm2 = _parse_qty(item.get("dm2", "0"))
        dm3 = _parse_qty(item.get("dm3", "0"))
        tot = _parse_qty(item.get("tot", "0"))

        # 필터: 3일 연속 매수세 확인
        if dm1 <= 0 or dm2 <= 0 or dm3 <= 0 or tot <= 0:
            continue

        # 3. 실시간 시장 상황 결합 (Redis)
        flu_rt = 0.0
        cntr_str = 100.0
        if rdb:
            tick = await rdb.hgetall(f"ws:tick:{stk_cd}")
            if tick:
                flu_rt = float(str(tick.get("flu_rt", "0")).replace("+", ""))
                cntr_str = float(str(tick.get("cntr_str", "100")).replace(",", ""))

        # WS 미수신 시에는 일봉 시가 대비 등락률과 REST 체결강도로 보강한다.
        if flu_rt == 0.0 or cntr_str <= 100.0:
            try:
                await asyncio.sleep(0.25)
                candles_fallback = await fetch_daily_candles(token, stk_cd)
                if candles_fallback:
                    cur_fb = _safe_price(candles_fallback[0].get("cur_prc"))
                    open_fb = _safe_price(candles_fallback[0].get("open_pric"))
                    if flu_rt == 0.0 and cur_fb > 0 and open_fb > 0:
                        flu_rt = (cur_fb - open_fb) / open_fb * 100
            except Exception as e:
                logger.debug("[S11] flu_rt fallback 실패 %s: %s", stk_cd, e)

            if cntr_str <= 100.0:
                try:
                    await asyncio.sleep(0.25)
                    cntr_str, _ = await fetch_cntr_strength_cached(token, stk_cd, rdb=rdb)
                except Exception as e:
                    logger.debug("[S11] 체결강도 fallback 실패 %s: %s", stk_cd, e)

        # 4. 진입 조건 필터링
        # - 당일 마이너스(-)이거나 10% 이상 과열된 종목 제외
        if not (0.0 < flu_rt <= 10.0):
            continue
        # - 체결강도가 100% 미만(매도우위)인 종목 제외
        if cntr_str < 100.0:
            continue

        # 5. 스코어링 (누적 매집량 + 최근 매수 강도 + 시장 탄력)
        # 100만 주 단위를 기준으로 가중치 부여
        score = (tot / 1_000_000) * 5 + (dm1 / 1_000_000) * 3 + (flu_rt * 0.5)
        cur_prc = abs(float(str(item.get("cur_prc", "0")).replace("+", "").replace(",", "")))

        stk_nm = await fetch_stk_nm(rdb, token, stk_cd)

        # 동적 TP/SL — 일봉 MA20 + 볼린저 상단 기반
        highs_d, lows_d, closes_d, ma20, bb_upper = [], [], [], None, None
        try:
            await asyncio.sleep(0.25)
            candles = await fetch_daily_candles(token, stk_cd)
            closes_d = [_safe_price(c.get("cur_prc")) for c in candles if _safe_price(c.get("cur_prc")) > 0]
            highs_d  = [_safe_price(c.get("high_pric")) for c in candles]
            lows_d   = [_safe_price(c.get("low_pric")) for c in candles]
            if len(closes_d) >= 20:
                ma20 = sum(closes_d[:20]) / 20
                bands = calc_bollinger(closes_d, 20, 2.0)
                if bands and bands[0][0] > cur_prc:
                    bb_upper = bands[0][0]
        except Exception as e:
            logger.debug("[S11] 일봉 조회 실패 %s: %s", stk_cd, e)

        tp_sl = calc_tp_sl("S11_FRGN_CONT", cur_prc, highs_d, lows_d, closes_d,
                           stk_cd=stk_cd, ma20=ma20, bb_upper=bb_upper)

        results.append({
            "stk_cd": stk_cd,
            "stk_nm": stk_nm,
            "strategy": "S11_FRGN_CONT",  # scorer.py case 키와 일치
            "score": round(score, 2),
            "cur_prc": round(cur_prc),
            "dm1": dm1,
            "dm2": dm2,   # scorer.py cont_days 계산에 필요
            "dm3": dm3,   # scorer.py cont_days 계산에 필요
            "tot": tot,
            "flu_rt": round(flu_rt, 2),
            "cntr_strength": round(cntr_str, 1),
            "entry_type": "현재가_종가",
            **tp_sl.to_signal_fields(),
        })

    # 점수 높은 순으로 상위 5개 반환
    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]
