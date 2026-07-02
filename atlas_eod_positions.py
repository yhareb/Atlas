#!/usr/bin/env python3
"""Atlas EOD open-position Telegram report.

Runs after the regular market close and summarizes every OPEN trade lot using the
canonical holding template. Dry-run prints the report and suppresses Telegram.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

SCRIPTS_DIR = os.environ.get("ATLAS_SCRIPTS_DIR") or os.path.dirname(os.path.abspath(__file__))
for _path in (SCRIPTS_DIR, "/Users/yasser/scripts"):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import atlas_db  # noqa: E402
from atlas_symbol_meta import ticker_label  # noqa: E402
from atlas_report_blocks import holding_block  # noqa: E402
from atlas_notify import send_telegram  # noqa: E402

if os.environ.get("ATLAS_DB"):
    atlas_db.DB_PATH = os.environ["ATLAS_DB"]

ET_TZ = ZoneInfo("America/New_York")
EOD_START_ET = dtime(16, 0)
MASSIVE_BASE = os.environ.get("MASSIVE_BASE", "https://api.massive.com")
MASSIVE_API_KEY = os.environ.get("MASSIVE_API_KEY") or os.environ.get("POLYGON_API_KEY")
ENV_PATH = os.path.expanduser("~/.hermes/profiles/atlas/.env")


def _load_env_file() -> None:
    if not os.path.exists(ENV_PATH):
        return
    try:
        with open(ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                if k and not os.environ.get(k):
                    os.environ[k] = v.strip().strip('"').strip("'")
    except Exception as exc:
        print(f"[eod_positions] env load warning: {type(exc).__name__}: {exc}", flush=True)


_load_env_file()
MASSIVE_API_KEY = os.environ.get("MASSIVE_API_KEY") or os.environ.get("POLYGON_API_KEY")


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _price(value: Any) -> str:
    return "N/A" if value in (None, "") else f"${_num(value):,.2f}"


def _money(value: Any) -> str:
    return "N/A" if value in (None, "") else f"${_num(value):,.0f}"


def _signed_money(value: Any) -> str:
    n = _num(value)
    sign = "+" if n >= 0 else "−"
    return f"{sign}${abs(n):,.0f}"


def _fmt_pct(value: Any, decimals: int = 1, signed: bool = True) -> str:
    n = _num(value)
    sign = "+" if signed and n >= 0 else ("−" if signed and n < 0 else "")
    return f"{sign}{abs(n):.{decimals}f}%" if signed else f"{n:.{decimals}f}%"


def _market_guard(force: bool) -> tuple[bool, str]:
    now_et = datetime.now(ET_TZ)
    if force:
        return True, f"force bypass — {now_et:%Y-%m-%d %H:%M %Z}"
    if now_et.weekday() >= 5:
        return False, f"weekend guard — {now_et:%Y-%m-%d %H:%M %Z}"
    if now_et.time() < EOD_START_ET:
        return False, f"before 4:00 PM ET guard — {now_et:%Y-%m-%d %H:%M %Z}"
    return True, f"after close — {now_et:%Y-%m-%d %H:%M %Z}"


def _cash_balance() -> float:
    db_path = getattr(atlas_db, "DB_PATH", "/Users/yasser/scripts/atlas.db")
    con = sqlite3.connect(db_path)
    try:
        row = con.execute("SELECT balance_after FROM cash_ledger ORDER BY id DESC LIMIT 1").fetchone()
        if row and row[0] is not None:
            return float(row[0])
        row = con.execute("SELECT starting_cash FROM account ORDER BY id ASC LIMIT 1").fetchone()
        return float(row[0]) if row and row[0] is not None else 0.0
    finally:
        con.close()


def _open_trades() -> list[dict[str, Any]]:
    rows = atlas_db.get_trades(status="OPEN", limit=1000)
    return sorted([dict(r) for r in rows], key=lambda r: (str(r.get("entry_at") or ""), int(r.get("id") or 0)))


def _mock_prices() -> dict[str, float]:
    raw = os.environ.get("ATLAS_EOD_MOCK_PRICES") or ""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {str(k).upper(): float(v) for k, v in data.items()}
    except Exception as exc:
        print(f"[eod_positions] mock price parse warning: {exc}", flush=True)
        return {}


def _snapshot_close_price(ticker: str, timeout: float = 8.0) -> float | None:
    ticker = str(ticker or "").upper()
    mock = _mock_prices()
    if ticker in mock:
        return mock[ticker]
    if not MASSIVE_API_KEY:
        print(f"[eod_positions] MASSIVE_API_KEY unavailable; {ticker} close fallback to entry", flush=True)
        return None
    url = f"{MASSIVE_BASE.rstrip('/')}/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}"
    try:
        resp = requests.get(url, params={"apiKey": MASSIVE_API_KEY}, timeout=timeout)
        if resp.status_code != 200:
            print(f"[eod_positions] {ticker} snapshot HTTP {resp.status_code}", flush=True)
            return None
        data = resp.json() or {}
        snap = data.get("ticker") or data.get("data") or data
        for container in (snap.get("day"), snap.get("prevDay"), snap.get("min"), snap):
            if isinstance(container, dict):
                for key in ("c", "close", "p", "price", "lastPrice"):
                    val = container.get(key)
                    if val not in (None, ""):
                        return float(val)
    except Exception as exc:
        print(f"[eod_positions] {ticker} close lookup failed: {type(exc).__name__}: {exc}", flush=True)
    return None


def build_report() -> str:
    market_day = datetime.now(ET_TZ).strftime("%B %-d, %Y")
    trades = _open_trades()
    cash = _cash_balance()
    rows = []
    total_unrealized = 0.0
    total_entry_cost = 0.0
    total_value = 0.0
    for row in trades:
        ticker = str(row.get("ticker") or "?").upper()
        entry = _num(row.get("entry_price"))
        qty = _num(row.get("quantity"))
        close = _snapshot_close_price(ticker)
        if close is None:
            close = entry
        stop = _num(row.get("stop_loss"))
        target = _num(row.get("target_price"))
        pnl = (close - entry) * qty
        pct = ((close - entry) / entry * 100.0) if entry else 0.0
        value = close * qty
        total_unrealized += pnl
        total_entry_cost += entry * qty
        total_value += value
        rows.append({"ticker": ticker, "entry_price": entry, "current_price": close, "stop_loss": stop, "target_price": target, "quantity": qty, "unrealized_pl_usd": pnl, "unrealized_pl_pct": pct, "current_value": value, "invested_capital": entry * qty, "row": row})
    roi = (total_unrealized / total_entry_cost * 100.0) if total_entry_cost else 0.0
    equity = cash + total_value
    lines = [
        f"━━━ 📊 EOD POSITIONS — {market_day} ━━━",
        "",
        f"💰 Equity {_money(equity)} · Cash {_money(cash)} · {len(rows)} positions · ROI {_fmt_pct(roi)}",
        "",
    ]
    lines.extend(holding_block(rows, {}))
    if rows:
        best = max(rows, key=lambda r: r["unrealized_pl_pct"])
        worst = min(rows, key=lambda r: r["unrealized_pl_pct"])
        best_line = f"Best: {best['ticker']} {_fmt_pct(best['unrealized_pl_pct'], decimals=0)}"
        worst_line = f"Worst: {worst['ticker']} {_fmt_pct(worst['unrealized_pl_pct'], decimals=0)}"
    else:
        best_line = "Best: none"
        worst_line = "Worst: none"
    lines += [
        "━━━ 📈 TODAY'S SUMMARY ━━━",
        best_line,
        worst_line,
        f"Cash: {_money(cash)}",
    ]
    return "\n".join(lines)

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Atlas EOD open-position report")
    parser.add_argument("--dry-run", action="store_true", help="Print report and suppress Telegram")
    parser.add_argument("--force", action="store_true", help="Bypass after-close guard")
    args = parser.parse_args(argv)
    ok, reason = _market_guard(args.force)
    print(f"[eod_positions] guard: {reason}", flush=True)
    if not ok:
        return 0
    report = build_report()
    print("[eod_positions] report body begin")
    print(report)
    print("[eod_positions] report body end")
    if args.dry_run:
        print("[eod_positions] dry-run: telegram suppressed")
        print("[eod_positions] telegram report success=True")
        return 0
    sent = send_telegram(report, label="atlas", parse_mode="", print_fallback=True)
    print(f"[eod_positions] telegram report success={sent}")
    return 0 if sent else 1


if __name__ == "__main__":
    raise SystemExit(main())
