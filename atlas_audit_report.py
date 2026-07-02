#!/usr/bin/env python3
"""Atlas Ops audit health reporter.

Reads the local Postgres audit DB and sends a short Telegram health summary.
Outside ET market hours it exits silently unless --force is supplied.
"""

import argparse
from collections import defaultdict
from datetime import datetime, time, timezone
import os
from pathlib import Path
import re
import sqlite3
import sys
from zoneinfo import ZoneInfo

import requests

sys.path.insert(0, "/Users/yasser/scripts")


ATLASOPS_ENV = Path("/Users/yasser/.hermes/profiles/atlasops/.env")


def _env_file_values(path):
    values = {}
    if not path.exists():
        return values
    for raw in path.read_text(errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _chunks(message, limit=3800):
    text = str(message or "")
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < 1000:
            cut = limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    chunks.append(text)
    return chunks


def send_atlasops_audit_telegram(message, label="atlas_audit", parse_mode=""):
    """Send audit reports through the AtlasOps bot only; never atlas_notify/Atlas bot."""
    values = _env_file_values(ATLASOPS_ENV)
    bot_token = values.get("TELEGRAM_BOT_TOKEN")
    chat_id = values.get("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        print(f"[{label}] telegram skipped: atlasops TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID unset")
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    sent = 0
    for chunk in _chunks(message):
        payload = {"chat_id": chat_id, "text": chunk}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        try:
            resp = requests.post(url, json=payload, timeout=(5, 25))
            if resp.status_code != 200:
                print(f"[{label}] telegram failed HTTP {resp.status_code}")
                return False
            sent += 1
        except Exception as exc:
            print(f"[{label}] telegram failed: {type(exc).__name__}")
            return False
    print(f"[{label}] telegram sent via atlasops bot: chunks={sent}")
    return True


from atlas_time import is_trading_day

try:
    import atlas_audit
except Exception:
    atlas_audit = None

ET = ZoneInfo("America/New_York")
WINDOW_MINUTES = 30
PROVIDERS = ("Massive", "EODHD", "Benzinga")
KEY_DB_TABLES = {"trades", "pending_pullbacks", "ema_retry_candidates"}
TRANSIENT_API_ERROR_MARKERS = (
    "read timed out",
    "connection reset",
    "connection aborted",
    "remote end closed connection",
    "remotedisconnected",
    "max retries exceeded",
)
TRANSIENT_ALERT_MIN_ERRORS = 3
TRANSIENT_ALERT_MIN_ERROR_RATE = 0.01


def _is_transient_api_error(error):
    text = str(error or "").lower()
    return any(marker in text for marker in TRANSIENT_API_ERROR_MARKERS)


def _in_market_hours(now_et):
    if not is_trading_day(now_et.date()):
        return False
    return time(9, 30) <= now_et.time().replace(tzinfo=None) <= time(16, 0)


def _connect_audit():
    if atlas_audit is None:
        return None
    try:
        return atlas_audit._connect()
    except Exception:
        return None


def _atlas_counts():
    out = {}
    try:
        conn = sqlite3.connect("/Users/yasser/scripts/atlas.db")
        cur = conn.cursor()
        for table in ("pending_pullbacks", "trades", "ema_retry_candidates"):
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            out[table] = int(cur.fetchone()[0])
        conn.close()
    except Exception:
        pass
    return out


def _fetch_window():
    data = {
        "api": [],
        "signals": [],
        "db_events": [],
        "code_changes": [],
    }
    conn = _connect_audit()
    if conn is None:
        return data, "audit db unavailable"
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT provider, endpoint, http_status, ok, error
                    FROM ops_api_calls
                    WHERE ts >= now() - interval '30 minutes'
                    ORDER BY ts DESC
                    """
                )
                data["api"] = cur.fetchall()
                cur.execute(
                    """
                    SELECT ticker, action, reason, score, pillars, source
                    FROM ops_signals
                    WHERE ts >= now() - interval '30 minutes'
                    ORDER BY ts DESC
                    """
                )
                data["signals"] = cur.fetchall()
                cur.execute(
                    """
                    SELECT table_name, operation, row_id, ticker, source_function
                    FROM ops_db_events
                    WHERE ts >= now() - interval '30 minutes'
                    ORDER BY ts DESC
                    """
                )
                data["db_events"] = cur.fetchall()
                cur.execute(
                    """
                    SELECT work_order, file_path
                    FROM ops_code_changes
                    WHERE ts >= now() - interval '30 minutes'
                    ORDER BY ts DESC
                    LIMIT 3
                    """
                )
                data["code_changes"] = cur.fetchall()
        return data, None
    except Exception as e:
        return data, f"audit query failed: {str(e)[:120]}"
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _space_report_items(message: str) -> str:
    out = []
    prev_item = False
    for line in str(message).splitlines():
        stripped = line.strip()
        is_item = stripped.startswith('- ')
        if is_item and prev_item and out and out[-1].strip():
            out.append("")
        out.append(line)
        prev_item = is_item
        if not stripped:
            prev_item = False
    return "\n".join(out)


def build_report(now_et=None):
    now_et = now_et or datetime.now(ET)
    data, audit_error = _fetch_window()
    counts = _atlas_counts()

    provider_counts = {p: {"calls": 0, "errors": 0} for p in PROVIDERS}
    provider_transient_errors = defaultdict(int)
    provider_transient_examples = {}
    alerts = []
    live_trade_fallback_ok = set()
    for _provider, endpoint, http_status, ok, _error in data["api"]:
        m = re.search(r"/v2/last/trade/([A-Z.\-]+)", str(endpoint or ""))
        if m and http_status == 200 and ok is True:
            live_trade_fallback_ok.add(m.group(1).upper())

    for provider, endpoint, http_status, ok, error in data["api"]:
        p = provider or "Unknown"
        provider_counts.setdefault(p, {"calls": 0, "errors": 0})
        provider_counts[p]["calls"] += 1
        if http_status is not None and int(http_status) != 200:
            endpoint_txt = str(endpoint or "")
            m = re.search(r"/v2/snapshot/locale/us/markets/stocks/tickers/([A-Z.\-]+)", endpoint_txt)
            if int(http_status) == 404 and m and m.group(1).upper() in live_trade_fallback_ok:
                continue
            provider_counts[p]["errors"] += 1
            alerts.append(f"HTTP {http_status} {p}: {endpoint}")
        elif ok is False:
            provider_counts[p]["errors"] += 1
            if error:
                if _is_transient_api_error(error):
                    provider_transient_errors[p] += 1
                    provider_transient_examples.setdefault(p, str(error)[:70])
                else:
                    alerts.append(f"{p} error: {str(error)[:70]}")

    for p, transient_errors in provider_transient_errors.items():
        calls = max(provider_counts.get(p, {}).get("calls", 0), 1)
        error_rate = transient_errors / calls
        if transient_errors >= TRANSIENT_ALERT_MIN_ERRORS or error_rate >= TRANSIENT_ALERT_MIN_ERROR_RATE:
            alerts.append(f"{p} transient errors: {transient_errors}/{calls} ({error_rate:.1%}) e.g. {provider_transient_examples.get(p, '')}")

    for p in PROVIDERS:
        if provider_counts.get(p, {}).get("calls", 0) == 0:
            alerts.append(f"{p}: zero calls in last {WINDOW_MINUTES}m")

    for table_name, operation, row_id, ticker, source_function in data["db_events"]:
        if table_name in KEY_DB_TABLES and str(operation).upper() == "DELETE":
            alerts.append(f"DB DELETE {table_name}: {ticker or row_id or ''}".strip())

    if audit_error:
        alerts.append(audit_error)

    sig_actions = defaultdict(int)
    tickers = set()
    for ticker, action, reason, score, pillars, source in data["signals"]:
        if ticker:
            tickers.add(str(ticker).upper())
        sig_actions[str(action or "").upper()] += 1

    db_total = len(data["db_events"])
    db_trades = sum(1 for r in data["db_events"] if r[0] == "trades")
    db_pending = sum(1 for r in data["db_events"] if r[0] == "pending_pullbacks")
    db_other = db_total - db_trades - db_pending

    lines = [f"🛡️ ATLAS OPS AUDIT — {now_et.strftime('%I:%M %p ET').lstrip('0')}"]
    if alerts:
        lines.append("🚨 ALERTS")
        for alert in alerts[:4]:
            lines.append(f"- {alert[:115]}")
            lines.append("")
    else:
        lines.append("✅ All systems healthy")

    lines.append("📡 API Health (last 30m)")
    for p in PROVIDERS:
        c = provider_counts.get(p, {"calls": 0, "errors": 0})
        lines.append(f"- {p}: {c['calls']} calls · {c['errors']} errors")
        lines.append("")

    lines.append("🎯 Signals")
    lines.append(f"- {len(tickers)} tickers · {sig_actions['WAITING']} WAITING · {sig_actions['SKIP']} SKIP · {sig_actions['TOO HOT']} TOO HOT")
    lines.append("")

    lines.append("💾 DB Events")
    lines.append(f"- {db_total} writes (trades: {db_trades} · pending_pullbacks: {db_pending} · other: {db_other})")
    lines.append("")

    lines.append("🛠️ Code Changes")
    if data["code_changes"]:
        for work_order, file_path in data["code_changes"][:3]:
            lines.append(f"- {work_order or 'NO-WO'} · {Path(file_path or '').name}")
            lines.append("")
    else:
        lines.append("- None")

    # Keep hard cap; preserve top alerts and summary if future edits add lines.
    return _space_report_items("\n".join(lines[:20])), counts


def main():
    parser = argparse.ArgumentParser(description="Send Atlas audit health report")
    parser.add_argument("--force", action="store_true", help="bypass market-hours gate")
    parser.add_argument("--no-send", action="store_true", help="print only; do not send Telegram")
    args = parser.parse_args()

    now_et = datetime.now(ET)
    if not args.force and not _in_market_hours(now_et):
        return 0

    message, counts = build_report(now_et=now_et)
    print(message)
    if not args.no_send:
        send_atlasops_audit_telegram(message, label="atlas_audit", parse_mode="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
