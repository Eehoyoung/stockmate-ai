"""
stockScore.py
/score {종목코드} 텔레그램 명령어 전용 – 종목 전략 적합도 판단 엔진.

흐름:
  1. 실시간 데이터 수집 (일봉 120봉, tick, hoga, 체결강도, VI, 기관/외인)
  2. S1~S15 전략 조건 경량 심사 (1차 필터)
     - 조건 미충족 또는 데이터 부족 → 탈락
     - S2: VI 미발동 → 자동 탈락
     - S7: 09:00~09:30 외 시간대 → 자동 탈락
     - S12: 14:30~15:30 외 시간대 → 자동 탈락
  3. 매칭 전략별 규칙 점수 (scorer.rule_score) + Claude AI 분석 (analyzer.analyze_signal)
  4. CLAUDE_THRESHOLDS 임계점수 이상인 전략 결과 반환

반환: {
  stk_cd, stk_nm, checked_at,
  matched_count,
  results: [ signal-dict (formatter.js formatSignal 호환) ],
  skipped: [ "S2_VI_PULLBACK(VI 미발동)", ... ]
}
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from http_utils import (
    validate_kiwoom_response, kiwoom_client,
    fetch_cntr_strength, fetch_stk_nm,
)
from ma_utils import (
    fetch_daily_candles, _safe_price, _safe_vol,
    detect_golden_cross, _calc_ma,
)
from redis_reader import get_tick_data, get_hoga_data, get_avg_cntr_strength, get_vi_status
from scorer import rule_score as _rule_score, CLAUDE_THRESHOLDS
from analyzer import analyze_signal
from tp_sl_engine import calc_tp_sl
from utils import safe_float as _sf

logger = logging.getLogger(__name__)
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")
_API_INTERVAL   = float(os.getenv("KIWOOM_API_INTERVAL", "0.25"))


def _parse_qty(val) -> int:
    try:
        return int(str(val).replace("+", "").replace(",", ""))
    except (TypeError, ValueError):
        return 0


# ─── 데이터 수집 ───────────────────────────────────────────────

@dataclass
class StockSnapshot:
    """전략 심사에 필요한 모든 실시간 데이터"""
    stk_cd:   str
    stk_nm:   str
    token:    str

    # 일봉
    candles:  list[dict]  = field(default_factory=list)
    closes:   list[float] = field(default_factory=list)
    highs:    list[float] = field(default_factory=list)
    lows:     list[float] = field(default_factory=list)
    vols:     list[int]   = field(default_factory=list)

    # 이동평균 (일봉 기반)
    ma5:      Optional[float] = None
    ma20:     Optional[float] = None
    ma60:     Optional[float] = None
    ma120:    Optional[float] = None
    vol_ma20: Optional[float] = None

    # 기술지표
    rsi14:    Optional[float] = None

    # 실시간 시세 (Redis tick)
    cur_prc:       float = 0.0
    flu_rt:        float = 0.0   # 당일 등락률 (%)
    acc_vol:       int   = 0     # 누적 거래량
    avg_strength:  float = 100.0 # 5분 평균 체결강도

    # 호가 (Redis hoga)
    hoga:      dict            = field(default_factory=dict)
    bid_ratio: Optional[float] = None

    # VI 이벤트
    vi_event:  dict = field(default_factory=dict)

    # 기관/외인 (선택적, API 조회)
    frgn_d1:       int  = 0      # 외인 D-1 순매수 수량
    frgn_d2:       int  = 0
    frgn_d3:       int  = 0
    frgn_tot:      int  = 0      # 누적 순매수 수량
    is_inst_frgn:  bool = False   # ka10063 기관+외인 동시순매수 목록에 포함 여부

    # ── 계산 속성 ──────────────────────────────────────────────

    @property
    def is_opening(self) -> bool:
        m = datetime.now().hour * 60 + datetime.now().minute
        return 540 <= m < 570   # 09:00~09:30

    @property
    def is_closing(self) -> bool:
        m = datetime.now().hour * 60 + datetime.now().minute
        return 870 <= m < 930   # 14:30~15:30

    @property
    def prev_close(self) -> float:
        return self.closes[1] if len(self.closes) > 1 else 0.0

    @property
    def vol_ratio(self) -> Optional[float]:
        if self.vol_ma20 and self.vol_ma20 > 0 and self.acc_vol > 0:
            return round(self.acc_vol / self.vol_ma20, 2)
        return None

    @property
    def high_52w(self) -> Optional[float]:
        """최근 250봉 최고가"""
        h = [_safe_price(c.get("high_pric")) for c in self.candles[:250]
             if _safe_price(c.get("high_pric")) > 0]
        return max(h) if h else None

    @property
    def high_20d(self) -> Optional[float]:
        h = [_safe_price(c.get("high_pric")) for c in self.candles[:20]
             if _safe_price(c.get("high_pric")) > 0]
        return max(h) if h else None

    @property
    def low_20d(self) -> Optional[float]:
        l = [_safe_price(c.get("low_pric")) for c in self.candles[:20]
             if _safe_price(c.get("low_pric")) > 0]
        return min(l) if l else None

    @property
    def is_kospi(self) -> bool:
        return str(self.stk_cd).startswith("0")

    def market_ctx(self) -> dict:
        """scorer.rule_score / analyzer.analyze_signal 용 market_ctx 구성"""
        return {
            "tick":     {"cur_prc": self.cur_prc, "flu_rt": self.flu_rt},
            "hoga":     self.hoga,
            "strength": self.avg_strength,
            "vi":       self.vi_event,
        }


def _calc_rsi(closes: list[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(period):
        d = closes[i] - closes[i + 1]
        (gains if d > 0 else losses).append(abs(d))
    avg_g = sum(gains) / period if gains else 0.0
    avg_l = sum(losses) / period if losses else 0.0
    if avg_l == 0:
        return 100.0
    return round(100 - 100 / (1 + avg_g / avg_l), 1)


async def _fetch_frgn_data(token: str, stk_cd: str) -> tuple[int, int, int, int]:
    """
    ka10035 외인연속순매매상위에서 특정 종목의 D1/D2/D3/tot 추출.
    목록에 없으면 (0,0,0,0) 반환.
    """
    try:
        async with kiwoom_client() as client:
            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/rkinfo",
                headers={
                    "api-id": "ka10035",
                    "authorization": f"Bearer {token}",
                    "Content-Type": "application/json;charset=UTF-8",
                    "cont-yn": "N", "next-key": "",
                },
                json={"mrkt_tp": "000", "trde_tp": "2",
                      "base_dt_tp": "1", "stex_tp": "3"},
            )
            data = resp.json()
            if not validate_kiwoom_response(data, "ka10035", logger):
                return 0, 0, 0, 0
            for item in data.get("for_cont_nettrde_upper", []):
                if item.get("stk_cd") == stk_cd:
                    return (
                        _parse_qty(item.get("dm1", 0)),
                        _parse_qty(item.get("dm2", 0)),
                        _parse_qty(item.get("dm3", 0)),
                        _parse_qty(item.get("tot", 0)),
                    )
    except Exception as e:
        logger.debug("[stockScore] ka10035 조회 실패: %s", e)
    return 0, 0, 0, 0


async def _fetch_inst_frgn_flag(token: str, stk_cd: str) -> bool:
    """
    ka10063 장중투자자별매매 기관+외인 동시순매수 목록에 해당 종목 포함 여부.
    """
    try:
        async with kiwoom_client() as client:
            resp = await client.post(
                f"{KIWOOM_BASE_URL}/api/dostk/mrkcond",
                headers={
                    "api-id": "ka10063",
                    "authorization": f"Bearer {token}",
                    "Content-Type": "application/json;charset=UTF-8",
                },
                json={
                    "mrkt_tp": "000", "amt_qty_tp": "1",
                    "invsr": "6", "frgn_all": "1",
                    "smtm_netprps_tp": "1", "stex_tp": "3",
                },
            )
            data = resp.json()
            if not validate_kiwoom_response(data, "ka10063", logger):
                return False
            for item in data.get("opmr_invsr_trde", []):
                if item.get("stk_cd") == stk_cd:
                    return True
    except Exception as e:
        logger.debug("[stockScore] ka10063 조회 실패: %s", e)
    return False


async def collect_snapshot(rdb, stk_cd: str) -> StockSnapshot:
    """
    전략 심사에 필요한 모든 데이터를 수집하여 StockSnapshot 반환.
    개별 항목 실패 시 기본값 유지 (전체 실패하지 않음).
    """
    token = (await rdb.get("kiwoom:token")) or ""
    stk_nm = stk_cd
    if token:
        stk_nm = await fetch_stk_nm(rdb, token, stk_cd) or stk_cd

    snap = StockSnapshot(stk_cd=stk_cd, stk_nm=stk_nm, token=token)

    # ── 일봉 데이터 ──────────────────────────────────────────────
    if token:
        try:
            candles = await asyncio.wait_for(
                fetch_daily_candles(token, stk_cd, target_count=120), timeout=15.0
            )
            snap.candles = candles
            if candles:
                snap.closes  = [_safe_price(c.get("cur_prc"))  for c in candles if _safe_price(c.get("cur_prc"))  > 0]
                snap.highs   = [_safe_price(c.get("high_pric")) for c in candles if _safe_price(c.get("high_pric")) > 0]
                snap.lows    = [_safe_price(c.get("low_pric"))  for c in candles if _safe_price(c.get("low_pric"))  > 0]
                snap.vols    = [int(_safe_vol(c.get("trde_qty"))) for c in candles]

                cl = snap.closes
                vl = snap.vols
                if len(cl) >= 5:   snap.ma5   = round(_calc_ma(cl, 5),   0)
                if len(cl) >= 20:  snap.ma20  = round(_calc_ma(cl, 20),  0)
                if len(cl) >= 60:  snap.ma60  = round(_calc_ma(cl, 60),  0)
                if len(cl) >= 120: snap.ma120 = round(_calc_ma(cl, 120), 0)
                if len(vl) >= 20:  snap.vol_ma20 = round(sum(vl[:20]) / 20, 0)
                snap.rsi14 = _calc_rsi(cl)

                # cur_prc 폴백: tick 없으면 최신 종가 사용
                if not snap.cur_prc and cl:
                    snap.cur_prc = cl[0]
        except Exception as e:
            logger.warning("[stockScore] 일봉 수집 실패 [%s]: %s", stk_cd, e)

    # ── Redis 실시간 데이터 (비동기 동시 조회) ────────────────────
    tick, hoga, strength, vi = await asyncio.gather(
        get_tick_data(rdb, stk_cd),
        get_hoga_data(rdb, stk_cd),
        get_avg_cntr_strength(rdb, stk_cd, 5),
        get_vi_status(rdb, stk_cd),
        return_exceptions=True,
    )

    if isinstance(tick, dict) and tick:
        snap.cur_prc = _sf(tick.get("cur_prc")) or snap.cur_prc
        snap.flu_rt  = _sf(tick.get("flu_rt"))
        snap.acc_vol = int(_sf(tick.get("acc_trde_qty")))

    if isinstance(hoga, dict):
        snap.hoga = hoga
        bid = _sf(hoga.get("total_buy_bid_req", 0))
        ask = _sf(hoga.get("total_sel_bid_req", 1))
        snap.bid_ratio = round(bid / ask, 2) if ask > 0 else None

    if isinstance(strength, float):
        snap.avg_strength = strength

    if isinstance(vi, dict):
        snap.vi_event = vi

    # flu_rt 폴백: tick 없으면 일봉 기반 계산
    if snap.flu_rt == 0.0 and snap.prev_close > 0 and snap.cur_prc > 0:
        snap.flu_rt = round((snap.cur_prc - snap.prev_close) / snap.prev_close * 100, 2)

    # ── 기관/외인 데이터 (API 호출, 실패 허용) ───────────────────
    if token:
        try:
            d1, d2, d3, tot = await asyncio.wait_for(
                _fetch_frgn_data(token, stk_cd), timeout=8.0
            )
            snap.frgn_d1, snap.frgn_d2, snap.frgn_d3, snap.frgn_tot = d1, d2, d3, tot
        except Exception as e:
            logger.debug("[stockScore] 외인 연속 조회 실패: %s", e)

        try:
            snap.is_inst_frgn = await asyncio.wait_for(
                _fetch_inst_frgn_flag(token, stk_cd), timeout=8.0
            )
        except Exception as e:
            logger.debug("[stockScore] 기관+외인 플래그 조회 실패: %s", e)

    return snap


# ─── 전략별 조건 체크 ──────────────────────────────────────────
# 반환: signal dict (scorer.rule_score 호환) | None (조건 미충족)

def _check_s1(snap: StockSnapshot) -> Optional[dict]:
    """S1 갭상승 개장: 등락률 3~15% + 체결강도 110+ + 거래량"""
    flu = snap.flu_rt
    if not (3.0 <= flu < 15.0):
        return None
    if snap.avg_strength < 110:
        return None
    gap_pct = flu  # 갭 프록시로 flu_rt 사용
    vol_ratio = snap.vol_ratio
    return {
        "strategy":      "S1_GAP_OPEN",
        "stk_cd":        snap.stk_cd,
        "stk_nm":        snap.stk_nm,
        "cur_prc":       snap.cur_prc,
        "entry_type":    "시장가",
        "gap_pct":       round(gap_pct, 2),
        "cntr_strength": round(snap.avg_strength, 1),
        "vol_ratio":     vol_ratio,
        "bid_ratio":     snap.bid_ratio,
        "flu_rt":        snap.flu_rt,
        "holding_days":  1,
    }


def _check_s2(snap: StockSnapshot) -> Optional[dict]:
    """S2 VI 눌림목: VI 이벤트 있어야 함 (없으면 자동 탈락)"""
    if not snap.vi_event:
        return None
    vi_price   = _sf(snap.vi_event.get("vi_prc", 0))
    if vi_price <= 0 or snap.cur_prc <= 0:
        return None
    pullback_pct = (snap.cur_prc - vi_price) / vi_price * 100
    if not (-3.0 <= pullback_pct <= -0.5):
        return None
    is_dynamic = snap.vi_event.get("vi_tp", "") == "2"
    return {
        "strategy":      "S2_VI_PULLBACK",
        "stk_cd":        snap.stk_cd,
        "stk_nm":        snap.stk_nm,
        "cur_prc":       snap.cur_prc,
        "entry_type":    "지정가",
        "pullback_pct":  round(pullback_pct, 2),
        "is_dynamic":    is_dynamic,
        "cntr_strength": round(snap.avg_strength, 1),
        "bid_ratio":     snap.bid_ratio,
        "holding_days":  1,
    }


def _check_s3(snap: StockSnapshot) -> Optional[dict]:
    """S3 기관+외인 동시순매수: ka10063 목록에 포함 + 거래량 1.5x 이상"""
    if not snap.is_inst_frgn:
        return None
    if snap.vol_ratio and snap.vol_ratio < 1.5:
        return None
    return {
        "strategy":       "S3_INST_FRGN",
        "stk_cd":         snap.stk_cd,
        "stk_nm":         snap.stk_nm,
        "cur_prc":        snap.cur_prc,
        "entry_type":     "시장가",
        "vol_ratio":      snap.vol_ratio,
        "continuous_days": 1,
        "net_buy_amt":    0,
        "cntr_strength":  round(snap.avg_strength, 1),
        "holding_days":   3,
    }


def _check_s4(snap: StockSnapshot) -> Optional[dict]:
    """S4 장대양봉: 등락률 3%+ + 거래량 3x+ + 체결강도 120+"""
    if snap.flu_rt < 3.0:
        return None
    vol_ratio = snap.vol_ratio
    if vol_ratio is None or vol_ratio < 3.0:
        return None
    if snap.avg_strength < 120:
        return None
    # 바디비율 근사: 등락률 높을수록 장대양봉 가능성 높음
    body_ratio = min(0.9, snap.flu_rt / 10.0 + 0.5)
    return {
        "strategy":      "S4_BIG_CANDLE",
        "stk_cd":        snap.stk_cd,
        "stk_nm":        snap.stk_nm,
        "cur_prc":       snap.cur_prc,
        "entry_type":    "시장가",
        "vol_ratio":     vol_ratio,
        "body_ratio":    round(body_ratio, 2),
        "is_new_high":   snap.high_52w and snap.cur_prc >= snap.high_52w * 0.99,
        "cntr_strength": round(snap.avg_strength, 1),
        "holding_days":  2,
    }


def _check_s5(snap: StockSnapshot) -> Optional[dict]:
    """S5 프로그램+외인: ka10063 목록 포함 + 체결강도 120+"""
    # S3과 같은 목록이므로 is_inst_frgn 재활용 (체결강도 조건 강화)
    if not snap.is_inst_frgn:
        return None
    if snap.avg_strength < 120:
        return None
    return {
        "strategy":      "S5_PROG_FRGN",
        "stk_cd":        snap.stk_cd,
        "stk_nm":        snap.stk_nm,
        "cur_prc":       snap.cur_prc,
        "entry_type":    "시장가",
        "net_buy_amt":   0,
        "cntr_strength": round(snap.avg_strength, 1),
        "bid_ratio":     snap.bid_ratio,
        "holding_days":  3,
    }


def _check_s6(snap: StockSnapshot) -> Optional[dict]:
    """S6 테마 후발주: 등락률 1~5% + 체결강도 120+ (테마 데이터 없으므로 간소화)"""
    if not (1.0 <= snap.flu_rt < 5.0):
        return None
    if snap.avg_strength < 120:
        return None
    return {
        "strategy":      "S6_THEME_LAGGARD",
        "stk_cd":        snap.stk_cd,
        "stk_nm":        snap.stk_nm,
        "cur_prc":       snap.cur_prc,
        "entry_type":    "시장가",
        "gap_pct":       snap.flu_rt,
        "flu_rt":        snap.flu_rt,
        "cntr_strength": round(snap.avg_strength, 1),
        "theme_name":    "N/A",
        "bid_ratio":     snap.bid_ratio,
        "holding_days":  2,
    }


def _check_s7(snap: StockSnapshot) -> Optional[dict]:
    """S7 일목 돌파 체크: 구름 돌파 + 후행/거래량 조건 + 보조 확인 2개 이상."""
    if len(snap.closes) < 78 or len(snap.highs) < 78 or len(snap.lows) < 78:
        return None

    ichi = calc_ichimoku(snap.highs, snap.lows, snap.closes)
    if ichi is None:
        return None
    if not (ichi.price_above_cloud and ichi.tenkan_above_kijun and ichi.is_bullish_cloud):
        return None

    vol_ratio = snap.vol_ratio or 0.0
    cond_count = sum([
        ichi.chikou_above_price,
        vol_ratio >= 1.5,
        bool(snap.rsi14 is not None and 45.0 <= snap.rsi14 <= 70.0),
        ichi.kijun_rising,
    ])
    if cond_count < 2:
        return None

    return {
        "strategy": "S7_ICHIMOKU_BREAKOUT",
        "stk_cd": snap.stk_cd,
        "stk_nm": snap.stk_nm,
        "cur_prc": snap.cur_prc,
        "entry_type": "일목돌파_시장가",
        "cloud_thickness_pct": round(ichi.cloud_thickness_pct, 2),
        "chikou_above": ichi.chikou_above_price,
        "vol_ratio": round(vol_ratio, 2) if vol_ratio else None,
        "rsi": snap.rsi14,
        "cntr_strength": round(snap.avg_strength, 1),
        "flu_rt": snap.flu_rt,
        "cond_count": cond_count,
        "holding_days": 5,
    }


def _check_s8(snap: StockSnapshot) -> Optional[dict]:
    """S8 골든크로스: MA5>MA20 크로스 3일 이내 + RSI<=75 + 거래량 1.3x+ + 등락 0~15%"""
    if len(snap.closes) < 25:
        return None
    if snap.rsi14 is not None and snap.rsi14 > 75:
        return None
    if not (0 <= snap.flu_rt < 15):
        return None

    is_cross, is_recent, gap_pct = detect_golden_cross(snap.candles, lookback_days=3)
    if not (is_cross or is_recent):
        return None
    if abs(gap_pct) > 5.0:   # MA5/MA20 이격 5% 초과 시 추격 방지
        return None

    # 거래량 확인
    vol_ratio = snap.vol_ratio
    if vol_ratio is not None and vol_ratio < 1.3:
        return None

    # MA60 지지권
    if snap.ma60 and snap.cur_prc < snap.ma60 * 0.95:
        return None

    return {
        "strategy":      "S8_GOLDEN_CROSS",
        "stk_cd":        snap.stk_cd,
        "stk_nm":        snap.stk_nm,
        "cur_prc":       snap.cur_prc,
        "entry_type":    "시장가",
        "rsi":           snap.rsi14,
        "vol_ratio":     vol_ratio,
        "cntr_strength": round(snap.avg_strength, 1),
        "flu_rt":        snap.flu_rt,
        "holding_days":  5,
        "cond_count":    3,
    }


def _check_s9(snap: StockSnapshot) -> Optional[dict]:
    """S9 눌림목 반등: 정배열 + 현재가가 MA5 ±3% 근접 + MA5 위에서 반등"""
    if snap.ma5 is None or snap.ma20 is None or snap.ma60 is None:
        return None
    # 정배열 조건
    if not (snap.ma5 > snap.ma20 > snap.ma60):
        return None
    if snap.cur_prc <= 0:
        return None
    # MA5 근접 (MA5 기준 -3% ~ +2%)
    pct_from_ma5 = (snap.cur_prc - snap.ma5) / snap.ma5 * 100
    if not (-3.0 <= pct_from_ma5 <= 2.0):
        return None
    # 과열 방지 (RSI)
    if snap.rsi14 is not None and snap.rsi14 > 70:
        return None

    pullback_pct = round(pct_from_ma5, 2)
    vol_ratio    = snap.vol_ratio
    return {
        "strategy":      "S9_PULLBACK_SWING",
        "stk_cd":        snap.stk_cd,
        "stk_nm":        snap.stk_nm,
        "cur_prc":       snap.cur_prc,
        "entry_type":    "지정가",
        "pullback_pct":  pullback_pct,
        "rsi":           snap.rsi14,
        "vol_ratio":     vol_ratio,
        "cntr_strength": round(snap.avg_strength, 1),
        "flu_rt":        snap.flu_rt,
        "holding_days":  5,
        "cond_count":    3,
    }


def _check_s10(snap: StockSnapshot) -> Optional[dict]:
    """S10 신고가 돌파: 52주(120봉) 고가 돌파 + 거래량 2x+ + 등락 1%+"""
    if len(snap.closes) < 60:
        return None
    high_ref = snap.high_52w
    if high_ref is None:
        return None
    # 현재가가 52주 고가의 98% 이상이어야 돌파로 간주
    if snap.cur_prc < high_ref * 0.98:
        return None
    if snap.flu_rt < 1.0:
        return None

    vol_ratio = snap.vol_ratio
    if vol_ratio is not None and vol_ratio < 2.0:
        return None

    # 이전 고가 대비 돌파 비율
    vol_surge_rt = round((vol_ratio or 1.0) * 100 - 100, 1)
    return {
        "strategy":      "S10_NEW_HIGH",
        "stk_cd":        snap.stk_cd,
        "stk_nm":        snap.stk_nm,
        "cur_prc":       snap.cur_prc,
        "entry_type":    "시장가",
        "vol_ratio":     vol_ratio,
        "vol_surge_rt":  vol_surge_rt,
        "rsi":           snap.rsi14,
        "cntr_strength": round(snap.avg_strength, 1),
        "flu_rt":        snap.flu_rt,
        "holding_days":  7,
        "cond_count":    2,
    }


def _check_s11(snap: StockSnapshot) -> Optional[dict]:
    """S11 외인연속순매수: D1/D2/D3 모두 양수 + 등락 0~10% + 체결강도 100+"""
    if snap.frgn_d1 <= 0 or snap.frgn_d2 <= 0 or snap.frgn_d3 <= 0:
        return None
    if not (0 < snap.flu_rt <= 10.0):
        return None
    if snap.avg_strength < 100:
        return None
    return {
        "strategy":      "S11_FRGN_CONT",
        "stk_cd":        snap.stk_cd,
        "stk_nm":        snap.stk_nm,
        "cur_prc":       snap.cur_prc,
        "entry_type":    "시장가",
        "dm1":           snap.frgn_d1,
        "dm2":           snap.frgn_d2,
        "dm3":           snap.frgn_d3,
        "rsi":           snap.rsi14,
        "cntr_strength": round(snap.avg_strength, 1),
        "flu_rt":        snap.flu_rt,
        "holding_days":  7,
    }


def _check_s12(snap: StockSnapshot) -> Optional[dict]:
    """S12 종가강도: 14:30~15:30 only + 등락 0~3% + 체결강도 110+"""
    if not snap.is_closing:
        return None
    if not (0.0 <= snap.flu_rt <= 3.0):
        return None
    if snap.avg_strength < 110:
        return None
    return {
        "strategy":      "S12_CLOSING",
        "stk_cd":        snap.stk_cd,
        "stk_nm":        snap.stk_nm,
        "cur_prc":       snap.cur_prc,
        "entry_type":    "종가",
        "cntr_strength": round(snap.avg_strength, 1),
        "flu_rt":        snap.flu_rt,
        "bid_ratio":     snap.bid_ratio,
        "rsi":           snap.rsi14,
        "holding_days":  3,
    }


def _check_s13(snap: StockSnapshot) -> Optional[dict]:
    """S13 박스권 돌파: 20일 고가 돌파 + 거래량 2x+ + RSI 45~70"""
    if len(snap.closes) < 20:
        return None

    high20 = snap.high_20d
    low20  = snap.low_20d
    if high20 is None or low20 is None:
        return None

    # 박스권 상단 돌파 여부 (현재가가 20일 고가를 넘어설 때)
    if snap.cur_prc < high20 * 0.99:
        return None
    if snap.flu_rt < 0.5:
        return None

    # 박스권이 충분히 형성되어 있어야 함 (고저 범위 3%+ )
    box_range_pct = (high20 - low20) / low20 * 100 if low20 > 0 else 0
    if box_range_pct < 3.0:
        return None

    vol_ratio = snap.vol_ratio
    if vol_ratio is not None and vol_ratio < 2.0:
        return None

    if snap.rsi14 is not None and not (45 <= snap.rsi14 <= 75):
        return None

    return {
        "strategy":      "S13_BOX_BREAKOUT",
        "stk_cd":        snap.stk_cd,
        "stk_nm":        snap.stk_nm,
        "cur_prc":       snap.cur_prc,
        "entry_type":    "시장가",
        "vol_ratio":     vol_ratio,
        "rsi":           snap.rsi14,
        "cntr_strength": round(snap.avg_strength, 1),
        "flu_rt":        snap.flu_rt,
        "holding_days":  5,
        "cond_count":    3,
    }


def _check_s14(snap: StockSnapshot) -> Optional[dict]:
    """S14 과매도 반등: RSI < 35 + 당일 양봉(등락 0%+) + MA20 근처"""
    if snap.rsi14 is None or snap.rsi14 >= 35:
        return None
    if snap.flu_rt < 0:
        return None
    # MA20 근처 (MA20 ±10% 이내)
    if snap.ma20:
        pct = (snap.cur_prc - snap.ma20) / snap.ma20 * 100
        if pct > 10.0 or pct < -15.0:
            return None

    vol_ratio = snap.vol_ratio
    return {
        "strategy":      "S14_OVERSOLD_BOUNCE",
        "stk_cd":        snap.stk_cd,
        "stk_nm":        snap.stk_nm,
        "cur_prc":       snap.cur_prc,
        "entry_type":    "지정가",
        "rsi":           snap.rsi14,
        "vol_ratio":     vol_ratio,
        "cntr_strength": round(snap.avg_strength, 1),
        "flu_rt":        snap.flu_rt,
        "holding_days":  3,
        "cond_count":    2,
    }


def _check_s15(snap: StockSnapshot) -> Optional[dict]:
    """S15 모멘텀 정렬: RSI 40~65 + 정배열 + 거래량 1.5x+ + 등락 0.5%+"""
    if snap.rsi14 is None or not (40 <= snap.rsi14 <= 65):
        return None
    if snap.ma5 is None or snap.ma20 is None or snap.ma60 is None:
        return None
    # 정배열
    if not (snap.ma5 > snap.ma20 > snap.ma60):
        return None
    if snap.flu_rt < 0.5:
        return None

    vol_ratio = snap.vol_ratio
    if vol_ratio is not None and vol_ratio < 1.5:
        return None

    return {
        "strategy":      "S15_MOMENTUM_ALIGN",
        "stk_cd":        snap.stk_cd,
        "stk_nm":        snap.stk_nm,
        "cur_prc":       snap.cur_prc,
        "entry_type":    "시장가",
        "rsi":           snap.rsi14,
        "vol_ratio":     vol_ratio,
        "cntr_strength": round(snap.avg_strength, 1),
        "flu_rt":        snap.flu_rt,
        "holding_days":  5,
        "cond_count":    3,
    }


# ─── 1차 필터 실행 ─────────────────────────────────────────────

_CHECKERS = [
    ("S1_GAP_OPEN",         _check_s1,  None),
    ("S2_VI_PULLBACK",      _check_s2,  "VI 미발동"),
    ("S3_INST_FRGN",        _check_s3,  "기관+외인 동시순매수 목록 미포함"),
    ("S4_BIG_CANDLE",       _check_s4,  None),
    ("S5_PROG_FRGN",        _check_s5,  "기관+외인 조건 미충족"),
    ("S6_THEME_LAGGARD",    _check_s6,  None),
    ("S7_ICHIMOKU_BREAKOUT", _check_s7,  "10:00~14:30 이외 시간대"),
    ("S8_GOLDEN_CROSS",     _check_s8,  None),
    ("S9_PULLBACK_SWING",   _check_s9,  None),
    ("S10_NEW_HIGH",        _check_s10, None),
    ("S11_FRGN_CONT",       _check_s11, "외인 연속매수 목록 미포함"),
    ("S12_CLOSING",         _check_s12, "14:30~15:30 이외 시간대"),
    ("S13_BOX_BREAKOUT",    _check_s13, None),
    ("S14_OVERSOLD_BOUNCE", _check_s14, None),
    ("S15_MOMENTUM_ALIGN",  _check_s15, None),
]


def run_all_checks(snap: StockSnapshot) -> tuple[list[dict], list[str]]:
    """
    15개 전략 조건 체크 실행.
    반환: (matched_signals, skipped_reasons)
    """
    matched: list[dict] = []
    skipped: list[str]  = []

    for strategy_id, checker, skip_reason in _CHECKERS:
        signal = checker(snap)
        if signal is not None:
            matched.append(signal)
        else:
            reason = skip_reason or "조건 미충족"
            skipped.append(f"{strategy_id}({reason})")

    return matched, skipped


# ─── 2차 스코어링 ──────────────────────────────────────────────

async def score_one_signal(
    signal: dict,
    snap: StockSnapshot,
    rdb,
    enable_ai: bool = True,
) -> Optional[dict]:
    """
    단일 신호에 대해 규칙 점수 + TP/SL + (선택) AI 점수 산출.
    임계점수 미달 시 None 반환.
    """
    strategy  = signal["strategy"]
    threshold = CLAUDE_THRESHOLDS.get(strategy, 60)
    mctx      = snap.market_ctx()

    # 규칙 점수
    r_score, _components = _rule_score(signal, mctx)
    signal["rule_score"] = round(r_score, 1)

    # TP/SL 계산 (일봉 기반, 실패 시 스킵)
    try:
        tpsl = calc_tp_sl(
            strategy=strategy,
            cur_prc=snap.cur_prc,
            candles=snap.candles,
            signal=signal,
        )
        if tpsl:
            signal.update(tpsl.to_signal_fields())
    except Exception as e:
        logger.debug("[stockScore] TP/SL 계산 실패 [%s %s]: %s", strategy, snap.stk_cd, e)

    # 규칙 점수 임계 미달 → 즉시 CANCEL
    if r_score < threshold:
        logger.info("[stockScore] 규칙점수 %.0f < 임계 %d → 탈락 [%s %s]",
                    r_score, threshold, snap.stk_cd, strategy)
        return None

    # AI 스코어링
    if enable_ai:
        try:
            ai_result = await asyncio.wait_for(
                analyze_signal(signal, mctx, r_score, rdb),
                timeout=15.0,
            )
            signal.update(ai_result)
            # AI가 CANCEL 판정 시 None 반환
            if signal.get("action") == "CANCEL":
                return None
        except asyncio.TimeoutError:
            logger.warning("[stockScore] AI 타임아웃 [%s %s] – 규칙점수로 폴백", snap.stk_cd, strategy)
            signal["action"]     = "ENTER"
            signal["ai_score"]   = round(r_score * 0.9, 1)
            signal["confidence"] = "LOW"
            signal["ai_reason"]  = "AI 분석 타임아웃 – 규칙 점수 기반 판단"
        except Exception as e:
            logger.error("[stockScore] AI 오류 [%s %s]: %s", snap.stk_cd, strategy, e)
            signal["action"]     = "ENTER"
            signal["ai_score"]   = round(r_score * 0.9, 1)
            signal["confidence"] = "LOW"
            signal["ai_reason"]  = f"AI 분석 실패 – 규칙 점수 기반 판단"
    else:
        signal["action"]     = "ENTER"
        signal["ai_score"]   = round(r_score, 1)
        signal["confidence"] = "MEDIUM"
        signal["ai_reason"]  = None

    signal.setdefault("action",     "ENTER")
    signal.setdefault("ai_score",   round(r_score, 1))
    signal.setdefault("confidence", "MEDIUM")

    from datetime import datetime as _dt
    signal["signal_time"] = _dt.now().isoformat()
    return signal


# ─── 메인 엔트리 포인트 ────────────────────────────────────────

async def score_stock(stk_cd: str, rdb, enable_ai: bool = True) -> dict:
    """
    종목 전략 심사 메인 함수.
    engine.py /score/{stk_cd} HTTP 핸들러에서 호출.

    반환:
    {
      "stk_cd": str,
      "stk_nm": str,
      "checked_at": str (ISO 8601),
      "no_match": bool,
      "matched_count": int,
      "results": [ signal-dict, ... ],     # formatter.js formatSignal 호환
      "skipped": [ "S2_VI_PULLBACK(VI 미발동)", ... ],
      "data": {                             # 참고용 스냅샷 수치
        "cur_prc", "flu_rt", "rsi14",
        "ma5", "ma20", "ma60",
        "avg_strength", "bid_ratio"
      }
    }
    """
    logger.info("[stockScore] 심사 시작: %s", stk_cd)

    # 1. 데이터 수집
    snap = await collect_snapshot(rdb, stk_cd)

    # 데이터 최소 유효성 확인
    if snap.cur_prc <= 0 and not snap.closes:
        return {
            "stk_cd":       stk_cd,
            "stk_nm":       snap.stk_nm,
            "checked_at":   datetime.now().isoformat(),
            "no_match":     True,
            "matched_count": 0,
            "results":      [],
            "skipped":      ["데이터 수집 실패 (토큰/연결 확인 필요)"],
            "data":         {},
        }

    # 2. 15전략 1차 체크
    matched_signals, skipped = run_all_checks(snap)

    if not matched_signals:
        logger.info("[stockScore] 매칭 전략 없음: %s", stk_cd)
        return {
            "stk_cd":        stk_cd,
            "stk_nm":        snap.stk_nm,
            "checked_at":    datetime.now().isoformat(),
            "no_match":      True,
            "matched_count": 0,
            "results":       [],
            "skipped":       skipped,
            "data": {
                "cur_prc":      snap.cur_prc,
                "flu_rt":       snap.flu_rt,
                "rsi14":        snap.rsi14,
                "ma5":          snap.ma5,
                "ma20":         snap.ma20,
                "ma60":         snap.ma60,
                "avg_strength": snap.avg_strength,
                "bid_ratio":    snap.bid_ratio,
            },
        }

    logger.info("[stockScore] %s → 1차 매칭 %d개: %s",
                stk_cd, len(matched_signals),
                [s["strategy"] for s in matched_signals])

    # 3. 매칭 전략별 스코어링 (AI 병렬 호출)
    score_tasks = [
        score_one_signal(sig, snap, rdb, enable_ai)
        for sig in matched_signals
    ]
    scored = await asyncio.gather(*score_tasks, return_exceptions=True)

    results = []
    for s in scored:
        if isinstance(s, Exception):
            logger.error("[stockScore] 스코어링 오류: %s", s)
        elif s is not None:
            results.append(s)

    # ai_score 내림차순 정렬
    results.sort(key=lambda x: x.get("ai_score", 0), reverse=True)

    logger.info("[stockScore] %s 최종 통과 %d/%d 전략",
                stk_cd, len(results), len(matched_signals))

    return {
        "stk_cd":        stk_cd,
        "stk_nm":        snap.stk_nm,
        "checked_at":    datetime.now().isoformat(),
        "no_match":      len(results) == 0,
        "matched_count": len(results),
        "results":       results,
        "skipped":       skipped,
        "data": {
            "cur_prc":      snap.cur_prc,
            "flu_rt":       snap.flu_rt,
            "rsi14":        snap.rsi14,
            "ma5":          snap.ma5,
            "ma20":         snap.ma20,
            "ma60":         snap.ma60,
            "avg_strength": snap.avg_strength,
            "bid_ratio":    snap.bid_ratio,
        },
    }
