"""
전술 5: 프로그램 순매수 + 외인 동반 상위
수정 사항: ka90003 URI 변경 및 ka10044/ka10001 필터 로직 추가
"""
import asyncio
import httpx
import logging
import os

from http_utils import validate_kiwoom_response

logger = logging.getLogger(__name__)
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")
_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))

# ka90003 mrkt_tp 매핑: 내부 시장코드 → Kiwoom P-코드
_KA90003_MRKT = {"001": "P00101", "101": "P10102", "000": "P00101"}

async def fetch_program_netbuy(token: str, market: str) -> dict:
    """ka90003 프로그램순매수상위50 (URI: /api/dostk/stkinfo)"""
    kiwoom_mrkt = _KA90003_MRKT.get(market, "P00101")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/stkinfo",
            headers={"api-id": "ka90003", "authorization": f"Bearer {token}",
                     "Content-Type": "application/json;charset=UTF-8"},
            json={
                "trde_upper_tp": "2", "amt_qty_tp": "1",
                "mrkt_tp": kiwoom_mrkt, "stex_tp": "1"
            }
        )
        resp.raise_for_status()
        data = resp.json()
        if not validate_kiwoom_response(data, "ka90003", logger):
            return {}
        items = data.get("prm_netprps_upper_50", [])
        return {x["stk_cd"]: int(str(x.get("prm_netprps_amt", "0")).replace("+", "").replace(",", "") or 0)
                for x in items if x.get("stk_cd")}

async def fetch_frgn_inst_upper(token: str, market: str) -> set:
    """ka90009 외국인기관매매상위 (URI: rkinfo)"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/rkinfo",
            headers={"api-id": "ka90009", "authorization": f"Bearer {token}",
                     "Content-Type": "application/json;charset=UTF-8"},
            json={"mrkt_tp": market, "amt_qty_tp": "1", "qry_dt_tp": "0", "stex_tp": "1"}
        )
        resp.raise_for_status()
        data = resp.json()
        if not validate_kiwoom_response(data, "ka90009", logger):
            return set()
        # 응답키: frgnr_orgn_trde_upper, 외인 순매수 종목코드 필드: for_netprps_stk_cd
        return {x["for_netprps_stk_cd"]
                for x in data.get("frgnr_orgn_trde_upper", [])
                if x.get("for_netprps_stk_cd")}

async def check_extra_conditions(token: str, stk_cd: str) -> bool:
    """ka10044 전일 기관 순매수 & ka10001 5일 이평선 상단 확인"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # 1. 일별 기관 매매 (ka10044)
            dly = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/stkinfo",
                headers={"api-id": "ka10044", "authorization": f"Bearer {token}"},
                json={"stk_cd": stk_cd}
            )
            # index 1이 전일 데이터 (0은 당일 진행중)
            inst_data = dly.json().get("inst_frgn_trde_tm", [])
            if len(inst_data) < 2 or int(inst_data[1].get("inst_net_buy_qty", 0)) <= 0:
                return False

            # 2. 주식기본정보 (ka10001) - 이평선 확인
            info = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/stkinfo",
                headers={"api-id": "ka10001", "authorization": f"Bearer {token}"},
                json={"stk_cd": stk_cd}
            )
            item = info.json().get("stk_info", [{}])[0]
            cur_prc = abs(float(item.get("cur_prc", 0)))
            ma5 = float(item.get("moving_avg_5", 0))

            return cur_prc >= ma5 if ma5 > 0 else False
    except Exception:
        return False

async def scan_program_buy(token: str, market: str = "000") -> list:
    prog_map, frgn_set = await asyncio.gather(
        fetch_program_netbuy(token, market),
        fetch_frgn_inst_upper(token, market)
    )

    overlap = set(prog_map.keys()) & frgn_set
    results = []

    for stk_cd in overlap:
        await asyncio.sleep(_API_INTERVAL) # 초당 호출 제한 방지
        if await check_extra_conditions(token, stk_cd):
            results.append({
                "stk_cd": stk_cd,
                "strategy": "S5_PROG_FRGN",
                "net_buy_amt": prog_map[stk_cd],
                "entry_type": "지정가_1호가",
                "target_pct": 3.0,
                "stop_pct": -2.0,
            })

    return sorted(results, key=lambda x: x["net_buy_amt"], reverse=True)[:5]
