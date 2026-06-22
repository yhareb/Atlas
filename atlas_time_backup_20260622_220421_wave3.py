from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

ET_TZ = ZoneInfo("America/New_York")

NYSE_HOLIDAYS_2026 = {
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
    date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
    date(2026, 11, 26), date(2026, 11, 27), date(2026, 12, 25),
}


def is_trading_day(day):
    return day.weekday() < 5 and day not in NYSE_HOLIDAYS_2026


def previous_trading_day(day):
    cur = day - timedelta(days=1)
    while not is_trading_day(cur):
        cur -= timedelta(days=1)
    return cur


def current_et_market_date(now=None, previous_after_close=False):
    """Return the ET market date used for Atlas handoff/report queries.

    If previous_after_close=True and now is after the ET session date has rolled
    into the next calendar day (e.g. 00:05 Dubai = 16:05 ET previous day), the
    returned date remains the current ET date. If called on a non-trading ET day,
    it falls back to the previous trading day.
    """
    now_et = (now.astimezone(ET_TZ) if now else datetime.now(ET_TZ))
    day = now_et.date()
    if is_trading_day(day):
        return day
    return previous_trading_day(day)


def current_et_market_date_str(now=None, previous_after_close=False):
    return current_et_market_date(now=now, previous_after_close=previous_after_close).strftime("%Y-%m-%d")


def previous_et_trading_date_str(day=None):
    day = day or current_et_market_date()
    return previous_trading_day(day).strftime("%Y-%m-%d")
