"""
전술 5: 프로그램 순매수 + 외인 동반 상위
수정 사항: ka90003 URI 변경 및 ka10044/ka10001 필터 로직 추가
"""
import asyncio
import httpx
import logging
import os
from datetime import datetime, timedelta
from statistics import mean

from http_utils import validate_kiwoom_response, fetch_stk_nm

logger = logging.getLogger(__name__)
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")
_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))

# 부호 및 콤마 제거 유틸리티
def clean_val(val) -> float:
    if not val: return 0.0
    return float(str(val).replace("+", "").replace("-", "").replace(",", ""))

async def fetch_program_netbuy(token: str, market: str) -> dict:
    """ka90003 프로그램순매수상위50 조회 (연속조회 포함)"""
    market_map = {"KOSPI": "P00101", "KOSDAQ": "P10102", "001": "P00101", "101": "P10102", "000": "P00101"}
    kiwoom_mrkt = market_map.get(market.upper(), "P00101")

    result = {}
    next_key = ""

    async with httpx.AsyncClient(timeout=10.0) as client:
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
                    "stex_tp": "1"         # KRX 고정
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
                    result[stk_cd] = int(clean_val(x.get("prm_netprps_amt", 0)))

            cont_yn = resp.headers.get("cont-yn", "N")
            next_key = resp.headers.get("next-key", "").strip()
            if cont_yn != "Y" or not next_key:
                break
    return result

async def fetch_frgn_inst_upper(token: str, market: str) -> set:
    """ka90009 외국인기관매매상위 - 외인 순매수 종목 코드 추출 (연속조회 포함)"""
    # ka90009는 시장코드가 001, 101 형태를 따름
    mrkt = "001" if market in ["KOSPI", "001", "000"] else "101"

    result_set = set()
    next_key = ""

    async with httpx.AsyncClient(timeout=10.0) as client:
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
                    "stex_tp": "1" # KRX 고정
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
    return result_set

async def check_extra_conditions(token: str, stk_cd: str, market: str = "001") -> bool:
    """전일 기관 순매수 여부 및 5분봉 5이평선 상단 확인"""
    try:
        # 전일 날짜 (단, 장 종료 후 호출 시 로직에 따라 당일/전일 조정 필요)
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        mrkt = "001" if market in ["KOSPI", "001", "000"] else "101"

        async with httpx.AsyncClient(timeout=10.0) as client:
            # 1. ka10044 전일 기관 순매수 리스트 확인
            inst_resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/mrkcond",
                headers={"api-id": "ka10044", "authorization": f"Bearer {token}", "Content-Type": "application/json;charset=UTF-8"},
                json={"strt_dt": yesterday, "end_dt": yesterday, "trde_tp": "2", "mrkt_tp": mrkt, "stex_tp": "1"}
            )
            inst_data = inst_resp.json()
            if validate_kiwoom_response(inst_data, "ka10044", logger):
                netbuy_list = inst_data.get("daly_orgn_trde_stk", [])
                if not any(item.get("stk_cd") == stk_cd for item in netbuy_list):
                    return False
            else:
                return False

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
                    return cur_prc >= ma5
            return False
    except Exception as e:
        logger.debug(f"[S5_Extra] {stk_cd} 필터 제외: {e}")
        return False

async def scan_program_buy(token: str, market: str = "000", rdb=None) -> list:
    """전술 5 메인 스캔 함수"""
    # 1. 기초 데이터 동시 수집
    prog_map, frgn_set = await asyncio.gather(
        fetch_program_netbuy(token, market),
        fetch_frgn_inst_upper(token, market)
    )

    # 2. 프로그램 순매수 & 외인 순매수 교집합 추출
    overlap = set(prog_map.keys()) & frgn_set
    results = []

    # 3. 교집합 종목들에 대해 정밀 필터 적용
    for stk_cd in overlap:
        await asyncio.sleep(_API_INTERVAL) # 과부하 방지
        if await check_extra_conditions(token, stk_cd, market):
            stk_nm = await fetch_stk_nm(rdb, token, stk_cd)
            results.append({
                "stk_cd": stk_cd,
                "stk_nm": stk_nm,
                "strategy": "프로그램_기관_수급",
                "net_buy_amt": prog_map[stk_cd],
                "entry_type": "지정가_1호가",
                "target_pct": 3.0,
                "stop_pct": -2.0,
            })

    # 순매수 금액 상위 5개 반환
    return sorted(results, key=lambda x: x["net_buy_amt"], reverse=True)[:5]
