from datetime import datetime, time as dtime, timedelta, timezone

KST = timezone(timedelta(hours=9))

WEEKDAYS = {0, 1, 2, 3, 4}

EARLY_CONNECT_START = dtime(7, 30)
PRE_MARKET_START = dtime(8, 0)
OPENING_AUCTION_START = dtime(8, 50)
MAIN_MARKET_START = dtime(9, 0, 30)
MARKET_CLOSE = dtime(15, 20)
AFTER_PREOPEN_START = dtime(15, 30)
AFTER_MARKET_START = dtime(15, 40)
POST_QUIET_START = dtime(20, 0)
CLOSED_START = dtime(20, 10)

ACTIVE_SESSIONS = {
    "pre_market",
    "opening_auction",
    "main_market",
    "closing_auction",
    "after_preopen",
    "after_market",
}


def now_kst() -> datetime:
    return datetime.now(KST)


def is_weekday(dt: datetime) -> bool:
    return dt.weekday() in WEEKDAYS


def current_session(dt: datetime) -> str:
    if not is_weekday(dt):
        return "closed"

    current_time = dt.time()
    if PRE_MARKET_START <= current_time < OPENING_AUCTION_START:
        return "pre_market"
    if OPENING_AUCTION_START <= current_time < MAIN_MARKET_START:
        return "opening_auction"
    if MAIN_MARKET_START <= current_time < MARKET_CLOSE:
        return "main_market"
    if MARKET_CLOSE <= current_time < AFTER_PREOPEN_START:
        return "closing_auction"
    if AFTER_PREOPEN_START <= current_time < AFTER_MARKET_START:
        return "after_preopen"
    if AFTER_MARKET_START <= current_time < POST_QUIET_START:
        return "after_market"
    if POST_QUIET_START <= current_time < CLOSED_START:
        return "post_quiet"
    return "closed"


def is_trading_active(dt: datetime) -> bool:
    return current_session(dt) in ACTIVE_SESSIONS


def is_early_connect_window(dt: datetime) -> bool:
    if not is_weekday(dt):
        return False
    return EARLY_CONNECT_START <= dt.time() < PRE_MARKET_START


def should_keep_ws_connected(dt: datetime) -> bool:
    return is_early_connect_window(dt) or is_trading_active(dt)


def next_ws_connect_time(dt: datetime) -> datetime:
    if is_weekday(dt) and dt.time() < EARLY_CONNECT_START:
        return dt.replace(
            hour=EARLY_CONNECT_START.hour,
            minute=EARLY_CONNECT_START.minute,
            second=0,
            microsecond=0,
        )

    days_ahead = 1
    if dt.weekday() >= 4:
        days_ahead = 7 - dt.weekday()

    base = dt.replace(
        hour=EARLY_CONNECT_START.hour,
        minute=EARLY_CONNECT_START.minute,
        second=0,
        microsecond=0,
    )
    return base + timedelta(days=days_ahead)
