from __future__ import annotations
"""전술 2: VI 발동 후 눌림목 재진입
타이밍: 장중 상시 (VI 발동 이벤트 기반)
진입 조건 (순서대로):

1h WebSocket → VI 발동 이벤트 수신 (동적 VI 우선)
VI 발동 당시 거래량이 직전 5분 대비 ≥ 3배
VI 해제 후 현재가가 VI 발동가 대비 -1% ~ -3% 눌림
호가잔량 매수/매도 비율 ≥ 1.3 (0D)
체결강도 ≥ 110% 유지 중"""

from collections import defaultdict
import os
import logging

import httpx

from http_utils import fetch_cntr_strength_cached, fetch_hoga, fetch_same_time_volume_ratio, fetch_stk_nm
from indicator_atr import get_atr_minute
from redis_reader import get_hoga_with_status, get_tick_with_status
from tp_sl_engine import calc_tp_sl

# NOTE: Python 메인 전술 실행자 (strategy_runner.py 에서 호출).
# Java api-orchestrator 는 토큰 관리·후보 풀 적재(candidates:s{N}:{market})만 담당.
# rdb (redis.asyncio.Redis) 는 strategy_runner.py 에서 전달받습니다.

logger = logging.getLogger(__name__)
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")

# Feature flag: ENABLE_S2_STRICT_VOLUME_GATE=true 시 vi_vol_ratio/vi_amount_ratio
# 미달 종목을 hard reject. false 여도 payload 필드는 항상 포함됨.
ENABLE_S2_STRICT_VOLUME_GATE = (
    os.getenv("ENABLE_S2_STRICT_VOLUME_GATE", "true").lower() == "true"
)

VI_VOL_RATIO_THRESHOLD = 3.0
VI_AMOUNT_RATIO_THRESHOLD = 3.0
S2_KA10055_ENRICH_ENABLED = (
    os.getenv("S2_KA10055_ENRICH_ENABLED", "true").lower() == "true"
)

# 2차 VI 위험 판단: VI 해제 후 이 시간(초) 이내에 같은 종목 VI 재발동 이력이 있으면 HIGH
SECONDARY_VI_RISK_WINDOW_SEC = 300  # 5분

vi_events = defaultdict(list)  # stk_cd → [vi_event, ...]


def _num(value) -> float:
    try:
        return abs(float(str(value).replace("+", "").replace(",", "")))
    except (TypeError, ValueError):
        return 0.0


def _parse_vi_vol_ratio(vi_data: dict) -> tuple[float, float, str]:
    """vi:{stk_cd} Redis 해시에서 vi_vol_ratio, vi_amount_ratio, vi_volume_source 추출.

    반환: (vol_ratio, amount_ratio, source)
    source: 'realtime_diff' | 'candle_avg' | 'unknown'
    """
    source = vi_data.get("vi_volume_source", "unknown")
    try:
        vol_ratio = float(vi_data.get("vi_vol_ratio", 0))
    except (TypeError, ValueError):
        vol_ratio = 0.0
    try:
        amount_ratio = float(vi_data.get("vi_amount_ratio", 0))
    except (TypeError, ValueError):
        amount_ratio = 0.0
    return vol_ratio, amount_ratio, source


def is_publishable_signal(signal: dict | None) -> bool:
    """S2 자동 발행 가능 여부. 실전 기준 미달 후보는 fail-closed로 제외한다."""
    if not signal:
        return False
    if signal.get("signal_mode") != "SHADOW":
        return True
    return False


async def handle_vi_event(rdb, event: dict):
    """VI 발동/해제 이벤트 처리 (비동기 Redis).

    발동 시: vi:{stk_cd} 해시에 거래량/거래대금 배수 관련 필드를 저장한다.
    - vi_vol_ratio: VI 발동 전후 거래량 배수 (실시간 차분 우선, 없으면 0)
    - vi_amount_ratio: VI 발동 전후 거래대금 배수
    - vi_volume_source: 데이터 출처 (realtime_diff / candle_avg / unknown)
    - vi_time: VI 발동 시각 (ISO)
    - is_dynamic: 동적 VI 여부
    """
    stk_cd = event.get("stk_cd")
    vi_type = event.get("vi_type")      # 1:정적, 2:동적, 3:동적+정적
    status = event.get("vi_stat")       # 1:발동, 2:해제
    vi_price = float(event.get("vi_pric", 0))
    volume = int(event.get("acc_trde_qty", 0))

    key = f"vi:{stk_cd}"

    if status == "1":  # 발동
        from datetime import datetime, timezone, timedelta
        _KST = timezone(timedelta(hours=9))
        vi_time = datetime.now(_KST).isoformat()
        vi_events[stk_cd].append({"ts": datetime.now(_KST).timestamp(), "vi_type": vi_type})
        cutoff_ts = datetime.now(_KST).timestamp() - SECONDARY_VI_RISK_WINDOW_SEC
        vi_events[stk_cd] = [e for e in vi_events[stk_cd] if e.get("ts", 0) >= cutoff_ts]
        recent_vi_count = len(vi_events[stk_cd])

        # 거래량/거래대금 배수 산출 시도
        # 우선순위: 실시간 체결 누적 차분 → 직전 5분봉 평균 → 산출 불가(unknown)
        vol_ratio = 0.0
        amount_ratio = 0.0
        vol_source = "unknown"

        if rdb:
            try:
                # 실시간 체결 체결강도 데이터에서 누적 거래량 차분 시도
                tick_result = await get_tick_with_status(rdb, stk_cd)
                tick = tick_result["data"]
                if tick:
                    acc_qty_now = _num(tick.get("acc_trde_qty", 0))
                    acc_amt_now = _num(tick.get("acc_trde_prica", 0))

                    # 직전 5분봉 평균 거래량을 ma_utils로 취득 (비동기 없이 Redis로만)
                    # ws:tick에 5분 전 스냅샷이 없으므로 candle_avg 경로로 추정
                    # 현재 구현: ws:tick 누적값을 활용한 간단 배수 산출
                    # 정밀 산출은 ka10080 분봉 데이터가 필요하나 이벤트 핸들러에서
                    # 외부 API 호출은 레이턴시 문제로 제한. volume 필드 자체로 추정.
                    if acc_qty_now > 0 and volume > 0:
                        # event의 acc_trde_qty(누적)와 tick 누적의 비율이 아니라
                        # 최근 5분 평균 대비 발동 시점 체결량이 필요함.
                        # 여기서는 tick에 prev_5m_avg_qty 필드가 있으면 활용.
                        prev5 = _num(tick.get("prev_5m_avg_qty", 0))
                        prev5_amt = _num(tick.get("prev_5m_avg_amt", 0))
                        if prev5 > 0:
                            vol_ratio = acc_qty_now / prev5
                            vol_source = "realtime_diff"
                            if prev5_amt > 0:
                                amount_ratio = acc_amt_now / prev5_amt
                            else:
                                amount_ratio = vol_ratio  # 금액 데이터 없으면 거래량 비율 동일 적용
            except Exception as e:
                logger.debug("[S2] handle_vi_event vol_ratio 산출 실패 %s: %s", stk_cd, e)

        # realtime_diff 실패 시 volume 필드만으로 candle_avg 경로 표시
        if vol_source == "unknown" and volume > 0:
            # 단순 보관: 발동 시 누적량을 저장해두고 check_vi_pullback에서 판단
            vol_source = "candle_avg"
            # vol_ratio는 후속 check에서 Redis 데이터로 보완되므로 0으로 둠

        await rdb.hset(key, mapping={
            "vi_price": str(vi_price),
            "vi_time": vi_time,
            "vi_type": vi_type,
            "vi_volume": str(volume),
            "vi_vol_ratio": str(vol_ratio),
            "vi_amount_ratio": str(amount_ratio),
            "vi_volume_source": vol_source,
            "is_dynamic": "1" if vi_type in ("2", "3") else "0",
            "recent_vi_count": str(recent_vi_count),
            "status": "active",
        })
        await rdb.expire(key, 3600)

    elif status == "2":  # 해제 → 눌림목 감시 시작
        from datetime import datetime, timezone, timedelta
        _KST = timezone(timedelta(hours=9))
        vi_data = await rdb.hgetall(key)
        if not vi_data:
            return
        await rdb.hset(key, "status", "released")
        # 눌림목 감시 큐에 등록
        import json
        import time
        await rdb.lpush("vi_watch_queue", json.dumps({
            "stk_cd": stk_cd,
            "vi_price": float(vi_data["vi_price"]),
            "watch_until": int((time.time() + 600) * 1000),  # 10분 감시 (밀리초, Java와 일치)
            "is_dynamic": vi_data.get("vi_type") in ("2", "3"),
        }))


def _assess_secondary_vi_risk(vi_data: dict) -> str:
    """2차 VI 재발동 위험을 판단한다.

    vi:{stk_cd} 해시의 필드를 바탕으로 SECONDARY_VI_RISK_WINDOW_SEC 이내에
    같은 종목이 VI 발동 이력을 가졌는지 확인한다.

    반환: 'HIGH' | 'LOW'
    """
    import time as _time
    from datetime import datetime, timezone, timedelta

    vi_time_str = vi_data.get("vi_time", "")
    if not vi_time_str:
        return "LOW"

    try:
        _KST = timezone(timedelta(hours=9))
        vi_dt = datetime.fromisoformat(vi_time_str)
        elapsed = _time.time() - vi_dt.timestamp()
        recent_count = int(_num(vi_data.get("recent_vi_count", vi_data.get("vi_event_count", 0))))
        status = str(vi_data.get("status", "") or "").lower()
        # 실제 반복 발동 이력이 있거나, 해제 직후 재감시 상태임이 명시된 경우만 HIGH로 본다.
        if 0 < elapsed < SECONDARY_VI_RISK_WINDOW_SEC and (
            recent_count >= 2 or status in {"retriggered", "secondary_risk"}
        ):
            return "HIGH"
    except Exception:
        pass

    return "LOW"


async def check_vi_pullback(token: str, watch_item: dict, rdb=None) -> dict | None:
    """VI 눌림목 진입 조건 체크.

    수정 사항 (2026-05-06):
    - vi_vol_ratio < 3.0 OR vi_amount_ratio < 3.0 → hard reject (ENABLE_S2_STRICT_VOLUME_GATE=true)
    - vi_volume_source=unknown 또는 ratio 산출 불가 → 실전 신호 생성 보류
    - payload에 vi_vol_ratio, vi_amount_ratio, volume_quality, secondary_vi_risk 포함
    """
    stk_cd = watch_item["stk_cd"]
    vi_price = watch_item["vi_price"]

    if not rdb:
        return None

    # 1. 현재가 조회 (ws:tick)
    tick_result = await get_tick_with_status(rdb, stk_cd)
    cur = tick_result["data"]
    if not cur:
        return None

    cur_price = _num(cur.get("cur_prc", 0))
    if cur_price == 0:
        return None

    # [조건 1] 눌림 범위 체크: -1% ~ -3% (가장 먼저 탈락시킴)
    pullback_pct = (cur_price - vi_price) / vi_price * 100
    if not (-3.0 <= pullback_pct <= -1.0):
        return None

    # [조건 2] 거래량/거래대금 배수 체크 (VI 발동 시 저장된 데이터)
    vi_data = await rdb.hgetall(f"vi:{stk_cd}")
    vi_vol_ratio, vi_amount_ratio, vol_source = _parse_vi_vol_ratio(vi_data)

    volume_quality: str
    signal_mode: str | None = None  # None = 정상 모드

    if vol_source == "unknown" or (vi_vol_ratio == 0.0 and vi_amount_ratio == 0.0):
        logger.debug("[S2] %s vol_ratio 산출 불가 → 신호 생성 보류", stk_cd)
        return None
    elif ENABLE_S2_STRICT_VOLUME_GATE and (
        vi_vol_ratio < VI_VOL_RATIO_THRESHOLD or vi_amount_ratio < VI_AMOUNT_RATIO_THRESHOLD
    ):
        # Strict gate 활성화 + 배수 미달 → hard reject
        logger.debug(
            "[S2] %s vi_vol_ratio=%.2f vi_amount_ratio=%.2f < %.1f → hard reject",
            stk_cd, vi_vol_ratio, vi_amount_ratio, VI_VOL_RATIO_THRESHOLD,
        )
        return None
    else:
        # 배수 정상 or strict gate 비활성화
        if vi_vol_ratio >= VI_VOL_RATIO_THRESHOLD and vi_amount_ratio >= VI_AMOUNT_RATIO_THRESHOLD:
            volume_quality = "CONFIRMED"
        elif vi_vol_ratio >= VI_VOL_RATIO_THRESHOLD or vi_amount_ratio >= VI_AMOUNT_RATIO_THRESHOLD:
            volume_quality = "PARTIAL"
        else:
            logger.debug("[S2] %s vol_ratio 미달 (strict gate off) → 신호 생성 보류", stk_cd)
            return None

    # [조건 3] 2차 VI 위험 판단
    secondary_vi_risk = _assess_secondary_vi_risk(vi_data)

    # [조건 3-1] VI 해제 후 반등 고점 회복 확인.
    # Redis가 post_release_high/rebound_high를 제공하는 경우에만 hard check한다.
    rebound_high = _num(
        vi_data.get("post_release_high", vi_data.get("rebound_high", vi_data.get("release_rebound_high", 0)))
    )
    rebound_reference = _num(vi_data.get("release_price", vi_price)) or vi_price
    rebound_high_breakout = "UNKNOWN"
    if rebound_high > 0:
        rebound_high_breakout = "PASS" if rebound_high >= rebound_reference else "FAIL"
        if rebound_high_breakout == "FAIL":
            logger.debug(
                "[S2] %s rebound high %.0f failed to retake %.0f",
                stk_cd, rebound_high, rebound_reference,
            )
            return None

    # [조건 4] 호가잔량 매수/매도 비율 체크 (ws:hoga — 0D 구독 데이터)
    hoga_result = await get_hoga_with_status(rdb, stk_cd)
    hoga = hoga_result["data"]
    bid_qty = _num(hoga.get("total_buy_bid_req", 0))
    ask_qty = _num(hoga.get("total_sel_bid_req", 0))
    bid_ratio = bid_qty / ask_qty if ask_qty > 0 else 0
    if bid_ratio <= 0:
        rest_ratio = await fetch_hoga(token, stk_cd, rdb=rdb)
        bid_ratio = rest_ratio if rest_ratio is not None else 0
    if bid_ratio < 1.3:
        return None

    # [조건 5] 체결강도 체크 (가장 무거운 작업 - 외부 API 호출)
    # 위 조건들을 모두 통과한 종목에 대해서만 API를 호출하여 쿼터 절약
    strength, _ = await fetch_cntr_strength_cached(token, stk_cd, rdb=rdb)
    if strength < 110:
        return None

    same_time_volume_ratio = 0.0
    same_time_volume_meta = {}
    if S2_KA10055_ENRICH_ENABLED:
        try:
            volume_summary, same_time_volume_meta = await fetch_same_time_volume_ratio(token, stk_cd)
            same_time_volume_ratio = float(volume_summary.get("same_time_volume_ratio") or 0.0)
            if same_time_volume_ratio >= 3.0 and volume_quality in {"UNKNOWN", "LOW", "PARTIAL"}:
                volume_quality = "CONFIRMED_BY_KA10055"
                signal_mode = None
        except Exception as exc:
            logger.debug("[S2] ka10055 volume enrich failed [%s]: %s", stk_cd, exc)

    stk_nm = await fetch_stk_nm(rdb, token, stk_cd)

    # 동적 TP/SL — 5분봉 ATR 기반 (VI 눌림목 = 단기 변동성 기준)
    atr_val = None
    try:
        atr_result = await get_atr_minute(token, stk_cd, tic_scope="5", period=7)
        atr_val = atr_result.atr
    except Exception:
        pass
    # vi_price: VI 발동가 → TP 목표 (VI 레벨 재탈환)
    tp_sl = calc_tp_sl("S2_VI_PULLBACK", cur_price, [], [], [],
                        stk_cd=stk_cd, atr=atr_val,
                        vi_price=vi_price if vi_price > cur_price else None,
                        min_rr=0.9)

    payload = {
        "stk_cd": stk_cd,
        "stk_nm": stk_nm,
        "cur_prc": round(cur_price),
        "strategy": "S2_VI_PULLBACK",
        "vi_price": vi_price,
        "pullback_pct": round(pullback_pct, 2),
        "cntr_strength": round(strength, 1),
        "bid_ratio": round(bid_ratio, 2),
        "is_dynamic": bool(watch_item.get("is_dynamic", False)),
        "entry_type": "지정가_눌림목",
        # 거래량 품질 필드 (항상 포함)
        "vi_vol_ratio": round(vi_vol_ratio, 2),
        "vi_amount_ratio": round(vi_amount_ratio, 2),
        "same_time_volume_ratio": round(same_time_volume_ratio, 2),
        "same_time_volume_meta": same_time_volume_meta,
        "volume_quality": volume_quality,
        "secondary_vi_risk": secondary_vi_risk,
        "rebound_high_breakout": rebound_high_breakout,
        **tp_sl.to_signal_fields(),
    }

    # SHADOW 모드: signal_mode 필드 추가 (자동 ENTER 불가 표시)
    if signal_mode:
        payload["signal_mode"] = signal_mode

    return payload
