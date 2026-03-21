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
import httpx
import logging
import os

logger = logging.getLogger(__name__)

# NOTE: Python 전술 스캐너 경로 (ENABLE_STRATEGY_SCANNER=true 시 활성화).
# 메인 전술 실행은 api-orchestrator/StrategyService.java에서 이루어집니다.
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://mockapi.kiwoom.com")


async def fetch_intraday_investor(token: str, market: str = "000") -> list:
    """ka10063 장중투자자별매매 - 외인+기관 동시 순매수"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/mrkcond",
            headers={"api-id": "ka10063", "authorization": f"Bearer {token}",
                     "Content-Type": "application/json;charset=UTF-8"},
            json={
                "mrkt_tp": market,
                "amt_qty_tp": "1",
                "invsr": "6",          # 외국인
                "frgn_all": "1",
                "smtm_netprps_tp": "1",  # 동시순매수
                "stex_tp": "1"
            }
        )
        resp.raise_for_status()
        return resp.json().get("opmr_invsr_trde", [])


CONTINUOUS_DAYS_QUERY = int(os.getenv("S3_CONTINUOUS_DAYS", "3"))  # API 조회 연속일


async def fetch_continuous_netbuy(token: str, market: str) -> dict:
    """ka10131 기관외국인연속매매 - CONTINUOUS_DAYS_QUERY일 연속 순매수 종목 및 연속일 정보 반환"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/frgnistt",
            headers={"api-id": "ka10131", "authorization": f"Bearer {token}",
                     "Content-Type": "application/json;charset=UTF-8"},
            json={
                "dt": str(CONTINUOUS_DAYS_QUERY),
                "mrkt_tp": market,
                "netslmt_tp": "2",  # 순매수
                "stk_inds_tp": "0",
                "amt_qty_tp": "0",
                "stex_tp": "1"
            }
        )
        resp.raise_for_status()
        items = resp.json().get("orgn_for_cont_trde", [])
        # stk_cd → continuous_days 매핑. API 응답에 cont_dt 필드가 있으면 사용,
        # 없으면 쿼리에 사용한 연속일(CONTINUOUS_DAYS_QUERY)로 폴백
        result = {}
        for x in items:
            stk_cd = x.get("stk_cd")
            if stk_cd:
                # API 응답에서 실제 연속일 추출 시도 (cont_dt, cont_days 등 필드명 대응)
                actual_days = x.get("cont_dt") or x.get("cont_days") or x.get("continuous_days")
                try:
                    result[stk_cd] = int(actual_days) if actual_days is not None else CONTINUOUS_DAYS_QUERY
                except (TypeError, ValueError):
                    result[stk_cd] = CONTINUOUS_DAYS_QUERY
        return result


async def fetch_volume_compare(token: str, stk_cd: str) -> float:
    """ka10055 당일전일체결량 - 동시간 거래량 비율"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        today = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/stkinfo",
            headers={"api-id": "ka10055", "authorization": f"Bearer {token}",
                     "Content-Type": "application/json;charset=UTF-8"},
            json={"stk_cd": stk_cd, "tdy_pred": "1"}  # 당일
        )
        today.raise_for_status()
        prev = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/stkinfo",
            headers={"api-id": "ka10055", "authorization": f"Bearer {token}",
                     "Content-Type": "application/json;charset=UTF-8"},
            json={"stk_cd": stk_cd, "tdy_pred": "2"}  # 전일
        )
        prev.raise_for_status()

    today_qty = sum(int(x.get("cntr_qty", 0))
                    for x in today.json().get("tdy_pred_cntr_qty", []))
    prev_qty = sum(int(x.get("cntr_qty", 0))
                   for x in prev.json().get("tdy_pred_cntr_qty", []))

    return today_qty / prev_qty if prev_qty > 0 else 0

async def scan_inst_foreign(token: str, market: str = "000") -> list:
    smtm_list = await fetch_intraday_investor(token, market)
    # cont_map: stk_cd → actual continuous_days (API 응답에서 추출, 없으면 쿼리 기본값)
    cont_map = await fetch_continuous_netbuy(token, market)

    results = []
    for item in smtm_list[:30]:
        stk_cd = item.get("stk_cd")
        if stk_cd not in cont_map:
            continue

        vol_ratio = await fetch_volume_compare(token, stk_cd)
        if vol_ratio < 1.5:
            continue

        net_buy_amt = float(item.get("net_buy_amt", 0))
        # API 응답에서 실제 연속일 사용 (하드코딩 3 제거)
        continuous_days = cont_map.get(stk_cd, 1)
        results.append({
            "stk_cd": stk_cd,
            "strategy": "S3_INST_FRGN",
            "net_buy_amt": net_buy_amt,
            "vol_ratio": round(vol_ratio, 2),
            "continuous_days": continuous_days,
            "entry_type": "지정가_1호가",
            "target_pct": 3.5,
            "stop_pct": -2.0,
        })

    return sorted(results, key=lambda x: x["net_buy_amt"], reverse=True)[:5]
