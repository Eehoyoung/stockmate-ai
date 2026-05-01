from __future__ import annotations
"""
전술 3: 외인 + 기관 동시 순매수 돌파
타이밍: 9:30 이후 장중
진입 조건 (AND):

ka10063 장중투자자별매매: 외국인 + 기관계 동시 순매수 종목 (smtm_netprps_tp: "1")
ka10065 장중투자자별매매상위: 외국인 상위 20위 내 + 기관 상위 30위 내 동시 해당
ka10131 기관외국인연속매매: 최근 3일 연속 기관+외인 순매수
현재가가 5일선 위 (ka10080 5분봉 데이터로 MA 계산)
당일 거래량이 전일 동시간 대비 ≥ 1.5배 (ka10055)
"""
import asyncio
import httpx
import logging
import os
from collections import Counter
from datetime import datetime, timedelta, timezone

from http_utils import validate_kiwoom_response, fetch_stk_nm, kiwoom_client
from ma_utils import fetch_daily_candles, _safe_price, _calc_ma
from indicator_atr import calc_atr
from tp_sl_engine import calc_tp_sl
from utils import normalize_stock_code
from strategy_perf import perf_timer
from strategy_shared_cache import cache_get_json, cache_set_json, flag_enabled

logger = logging.getLogger(__name__)
KST    = timezone(timedelta(hours=9))

# 키움 REST API 초당 약 5회 제한 → 루프 내 0.25s 대기
_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))

# NOTE: Python 메인 전술 실행자 (strategy_runner.py 에서 호출).
# Java api-orchestrator 는 토큰 관리·후보 풀 적재(candidates:s{N}:{market})만 담당.
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")
_KA10055_MAX_PAGES = int(os.getenv("S3_KA10055_MAX_PAGES", "3"))
_KA10055_CACHE_TTL = int(os.getenv("S3_KA10055_CACHE_TTL", "30"))


class Ka10055RunStats:
    def __init__(self) -> None:
        self.counters = Counter()
        self._seen = set()

    def warn(self, reason: str, dedupe_key: tuple, message: str, *args) -> None:
        self.counters[reason] += 1
        key = (reason, dedupe_key)
        if key in self._seen:
            return
        self._seen.add(key)
        logger.warning(message, *args)

    def log_summary(self) -> None:
        if not self.counters:
            return
        logger.warning(
            "[S3] ka10055 summary page_cap=%d next_key_loop=%d repeated_page=%d",
            self.counters.get("page_cap", 0),
            self.counters.get("next_key_loop", 0),
            self.counters.get("repeated_page", 0),
        )


async def fetch_intraday_investor(token: str, market_type: str = "000") -> list:
    """
    ka10063 장중투자자별매매 - 외인+기관 동시 순매수 종목 조회
    :param token:
    :param market_type: "000":전체, "001":코스피, "101":코스닥
    """
    results = []
    next_key = ""

    async with kiwoom_client() as client:
        while True:
            headers = {
                "api-id": "ka10063",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8"
            }
            # 연속 조회가 필요한 경우 헤더 추가
            if next_key:
                headers["cont-yn"] = "Y"
                headers["next-key"] = next_key

            payload = {
                "mrkt_tp": market_type,
                "amt_qty_tp": "1",      # 금액&수량
                "invsr": "6",           # 외국인 (기준 투자자)
                "frgn_all": "1",        # 외국계 전체 체크
                "smtm_netprps_tp": "1", # ★동시순매수 체크 (외인+기관)
                "stex_tp": "3"          # KRX
            }

            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/mrkcond",
                headers=headers,
                json=payload
            )
            resp.raise_for_status()
            data = resp.json()

            if not validate_kiwoom_response(data, "ka10063", logger):
                break

            # 데이터 추출 및 병합
            items = data.get("opmr_invsr_trde", [])
            results.extend(items)

            # 연속 조회 여부 확인 (헤더에서 추출)
            cont_yn = resp.headers.get("cont-yn", "N")
            next_key = resp.headers.get("next-key", "")

            if cont_yn != "Y" or not next_key:
                break

    return results


CONTINUOUS_DAYS_QUERY = int(os.getenv("S3_CONTINUOUS_DAYS", "3"))  # API 조회 연속일


async def fetch_continuous_netbuy(token: str, market: str) -> dict:
    """ka10131 기관외국인연속매매 - 연속조회를 통해 전체 종목 가져오기"""
    result = {}
    next_key = ""

    async with kiwoom_client() as client:
        while True:
            # 1. 헤더 설정 (연속조회 키 포함)
            headers = {
                "api-id": "ka10131",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8"
            }
            if next_key:
                headers["cont-yn"] = "Y"
                headers["next-key"] = next_key

            # 2. 요청 바디
            payload = {
                "dt": str(CONTINUOUS_DAYS_QUERY),
                "mrkt_tp": market,
                "netslmt_tp": "2",
                "stk_inds_tp": "0",
                "amt_qty_tp": "0",
                "stex_tp": "3"
            }

            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/frgnistt",
                headers=headers,
                json=payload
            )
            resp.raise_for_status()
            data = resp.json()

            if not validate_kiwoom_response(data, "ka10131", logger):
                break

            # 3. 데이터 파싱 및 저장
            items = data.get("orgn_frgnr_cont_trde_prst", [])
            for x in items:
                stk_cd = normalize_stock_code(x.get("stk_cd"))
                if stk_cd:
                    raw_days = x.get("tot_cont_netprps_dys", "0")
                    # 부호(+) 제거 및 정수 변환
                    try:
                        result[stk_cd] = int(raw_days.replace("+", "").replace(",", ""))
                    except:
                        result[stk_cd] = 0

            # 4. 다음 페이지가 있는지 확인 (응답 헤더에서 추출)
            cont_yn = resp.headers.get("cont-yn", "N")
            next_key = resp.headers.get("next-key", "").strip()

            # 다음 데이터가 없으면 루프 종료
            if cont_yn != "Y" or not next_key:
                break

            # API 과부하 방지를 위한 미세한 대기 (선택 사항)
            # await asyncio.sleep(0.05)

    return result


import asyncio
from datetime import datetime

async def fetch_volume_compare(token: str, stk_cd: str, rdb=None, run_stats: Ka10055RunStats | None = None) -> float:
    """ka10055 당일전일체결량 - 동시간 거래량 비율"""

    # 현재 시간 추출 (HHMMSS 형식) - 전일 데이터의 동시간 필터링을 위함
    stk_cd = normalize_stock_code(stk_cd)
    if not stk_cd:
        return 0.0

    current_time = datetime.now(KST).strftime("%H%M%S")
    use_cache = flag_enabled("S3_KA10055_CACHE_ENABLED") and rdb is not None
    cache_key = f"strategy:s3:ka10055:{stk_cd}:{current_time[:4]}"
    if use_cache:
        cached = await cache_get_json(rdb, cache_key)
        if isinstance(cached, (int, float)):
            return float(cached)

    def warn(reason: str, tdy_pred: str, message: str, *args) -> None:
        if run_stats:
            run_stats.warn(reason, (stk_cd, tdy_pred), message, *args)
        else:
            logger.warning(message, *args)

    async def get_total_volume(tdy_pred: str) -> int:
        total_qty = 0
        next_key = ""
        page = 0
        requested_next_keys = set()
        prev_page_signature = None
        repeated_page_count = 0
        async with kiwoom_client() as client:
            while True:
                page += 1
                if page > _KA10055_MAX_PAGES:
                    warn("page_cap", tdy_pred,
                         "[S3] ka10055 %s/%s page cap(%d) reached, forced stop",
                         stk_cd, tdy_pred, _KA10055_MAX_PAGES)
                    break
                if next_key:
                    if next_key in requested_next_keys:
                        warn("next_key_loop", tdy_pred,
                             "[S3] ka10055 %s/%s next-key loop detected: %s", stk_cd, tdy_pred, next_key)
                        break
                    requested_next_keys.add(next_key)

                headers = {
                    "api-id": "ka10055",
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
                        "stk_cd": stk_cd,
                        "tdy_pred": tdy_pred
                    }
                )
                resp.raise_for_status()
                data = resp.json()

                if not validate_kiwoom_response(data, "ka10055", logger):
                    break

                items = data.get("tdy_pred_cntr_qty", [])
                # 빈 응답 = 휴장·시간외 등 더 이상 데이터 없음 → 즉시 종료
                if not items:
                    break

                page_qty = 0

                for x in items:
                    cntr_tm = x.get("cntr_tm", "")

                    # 전일(2) 데이터 수집 시, 현재 시간보다 늦은 체결 내역은 패스 (동시간 비교)
                    if tdy_pred == "2" and cntr_tm > current_time:
                        continue

                    raw_qty = x.get("cntr_qty", "0")
                    try:
                        # 키움 API는 매도(-), 매수(+) 기호가 포함되므로 절대값으로 순수 거래량만 합산
                        clean_qty = abs(int(raw_qty.replace("+", "").replace("-", "").replace(",", "")))
                        total_qty += clean_qty
                        page_qty += clean_qty
                    except ValueError:
                        pass

                page_signature = (
                    len(items),
                    items[0].get("cntr_tm", ""),
                    items[-1].get("cntr_tm", ""),
                    items[0].get("cntr_qty", ""),
                    items[-1].get("cntr_qty", ""),
                    page_qty,
                )
                if page_signature == prev_page_signature:
                    repeated_page_count += 1
                    if repeated_page_count >= 2:
                        warn("repeated_page", tdy_pred,
                             "[S3] ka10055 %s/%s repeated page payload detected - page=%d next_key=%s",
                             stk_cd, tdy_pred, page, next_key or "-")
                        break
                else:
                    repeated_page_count = 0
                prev_page_signature = page_signature

                cont_yn = resp.headers.get("cont-yn", "N")
                next_key = resp.headers.get("next-key", "").strip()

                # 다음 페이지가 없으면 루프 종료
                if cont_yn != "Y" or not next_key:
                    break

        return total_qty

    # 순차 실행 — 동시 호출 시 /api/dostk/stkinfo 429 과부하 발생
    async with perf_timer("s3_ka10055", rdb=rdb, fields={"stk_cd": stk_cd}):
        today_qty = await get_total_volume("1")
        await asyncio.sleep(_API_INTERVAL)
        prev_qty = await get_total_volume("2")

    # 전일 동시간 거래량이 0인 경우 ZeroDivisionError 방지
    ratio = today_qty / prev_qty if prev_qty > 0 else 0.0
    if use_cache:
        await cache_set_json(rdb, cache_key, ratio, _KA10055_CACHE_TTL)
    return ratio

async def scan_inst_foreign(token: str, market: str = "000", rdb=None) -> list:
    # 1. candidates:s3:{market} 풀 우선 확인
    pool_codes: list = []
    if rdb:
        try:
            pool_codes = await rdb.lrange(f"candidates:s3:{market}", 0, -1)
            if pool_codes:
                logger.debug("[S3] candidates:s3:%s 풀 사용 (%d개)", market, len(pool_codes))
        except Exception as e:
            logger.debug("[S3] 풀 조회 실패: %s", e)

    smtm_list = await fetch_intraday_investor(token, market)

    # 풀이 있으면 풀 종목만 필터
    if pool_codes:
        pool_set = {normalize_stock_code(code) for code in pool_codes if normalize_stock_code(code)}
        smtm_list = [it for it in smtm_list if normalize_stock_code(it.get("stk_cd")) in pool_set]
        logger.debug("[S3] 풀 필터 후 %d개", len(smtm_list))
    else:
        logger.debug("[S3] 풀 없음 – ka10063 전수 조회")

    # cont_map: stk_cd → actual continuous_days (API 응답에서 추출, 없으면 쿼리 기본값)
    cont_map = await fetch_continuous_netbuy(token, market)

    results = []
    ka10055_stats = Ka10055RunStats()
    scan_items = smtm_list[:5]
    for item in scan_items:  # 429 방지: ka10055×2 호출 상한 5종목
        stk_cd = normalize_stock_code(item.get("stk_cd"))
        if not stk_cd:
            continue
        if stk_cd not in cont_map:
            continue

        await asyncio.sleep(_API_INTERVAL)   # Rate limit: ka10055 × 2회 호출 전 대기
        vol_ratio = await fetch_volume_compare(token, stk_cd, rdb=rdb, run_stats=ka10055_stats)
        if vol_ratio < 1.5:
            continue

        # ka10063 실제 응답 필드: netprps_qty(순매수수량), netprps_amt(순매수금액)
        # net_buy_amt: 원(KRW) 단위 금액 사용 → scorer S3 `min(25, amt/1_000_000_000*25)` 기준
        try:
            raw_amt = str(item.get("netprps_amt", "0")).replace("+", "").replace(",", "")
            net_buy_amt = int(raw_amt) if raw_amt.lstrip("-").isdigit() else 0
        except (TypeError, ValueError):
            net_buy_amt = 0

        # 순매수 집중도: |netprps_qty| / acc_trde_qty * 100 (%)
        # smtm_netprps_tp="1" 필터 자체가 외인+기관 동시 순매수를 보장함
        try:
            net_qty = abs(int(str(item.get("netprps_qty", "0")).replace("+", "").replace(",", "").replace("-", "") or "0"))
            acc_qty = int(str(item.get("acc_trde_qty", "0")).replace("+", "").replace(",", "") or "0")
            buy_concentration_pct = round(net_qty / acc_qty * 100, 1) if acc_qty > 0 else 0.0
        except (TypeError, ValueError, ZeroDivisionError):
            buy_concentration_pct = 0.0

        # cur_prc, flu_rt: ka10063 응답에 포함 (부호 처리)
        try:
            cur_prc = abs(int(str(item.get("cur_prc", "0")).replace("+", "").replace(",", "").replace("-", "") or "0"))
        except (TypeError, ValueError):
            cur_prc = 0
        try:
            flu_rt = float(str(item.get("flu_rt", "0")).replace("+", "").replace(",", ""))
        except (TypeError, ValueError):
            flu_rt = 0.0

        continuous_days = cont_map.get(stk_cd, 1)
        stk_nm = str(item.get("stk_nm", "")).strip() or await fetch_stk_nm(rdb, token, stk_cd)

        # 동적 TP/SL — 일봉 기반 (기관+외인 수급 스윙 목표)
        highs_d, lows_d, closes_d, ma20, atr_val = [], [], [], None, None
        try:
            await asyncio.sleep(_API_INTERVAL)
            candles = await fetch_daily_candles(token, stk_cd)
            closes_d = [_safe_price(c.get("cur_prc")) for c in candles if _safe_price(c.get("cur_prc")) > 0]
            highs_d  = [_safe_price(c.get("high_pric")) for c in candles]
            lows_d   = [_safe_price(c.get("low_pric"))  for c in candles]
            if len(closes_d) >= 20:
                ma20 = sum(closes_d[:20]) / 20
            if len(highs_d) >= 14 and len(lows_d) >= 14 and len(closes_d) >= 14:
                atr_vals = calc_atr(highs_d, lows_d, closes_d, 14)
                atr_val  = atr_vals[0] if atr_vals and atr_vals[0] != 0.0 else None
        except Exception as e:
            logger.debug("[S3] 일봉 조회 실패 %s: %s", stk_cd, e)

        tp_sl = calc_tp_sl("S3_INST_FRGN", cur_prc, highs_d, lows_d, closes_d,
                            stk_cd=stk_cd, ma20=ma20, atr=atr_val)

        results.append({
            "stk_cd": stk_cd,
            "stk_nm": stk_nm,
            "cur_prc": cur_prc,
            "strategy": "S3_INST_FRGN",  # scorer.py case 키와 일치
            "net_buy_amt": net_buy_amt,    # 순매수금액(원) — scorer S3 min(25, amt/1_000_000_000*25)
            "flu_rt": round(flu_rt, 2),
            "vol_ratio": round(vol_ratio, 2),
            "continuous_days": continuous_days,
            "inst_frgn_smtm": True,        # smtm_netprps_tp="1" → 외인+기관 동시 순매수 확인
            "buy_concentration_pct": buy_concentration_pct,
            "entry_type": "지정가_1호가",
            **tp_sl.to_signal_fields(),
        })

    ka10055_stats.log_summary()
    return sorted(results, key=lambda x: x.get("net_buy_amt", 0), reverse=True)[:5]
