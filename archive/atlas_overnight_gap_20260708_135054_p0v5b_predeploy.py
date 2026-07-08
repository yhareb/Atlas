#!/usr/bin/env python3
"""Atlas overnight gap alert.

Checks OPEN trades before the regular session. Sends a Telegram alert only when
one or more long positions are down at least 2.5% versus entry. Dry-run prints
what would be sent and suppresses Telegram. No DB writes.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, time as dtime
from typing import Any
from zoneinfo import ZoneInfo

import requests

SCRIPTS_DIR = os.environ.get("ATLAS_SCRIPTS_DIR") or os.path.dirname(os.path.abspath(__file__))
for _path in (SCRIPTS_DIR, "/Users/yasser/scripts"):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import atlas_db  # noqa: E402
from atlas_symbol_meta import ticker_label  # noqa: E402
from atlas_notify import send_telegram  # noqa: E402

if os.environ.get("ATLAS_DB"):
    atlas_db.DB_PATH = os.environ["ATLAS_DB"]

ET_TZ = ZoneInfo("America/New_York")
WINDOW_START_ET = dtime(8, 0)
WINDOW_END_ET = dtime(9, 30)
TRIGGER_PCT = -2.5
MASSIVE_BASE = os.environ.get("MASSIVE_BASE", "https://api.massive.com")
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
        print(f"[overnight_gap] env load warning: {type(exc).__name__}: {exc}", flush=True)


_load_env_file()
MASSIVE_API_KEY = os.environ.get("MASSIVE_API_KEY") or os.environ.get("POLYGON_API_KEY")


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _price(value: Any) -> str:
    return "N/A" if value in (None, "") else f"${_num(value):,.2f}"


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
    if not (WINDOW_START_ET <= now_et.time() <= WINDOW_END_ET):
        return False, f"outside 8:00-9:30 AM ET guard — {now_et:%Y-%m-%d %H:%M %Z}"
    return True, f"pre-market alert window — {now_et:%Y-%m-%d %H:%M %Z}"


def _mock_positions() -> list[dict[str, Any]] | None:
    raw = os.environ.get("ATLAS_GAP_MOCK_POSITIONS") or ""
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return [dict(x) for x in data]
    except Exception as exc:
        print(f"[overnight_gap] mock positions parse warning: {exc}", flush=True)
        return []


def _open_trades() -> list[dict[str, Any]]:
    mock = _mock_positions()
    if mock is not None:
        return mock
    rows = atlas_db.get_trades(status="OPEN", limit=1000)
    return sorted([dict(r) for r in rows], key=lambda r: (str(r.get("entry_at") or ""), int(r.get("id") or 0)))


def _mock_prices() -> dict[str, float]:
    raw = os.environ.get("ATLAS_GAP_MOCK_PRICES") or ""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {str(k).upper(): float(v) for k, v in data.items()}
    except Exception as exc:
        print(f"[overnight_gap] mock price parse warning: {exc}", flush=True)
        return {}


def _premarket_price(ticker: str, timeout: float = 8.0) -> float | None:
    ticker = str(ticker or "").upper()
    mock = _mock_prices()
    if ticker in mock:
        return mock[ticker]
    if not MASSIVE_API_KEY:
        print(f"[overnight_gap] MASSIVE_API_KEY unavailable; skipping {ticker}", flush=True)
        return None
    url = f"{MASSIVE_BASE.rstrip('/')}/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}"
    try:
        resp = requests.get(url, params={"apiKey": MASSIVE_API_KEY}, timeout=timeout)
        if resp.status_code != 200:
            print(f"[overnight_gap] {ticker} snapshot HTTP {resp.status_code}", flush=True)
            return None
        data = resp.json() or {}
        snap = data.get("ticker") or data.get("data") or data
        for container in (snap.get("min"), snap.get("day"), snap.get("prevDay"), snap):
            if isinstance(container, dict):
                for key in ("p", "price", "lastPrice", "c", "close"):
                    val = container.get(key)
                    if val not in (None, ""):
                        return float(val)
    except Exception as exc:
        print(f"[overnight_gap] {ticker} pre-market lookup failed: {type(exc).__name__}: {exc}", flush=True)
    return None


def build_alert() -> str | None:
    market_day = datetime.now(ET_TZ).strftime("%B %-d, %Y")
    triggered: list[dict[str, Any]] = []
    for row in _open_trades():
        ticker = str(row.get("ticker") or "?").upper()
        entry = _num(row.get("entry_price") or row.get("price"))
        stop = _num(row.get("stop_loss"))
        pre = _premarket_price(ticker)
        if pre is None or not entry:
            continue
        move = (pre - entry) / entry * 100.0
        if move <= TRIGGER_PCT:
            distance = ((pre - stop) / pre * 100.0) if pre else 0.0
            triggered.append({"ticker": ticker, "entry": entry, "premarket": pre, "stop": stop, "move": move, "distance": distance, "row": row})
    if not triggered:
        return None
    lines = [
        f"⚠️ OVERNIGHT GAP ALERT — {market_day} 8:00 AM ET",
        "",
    ]
    for idx, item in enumerate(triggered, 1):
        label = ticker_label(item["ticker"], item["row"])
        lines += [
            f"{idx}. 🔴 {label} — GAP DOWN",
            f"   💵 Entry {_price(item['entry'])}",
            f"   👀 Pre-market {_price(item['premarket'])}",
            f"   📉 {_fmt_pct(item['move'])} overnight",
            f"   🚦 Stop {_price(item['stop'])} · distance: {_fmt_pct(item['distance'], signed=False)}",
            "",
        ]
    return "\n".join(lines).rstrip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Atlas overnight gap alert")
    parser.add_argument("--dry-run", action="store_true", help="Print alert and suppress Telegram")
    parser.add_argument("--force", action="store_true", help="Bypass 8:00-9:30 AM ET guard")
    args = parser.parse_args(argv)
    ok, reason = _market_guard(args.force)
    print(f"[overnight_gap] guard: {reason}", flush=True)
    if not ok:
        return 0
    alert = build_alert()
    if not alert:
        print("[overnight_gap] no triggered positions; silent pass")
        return 0
    print("[overnight_gap] alert body begin")
    print(alert)
    print("[overnight_gap] alert body end")
    if args.dry_run:
        print("[overnight_gap] dry-run: telegram suppressed")
        print("[overnight_gap] telegram alert success=True")
        return 0
    sent = send_telegram(alert, label="atlas", parse_mode="", print_fallback=True, route="professor_dm", report_type="overnight_gap")
    print(f"[overnight_gap] telegram alert success={sent}")
    return 0 if sent else 1


if __name__ == "__main__":
    raise SystemExit(main())
