#!/usr/bin/env python3
"""Perme execution engine for Atlas macro/risk briefings.

Collects read-only macro/news/sector context, asks the `perme` Hermes profile to
produce a structured Markdown briefing, and drops the result into atlas_inbox.

Safety invariants:
- Read-only provider collection.
- No local trading datastore access.
- No vector-store writes.
- Output goes to /Users/yasser/atlas_inbox for the ingest daemon to handle.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
SCRIPTS_DIR = Path("/Users/yasser/scripts")
ATLAS_ENV = Path("/Users/yasser/.hermes/profiles/atlas/.env")
PERME_PROFILE = "perme"
HERMES_HOME = "/Users/yasser/.hermes/profiles/perme"
HERMES_BIN = os.environ.get("HERMES_BIN", "hermes")
OUTBOX = Path(os.environ.get("PERME_OUTBOX", "/Users/yasser/atlas_inbox"))
MASSIVE_BASE = os.environ.get("MASSIVE_BASE", "https://api.massive.com")
SECTOR_ETFS = {
    "XLK": "TECH",
    "XLF": "FINANCIALS",
    "XLE": "ENERGY",
    "XLV": "HEALTHCARE",
    "XLI": "INDUSTRIALS",
    "XLY": "CONSUMER_DISCRETIONARY",
    "XLP": "CONSUMER_STAPLES",
    "XLC": "COMMUNICATIONS",
    "XLB": "MATERIALS",
    "XLU": "UTILITIES",
    "SMH": "SEMI",
}


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _json_get(url: str, params: dict[str, Any] | None = None, timeout: int = 15) -> Any:
    query = urlencode(params or {}, doseq=True)
    full_url = f"{url}?{query}" if query else url
    req = Request(full_url, headers={"Accept": "application/json", "User-Agent": "AtlasPerme/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        data = resp.read().decode("utf-8", errors="replace")
    return json.loads(data) if data else None


def _now_et() -> datetime:
    return datetime.now(ET)


def _routine_from_time(now_et: datetime) -> str:
    if now_et.weekday() == 5 and now_et.hour == 9:
        return "weekend"
    if now_et.weekday() >= 5:
        return "weekend"
    hm = now_et.strftime("%H:%M")
    if hm < "09:30":
        return "pre_market"
    if "09:30" <= hm <= "16:00":
        return "intraday"
    return "post_market"


def _date_params_for_news(routine: str, now_et: datetime) -> tuple[str, str]:
    if routine == "pre_market":
        start = (now_et - timedelta(hours=16)).date()
    elif routine == "intraday":
        start = now_et.date()
    elif routine == "post_market":
        start = now_et.date()
    else:
        start = (now_et - timedelta(days=7)).date()
    return start.isoformat(), now_et.date().isoformat()


def fetch_benzinga_news(routine: str, now_et: datetime, mock: bool = False) -> list[dict[str, Any]]:
    if mock:
        return [
            {"title": "Fed speakers keep real-rate sensitivity elevated", "created": now_et.isoformat(), "tickers": []},
            {"title": "Semiconductor ETF extends intraday strength", "created": now_et.isoformat(), "tickers": ["SMH"]},
        ]
    token = os.environ.get("BENZINGA_API_KEY")
    if not token:
        return []
    date_from, date_to = _date_params_for_news(routine, now_et)
    data = _json_get(
        "https://api.benzinga.com/api/v2/news",
        {
            "token": token,
            "dateFrom": date_from,
            "dateTo": date_to,
            "pageSize": 20,
            "displayOutput": "full",
            "sort": "created",
            "sortDir": "desc",
        },
        timeout=12,
    )
    rows = data if isinstance(data, list) else (data or {}).get("data") or []
    out = []
    for row in rows[:20]:
        out.append({
            "title": row.get("title") or row.get("headline"),
            "created": row.get("created") or row.get("updated") or row.get("published"),
            "tickers": row.get("stocks") or row.get("tickers") or [],
        })
    return out


def fetch_benzinga_earnings(routine: str, now_et: datetime, mock: bool = False) -> list[dict[str, Any]]:
    if mock:
        return [{"ticker": "ABNB", "date": now_et.date().isoformat(), "time": "AMC", "importance": "mock"}]
    token = os.environ.get("BENZINGA_API_KEY")
    if not token:
        return []
    if routine == "weekend":
        start = now_et.date().isoformat()
        end = (now_et.date() + timedelta(days=7)).isoformat()
    else:
        start = end = now_et.date().isoformat()
    data = _json_get(
        "https://api.benzinga.com/api/v2.1/calendar/earnings",
        {"token": token, "parameters[date_from]": start, "parameters[date_to]": end, "pagesize": 50},
        timeout=12,
    )
    rows = (data or {}).get("earnings") if isinstance(data, dict) else data
    out = []
    for row in (rows or [])[:30]:
        out.append({
            "ticker": row.get("ticker") or row.get("symbol"),
            "date": row.get("date"),
            "time": row.get("time"),
            "eps": row.get("eps"),
            "eps_est": row.get("eps_est"),
            "revenue": row.get("revenue"),
            "revenue_est": row.get("revenue_est"),
        })
    return out


def fetch_eodhd_economic_calendar(routine: str, now_et: datetime, mock: bool = False) -> list[dict[str, Any]]:
    if mock:
        return [{"date": now_et.isoformat(), "type": "Fed Speaker", "country": "US", "impact": "medium"}]
    token = os.environ.get("EODHD_API_KEY") or os.environ.get("EODHD_TOKEN")
    if not token:
        return []
    start = now_et.date()
    end = start + (timedelta(days=7) if routine == "weekend" else timedelta(days=1))
    data = _json_get(
        "https://eodhd.com/api/economic-events",
        {"api_token": token, "fmt": "json", "from": start.isoformat(), "to": end.isoformat(), "country": "US"},
        timeout=12,
    )
    return list(data or [])[:40] if isinstance(data, list) else []


def _snapshot_price(row: dict[str, Any]) -> tuple[float | None, float | None]:
    ticker = row.get("ticker") or row
    day = (ticker.get("day") if isinstance(ticker, dict) else {}) or {}
    prev = (ticker.get("prevDay") if isinstance(ticker, dict) else {}) or {}
    price = day.get("c") or (ticker.get("lastTrade") or {}).get("p") if isinstance(ticker, dict) else None
    prev_close = prev.get("c")
    pct = ticker.get("todaysChangePerc") if isinstance(ticker, dict) else None
    try:
        price = float(price) if price is not None else None
    except Exception:
        price = None
    try:
        pct = float(pct) if pct is not None else None
    except Exception:
        try:
            pct = ((float(price) / float(prev_close)) - 1.0) * 100.0 if price and prev_close else None
        except Exception:
            pct = None
    return price, pct


def fetch_sector_etfs(mock: bool = False) -> list[dict[str, Any]]:
    if mock:
        return [
            {"ticker": "SMH", "sector": "SEMI", "price": 284.20, "change_pct": 1.8, "rsi": 72.5, "overbought": True},
            {"ticker": "XLK", "sector": "TECH", "price": 245.10, "change_pct": 0.6, "rsi": 64.0, "overbought": False},
        ]
    api_key = os.environ.get("MASSIVE_API_KEY")
    if not api_key:
        return []
    rows = []
    for ticker, sector in SECTOR_ETFS.items():
        item: dict[str, Any] = {"ticker": ticker, "sector": sector}
        try:
            snap = _json_get(
                f"{MASSIVE_BASE}/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}",
                {"apiKey": api_key},
                timeout=8,
            )
            price, pct = _snapshot_price(snap or {})
            item.update({"price": price, "change_pct": pct})
        except Exception as exc:
            item["snapshot_error"] = f"{type(exc).__name__}: {exc}"
        try:
            rsi = _json_get(
                f"{MASSIVE_BASE}/v1/indicators/rsi/{ticker}",
                {"apiKey": api_key, "timespan": "day", "adjusted": "true", "window": 14, "series_type": "close", "limit": 1},
                timeout=8,
            )
            values = (((rsi or {}).get("results") or {}).get("values") or [])
            val = values[0].get("value") if values else None
            item["rsi"] = float(val) if val is not None else None
            item["overbought"] = bool(item.get("rsi") is not None and item["rsi"] >= 70)
        except Exception as exc:
            item["rsi_error"] = f"{type(exc).__name__}: {exc}"
            item.setdefault("overbought", False)
        rows.append(item)
    return rows


def collect_context(routine: str, mock: bool = False) -> dict[str, Any]:
    now = _now_et()
    resolved_routine = _routine_from_time(now) if routine == "auto" else routine
    return {
        "generated_at_et": now.isoformat(timespec="seconds"),
        "routine": resolved_routine,
        "source_mode": "mock" if mock else "live",
        "benzinga_news": fetch_benzinga_news(resolved_routine, now, mock=mock),
        "benzinga_earnings": fetch_benzinga_earnings(resolved_routine, now, mock=mock),
        "eodhd_economic_calendar": fetch_eodhd_economic_calendar(resolved_routine, now, mock=mock),
        "massive_sector_etfs": fetch_sector_etfs(mock=mock),
    }


def build_prompt(context: dict[str, Any]) -> str:
    template = """# PERME BRIEFING — [YYYY-MM-DD HH:MM ET]

## FLAGS
[List exact trigger keywords here, one per line. If none, write "None."]

## REGIME
[One sentence defining the current macro environment]

## EVIDENCE
- [Data point 1]
- [Data point 2]
- [Data point 3]

## RISK FACTORS
1. [Risk Factor 1 Name]
   - [Context bullet]
2. [Risk Factor 2 Name]
   - [Context bullet]
"""
    return (
        "Generate a Perme briefing from the raw data below. Output Markdown only. "
        "You MUST follow this exact section structure and heading syntax; do not use alternate headings such as CONTEXT or META. "
        "Use only these FLAGS when justified: RISK-OFF, FED_DAY, FOMC_DAY, CPI_DAY, EARNINGS_RISK: <TICKER>, "
        "TICKER_NOTE: <TICKER>, SECTOR_OVERBOUGHT: <SECTOR>, SECTOR_NOTE: <SECTOR>. "
        "If no flags apply, write None. under ## FLAGS. Do not mention buy/sell/stop/target.\n\n"
        "REQUIRED_TEMPLATE:\n" + template + "\n"
        "RAW_DATA_JSON:\n"
        + json.dumps(context, indent=2, sort_keys=True, default=str)
    )


def run_perme(prompt: str, timeout: int = 180) -> str:
    env = os.environ.copy()
    env.setdefault("HERMES_HOME", HERMES_HOME)
    proc = subprocess.run(
        [HERMES_BIN, "-p", PERME_PROFILE, "-z", prompt],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        raise RuntimeError(f"Hermes Perme failed rc={proc.returncode} stderr={(proc.stderr or '')[:500]}")
    return proc.stdout.strip()


def output_path(now_et: datetime | None = None) -> Path:
    now_et = now_et or _now_et()
    OUTBOX.mkdir(parents=True, exist_ok=True)
    return OUTBOX / f"perme_brief_{now_et.strftime('%Y%m%d_%H%M')}.md"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Atlas Perme briefing engine")
    parser.add_argument("--routine", required=True, choices=["auto", "pre_market", "intraday", "post_market", "weekend"])
    parser.add_argument("--dry-run", action="store_true", help="Print diagnostics; still writes the Markdown file")
    parser.add_argument("--mock-data", action="store_true", help="Use deterministic mock API payloads for Gate 1")
    parser.add_argument("--output", default="", help="Optional explicit output path")
    args = parser.parse_args(argv)

    _load_env_file(ATLAS_ENV)
    context = collect_context(args.routine, mock=args.mock_data)
    prompt = build_prompt(context)
    briefing = run_perme(prompt)
    path = Path(args.output).expanduser() if args.output else output_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(briefing.rstrip() + "\n")
    print("PERME_RESULT_JSON=" + json.dumps({
        "routine": context.get("routine"),
        "source_mode": context.get("source_mode"),
        "output_path": str(path),
        "bytes": path.stat().st_size,
        "news_count": len(context.get("benzinga_news") or []),
        "earnings_count": len(context.get("benzinga_earnings") or []),
        "economic_events_count": len(context.get("eodhd_economic_calendar") or []),
        "sector_count": len(context.get("massive_sector_etfs") or []),
    }, sort_keys=True))
    if args.dry_run:
        print("PERME_BRIEF_BEGIN")
        print(briefing)
        print("PERME_BRIEF_END")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
