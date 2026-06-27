#!/usr/bin/env python3
"""Atlas 9:25 AM ET pre-open system check.

Self-gates to 9:25 AM ET trading weekdays unless --force is supplied.
"""

import argparse
from datetime import datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
import time as _time
from zoneinfo import ZoneInfo

import requests

sys.path.insert(0, "/Users/yasser/scripts")
from atlas_time import is_trading_day
from atlas_notify import send_message

try:
    import atlas_audit
except Exception:
    atlas_audit = None

ET = ZoneInfo("America/New_York")
SCRIPTS = Path("/Users/yasser/scripts")
ENV_PATH = Path("/Users/yasser/.hermes/profiles/atlas/.env")


def _load_env():
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _in_preopen_window(now_et):
    if not is_trading_day(now_et.date()):
        return False
    return time(9, 25) <= now_et.time().replace(tzinfo=None) < time(9, 26)


def _provider_from_url(url):
    u = str(url).lower()
    if "massive.com" in u or "polygon.io" in u:
        return "Massive"
    if "benzinga.com" in u:
        return "Benzinga"
    if "eodhd.com" in u:
        return "EODHD"
    return "Unknown"


def _audit_api(provider, endpoint, status, latency_ms, ok, error=None):
    try:
        if atlas_audit:
            atlas_audit.log_api_call(provider, "atlas_preopen_check.py", "probe", endpoint, status, latency_ms, ok, error, {"preopen_check": True})
    except Exception:
        pass


def _probe(name, url, params=None, headers=None):
    provider = _provider_from_url(url)
    start = _time.perf_counter()
    try:
        r = requests.get(url, params=params or {}, headers=headers or {"Accept": "application/json"}, timeout=10)
        latency = int((_time.perf_counter() - start) * 1000)
        ok = r.status_code == 200
        _audit_api(provider, url, r.status_code, latency, ok, None if ok else r.text[:160])
        return {"name": name, "provider": provider, "url": url, "status": r.status_code, "ok": ok, "error": None if ok else r.text[:160]}
    except Exception as e:
        latency = int((_time.perf_counter() - start) * 1000)
        _audit_api(provider, url, None, latency, False, str(e)[:160])
        return {"name": name, "provider": provider, "url": url, "status": None, "ok": False, "error": str(e)[:160]}


def _provider_probes():
    today = datetime.now(ET).date().isoformat()
    start = (datetime.now(ET).date() - timedelta(days=30)).isoformat()
    massive_key = os.environ.get("MASSIVE_API_KEY") or os.environ.get("POLYGON_API_KEY")
    benzinga_key = os.environ.get("BENZINGA_API_KEY")
    eodhd_key = os.environ.get("EODHD_API_KEY") or os.environ.get("EODHD_TOKEN")
    mbase = os.environ.get("MASSIVE_BASE", "https://api.massive.com")

    probes = []
    if massive_key:
        probes += [
            ("Massive aggs", f"{mbase}/v2/aggs/ticker/AAPL/range/1/day/{start}/{today}", {"apiKey": massive_key, "adjusted": "true", "sort": "asc"}),
            ("Massive ticker snapshot", f"{mbase}/v2/snapshot/locale/us/markets/stocks/tickers/AAPL", {"apiKey": massive_key}),
            ("Massive gainers", f"{mbase}/v2/snapshot/locale/us/markets/stocks/gainers", {"apiKey": massive_key}),
            ("Massive losers", f"{mbase}/v2/snapshot/locale/us/markets/stocks/losers", {"apiKey": massive_key}),
            ("Massive all tickers", f"{mbase}/v2/snapshot/locale/us/markets/stocks/tickers", {"apiKey": massive_key}),
            ("Massive reference news", f"{mbase}/v2/reference/news", {"apiKey": massive_key, "ticker": "AAPL", "limit": 1}),
            ("Massive Benzinga news", f"{mbase}/benzinga/v2/news", {"apiKey": massive_key, "tickers": "AAPL", "limit": 1}),
            ("Massive ratings", f"{mbase}/benzinga/v1/ratings", {"apiKey": massive_key, "ticker": "AAPL", "limit": 1}),
            ("Massive earnings", f"{mbase}/benzinga/v1/earnings", {"apiKey": massive_key, "ticker": "AAPL", "limit": 1}),
            ("Massive analyst insights", f"{mbase}/benzinga/v1/analyst-insights", {"apiKey": massive_key, "ticker": "AAPL", "limit": 1}),
            ("Massive RSI", f"{mbase}/v1/indicators/rsi/AAPL", {"apiKey": massive_key, "timespan": "day", "adjusted": "true", "series_type": "close", "order": "desc", "limit": 1, "window": 14}),
        ]
    else:
        probes.append(("Massive key missing", "https://api.massive.com", {}))

    if benzinga_key:
        probes += [
            ("Benzinga direct news", "https://api.benzinga.com/api/v2/news", {"token": benzinga_key, "dateFrom": today, "pageSize": 1}),
            ("Benzinga FDA", "https://api.benzinga.com/api/v2.1/calendar/fda", {"token": benzinga_key, "dateFrom": today, "dateTo": today, "limit": 1}),
        ]
    else:
        probes.append(("Benzinga key missing", "https://api.benzinga.com", {}))

    if eodhd_key:
        spy_filter = json.dumps([["code", "=", "SPY"], ["exchange", "=", "US"]])
        probes += [
            ("EODHD screener", "https://eodhd.com/api/screener", {"api_token": eodhd_key, "fmt": "json", "filters": spy_filter, "limit": 1}),
            ("EODHD fundamentals", "https://eodhd.com/api/fundamentals/AAPL.US", {"api_token": eodhd_key, "fmt": "json"}),
            ("EODHD sentiments", "https://eodhd.com/api/sentiments", {"api_token": eodhd_key, "fmt": "json", "s": "AAPL.US"}),
            ("EODHD news", "https://eodhd.com/api/news", {"api_token": eodhd_key, "fmt": "json", "s": "AAPL.US", "limit": 1}),
            ("EODHD economic events", "https://eodhd.com/api/economic-events", {"api_token": eodhd_key, "fmt": "json", "from": today, "to": today, "country": "US"}),
            ("EODHD Form4", "https://eodhd.com/api/sec-filings/AAPL/form4", {"api_token": eodhd_key, "fmt": "json", "page[limit]": 1}),
        ]
    else:
        probes.append(("EODHD key missing", "https://eodhd.com", {}))

    return [_probe(name, url, params) for name, url, params in probes]


def _check_postgres():
    try:
        if not atlas_audit:
            return False, "atlas_audit import failed"
        conn = atlas_audit._connect()
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True, None
    except Exception as e:
        return False, str(e)[:160]


def _check_atlas_db():
    try:
        conn = sqlite3.connect("/Users/yasser/scripts/atlas.db")
        cur = conn.cursor()
        counts = {}
        for table in ("pending_pullbacks", "trades", "ema_retry_candidates"):
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            counts[table] = int(cur.fetchone()[0])
            if counts[table] < 0:
                return False, counts, f"negative count {table}"
        conn.close()
        return True, counts, None
    except Exception as e:
        return False, {}, str(e)[:160]


def _check_premarket_seen(now_et):
    try:
        marker = Path("/tmp/atlas_pre_market_report_last_run.json")
        if marker.exists():
            data = json.loads(marker.read_text(errors="ignore") or "{}")
            if str(data.get("market_date") or "") == now_et.date().isoformat():
                return True
    except Exception:
        pass
    try:
        if not atlas_audit:
            return False
        start_et = datetime.combine(now_et.date(), time(0, 0), ET)
        start_utc = start_et.astimezone(timezone.utc)
        conn = atlas_audit._connect()
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM ops_api_calls
                    WHERE ts >= %s AND file_path = 'pre_market_report.py'
                    """,
                    (start_utc,),
                )
                api_count = int(cur.fetchone()[0])
                cur.execute("SELECT COUNT(*) FROM ops_signals WHERE ts >= %s", (start_utc,))
                signal_count = int(cur.fetchone()[0])
        return bool(api_count or signal_count)
    except Exception:
        return False


def build_message(force=False):
    now_et = datetime.now(ET)
    probes = _provider_probes()
    pg_ok, pg_err = _check_postgres()
    db_ok, counts, db_err = _check_atlas_db()
    premarket_seen = _check_premarket_seen(now_et)

    broken = [p for p in probes if not p["ok"]]
    alerts = []
    for p in broken[:6]:
        alerts.append(f"{p['provider']} {p['name']} HTTP {p['status'] or 'ERR'}")
    if not pg_ok:
        alerts.append(f"atlas_ops: {pg_err}")
    if not db_ok:
        alerts.append(f"atlas.db: {db_err}")

    by_provider = {"Massive": [], "Benzinga": [], "EODHD": []}
    for p in probes:
        by_provider.setdefault(p["provider"], []).append(p)

    def prov_line(name):
        rows = by_provider.get(name, [])
        bad = [r for r in rows if not r["ok"]]
        return f"- {name}: {'✅' if not bad else '🚨 ' + bad[0]['name']}"

    lines = ["🌅 ATLAS PRE-OPEN CHECK — 9:25 AM ET"]
    if alerts:
        lines.append("🚨 " + " | ".join(alerts[:3]))
    else:
        lines.append("✅ All systems ready — market opens in 5 minutes")
    lines += ["", "📡 Providers", prov_line("Massive"), prov_line("Benzinga"), prov_line("EODHD")]
    lines += ["", "🗄️ Databases", f"- atlas.db: {'✅' if db_ok else '🚨'}", f"- atlas_ops (PostgreSQL): {'✅' if pg_ok else '🚨'}"]
    lines.append(f"📋 Pre-market report: {'✅ ran today' if premarket_seen else '⚠️ not detected'}")
    return "\n".join(lines), {"probes": probes, "pg_ok": pg_ok, "db_ok": db_ok, "counts": counts, "premarket_seen": premarket_seen}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-send", action="store_true")
    args = parser.parse_args()

    _load_env()
    now_et = datetime.now(ET)
    if not args.force and not _in_preopen_window(now_et):
        return 0
    msg, meta = build_message(force=args.force)
    print(msg)
    if not args.no_send:
        send_message(msg, label="atlas_preopen_check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
