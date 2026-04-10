import asyncio
import httpx
import os
import logging
from datetime import datetime

from http_utils import validate_kiwoom_response, fetch_cntr_strength, fetch_stk_nm, kiwoom_client
from indicator_atr import get_atr_minute
from ma_utils import fetch_daily_candles, _safe_price
from tp_sl_engine import calc_tp_sl

_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))
logger = logging.getLogger(__name__)

KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")


async def get_expected_execution(rdb, stk_cd: str) -> dict:
    """0H 주식예상체결 WebSocket 데이터 → Redis에서 조회 (비동기)"""
    try:
        return await rdb.hgetall(f"ws:expected:{stk_cd}")
    except Exception:
        return {}


async def fetch_gap_candidates(token: str) -> list:
    """ka10029 예상체결등락률상위 호출 → 갭 3~15% 후보 반환 (연속조회 적용)"""
    result = []
    next_key = ""

    try:
        async with kiwoom_client() as client:
            while True:
                headers = {
                    "api-id": "ka10029",
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
                        "mrkt_tp": "000",
                        "sort_tp": "1",         # 상승률
                        "trde_qty_cnd": "10",   # 만주이상
                        "stk_cnd": "1",         # 관리종목제외
                        "crd_cnd": "0",
                        "pric_cnd": "8",        # 1천원이상
                        "stex_tp": "3"          # krx
                    },
                )
                data = resp.json()
                if not validate_kiwoom_response(data, "ka10029", logger):
                    break

                items = data.get("exp_cntr_flu_rt_upper", [])
                for item in items:
                    try:
                        # 부호(+,-) 제거 후 float 변환
                        flu_rt = float(item.get("flu_rt", "0").replace("+", "").replace(",", ""))
                        if 3.0 <= flu_rt <= 15.0:
                            result.append(item.get("stk_cd"))
                    except ValueError:
                        continue

                # 연속조회 처리
                cont_yn = resp.headers.get("cont-yn", "N")
                next_key = resp.headers.get("next-key", "").strip()

                if cont_yn != "Y" or not next_key:
                    break

        return list(set(result)) # 중복 방지
    except Exception as e:
        logger.warning("[S1] ka10029 호출 실패: %s", e)
        return []


async def scan_gap_opening(token: str, candidates: list, rdb=None) -> list:
    """예상체결가 및 체결강도 기반 최종 시초가 진입 후보 스캔"""
    effective = candidates
    results = []

    for stk_cd in effective:
        exp = await get_expected_execution(rdb, stk_cd) if rdb else {}
        if not exp:
            continue

        try:
            # 1. 예상 체결가 파싱 (Java가 파싱한 영문키 or Kiwoom Raw FID '10' 대응)
            raw_exp_price = exp.get("exp_cntr_pric") or exp.get("10", "0")
            exp_price = abs(int(str(raw_exp_price).replace("+", "").replace("-", "").replace(",", "")))

            # 2. 예상 등락률 파싱 (ws:expected 저장 키: exp_flu_rt, FID 12)
            raw_gap_pct = exp.get("exp_flu_rt") or exp.get("12", "0")
            gap_pct = float(str(raw_gap_pct).replace("+", "").replace(",", ""))
        except ValueError:
            continue

        if exp_price <= 0 or gap_pct < 2.5:  # 갭 3% → 2.5% (후보 유연화)
            continue

        # API 호출 제한 속도 조절
        await asyncio.sleep(_API_INTERVAL)
        strength = await fetch_cntr_strength(token, stk_cd)

        if strength < 120.0:  # 체결강도 130% → 120% (후보 유연화)
            continue

        stk_nm = await fetch_stk_nm(rdb, token, stk_cd)

        # 스코어링 로직 (갭상승률과 체결강도 가중치 반영)
        score = (gap_pct * 0.5) + ((strength - 100) * 0.5)

        # 동적 TP/SL — 전일 종가(갭 베이스) + 5분봉 ATR 기반
        atr_val    = None
        prev_close = None
        try:
            await asyncio.sleep(_API_INTERVAL)
            atr_result = await get_atr_minute(token, stk_cd, tic_scope="5", period=7)
            atr_val = atr_result.atr
        except Exception:
            pass
        try:
            # 전일 종가 = 일봉 2번째(index 1) — SL(갭 필) 기준
            daily = await fetch_daily_candles(token, stk_cd, target_count=2)
            if len(daily) >= 2:
                prev_close = _safe_price(daily[1].get("cur_prc"))
        except Exception:
            pass
        tp_sl = calc_tp_sl("S1_GAP_OPEN", exp_price, [], [], [],
                            stk_cd=stk_cd, atr=atr_val, prev_close=prev_close)

        results.append({
            "stk_cd": stk_cd,
            "stk_nm": stk_nm,
            "cur_prc": exp_price,   # 예상체결가 = 시초가 진입가
            "strategy": "S1_GAP_OPEN",
            "gap_pct": round(gap_pct, 2),
            "cntr_strength": round(strength, 1),
            "score": round(score, 2),
            "entry_type": "시초가_시장가",
            **tp_sl.to_signal_fields(),
        })

    # 스코어 기준 내림차순 정렬 후 상위 5개 반환
    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]
