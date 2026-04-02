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

from http_utils import validate_kiwoom_response, fetch_stk_nm

logger = logging.getLogger(__name__)

# 키움 REST API 초당 약 5회 제한 → 루프 내 0.25s 대기
_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))

# NOTE: Python 메인 전술 실행자 (strategy_runner.py 에서 호출).
# Java api-orchestrator 는 토큰 관리·후보 풀 적재(candidates:s{N}:{market})만 담당.
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://mockapi.kiwoom.com")


async def fetch_intraday_investor(token: str, market_type: str = "000") -> list:
    """
    ka10063 장중투자자별매매 - 외인+기관 동시 순매수 종목 조회
    :param token:
    :param market_type: "000":전체, "001":코스피, "101":코스닥
    """
    results = []
    next_key = ""

    async with httpx.AsyncClient(timeout=10.0) as client:
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
                "stex_tp": "1"          # KRX
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

    async with httpx.AsyncClient(timeout=10.0) as client:
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
                "stex_tp": "1"
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
                stk_cd = x.get("stk_cd")
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

async def fetch_volume_compare(token: str, stk_cd: str) -> float:
    """ka10055 당일전일체결량 - 동시간 거래량 비율"""

    # 현재 시간 추출 (HHMMSS 형식) - 전일 데이터의 동시간 필터링을 위함
    current_time = datetime.now().strftime("%H%M%S")

    async def get_total_volume(tdy_pred: str) -> int:
        total_qty = 0
        next_key = ""

        async with httpx.AsyncClient(timeout=10.0) as client:
            while True:
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
                    except ValueError:
                        pass

                cont_yn = resp.headers.get("cont-yn", "N")
                next_key = resp.headers.get("next-key", "").strip()

                # 다음 페이지가 없으면 루프 종료
                if cont_yn != "Y" or not next_key:
                    break

        return total_qty

    # 당일(1)과 전일(2) 볼륨 수집을 비동기로 동시 실행 (속도 대폭 향상)
    today_qty, prev_qty = await asyncio.gather(
        get_total_volume("1"),
        get_total_volume("2")
    )

    # 전일 동시간 거래량이 0인 경우 ZeroDivisionError 방지
    return today_qty / prev_qty if prev_qty > 0 else 0.0

async def scan_inst_foreign(token: str, market: str = "000", rdb=None) -> list:
    smtm_list = await fetch_intraday_investor(token, market)
    # cont_map: stk_cd → actual continuous_days (API 응답에서 추출, 없으면 쿼리 기본값)
    cont_map = await fetch_continuous_netbuy(token, market)

    results = []
    for item in smtm_list[:30]:
        stk_cd = item.get("stk_cd")
        if stk_cd not in cont_map:
            continue

        await asyncio.sleep(_API_INTERVAL)   # Rate limit: ka10055 × 2회 호출 전 대기
        vol_ratio = await fetch_volume_compare(token, stk_cd)
        if vol_ratio < 1.5:
            continue

        net_buy_amt = float(item.get("net_buy_amt", 0))
        # API 응답에서 실제 연속일 사용 (하드코딩 3 제거)
        continuous_days = cont_map.get(stk_cd, 1)
        stk_nm = str(item.get("stk_nm", "")).strip() or await fetch_stk_nm(rdb, token, stk_cd)
        results.append({
            "stk_cd": stk_cd,
            "stk_nm": stk_nm,
            "strategy": "슈급 집중!",
            "net_buy_amt": net_buy_amt,
            "vol_ratio": round(vol_ratio, 2),
            "continuous_days": continuous_days,
            "entry_type": "지정가_1호가",
            "target_pct": 3.5,
            "stop_pct": -2.0,
        })

    return sorted(results, key=lambda x: x["net_buy_amt"], reverse=True)[:5]
