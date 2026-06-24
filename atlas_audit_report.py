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
import sqlite3
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, "/Users/yasser/scripts")


def _load_atlasops_telegram_env():
    """Force audit reports to use AtlasOps Telegram routing, not Atlas routing."""
    env_path = Path("/Users/yasser/.hermes/profiles/atlasops/.env")
    if not env_path.exists():
        return
    values = {}
    for raw in env_path.read_text(errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_ALLOWED_USERS", "TELEGRAM_HOME_CHANNEL"}:
            values[key] = value.strip().strip('"').strip("'")
    for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS", "TELEGRAM_HOME_CHANNEL"):
        if values.get(key):
            os.environ[key] = values[key]
    chat = values.get("TELEGRAM_CHAT_ID") or values.get("TELEGRAM_ALLOWED_USERS") or values.get("TELEGRAM_HOME_CHANNEL")
    if chat:
        os.environ["TELEGRAM_CHAT_ID"] = chat


_load_atlasops_telegram_env()

from atlas_time import is_trading_day
from atlas_notify import send_message

try:
    import atlas_audit
except Exception:
    atlas_audit = None

ET = ZoneInfo("America/New_York")
WINDOW_MINUTES = 30
PROVIDERS = ("Massive", "EODHD", "Benzinga")
KEY_DB_TABLES = {"trades", "pending_pullbacks", "ema_retry_candidates"}


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


def build_report(now_et=None):
    now_et = now_et or datetime.now(ET)
    data, audit_error = _fetch_window()
    counts = _atlas_counts()

    provider_counts = {p: {"calls": 0, "errors": 0} for p in PROVIDERS}
    alerts = []

    for provider, endpoint, http_status, ok, error in data["api"]:
        p = provider or "Unknown"
        provider_counts.setdefault(p, {"calls": 0, "errors": 0})
        provider_counts[p]["calls"] += 1
        if http_status is not None and int(http_status) != 200:
            provider_counts[p]["errors"] += 1
            alerts.append(f"HTTP {http_status} {p}: {endpoint}")
        elif ok is False:
            provider_counts[p]["errors"] += 1
            if error:
                alerts.append(f"{p} error: {str(error)[:70]}")

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
    else:
        lines.append("✅ All systems healthy")

    lines.append("📡 API Health (last 30m)")
    for p in PROVIDERS:
        c = provider_counts.get(p, {"calls": 0, "errors": 0})
        lines.append(f"- {p}: {c['calls']} calls · {c['errors']} errors")

    lines.append("🎯 Signals")
    lines.append(f"- {len(tickers)} tickers · {sig_actions['WAITING']} WAITING · {sig_actions['SKIP']} SKIP · {sig_actions['TOO HOT']} TOO HOT")

    lines.append("💾 DB Events")
    lines.append(f"- {db_total} writes (trades: {db_trades} · pending_pullbacks: {db_pending} · other: {db_other})")

    lines.append("🛠️ Code Changes")
    if data["code_changes"]:
        for work_order, file_path in data["code_changes"][:3]:
            lines.append(f"- {work_order or 'NO-WO'} · {Path(file_path or '').name}")
    else:
        lines.append("- None")

    # Keep hard cap; preserve top alerts and summary if future edits add lines.
    return "\n".join(lines[:20]), counts


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
        send_message(message, label="atlas_audit", print_fallback=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
