from __future__ import annotations

import datetime
from enum import Enum


KST = datetime.timezone(datetime.timedelta(hours=9))


class MarketSession(str, Enum):
    PRE_MARKET = "PRE_MARKET"
    OPENING_AUCTION = "OPENING_AUCTION"
    MAIN_MARKET = "MAIN_MARKET"
    CLOSING_AUCTION = "CLOSING_AUCTION"
    AFTER_PREOPEN = "AFTER_PREOPEN"
    AFTER_MARKET = "AFTER_MARKET"
    POST_QUIET = "POST_QUIET"
    CLOSED = "CLOSED"


PRE_MARKET_START = datetime.time(8, 0)
OPENING_AUCTION_START = datetime.time(8, 50)
MAIN_MARKET_START = datetime.time(9, 0, 30)
MARKET_CLOSE = datetime.time(15, 20)
AFTER_PREOPEN_START = datetime.time(15, 30)
AFTER_MARKET_START = datetime.time(15, 40)
POST_QUIET_START = datetime.time(20, 0)
CLOSED_START = datetime.time(20, 10)
FORCE_CLOSE_TIME = datetime.time(14, 50)


def now_kst() -> datetime.datetime:
    return datetime.datetime.now(KST)


def _as_kst_datetime(date_time: datetime.datetime | None) -> datetime.datetime:
    if date_time is None:
        return now_kst()
    if date_time.tzinfo is None:
        return date_time
    return date_time.astimezone(KST)


def is_weekday(date: datetime.date | None = None) -> bool:
    target = date or now_kst().date()
    return target.weekday() < 5


def current_session(date_time: datetime.datetime | None = None) -> MarketSession:
    target = _as_kst_datetime(date_time)
    if not is_weekday(target.date()):
        return MarketSession.CLOSED

    now = target.time()
    if PRE_MARKET_START <= now < OPENING_AUCTION_START:
        return MarketSession.PRE_MARKET
    if OPENING_AUCTION_START <= now < MAIN_MARKET_START:
        return MarketSession.OPENING_AUCTION
    if MAIN_MARKET_START <= now < MARKET_CLOSE:
        return MarketSession.MAIN_MARKET
    if MARKET_CLOSE <= now < AFTER_PREOPEN_START:
        return MarketSession.CLOSING_AUCTION
    if AFTER_PREOPEN_START <= now < AFTER_MARKET_START:
        return MarketSession.AFTER_PREOPEN
    if AFTER_MARKET_START <= now < POST_QUIET_START:
        return MarketSession.AFTER_MARKET
    if POST_QUIET_START <= now < CLOSED_START:
        return MarketSession.POST_QUIET
    return MarketSession.CLOSED


def is_pre_market(date_time: datetime.datetime | None = None) -> bool:
    return current_session(date_time) == MarketSession.PRE_MARKET


def is_auction_time(date_time: datetime.datetime | None = None) -> bool:
    return current_session(date_time) in {
        MarketSession.OPENING_AUCTION,
        MarketSession.CLOSING_AUCTION,
    }


def is_market_hours(date_time: datetime.datetime | None = None) -> bool:
    return current_session(date_time) == MarketSession.MAIN_MARKET


def is_force_close_time(date_time: datetime.datetime | None = None) -> bool:
    target = _as_kst_datetime(date_time)
    now = target.time()
    return is_weekday(target.date()) and FORCE_CLOSE_TIME <= now < MARKET_CLOSE


def is_trading_active(date_time: datetime.datetime | None = None) -> bool:
    return current_session(date_time) in {
        MarketSession.PRE_MARKET,
        MarketSession.OPENING_AUCTION,
        MarketSession.MAIN_MARKET,
        MarketSession.CLOSING_AUCTION,
        MarketSession.AFTER_PREOPEN,
        MarketSession.AFTER_MARKET,
    }


def should_force_close(date_time: datetime.datetime | None = None) -> bool:
    return is_force_close_time(date_time)


def get_candidate_builder_session(date_time: datetime.datetime | datetime.time | None = None) -> str:
    """Return the candidate-builder phase for the current KST session.

    The 14:50-14:55 window is intentionally separated so only S12 candidates are
    refreshed while other intraday pools stop producing late-session entries.
    """
    if isinstance(date_time, datetime.time):
        now = date_time
    else:
        target = _as_kst_datetime(date_time)
        if not is_weekday(target.date()):
            return "idle"
        now = target.time()

    if datetime.time(7, 25) <= now <= datetime.time(8, 25):
        return "pre_market"
    if datetime.time(9, 5) <= now < datetime.time(14, 50):
        return "intraday"
    if datetime.time(14, 50) <= now <= datetime.time(14, 55):
        return "s12_only"
    return "idle"
