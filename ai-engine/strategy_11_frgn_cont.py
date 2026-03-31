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

import httpx

from http_utils import validate_kiwoom_response

# NOTE: Python 전술 스캐너 경로 (ENABLE_STRATEGY_SCANNER=true 시 활성화).
# 메인 전술 실행은 api-orchestrator/StrategyService.java에서 이루어집니다.

logger = logging.getLogger(__name__)
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://mockapi.kiwoom.com")


def _parse_qty(val: str) -> int:
    """'+34396981', '-140' 형식의 수량 문자열 → 정수 변환"""
    try:
        return int(str(val).replace("+", "").replace(",", ""))
    except (TypeError, ValueError):
        return 0


async def fetch_frgn_cont_buy(token: str, market: str = "000") -> list[dict]:
    """ka10035 외인연속순매매상위요청 – 연속 순매수 상위 종목
    응답 배열키: for_cont_nettrde_upper
    파라미터: trde_tp=2(순매수), base_dt_tp=1(전일기준)
    응답 필드: dm1(D-1 수량), dm2(D-2 수량), dm3(D-3 수량), tot(누적합계)
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{KIWOOM_BASE_URL}/api/dostk/rkinfo",
            headers={
                "api-id": "ka10035",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
            },
            json={
                "mrkt_tp": market,
                "trde_tp": "2",       # 2: 연속순매수 (1: 연속순매도)
                "base_dt_tp": "1",    # 1: 전일기준
                "stex_tp": "1",       # KRX
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if not validate_kiwoom_response(data, "ka10035", logger):
            return []
        return data.get("for_cont_nettrde_upper", [])


async def scan_frgn_cont_swing(token: str, market: str = "000", rdb=None) -> list:
    """외국인 연속 순매수 스윙 전략 스캔"""
    # Java candidates:s11:{market} 풀 우선 사용 (Java 미실행 시 ka10035 폴백)
    pool: list[str] = []
    if rdb:
        try:
            pool = await rdb.lrange(f"candidates:s11:{market}", 0, 99)
        except Exception:
            pass

    if pool:
        raw_items = [{"stk_cd": c} for c in pool]
    else:
        raw_items = await fetch_frgn_cont_buy(token, market)

    results = []
    for item in raw_items:
        stk_cd = item.get("stk_cd")
        if not stk_cd:
            continue

        # D-1, D-2, D-3 각 일별 순매수 수량 확인 — 모두 양수여야 3일 연속 매수
        dm1 = _parse_qty(item.get("dm1", "0"))
        dm2 = _parse_qty(item.get("dm2", "0"))
        dm3 = _parse_qty(item.get("dm3", "0"))

        if not (dm1 > 0 and dm2 > 0 and dm3 > 0):
            continue

        # 누적 합계 (tot): 외국인 매집 강도 스코어링에 활용
        tot = _parse_qty(item.get("tot", "0"))
        if tot <= 0:
            continue

        # 등락률·현재가·체결강도는 응답에 없으므로 Redis에서 조회
        flu_rt = 0.0
        cur_prc = 0.0
        cntr_str = 100.0
        if rdb:
            try:
                tick = await rdb.hgetall(f"ws:tick:{stk_cd}")
                flu_rt = float(str(tick.get("flu_rt", "0")).replace("+", "").replace(",", ""))
                # 현재가 (부호 제거 후 절대값)
                raw_prc = tick.get("cur_prc", "")
                cur_prc = abs(float(raw_prc.replace(",", "").replace("+", "") or "0")) if raw_prc else 0.0
                # 체결강도: ws:strength(TTL 300s) 우선, 없으면 ws:tick(TTL 30s) fallback
                strength_data = await rdb.lrange(f"ws:strength:{stk_cd}", 0, 4)
                if strength_data:
                    cntr_str = sum(float(s) for s in strength_data) / len(strength_data)
                elif tick:
                    cntr_str = float(tick.get("cntr_str", 100))
            except Exception:
                pass

        # 당일 하락 또는 과열 제외
        if flu_rt <= 0 or flu_rt > 10.0:
            continue

        if cntr_str < 100.0:
            continue

        # 스코어: 누적 수량 비중 + 최근일(D-1) 매수 강도 + 등락률
        score = (tot / 1_000_000) * 5 + (dm1 / 1_000_000) * 3 + flu_rt * 0.5
        results.append({
            "stk_cd": stk_cd,
            "cur_prc": round(cur_prc) if cur_prc > 0 else None,
            "strategy": "S11_FRGN_CONT",
            "dm1": dm1,
            "dm2": dm2,
            "dm3": dm3,
            "tot": tot,
            "flu_rt": round(flu_rt, 2),
            "cntr_strength": round(cntr_str, 1),
            "score": round(score, 2),
            "entry_type": "당일종가_또는_익일시가",
            "holding_days": "5~7거래일",
            "target_pct": 8.0,
            "stop_pct": -4.0,
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]
