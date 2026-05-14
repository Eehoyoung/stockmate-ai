from __future__ import annotations
"""
전술 6: 섹터 강세 확산 포착 (S6_THEME_LAGGARD)

3개 모드로 평가:
  LEADER_PULLBACK    — 섹터 주도주, rank_pct>=70% & flu_rt 3~8%
  SECONDARY_ROTATION — 2/3등주 수급 확산, rank_pct>=30% & flu_rt 1~5%
  LAGGARD_CATCHUP    — 기존 후발주 로직, flu_rt 0.5~4%

공통 조건: 테마 상승률 +1.5% 이상, 체결강도 115 이상, 거래량비율 1.5배 이상(소프트)
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from http_utils import (
    fetch_cntr_strength_cached,
    fetch_hoga,
    fetch_stk_nm,
    kiwoom_client,
    validate_kiwoom_response,
)
from indicator_atr import calc_atr
from ma_utils import _safe_price, fetch_daily_candles
from tp_sl_engine import calc_tp_sl
from utils import safe_float as clean_num

logger = logging.getLogger(__name__)

_API_INTERVAL   = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")


def _redis_text(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return str(value)


def _redis_hash_text(data: dict | None) -> dict[str, str]:
    decoded: dict[str, str] = {}
    for key, value in (data or {}).items():
        decoded[_redis_text(key)] = _redis_text(value)
    return decoded

# ── 모드 상수 ──────────────────────────────────────────────────────────────
S6_MODE_LEADER    = "LEADER_PULLBACK"
S6_MODE_SECONDARY = "SECONDARY_ROTATION"
S6_MODE_LAGGARD   = "LAGGARD_CATCHUP"

# ── 임계값 ────────────────────────────────────────────────────────────────
_MIN_THEME_FLU_RT       = 1.5    # 테마 최소 상승률 (%)
_MIN_STR_COMMON         = 115.0  # 공통 최소 체결강도
_MIN_STR_LAGGARD        = 120.0  # 후발주 최소 체결강도
_MIN_VOL_RATIO_COMMON   = 1.5    # 공통 최소 거래량비율 (소프트: 미조회시 허용)
_MIN_VOL_RATIO_LAGGARD  = 2.0    # 후발주 최소 거래량비율 (스트릭트)
_MIN_BID_RATIO          = 1.0    # 최소 호가비율 (소프트: 미조회시 허용)
_MAX_SIGNALS_PER_SCAN   = 5      # 스캔당 최대 신호 수


# ── 유틸 ──────────────────────────────────────────────────────────────────

def _classify_mode(flu_rt: float, rank_pct: float) -> str | None:
    """테마 내 순위(rank_pct 0-1)와 등락률로 모드 분류.

    rank_pct: 전체 테마 구성종목 중 이 종목보다 flu_rt 낮은 종목 비율
    (0=최하위, 1=최상위)
    """
    if rank_pct >= 0.70 and 3.0 <= flu_rt <= 8.0:
        return S6_MODE_LEADER
    if rank_pct >= 0.30 and 1.0 <= flu_rt <= 5.0:
        return S6_MODE_SECONDARY
    if 0.5 <= flu_rt <= 4.0:
        return S6_MODE_LAGGARD
    return None


def _calc_volume_ratio(acc_vol: float, candles: list[dict]) -> float:
    """오늘 누적거래량 / 최근 5일 평균 일거래량."""
    if acc_vol <= 0:
        return 0.0
    try:
        daily_vols = [clean_num(c.get("trde_qty", 0)) for c in candles[:5]]
        daily_vols = [v for v in daily_vols if v > 0]
        if not daily_vols:
            return 0.0
        avg_vol = sum(daily_vols) / len(daily_vols)
        return round(acc_vol / avg_vol, 2) if avg_vol > 0 else 0.0
    except Exception:
        return 0.0


async def _get_bid_ratio(token: str, rdb, stk_cd: str) -> float | None:
    """Redis ws:hoga에서 총매수잔량/총매도잔량. 데이터 없으면 None."""
    try:
        if rdb:
            hoga = _redis_hash_text(await rdb.hgetall(f"ws:hoga:{stk_cd}"))
            if hoga:
                buy  = clean_num(hoga.get("total_buy_bid_req", 0))
                sell = clean_num(hoga.get("total_sel_bid_req", 0))
                if sell > 0:
                    return round(buy / sell, 2)
    except Exception:
        pass
    try:
        ratio = await fetch_hoga(token, stk_cd, rdb=rdb)
        return round(float(ratio), 2) if ratio is not None else None
    except Exception:
        pass
    return None


async def _get_acc_vol(rdb, stk_cd: str) -> float:
    """Redis ws:tick에서 누적거래량(acc_trde_qty) 조회."""
    if not rdb:
        return 0.0
    try:
        tick = _redis_hash_text(await rdb.hgetall(f"ws:tick:{stk_cd}"))
        if tick:
            return clean_num(tick.get("acc_trde_qty", 0))
    except Exception:
        pass
    return 0.0


def _fallback_acc_vol_from_candles(candles: list[dict]) -> float:
    """Use today's daily candle volume when realtime tick volume is unavailable."""
    if not candles:
        return 0.0
    return clean_num(candles[0].get("trde_qty", 0))


def _log_reject(stk_cd: str, theme: str, mode: str, reason: str, **kv) -> None:
    extra = " ".join(f"{k}={v}" for k, v in kv.items())
    logger.debug("[S6][reject] stk=%s theme=%s mode=%s reason=%s%s",
                 stk_cd, theme, mode, reason, f" {extra}" if extra else "")


# ── API 조회 ──────────────────────────────────────────────────────────────

async def fetch_theme_groups(token: str) -> list:
    """ka90001 테마그룹 당일 상위 등락률순 (최대 10개)"""
    results = []
    next_key = ""
    async with kiwoom_client() as client:
        while True:
            headers = {
                "api-id": "ka90001",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
            }
            if next_key:
                headers.update({"cont-yn": "Y", "next-key": next_key})
            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/thme",
                headers=headers,
                json={"qry_tp": "1", "date_tp": "1", "flu_pl_amt_tp": "3", "stex_tp": "3"},
            )
            data = resp.json()
            if not validate_kiwoom_response(data, "ka90001", logger):
                break
            results.extend(data.get("thema_grp", []))
            next_key = resp.headers.get("next-key", "").strip()
            if resp.headers.get("cont-yn") != "Y" or not next_key or len(results) >= 20:
                break
    return results[:10]


async def fetch_theme_stocks(token: str, thema_grp_cd: str) -> list:
    """ka90002 테마구성종목 (연속조회)"""
    results = []
    next_key = ""
    async with kiwoom_client() as client:
        while True:
            headers = {
                "api-id": "ka90002",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
            }
            if next_key:
                headers.update({"cont-yn": "Y", "next-key": next_key})
            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/thme",
                headers=headers,
                json={"date_tp": "1", "thema_grp_cd": thema_grp_cd, "stex_tp": "3"},
            )
            data = resp.json()
            if not validate_kiwoom_response(data, "ka90002", logger):
                break
            results.extend(data.get("thema_comp_stk", []))
            next_key = resp.headers.get("next-key", "").strip()
            if resp.headers.get("cont-yn") != "Y" or not next_key:
                break
    return results


# ── 메인 스캔 ─────────────────────────────────────────────────────────────

async def scan_theme_laggard(token: str, rdb=None) -> list:
    """S6 섹터 강세 확산 포착 — 3개 모드 평가.

    pool(candidates:s6) 사전 필터를 사용하지 않음:
    모든 테마 구성종목을 직접 평가하여 주도주·2등주·후발주를 모두 포착.
    """
    themes = await fetch_theme_groups(token)
    final_candidates: dict[str, dict] = {}
    _processed: set[str] = set()  # 동일 종목 중복 API 호출 방지

    for theme in themes:
        if len(final_candidates) >= _MAX_SIGNALS_PER_SCAN:
            break

        thema_grp_cd = theme.get("thema_grp_cd", "")
        theme_nm     = theme.get("thema_nm", "")
        theme_flu_rt = clean_num(theme.get("flu_rt"))

        if theme_flu_rt < _MIN_THEME_FLU_RT:
            logger.debug("[S6] 테마 약세 건너뜀: theme=%s flu_rt=%.2f", theme_nm, theme_flu_rt)
            continue

        await asyncio.sleep(_API_INTERVAL)
        stocks = await fetch_theme_stocks(token, thema_grp_cd)
        if len(stocks) < 3:
            logger.debug("[S6] 구성종목 부족 건너뜀: theme=%s count=%d", theme_nm, len(stocks))
            continue

        # 테마 내 등락률 백분위 계산
        flu_vals = sorted(clean_num(s.get("flu_rt", 0)) for s in stocks)
        n = len(flu_vals)

        def _rank_pct(fr: float) -> float:
            cnt = sum(1 for f in flu_vals if f < fr)
            return cnt / n if n > 0 else 0.0

        for stk in stocks:
            if len(final_candidates) >= _MAX_SIGNALS_PER_SCAN:
                break

            stk_cd = stk.get("stk_cd", "").strip()
            flu_rt = clean_num(stk.get("flu_rt", 0))

            if not stk_cd or stk_cd in _processed:
                continue
            _processed.add(stk_cd)

            # ── 당일 반복 방지: 3회 이상 emit된 종목 건너뜀 ─────────────────
            _today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m%d")
            _s6_skip_key = f"s6:skip:{stk_cd}:{_today}"
            if rdb:
                try:
                    _skip_cnt = await rdb.get(_s6_skip_key)
                    if _skip_cnt and int(_skip_cnt) >= 3:
                        logger.debug("[S6][skip_cache] stk=%s today_emit=%s, skipping", stk_cd, int(_skip_cnt))
                        continue
                except Exception:
                    pass

            rank_pct = _rank_pct(flu_rt)
            mode     = _classify_mode(flu_rt, rank_pct)

            if mode is None:
                _log_reject(stk_cd, theme_nm, "NONE", "no_mode_match",
                            flu_rt=round(flu_rt, 2), rank_pct=round(rank_pct, 2))
                continue

            # ── 체결강도 (Redis 캐시 우선, REST fallback) ──────────────────
            await asyncio.sleep(_API_INTERVAL)
            strength, src = await fetch_cntr_strength_cached(token, stk_cd, rdb=rdb)
            min_str = _MIN_STR_LAGGARD if mode == S6_MODE_LAGGARD else _MIN_STR_COMMON

            if strength < min_str:
                _log_reject(stk_cd, theme_nm, mode, "weak_strength",
                            strength=round(strength, 1), min=min_str, src=src)
                continue

            # ── 호가비율 (소프트: 없으면 체결강도/거래량으로 보완) ──────────
            bid_ratio = await _get_bid_ratio(token, rdb, stk_cd)
            if bid_ratio is not None and bid_ratio < _MIN_BID_RATIO and strength < 130:
                _log_reject(stk_cd, theme_nm, mode, "weak_bid_ratio",
                            bid_ratio=bid_ratio, strength=round(strength, 1))
                continue

            # ── 일봉 조회 (TP/SL + 거래량비율 계산 겸용) ──────────────────
            cur_prc  = abs(clean_num(stk.get("cur_prc", 0)))
            candles: list[dict] = []
            highs_d, lows_d, closes_d = [], [], []
            ma5, atr_val = None, None
            try:
                await asyncio.sleep(_API_INTERVAL)
                candles  = await fetch_daily_candles(token, stk_cd)
                closes_d = [_safe_price(c.get("cur_prc")) for c in candles if _safe_price(c.get("cur_prc")) > 0]
                highs_d  = [_safe_price(c.get("high_pric")) for c in candles]
                lows_d   = [_safe_price(c.get("low_pric"))  for c in candles]
                if len(closes_d) >= 5:
                    ma5 = sum(closes_d[:5]) / 5
                if len(highs_d) >= 14 and len(lows_d) >= 14 and len(closes_d) >= 14:
                    atr_vals = calc_atr(highs_d, lows_d, closes_d, 14)
                    atr_val  = atr_vals[0] if atr_vals and atr_vals[0] != 0.0 else None
            except Exception as e:
                logger.debug("[S6] 일봉 조회 실패 %s: %s", stk_cd, e)

            # ── 거래량비율 ───────────────────────────────────────────────
            acc_vol   = await _get_acc_vol(rdb, stk_cd)
            if acc_vol <= 0:
                acc_vol = _fallback_acc_vol_from_candles(candles)
            vol_ratio = _calc_volume_ratio(acc_vol, candles)
            min_vol   = _MIN_VOL_RATIO_LAGGARD if mode == S6_MODE_LAGGARD else _MIN_VOL_RATIO_COMMON

            if vol_ratio > 0 and vol_ratio < min_vol:
                _log_reject(stk_cd, theme_nm, mode, "low_volume_ratio",
                            vol_ratio=vol_ratio, min=min_vol, strength=round(strength, 1))
                continue

            # ── TP/SL ───────────────────────────────────────────────────
            tp_sl = calc_tp_sl(
                "S6_THEME_LAGGARD", cur_prc, highs_d, lows_d, closes_d,
                stk_cd=stk_cd, ma5=ma5, atr=atr_val,
            )

            stk_nm = (stk.get("stk_nm", "").strip()
                      or await fetch_stk_nm(rdb, token, stk_cd))

            rr = getattr(tp_sl, "rr_ratio", 0) or 0
            logger.info(
                "[S6][pass] stk=%s theme=%s mode=%s "
                "flu_rt=%.1f%% rank_pct=%.0f%% strength=%.1f vol_ratio=%.2f "
                "bid_ratio=%s rr=%.2f",
                stk_cd, theme_nm, mode,
                flu_rt, rank_pct * 100, strength, vol_ratio,
                f"{bid_ratio:.2f}" if bid_ratio is not None else "n/a",
                rr,
            )

            final_candidates[stk_cd] = {
                "stk_cd":         stk_cd,
                "stk_nm":         stk_nm,
                "cur_prc":        cur_prc,
                "strategy":       "S6_THEME_LAGGARD",
                "s6_mode":        mode,
                "theme_name":     theme_nm,
                "theme_flu_rt":   theme_flu_rt,
                "flu_rt":         flu_rt,
                "gap_pct":        flu_rt,   # scorer 하위 호환
                "theme_rank_pct": round(rank_pct, 2),
                "cntr_strength":  round(strength, 1),
                "volume_ratio":   vol_ratio,
                "bid_ratio":      bid_ratio,
                "entry_type":     "지정가_1호가",
                **tp_sl.to_signal_fields(),
            }

            if rdb:
                try:
                    await rdb.incr(_s6_skip_key)
                    await rdb.expire(_s6_skip_key, 86400)
                except Exception:
                    pass

    # 체결강도 + 거래량비율 복합 정렬
    sorted_results = sorted(
        final_candidates.values(),
        key=lambda x: (x["cntr_strength"] + x.get("volume_ratio", 0) * 5),
        reverse=True,
    )
    return sorted_results[:_MAX_SIGNALS_PER_SCAN]
