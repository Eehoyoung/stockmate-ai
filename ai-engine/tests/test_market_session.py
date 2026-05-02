import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_session import (
    MarketSession,
    current_session,
    get_candidate_builder_session,
    is_auction_time,
    is_force_close_time,
    is_market_hours,
    is_pre_market,
    is_trading_active,
    is_weekday,
    should_force_close,
)


MONDAY = datetime.date(2026, 5, 4)
SATURDAY = datetime.date(2026, 5, 2)


def _at(date, hour, minute, second=0):
    return datetime.datetime.combine(date, datetime.time(hour, minute, second))


def test_session_boundaries_are_inclusive_at_start_and_exclusive_at_end():
    assert current_session(_at(MONDAY, 7, 59)) == MarketSession.CLOSED
    assert current_session(_at(MONDAY, 8, 0)) == MarketSession.PRE_MARKET
    assert current_session(_at(MONDAY, 8, 50)) == MarketSession.OPENING_AUCTION
    assert current_session(_at(MONDAY, 9, 0, 29)) == MarketSession.OPENING_AUCTION
    assert current_session(_at(MONDAY, 9, 0, 30)) == MarketSession.MAIN_MARKET
    assert current_session(_at(MONDAY, 15, 20)) == MarketSession.CLOSING_AUCTION
    assert current_session(_at(MONDAY, 15, 30)) == MarketSession.AFTER_PREOPEN
    assert current_session(_at(MONDAY, 15, 40)) == MarketSession.AFTER_MARKET
    assert current_session(_at(MONDAY, 20, 0)) == MarketSession.POST_QUIET
    assert current_session(_at(MONDAY, 20, 10)) == MarketSession.CLOSED

    assert is_pre_market(_at(MONDAY, 8, 0))
    assert is_auction_time(_at(MONDAY, 8, 50))
    assert not is_market_hours(_at(MONDAY, 9, 0, 29))
    assert is_market_hours(_at(MONDAY, 9, 0, 30))
    assert is_market_hours(_at(MONDAY, 15, 19))
    assert not is_market_hours(_at(MONDAY, 15, 20))


def test_trading_active_combines_pre_market_and_regular_sessions():
    assert is_trading_active(_at(MONDAY, 8, 0))
    assert is_trading_active(_at(MONDAY, 9, 0, 30))
    assert is_trading_active(_at(MONDAY, 15, 40))
    assert not is_trading_active(_at(MONDAY, 20, 0))


def test_force_close_matches_dedicated_force_close_window():
    assert not should_force_close(_at(MONDAY, 14, 49))
    assert is_force_close_time(_at(MONDAY, 14, 50))
    assert should_force_close(_at(MONDAY, 14, 50))
    assert not should_force_close(_at(MONDAY, 15, 20))


def test_weekend_never_enters_trading_sessions():
    assert not is_weekday(SATURDAY)
    assert not is_pre_market(_at(SATURDAY, 8, 30))
    assert not is_auction_time(_at(SATURDAY, 8, 30))
    assert not is_market_hours(_at(SATURDAY, 9, 0))
    assert not is_trading_active(_at(SATURDAY, 9, 0))
    assert not should_force_close(_at(SATURDAY, 14, 50))


def test_candidate_builder_session_preserves_legacy_windows():
    assert get_candidate_builder_session(datetime.time(7, 25)) == "pre_market"
    assert get_candidate_builder_session(datetime.time(8, 25)) == "pre_market"
    assert get_candidate_builder_session(datetime.time(9, 4, 59)) == "idle"
    assert get_candidate_builder_session(datetime.time(9, 5)) == "intraday"
    assert get_candidate_builder_session(datetime.time(14, 49, 59)) == "intraday"
    assert get_candidate_builder_session(datetime.time(14, 50)) == "s12_only"
    assert get_candidate_builder_session(datetime.time(14, 55)) == "s12_only"
    assert get_candidate_builder_session(datetime.time(14, 55, 1)) == "idle"


def test_candidate_builder_session_keeps_weekends_idle_with_datetime():
    assert get_candidate_builder_session(_at(SATURDAY, 8, 0)) == "idle"
    assert get_candidate_builder_session(_at(SATURDAY, 14, 50)) == "idle"
