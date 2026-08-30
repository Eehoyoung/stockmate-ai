from __future__ import annotations
"""
ma_utils.py
이동평균선 유틸리티 – ka10081 주식일봉차트 기반

MA5/MA20/MA60/MA120 계산, 정배열 판단, 지지/저항 근접도 검사,
골든크로스·눌림목·박스권 돌파 감지 헬퍼 제공.

모든 함수는 실패 시 안전 기본값을 반환하여 호출처의 예외 처리 부담을 줄인다.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from http_utils import KiwoomCallBudgetExceeded, validate_kiwoom_response, kiwoom_client, coalesce_request
from toss_client import fetch_stock_candles as _toss_fetch_stock_candles, toss_enabled as _toss_enabled

logger = logging.getLogger(__name__)
KST    = timezone(timedelta(hours=9))
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")
_DEFAULT_TIMEOUT = 10.0
_API_INTERVAL = float(os.getenv("KIWOOM_API_INTERVAL", "0.8"))
_TOSS_CANDLE_FALLBACK_ENABLED = os.getenv("TOSS_CANDLE_FALLBACK_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}

# ka10081 호출은 함수 시그니처상 rdb를 받지 않는(token만 받는) 20여개 호출부를
# 그대로 유지하기 위해, 토스 토큰 조회용 Redis 연결을 이 모듈이 지연 생성해 자체
# 보유한다 — http_utils.py의 _GlobalRateLimiter._redis_client()와 동일 패턴.
_toss_fallback_redis = None


def _get_toss_fallback_redis():
    global _toss_fallback_redis
    if _toss_fallback_redis is None:
        import redis.asyncio as _redis_async
        from config import REDIS_HOST, REDIS_PASSWORD, REDIS_PORT
        _toss_fallback_redis = _redis_async.Redis(
            host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD,
            decode_responses=True, socket_connect_timeout=1.0, socket_timeout=1.0,
        )
    return _toss_fallback_redis


# ──────────────────────────────────────────────────────────────
# MAContext – 이동평균 컨텍스트 데이터클래스
# ──────────────────────────────────────────────────────────────

@dataclass
class MAContext:
    """ka10081 일봉 기반 이동평균 컨텍스트"""
    stk_cd:   str   = ""
    cur_prc:  float = 0.0          # 최근 종가 (index 0)
    ma5:      Optional[float] = None
    ma20:     Optional[float] = None
    ma60:     Optional[float] = None
    ma120:    Optional[float] = None
    vol_ma20: Optional[float] = None  # 거래량 20일 평균

    @property
    def valid(self) -> bool:
        """MA20 이상 유효 데이터 보유 여부"""
        return self.ma20 is not None

    @property
    def is_bullish_aligned(self) -> bool:
        """정배열: MA5 > MA20 > MA60 (상승 추세 최소 조건)"""
        return bool(self.ma5 and self.ma20 and self.ma60
                    and self.ma5 > self.ma20 > self.ma60)

    @property
    def is_above_ma20(self) -> bool:
        """현재가 ≥ MA20"""
        return bool(self.ma20 and self.cur_prc >= self.ma20)

    @property
    def is_above_ma60(self) -> bool:
        """현재가 ≥ MA60"""
        return bool(self.ma60 and self.cur_prc >= self.ma60)

    def pct_from_ma20(self) -> Optional[float]:
        """(현재가 - MA20) / MA20 × 100 (%)
        양수 = MA20 위, 음수 = MA20 아래"""
        if self.ma20 and self.ma20 > 0:
            return (self.cur_prc - self.ma20) / self.ma20 * 100
        return None

    def pct_from_ma60(self) -> Optional[float]:
        if self.ma60 and self.ma60 > 0:
            return (self.cur_prc - self.ma60) / self.ma60 * 100
        return None

    def near_ma_support(self, ma_val: Optional[float],
                        tolerance_pct: float = 5.0) -> bool:
        """현재가가 ma_val 위 0% ~ tolerance_pct% 이내 (지지선 근접 매수 구간)"""
        if ma_val and ma_val > 0:
            d = (self.cur_prc - ma_val) / ma_val * 100
            return 0.0 <= d <= tolerance_pct
        return False

    def is_overextended(self, threshold_pct: float = 25.0) -> bool:
        """MA20 대비 threshold_pct% 이상 이격 (과열·버블권 진입 경보)"""
        d = self.pct_from_ma20()
        return d is not None and d > threshold_pct


# ──────────────────────────────────────────────────────────────
# 내부 유틸
# ──────────────────────────────────────────────────────────────

def _calc_ma(prices: list[float], period: int) -> Optional[float]:
    if len(prices) < period:
        return None
    return sum(prices[:period]) / period


def _safe_price(raw) -> float:
    try:
        return abs(float(str(raw).replace(",", "").replace("+", "") or "0"))
    except (ValueError, TypeError):
        return 0.0


def _safe_vol(raw) -> float:
    try:
        return float(str(raw).replace(",", "").replace("+", "") or "0")
    except (ValueError, TypeError):
        return 0.0


# ──────────────────────────────────────────────────────────────
# ka10081 일봉 조회 (인메모리 TTL 캐시)
# ──────────────────────────────────────────────────────────────

import time as _time

# 일봉 캐시: {stk_cd: (candles, expire_at)}
_CANDLE_CACHE: dict[str, tuple[list[dict], float]] = {}
_CANDLE_CACHE_TTL = int(os.getenv("MA_CACHE_TTL_SEC", "3600"))

# 분봉 캐시: {(stk_cd, tic_scope): (candles, expire_at)}
_MIN_CANDLE_CACHE: dict[tuple[str, str, str], tuple[list[dict], float]] = {}
# scope 별 캐시 TTL – 단기 프레임일수록 짧게 유지해 stale 봉 사용을 방지
_MIN_CACHE_TTL_BY_SCOPE: dict[str, int] = {
    "1":  int(os.getenv("RSI_MIN_CACHE_TTL_1M_SEC",  "15")),
    "5":  int(os.getenv("RSI_MIN_CACHE_TTL_5M_SEC",  "45")),
    "30": int(os.getenv("RSI_MIN_CACHE_TTL_30M_SEC", "240")),
    "60": int(os.getenv("RSI_MIN_CACHE_TTL_60M_SEC", "600")),
}
_MIN_CACHE_TTL_DEFAULT = int(os.getenv("RSI_MIN_CACHE_TTL_SEC", "300"))


def _min_cache_ttl(tic_scope: str) -> int:
    return _MIN_CACHE_TTL_BY_SCOPE.get(str(tic_scope), _MIN_CACHE_TTL_DEFAULT)


def _candle_cache_get(stk_cd: str) -> list[dict] | None:
    entry = _CANDLE_CACHE.get(stk_cd)
    if entry and _time.monotonic() < entry[1]:
        return entry[0]
    return None


def _candle_cache_set(stk_cd: str, candles: list[dict]) -> None:
    _CANDLE_CACHE[stk_cd] = (candles, _time.monotonic() + _CANDLE_CACHE_TTL)


async def fetch_daily_candles(token: str, stk_cd: str, target_count: int = 120) -> list[dict]:
    """
    ka10081 주식일봉차트 조회 - 연속조회 지원
    :param stk_cd:
    :param token:
    :param target_count: 최소로 확보하고자 하는 봉 수 (기본 120봉)

    같은 (stk_cd, target_count)에 대한 동시 호출은 진행 중인 태스크를 공유한다.
    2026-08-06: 10:00-14:30에 11~13개 전략이 동시 스케줄되며 대부분 같은 종목의
    일봉을 각자 따로 요청해 공유 TR 레이트리밋 예산을 불필요하게 나눠 쓰다가
    S8/S9/S11이 300초 타임아웃으로 후보를 통째로 잃는 사례가 반복됐다. 캐시가
    아직 없는 상태에서 여러 전략이 동시에 같은 종목을 요청해도 실제 Kiwoom
    호출은 한 번만 나가도록 한다.
    """
    cached = _candle_cache_get(stk_cd)
    if cached is not None and len(cached) >= target_count:
        return cached

    return await coalesce_request(
        ("ka10081", stk_cd, target_count),
        lambda: _fetch_daily_candles_uncached(token, stk_cd, target_count),
    )


def _toss_candles_to_kiwoom_shape(toss_candles: list[dict]) -> list[dict]:
    """토스 /api/v1/candles 응답을 ka10081 호출부가 기대하는 필드명으로 변환한다.
    두 소스 모두 최신봉이 index 0이라 순서 반전은 필요 없다."""
    converted = []
    for c in toss_candles:
        ts = str(c.get("timestamp") or "")
        dt = ts[:10].replace("-", "") if len(ts) >= 10 else ""
        converted.append({
            "cur_prc": c.get("closePrice", "0"),
            "open_pric": c.get("openPrice", "0"),
            "high_pric": c.get("highPrice", "0"),
            "low_pric": c.get("lowPrice", "0"),
            "trde_qty": c.get("volume", "0"),
            "dt": dt,
            "source": "toss_candle_fallback",
        })
    return converted


async def _try_toss_candle_fallback(stk_cd: str, target_count: int, kiwoom_count: int) -> list[dict] | None:
    """Kiwoom ka10081이 글로벌 리미터 혼잡 등으로 실패/부족할 때만 호출되는 폴백.
    부분 병합은 하지 않는다 — 날짜 정렬/중복 제거 로직이 미묘하게 어긋나면 MA
    계산이 조용히 틀어질 수 있어(금융 로직) 리스크가 크다. 대신 토스가 Kiwoom보다
    더 많은 봉을 확보했을 때만 전체를 토스 결과로 교체하는 단순한 규칙을 쓴다."""
    if not _TOSS_CANDLE_FALLBACK_ENABLED or not _toss_enabled():
        return None
    try:
        toss_candles = await _toss_fetch_stock_candles(
            _get_toss_fallback_redis(), stk_cd, interval="1d", count=min(max(target_count, 1), 200),
        )
    except Exception as e:
        logger.debug("[ma] 토스 캔들 폴백 실패 [%s]: %s", stk_cd, e)
        return None
    if len(toss_candles) <= kiwoom_count:
        return None
    logger.info(
        "[ma] 토스 캔들 폴백 사용 [%s] kiwoom=%d개 → 토스 %d개로 대체",
        stk_cd, kiwoom_count, len(toss_candles),
    )
    return _toss_candles_to_kiwoom_shape(toss_candles)


async def _fetch_daily_candles_uncached(token: str, stk_cd: str, target_count: int) -> list[dict]:
    all_candles = []
    cont_yn = "N"
    next_key = ""
    base_dt = datetime.now(KST).strftime("%Y%m%d")

    async with kiwoom_client() as client:
        while len(all_candles) < target_count:
            headers = {
                "api-id": "ka10081",
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
                "cont-yn": cont_yn,
                "next-key": next_key
            }

            body = {
                "stk_cd": stk_cd.strip(),
                "base_dt": base_dt,
                "upd_stkpc_tp": "1"
            }

            try:
                resp = await client.post(
                    f"{KIWOOM_BASE_URL}/api/dostk/chart",
                    headers=headers,
                    json=body
                )
                resp.raise_for_status()
                data = resp.json()

                if not validate_kiwoom_response(data, "ka10081", logger):
                    break

                candles = data.get("stk_dt_pole_chart_qry", [])
                if not candles:
                    break

                all_candles.extend(candles)

                # 응답 헤더에서 연속조회 정보 추출
                cont_yn = resp.headers.get("cont-yn", "N")
                next_key = resp.headers.get("next-key", "")

                if cont_yn != "Y" or not next_key:
                    break

                # API 호출 간격 준수 (연속조회 시에도 과부하 방지)
                import asyncio
                await asyncio.sleep(_API_INTERVAL)

            except KiwoomCallBudgetExceeded:
                raise
            except Exception as e:
                logger.error(f"[ma] ka10081 연속조회 중 오류 [%s]: %s", stk_cd, e)
                break

    if len(all_candles) < target_count:
        fallback = await _try_toss_candle_fallback(stk_cd, target_count, len(all_candles))
        if fallback:
            all_candles = fallback

    if all_candles:
        _candle_cache_set(stk_cd, all_candles)

    return all_candles


async def fetch_minute_candles(
    token: str,
    stk_cd: str,
    tic_scope: str = "5",
    base_dt: str | None = None,
) -> list[dict]:
    """
    ka10080 주식분봉차트조회요청.
    오류 시 빈 리스트. 결과는 최신순(index 0 = 가장 최근 봉).
    """
    base_dt = base_dt or datetime.now(KST).strftime("%Y%m%d")
    key = (stk_cd, tic_scope, base_dt)
    entry = _MIN_CANDLE_CACHE.get(key)
    if entry and _time.monotonic() < entry[1]:
        return entry[0]

    # ka10080은 heavy TR(최대 5페이지 순회)이고 여러 지표 모듈이 같은 종목/스코프를
    # 동시에 요청한다. 캐시가 비어 있는 동안 몰리는 중복 호출을 하나로 합친다.
    return await coalesce_request(
        ("ka10080", stk_cd, tic_scope, base_dt),
        lambda: _fetch_minute_candles_uncached(token, stk_cd, tic_scope, base_dt, key),
    )


async def _fetch_minute_candles_uncached(
    token: str,
    stk_cd: str,
    tic_scope: str,
    base_dt: str,
    key: tuple,
) -> list[dict]:
    try:
        headers = {
            "api-id": "ka10080",
            "authorization": f"Bearer {token}",
            "Content-Type": "application/json;charset=UTF-8",
        }
        body = {
            "stk_cd": stk_cd.strip(),
            "tic_scope": tic_scope,
            "upd_stkpc_tp": "1",
            "base_dt": base_dt,
        }
        candles: list[dict] = []
        seen_times: set[str] = set()
        seen_next_keys: set[str] = set()
        max_pages = max(1, int(os.getenv("KIWOOM_MINUTE_MAX_PAGES", "5")))
        async with kiwoom_client() as client:
            for _ in range(max_pages):
                resp = await client.post(
                    f"{KIWOOM_BASE_URL}/api/dostk/chart",
                    headers=headers,
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()
                if not validate_kiwoom_response(data, "ka10080", logger):
                    return []
                for candle in data.get("stk_min_pole_chart_qry", []):
                    candle_time = str(candle.get("cntr_tm", ""))
                    if candle_time and candle_time in seen_times:
                        continue
                    if candle_time:
                        seen_times.add(candle_time)
                    candles.append(candle)

                cont_yn = str(resp.headers.get("cont-yn", "N")).upper()
                next_key = str(resp.headers.get("next-key", "")).strip()
                if cont_yn != "Y":
                    break
                if not next_key or next_key in seen_next_keys:
                    logger.warning("[ma] ka10080 continuation incomplete [%s/%s]", stk_cd, tic_scope)
                    break
                seen_next_keys.add(next_key)
                headers["cont-yn"] = "Y"
                headers["next-key"] = next_key
            if candles:
                _MIN_CANDLE_CACHE[key] = (candles, _time.monotonic() + _min_cache_ttl(tic_scope))
            return candles
    except Exception as e:
        logger.debug("[ma] ka10080 실패 [%s/%s]: %s", stk_cd, tic_scope, e)
        return []


def _is_bar_closed(tic_scope: str) -> bool:
    """현재봉(index 0)이 확정봉인지 추정한다.
    봉 경계 기준 30초 이상 경과했으면 True (이전 봉 확정, 새 봉 형성 중)."""
    try:
        scope_min = int(tic_scope)
        now = datetime.now(KST)
        secs_into_bar = (now.minute % scope_min) * 60 + now.second
        return secs_into_bar >= 30
    except Exception:
        return True


def filter_closed_minute_candles(
    candles: list[dict],
    tic_scope: str,
    *,
    now: datetime | None = None,
) -> list[dict]:
    """Return only ka10080 bars whose full interval has elapsed.

    ``cntr_tm`` is the bar timestamp in YYYYMMDDHHmmss. Malformed timestamps are
    excluded so a live strategy cannot accidentally treat an unknown bar as final.
    """
    try:
        scope = max(1, int(tic_scope))
    except (TypeError, ValueError):
        return []
    current = now or datetime.now(KST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=KST)
    else:
        current = current.astimezone(KST)

    closed: list[dict] = []
    for candle in candles or []:
        raw = str(candle.get("cntr_tm", ""))[:14]
        try:
            started_at = datetime.strptime(raw, "%Y%m%d%H%M%S").replace(tzinfo=KST)
        except (TypeError, ValueError):
            continue
        if started_at + timedelta(minutes=scope) <= current:
            closed.append(candle)
    return closed


async def fetch_minute_candles_with_status(
    token: str,
    stk_cd: str,
    tic_scope: str = "5",
) -> tuple[list[dict], dict]:
    """
    fetch_minute_candles 와 동일하지만 캐시·데이터 품질 메타데이터도 함께 반환한다.

    Returns:
        (candles, status_dict) where status_dict = {
            scope          : "1m" | "5m" | "30m" | "60m",
            candle_count   : int,
            cache_hit      : bool,
            cache_ttl_remaining_ms : int | None,
            source         : "CACHE" | "REST" | "EMPTY",
            latest_ts      : str (봉 기준시각, 없으면 ""),
            is_current_bar_closed : bool,
        }
    """
    base_dt = datetime.now(KST).strftime("%Y%m%d")
    key = (stk_cd, tic_scope, base_dt)
    now_mono = _time.monotonic()
    entry = _MIN_CANDLE_CACHE.get(key)

    if entry and now_mono < entry[1]:
        candles = entry[0]
        return candles, {
            "scope": f"{tic_scope}m",
            "candle_count": len(candles),
            "cache_hit": True,
            "cache_ttl_remaining_ms": int((entry[1] - now_mono) * 1000),
            "source": "CACHE",
            "latest_ts": (candles[0].get("cntr_tm") or candles[0].get("stk_clcl_dt") or "") if candles else "",
            "is_current_bar_closed": _is_bar_closed(tic_scope),
        }

    candles = await fetch_minute_candles(token, stk_cd, tic_scope, base_dt=base_dt)
    return candles, {
        "scope": f"{tic_scope}m",
        "candle_count": len(candles),
        "cache_hit": False,
        "cache_ttl_remaining_ms": int(_min_cache_ttl(tic_scope) * 1000) if candles else 0,
        "source": "REST" if candles else "EMPTY",
        "latest_ts": (candles[0].get("cntr_tm") or candles[0].get("stk_clcl_dt") or "") if candles else "",
        "is_current_bar_closed": _is_bar_closed(tic_scope),
    }


def build_weekly_candles(daily_candles: list[dict]) -> list[dict]:
    """
    일봉 리스트를 ISO 주 단위로 집계해 주봉을 반환한다 (최신 주가 index 0).

    Args:
        daily_candles: ka10081 응답 형식 (최신순). 필드: dt 또는 stk_bsic_dt, stk_opnpric,
                       stk_hgpric, stk_lwpric, stk_clpr, acml_vol
    Returns:
        주봉 리스트 [{week_key, dt_start, dt_end, open, high, low, close, volume, candle_count}]
    """
    from datetime import date as _date
    from collections import defaultdict

    weeks: dict[str, list[dict]] = defaultdict(list)
    for c in daily_candles:
        dt_str = str(c.get("dt") or c.get("stk_bsic_dt") or "")
        if len(dt_str) < 8:
            continue
        try:
            d = _date(int(dt_str[:4]), int(dt_str[4:6]), int(dt_str[6:8]))
            iso_year, iso_week, _ = d.isocalendar()
            weeks[f"{iso_year}-W{iso_week:02d}"].append({"dt": dt_str, **c})
        except ValueError:
            continue

    result = []
    for week_key, days in sorted(weeks.items(), reverse=True):
        days_sorted = sorted(days, key=lambda x: x["dt"])
        try:
            open_price  = float(days_sorted[0].get("stk_opnpric") or 0)
            close_price = float(days_sorted[-1].get("stk_clpr") or 0)
            high_price  = max(float(d.get("stk_hgpric") or 0) for d in days_sorted)
            lows = [float(d.get("stk_lwpric") or 0) for d in days_sorted if float(d.get("stk_lwpric") or 0) > 0]
            low_price   = min(lows) if lows else 0.0
            total_vol   = sum(int(d.get("acml_vol") or 0) for d in days_sorted)
        except (ValueError, TypeError):
            continue
        result.append({
            "week_key": week_key,
            "dt_start": days_sorted[0]["dt"],
            "dt_end": days_sorted[-1]["dt"],
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": total_vol,
            "candle_count": len(days_sorted),
        })

    return result


# ──────────────────────────────────────────────────────────────
# Phase 2: 진행봉/확정봉 분리 + 멀티타임프레임 provider
# ──────────────────────────────────────────────────────────────

def _is_intraday_kst() -> bool:
    """장중(09:00~15:30 KST 평일)이면 True."""
    now = datetime.now(KST)
    if now.weekday() >= 5:
        return False
    t_min = now.hour * 60 + now.minute
    return 540 <= t_min < 930  # 09:00=540, 15:30=930


def get_confirmed_candles(candles: list[dict]) -> list[dict]:
    """
    확정봉만 반환한다.

    장중(09:00~15:30): index 0은 진행 중인 봉이므로 제외하고 index 1+를 반환.
    장후(15:30~): index 0이 이미 확정봉이므로 전체 반환.
    """
    if not candles:
        return []
    return candles[1:] if _is_intraday_kst() else candles


def get_current_bar(candles: list[dict]) -> dict | None:
    """장중이면 진행봉(index 0)을, 장후이면 None을 반환한다."""
    if not candles:
        return None
    return candles[0] if _is_intraday_kst() else None


async def fetch_daily_candles_with_status(
    token: str,
    stk_cd: str,
    target_count: int = 120,
) -> tuple[list[dict], dict]:
    """
    fetch_daily_candles 와 동일하지만 장중/장마감 상태 메타데이터도 반환한다.

    Returns:
        (candles, status_dict) where status_dict = {
            scope               : "1d",
            candle_count        : int,
            cache_hit           : bool,
            cache_ttl_remaining_ms : int,
            source              : "CACHE" | "REST" | "EMPTY",
            source_date         : str  (조회 기준일 YYYYMMDD),
            computed_at         : str  (KST ISO 8601),
            is_final_daily_bar  : bool (장마감 확정봉 여부),
            intraday_day_bar    : bool (장중 진행봉 포함 여부),
        }
    """
    now_kst = datetime.now(KST)
    intraday = _is_intraday_kst()

    now_mono = _time.monotonic()
    cached = _CANDLE_CACHE.get(stk_cd)
    cache_hit = (
        cached is not None
        and now_mono < cached[1]
        and len(cached[0]) >= target_count
    )

    if cache_hit:
        candles = cached[0]
        ttl_remaining_ms = int((cached[1] - now_mono) * 1000)
        source = "CACHE"
    else:
        candles = await fetch_daily_candles(token, stk_cd, target_count)
        ttl_remaining_ms = int(_CANDLE_CACHE_TTL * 1000) if candles else 0
        source = "REST" if candles else "EMPTY"

    return candles, {
        "scope": "1d",
        "candle_count": len(candles),
        "cache_hit": cache_hit,
        "cache_ttl_remaining_ms": ttl_remaining_ms,
        "source": source,
        "source_date": now_kst.strftime("%Y%m%d"),
        "computed_at": now_kst.isoformat(),
        "is_final_daily_bar": not intraday,
        "intraday_day_bar": intraday,
    }


async def fetch_multi_scope_candles(
    token: str,
    stk_cd: str,
    scopes: tuple[str, ...] = ("5", "30", "60"),
) -> dict[str, tuple[list[dict], dict]]:
    """
    복수 분봉 scope를 병렬로 조회한다.

    Args:
        token : Kiwoom API 토큰
        stk_cd: 종목 코드
        scopes: 조회할 분봉 scope 목록 (예: ("1", "5", "30", "60"))

    Returns:
        {scope_str: (candles, status_dict)} — 키는 scope 문자열 ("1", "5" 등).
        scope별 오류는 빈 candles + source="ERROR" status로 안전하게 처리한다.
    """
    results = await asyncio.gather(
        *[fetch_minute_candles_with_status(token, stk_cd, s) for s in scopes],
        return_exceptions=True,
    )
    out: dict[str, tuple[list[dict], dict]] = {}
    for scope, res in zip(scopes, results):
        if isinstance(res, Exception):
            out[scope] = ([], {
                "scope": f"{scope}m",
                "candle_count": 0,
                "cache_hit": False,
                "cache_ttl_remaining_ms": 0,
                "source": "ERROR",
                "latest_ts": "",
                "is_current_bar_closed": True,
                "error": str(res),
            })
        else:
            out[scope] = res
    return out


# ──────────────────────────────────────────────────────────────
# 이동평균 컨텍스트 조회
# ──────────────────────────────────────────────────────────────

async def get_ma_context(token: str, stk_cd: str) -> MAContext:
    """
    종목의 이동평균 컨텍스트 반환 (ka10081 기반).
    실패 시 ctx.valid = False 인 빈 MAContext 반환.
    """
    candles = await fetch_daily_candles(token, stk_cd)
    if not candles:
        return MAContext(stk_cd=stk_cd)

    closes: list[float] = []
    vols:   list[float] = []
    for c in candles:
        p = _safe_price(c.get("cur_prc"))
        v = _safe_vol(c.get("trde_qty"))
        if p > 0:
            closes.append(p)
            vols.append(v)

    if not closes:
        return MAContext(stk_cd=stk_cd)

    return MAContext(
        stk_cd=stk_cd,
        cur_prc=closes[0],
        ma5=_calc_ma(closes, 5),
        ma20=_calc_ma(closes, 20),
        ma60=_calc_ma(closes, 60),
        ma120=_calc_ma(closes, 120),
        vol_ma20=_calc_ma(vols, 20),
    )


# ──────────────────────────────────────────────────────────────
# 패턴 감지 헬퍼 (candles 직접 수신 – API 재호출 없음)
# ──────────────────────────────────────────────────────────────

def detect_golden_cross(candles: list[dict], lookback_days: int = 3) -> tuple[bool, bool, float]:
    """
    최근 n일 이내에 골든크로스가 발생했는지 확인
    """
    closes = [_safe_price(c.get("cur_prc")) for c in candles]
    if len(closes) < 25: return False, False, 0.0

    # 1. 오늘 기준 이격률 계산
    ma5_now = sum(closes[:5]) / 5
    ma20_now = sum(closes[:20]) / 20
    gap_pct = (ma5_now / ma20_now - 1) * 100 if ma20_now > 0 else 0.0

    # 2. 오늘 발생 여부
    is_today = (sum(closes[0:5])/5 > sum(closes[0:20])/20) and \
               (sum(closes[1:6])/5 <= sum(closes[1:21])/20)

    # 3. 최근 n일 내 발생 여부
    is_recent = False
    for i in range(lookback_days):
        m5_t = sum(closes[i:i+5]) / 5
        m20_t = sum(closes[i:i+20]) / 20
        m5_y = sum(closes[i+1:i+6]) / 5
        m20_y = sum(closes[i+1:i+21]) / 20
        if m5_t > m20_t and m5_y <= m20_y:
            is_recent = True
            break

    return is_today, (is_recent and gap_pct <= 5.0), gap_pct


def detect_pullback_setup(candles: list[dict]) -> tuple[bool, float, float]:
    """
    정배열 눌림목 감지 (일봉 기반).

    반환: (is_setup, pct_from_ma5, pct_from_ma20)
    - is_setup      : 정배열 + 현재가 MA5 근접(-3%~+3%) 조건 만족 여부
    - pct_from_ma5  : MA5 대비 현재가 위치 (%)
    - pct_from_ma20 : MA20 대비 현재가 위치 (%)
    """
    closes: list[float] = []
    for c in candles:
        p = _safe_price(c.get("cur_prc"))
        if p > 0:
            closes.append(p)

    if len(closes) < 61:
        return False, 0.0, 0.0

    cur  = closes[0]
    ma5  = sum(closes[:5])  / 5
    ma20 = sum(closes[:20]) / 20
    ma60 = sum(closes[:60]) / 60

    pct_ma5  = (cur - ma5)  / ma5  * 100 if ma5  > 0 else 0.0
    pct_ma20 = (cur - ma20) / ma20 * 100 if ma20 > 0 else 0.0

    if not (ma5 > ma20 > ma60):         # 정배열 미충족
        return False, pct_ma5, pct_ma20
    if not (-3.0 <= pct_ma5 <= 3.0):    # MA5 근접 구간 이탈
        return False, pct_ma5, pct_ma20

    return True, pct_ma5, pct_ma20


def detect_box_breakout(candles: list[dict],
                        box_period: int = 15,
                        max_range_pct: float = 8.0) -> tuple[bool, float]:
    """
    박스권 돌파 감지 (일봉 기반) — 박스 형태·가격 돌파만 판정한다.

    거래량 급증 확인은 여기서 하지 않는다. 예전에는 이 함수 안에서
    "오늘 누적거래량(t_vol, 장중 계속 불어나는 값) >= 15일 평균 *하루 전체*
    거래량 * vol_mul"을 게이트로 걸었는데, 이건 시간대 편향이 있다 — 예를
    들어 11시에 스캔하면 t_vol은 하루치의 일부에 불과해서 실제로 강한
    돌파가 나와도 게이트를 통과하기 어렵다(2026-08-13 트레이더 리뷰에서
    발견). 거래량 판정은 호출부(strategy_13_box_breakout.py)에서 ka10055
    전일 동시간대 비교(resolve_effective_volume_ratio, S7/S8/S9와 동일
    패턴)로 시간대 편향 없이 수행한다.

    반환: (is_breakout, box_range_pct)
    - is_breakout    : 박스권 상단 돌파 + 양봉 동시 충족 (거래량 제외)
    - box_range_pct  : 박스권 폭 (%)
    """
    if len(candles) < box_period + 2:
        return False, 0.0

    today  = candles[0]
    box_cs = candles[1:box_period + 1]

    t_close = _safe_price(today.get("cur_prc"))
    t_open  = _safe_price(today.get("open_pric"))

    if t_close <= 0 or t_open <= 0:
        return False, 0.0

    highs, lows = [], []
    for c in box_cs:
        h = _safe_price(c.get("high_pric"))
        l = _safe_price(c.get("low_pric"))
        if h > 0 and l > 0:
            highs.append(h)
            lows.append(l)

    if not highs:
        return False, 0.0

    box_high = max(highs)
    box_low  = min(lows)
    box_range_pct = (box_high - box_low) / box_low * 100 if box_low > 0 else 0.0

    # 박스권 확인
    if box_range_pct > max_range_pct:
        return False, box_range_pct

    # 돌파 조건: 오늘 종가 > 박스 상단 + 양봉
    if t_close <= box_high or t_close <= t_open:
        return False, box_range_pct

    return True, box_range_pct
