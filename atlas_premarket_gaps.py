#!/usr/bin/env python3
"""atlas_premarket_gaps.py — Atlas pre-market gap visibility report.

Scans the Atlas discovery universe for significant pre-market gaps and sends a
Telegram visibility alert. This is not a trading signal.
"""
import argparse
import datetime as _dt
import json
import os
import re
import sys
import time as _time
from concurrent.futures import ThreadPoolExecutor, as_completed
from zoneinfo import ZoneInfo

import requests

SCRIPT_DIR = "/Users/yasser/scripts"
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

ENV_PATH = os.path.expanduser("~/.hermes/profiles/atlas/.env")
if os.path.exists(ENV_PATH):
    with open(ENV_PATH) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

MASSIVE_API_KEY = os.environ.get("MASSIVE_API_KEY")
MASSIVE_BASE = os.environ.get("MASSIVE_BASE", "https://api.massive.com")
EODHD_API_KEY = os.environ.get("EODHD_API_KEY") or os.environ.get("EODHD_TOKEN")
BENZINGA_API_KEY = os.environ.get("BENZINGA_API_KEY")
ET = ZoneInfo("America/New_York")
UTC = _dt.timezone.utc
GAP_THRESHOLD = 5.0
HTTP_TIMEOUT = float(os.environ.get("ATLAS_GAP_HTTP_TIMEOUT", "8"))
MAX_WORKERS = int(os.environ.get("ATLAS_GAP_WORKERS", "10"))
BENZINGA_UNCOVERED = {"FCEL", "ZURA", "PCLA", "CNVS", "WSHP", "SDOT"}
BENZINGA_SKIP_SET = set()

try:
    from atlas_notify import send_telegram as _send_telegram
except Exception:
    _send_telegram = None


def _log(msg):
    print(f"[premarket-gaps] {msg}", file=sys.stderr)


def _dedupe(items, limit=100):
    out, seen = [], set()
    for item in items or []:
        s = str(item or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{1,5}", s):
            continue
        if s in {"SPY", "QQQ", "DIA", "IWM", "VOO", "VTI", "IVV"}:
            continue
        if s not in seen:
            seen.add(s)
            out.append(s)
        if len(out) >= limit:
            break
    return out


def _fallback_universe():
    return [
        "NVDA", "AMD", "AVGO", "SMCI", "MU", "AAPL", "MSFT", "GOOGL", "GOOG", "META",
        "AMZN", "TSLA", "NFLX", "PLTR", "SNOW", "CRWD", "LLY", "JPM", "BAC", "COIN",
        "ORCL", "NOW", "ARM", "TSM", "QCOM", "INTC", "AMAT", "LRCX", "KLAC", "ASML",
        "MRVL", "WMT", "COST", "HD", "TGT", "NKE", "DIS", "V", "MA", "PYPL",
        "XOM", "CVX", "GE", "CAT", "BA", "UNH", "JNJ", "MRK", "ABBV", "PFE",
    ]


def atlas_universe(limit=100):
    """Fast Atlas universe from current handoff + recent Atlas signal history.

    Avoids importing the trading engine during this visibility-only report while
    still scanning the same names Atlas has recently discovered/scored.
    """
    names = []
    try:
        import atlas_db
        market_day = _dt.datetime.now(ET).date().isoformat()
        handoff = atlas_db.get_handoff(market_day) or {}
        names.extend(handoff.get("BUY", []) or [])
        names.extend(handoff.get("WATCH", []) or [])
        conn = atlas_db.get_connection()
        cutoff = (_dt.datetime.now() - _dt.timedelta(days=3)).strftime("%Y-%m-%d")
        rows = conn.execute(
            "SELECT ticker, MAX(timestamp) AS last_seen FROM signals WHERE date(timestamp) >= ? GROUP BY ticker ORDER BY last_seen DESC",
            (cutoff,),
        ).fetchall()
        names.extend([r[0] for r in rows])
        conn.close()
        _log(f"universe db_recent={len(rows)} handoff={len(handoff.get('BUY', []) or []) + len(handoff.get('WATCH', []) or [])}")
    except Exception as e:
        _log(f"DB universe supplement skipped: {e}")

    names.extend(_fallback_universe())
    return _dedupe(names, limit=limit)


def _get_json(url, params=None, timeout=HTTP_TIMEOUT):
    r = requests.get(url, params=params or {}, timeout=timeout, headers={"Accept": "application/json"})
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:180]}")
    return r.json()


def _previous_trading_day(day):
    d = day - _dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= _dt.timedelta(days=1)
    return d


def _market_window_utc(day):
    start = _dt.datetime.combine(day, _dt.time(4, 0), ET).astimezone(UTC)
    end = _dt.datetime.combine(day, _dt.time(9, 29, 59), ET).astimezone(UTC)
    return start, end


def _epoch_seconds(dt):
    return int(dt.timestamp())


def _fnum(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def prior_close_massive(ticker, prev_day):
    if not MASSIVE_API_KEY:
        return None
    url = f"{MASSIVE_BASE}/v2/aggs/ticker/{ticker}/prev"
    data = _get_json(url, {"apiKey": MASSIVE_API_KEY, "adjusted": "true"})
    rows = data.get("results") or []
    if not rows:
        return None
    return _fnum(rows[0].get("c"))


def premarket_price_massive(ticker, day):
    if not MASSIVE_API_KEY:
        return None
    url = f"{MASSIVE_BASE}/v2/aggs/ticker/{ticker}/range/1/minute/{day.isoformat()}/{day.isoformat()}"
    data = _get_json(url, {"apiKey": MASSIVE_API_KEY, "adjusted": "true", "sort": "asc", "limit": 50000})
    rows = data.get("results") or []
    if not rows:
        return None
    start_utc, end_utc = _market_window_utc(day)
    start_ms, end_ms = int(start_utc.timestamp() * 1000), int(end_utc.timestamp() * 1000)
    pm_rows = [r for r in rows if start_ms <= int(r.get("t") or 0) <= end_ms]
    if not pm_rows:
        return None
    # Use latest pre-market close/price in the 04:00–09:29 ET window.
    return _fnum(pm_rows[-1].get("c"))


def eodhd_intraday_rows(ticker, day):
    if not EODHD_API_KEY:
        return []
    start_utc, end_utc = _market_window_utc(day)
    url = f"https://eodhd.com/api/intraday/{ticker}.US"
    try:
        data = _get_json(url, {
            "api_token": EODHD_API_KEY,
            "fmt": "json",
            "interval": "5m",
            "from": _epoch_seconds(start_utc),
            "to": _epoch_seconds(end_utc),
        })
        return data if isinstance(data, list) else []
    except Exception as e:
        _log(f"EODHD intraday failed {ticker}: {e}")
        return []


def premarket_price_eodhd(ticker, day):
    rows = eodhd_intraday_rows(ticker, day)
    if not rows:
        return None
    for row in reversed(rows):
        px = _fnum(row.get("close") or row.get("price"))
        if px:
            return px
    return None


def prior_close_eodhd(ticker, prev_day):
    if not EODHD_API_KEY:
        return None
    url = f"https://eodhd.com/api/eod/{ticker}.US"
    data = _get_json(url, {
        "api_token": EODHD_API_KEY,
        "fmt": "json",
        "from": prev_day.isoformat(),
        "to": prev_day.isoformat(),
    })
    if isinstance(data, list) and data:
        return _fnum(data[-1].get("adjusted_close") or data[-1].get("close"))
    return None


def fetch_gap(ticker, day):
    prev_day = _previous_trading_day(day)
    errors = []
    prior = pre = None
    source = None
    try:
        prior = prior_close_massive(ticker, prev_day)
        pre = premarket_price_massive(ticker, day)
        if prior and pre:
            source = "Massive"
    except Exception as e:
        errors.append(f"Massive:{e}")
    if not (prior and pre):
        try:
            prior = prior or prior_close_eodhd(ticker, prev_day)
            pre = pre or premarket_price_eodhd(ticker, day)
            if prior and pre:
                source = "EODHD"
        except Exception as e:
            errors.append(f"EODHD:{e}")
    if not (prior and pre):
        return {"ticker": ticker, "ok": False, "error": "; ".join(errors)[:240] or "missing price"}
    gap = ((pre - prior) / prior) * 100.0
    return {"ticker": ticker, "ok": True, "prior_close": prior, "premarket": pre, "gap_pct": gap, "source": source}


def _clean_title(title):
    text = re.sub(r"\s+", " ", str(title or "")).strip()
    return text[:140]


def benzinga_catalyst(ticker, now_et):
    ticker = (ticker or "").upper()
    if not ticker or ticker in BENZINGA_UNCOVERED or ticker in BENZINGA_SKIP_SET or not BENZINGA_API_KEY:
        return None
    start = _dt.datetime.combine(_previous_trading_day(now_et.date()), _dt.time(16, 0), ET)
    end = min(now_et, _dt.datetime.combine(now_et.date(), _dt.time(9, 30), ET))
    url = "https://api.benzinga.com/api/v2/news"
    params = {
        "token": BENZINGA_API_KEY,
        "tickers": ticker,
        "dateFrom": start.date().isoformat(),
        "dateTo": end.date().isoformat(),
        "pageSize": 10,
        "sort": "created",
        "sortDir": "desc",
    }
    try:
        data = _get_json(url, params, timeout=HTTP_TIMEOUT)
    except (json.JSONDecodeError, ValueError, requests.exceptions.RequestException):
        BENZINGA_SKIP_SET.add(ticker)
        return None
    if not isinstance(data, list):
        return None
    for item in data:
        stocks = item.get("stocks") or []
        stock_names = {str(s.get("name") or "").upper() for s in stocks if isinstance(s, dict)}
        if stock_names and ticker not in stock_names:
            continue
        title = _clean_title(item.get("title"))
        if title:
            return title
    if data:
        return None

    fallback_params = dict(params)
    fallback_params.pop("tickers", None)
    fallback_params["pageSize"] = 20
    try:
        fallback_data = _get_json(url, fallback_params, timeout=HTTP_TIMEOUT)
    except (json.JSONDecodeError, ValueError, requests.exceptions.RequestException):
        BENZINGA_SKIP_SET.add(ticker)
        return None
    if not isinstance(fallback_data, list):
        return None
    for item in fallback_data:
        stocks = item.get("stocks") or []
        stock_names = {str(s.get("name") or "").upper() for s in stocks if isinstance(s, dict)}
        if ticker not in stock_names:
            continue
        title = _clean_title(item.get("title"))
        if title:
            return title
    return None


def scan_gaps(day, universe_limit=100, workers=MAX_WORKERS):
    tickers = atlas_universe(limit=universe_limit)
    started = _time.perf_counter()
    rows, failures = [], []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(fetch_gap, t, day): t for t in tickers}
        for fut in as_completed(futures):
            row = fut.result()
            if row.get("ok"):
                rows.append(row)
            else:
                failures.append(row)
    flagged = [r for r in rows if abs(float(r.get("gap_pct") or 0)) >= GAP_THRESHOLD]
    flagged.sort(key=lambda r: abs(r["gap_pct"]), reverse=True)
    elapsed = _time.perf_counter() - started
    return tickers, rows, flagged, failures, elapsed


def _space_report_items(message: str) -> str:
    out = []
    prev_item = False
    for line in str(message).splitlines():
        stripped = line.strip()
        is_item = bool(re.match(r"^(?:\d+\.|[-•]|[🟢🟡🔴🔹🔸🚀📈🎣🔥])\s+", stripped))
        if is_item and prev_item and out and out[-1].strip():
            out.append("")
        out.append(line)
        prev_item = is_item
        if not stripped:
            prev_item = False
    return "\n".join(out)


def render_report(flagged, now_et):
    stamp = now_et.strftime("%-I:%M %p ET") if sys.platform != "win32" else now_et.strftime("%I:%M %p ET").lstrip("0")
    if not flagged:
        return "No significant pre-market gaps today."
    ups = [r for r in flagged if r["gap_pct"] >= GAP_THRESHOLD]
    downs = [r for r in flagged if r["gap_pct"] <= -GAP_THRESHOLD]
    lines = [
        f"━━━ 🌅 PRE-MARKET GAPS — {stamp} ━━━",
        "Visibility only — not a buy/sell signal.",
        "",
        "🟢 GAP UPS",
    ]
    if ups:
        for i, r in enumerate(ups, 1):
            catalyst = r.get("catalyst") or "No catalyst found"
            lines.append(f"{i}. {r['ticker']} +{r['gap_pct']:.1f}% · pre-mkt ${r['premarket']:.2f} · prior close ${r['prior_close']:.2f} · Catalyst: {catalyst}" if r.get("catalyst") else f"{i}. {r['ticker']} +{r['gap_pct']:.1f}% · pre-mkt ${r['premarket']:.2f} · prior close ${r['prior_close']:.2f} · No catalyst found")
    else:
        lines.append("None")
    lines += ["", "🔴 GAP DOWNS"]
    if downs:
        for i, r in enumerate(downs, 1):
            lines.append(f"{i}. {r['ticker']} {r['gap_pct']:.1f}% · pre-mkt ${r['premarket']:.2f} · prior close ${r['prior_close']:.2f} · Catalyst: {r['catalyst']}" if r.get("catalyst") else f"{i}. {r['ticker']} {r['gap_pct']:.1f}% · pre-mkt ${r['premarket']:.2f} · prior close ${r['prior_close']:.2f} · No catalyst found")
    else:
        lines.append("None")
    return _space_report_items("\n".join(lines))


def timing_gate(now_et):
    start = _dt.time(8, 25)
    end = _dt.time(8, 40)
    return start <= now_et.time() <= end


def parse_now_et(value):
    if not value:
        return _dt.datetime.now(ET)
    dt = _dt.datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ET)
    return dt.astimezone(ET)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Atlas pre-market gap visibility scanner")
    ap.add_argument("--dry-run", action="store_true", help="Generate report without sending Telegram")
    ap.add_argument("--force", action="store_true", help="Bypass 08:25-08:40 ET timing gate for live verification")
    ap.add_argument("--now-et", help="Testing override, e.g. 2026-06-29T08:30:00-04:00")
    ap.add_argument("--universe-limit", type=int, default=100)
    ap.add_argument("--workers", type=int, default=MAX_WORKERS)
    ap.add_argument("--skip-catalysts", action="store_true", help="Testing only: skip Benzinga catalyst checks")
    args = ap.parse_args(argv)

    now_et = parse_now_et(args.now_et)
    if not args.dry_run and not args.force and not timing_gate(now_et):
        print(f"[timing-gate] outside 08:25-08:40 ET; now={now_et.isoformat()}; no report sent")
        return 0

    day = now_et.date()
    tickers, rows, flagged, failures, elapsed = scan_gaps(day, universe_limit=args.universe_limit, workers=args.workers)
    for r in flagged:
        if not args.skip_catalysts:
            r["catalyst"] = benzinga_catalyst(r["ticker"], now_et)
    report = render_report(flagged, now_et)

    print(report)
    print("")
    print(f"[meta] mode={'dry-run' if args.dry_run else 'live'} now_et={now_et.isoformat()} scanned={len(tickers)} priced={len(rows)} flagged={len(flagged)} failures={len(failures)} elapsed={elapsed:.2f}s")
    if failures:
        sample = ", ".join(f"{f['ticker']}" for f in failures[:12])
        print(f"[meta] price_failures_sample={sample}")

    if args.dry_run:
        return 0
    if _send_telegram is None:
        print("[telegram] sender unavailable; not sent", file=sys.stderr)
        return 1
    ok = _send_telegram(report, label="premarket_gaps", parse_mode=None)
    print(f"[telegram] sent={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
