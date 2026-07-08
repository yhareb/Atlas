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
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from atlas_provider_guard import eodhd_get_json  # noqa: E402
from atlas_rag_flags import parse_flags  # noqa: E402
try:
    from atlas_perme_engine_packet import validate_packet as _validate_engine_packet
except Exception:
    _validate_engine_packet = None

ET = ZoneInfo("America/New_York")
SCRIPTS_DIR = Path("/Users/yasser/scripts")
ATLAS_ENV = Path("/Users/yasser/.hermes/profiles/atlas/.env")
PERME_ENV = Path("/Users/yasser/.hermes/profiles/perme/.env")
PERME_PROFILE = "perme"
HERMES_HOME = "/Users/yasser/.hermes/profiles/perme"
HERMES_BIN = os.environ.get("HERMES_BIN", "hermes")
OUTBOX = Path(os.environ.get("PERME_OUTBOX", "/Users/yasser/atlas_inbox"))
MASSIVE_BASE = os.environ.get("MASSIVE_BASE", "https://api.massive.com")
WEEKEND_ROUTINES = {"weekend", "weekend_afternoon", "sunday_evening"}
OWNER_DM_CHAT_ID_ENV = "TELEGRAM_ADMIN_CHAT_ID"
ATLAS_CHANNEL_CHAT_ID_ENV = "TELEGRAM_CHAT_ID"
MACRO_EVENT_STATE = Path(os.environ.get("PERME_MACRO_EVENT_STATE", "/Users/yasser/scripts/perme_macro_event_seen.json"))
MAJOR_MACRO_EVENT_KEYWORDS = ("ISM", "ADP", "NFP", "NONFARM", "CPI", "FED STATEMENT", "FOMC", "FED RATE")
HIGH_MAIN_EVENT_KEYWORDS = (
    "NFP",
    "NONFARM",
    "NON FARM",
    "NON-FARM",
    "PAYROLLS",
    "CPI",
    "PPI",
    "FED RATE",
    "FED INTEREST RATE",
    "RATE DECISION",
    "INTEREST RATE DECISION",
    "FOMC MINUTES",
    "GDP",
    "UNEMPLOYMENT RATE",
    "RETAIL SALES",
)
MEDIUM_MAIN_EVENT_KEYWORDS = (
    "FED SPEAKER",
    "PMI",
    "CONSUMER CONFIDENCE",
    "JOBLESS CLAIMS",
)
LOW_MAIN_EVENT_KEYWORDS = (
    "CFTC",
    "COMMITMENTS OF TRADERS",
    "GOLD POSITIONS",
    "CRUDE OIL INVENTORIES",
    "OIL INVENTORIES",
    "GASOLINE INVENTORIES",
    "NATURAL GAS STORAGE",
    "COMMODITY INVENTORY",
    "ECB",
    "BOE",
    "BOJ",
    "PBOC",
    "FOREIGN CENTRAL BANK",
)

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


def _env_file_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _perme_telegram_credentials() -> tuple[str | None, str | None, str, str]:
    """Return owner chat + Perme bot token without exposing secret values.

    Perme owner-DM reports must be sent by the Perme bot, not the Atlas bot.
    Atlas env remains available for provider/API credentials, but Telegram delivery
    prefers the dedicated Perme profile env.
    """
    atlas_values = _env_file_values(ATLAS_ENV)
    perme_values = _env_file_values(PERME_ENV)
    bot_var = "PERME_ENV:TELEGRAM_BOT_TOKEN"
    chat_var = "PERME_ENV:TELEGRAM_CHAT_ID"
    bot_token = os.environ.get("PERME_TELEGRAM_BOT_TOKEN") or perme_values.get("TELEGRAM_BOT_TOKEN")
    if os.environ.get("PERME_TELEGRAM_BOT_TOKEN"):
        bot_var = "PERME_TELEGRAM_BOT_TOKEN"
    owner_chat = perme_values.get("TELEGRAM_ADMIN_CHAT_ID")
    if owner_chat:
        chat_var = "PERME_ENV:TELEGRAM_ADMIN_CHAT_ID"
    else:
        owner_chat = perme_values.get("TELEGRAM_CHAT_ID")
        if not owner_chat:
            owner_chat = atlas_values.get("TELEGRAM_ADMIN_CHAT_ID") or os.environ.get("TELEGRAM_ADMIN_CHAT_ID")
            chat_var = "ATLAS_ENV:TELEGRAM_ADMIN_CHAT_ID"
    return owner_chat, bot_token, chat_var, bot_var


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
    hm = now_et.strftime("%H:%M")
    if now_et.weekday() == 5:  # Saturday
        return "weekend_afternoon" if hm >= "15:00" else "weekend"
    if now_et.weekday() == 6:  # Sunday
        return "sunday_evening" if hm >= "18:00" else "weekend"
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
    if routine in WEEKEND_ROUTINES:
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
        return [{"date": f"{now_et.date().isoformat()} 05:57 ET", "type": "Fed Speaker", "country": "US", "impact": "medium"}]
    token = os.environ.get("EODHD_API_KEY") or os.environ.get("EODHD_TOKEN")
    if not token:
        return []
    start = now_et.date()
    end = start + (timedelta(days=7) if routine in WEEKEND_ROUTINES else timedelta(days=1))
    data = eodhd_get_json(
        "https://eodhd.com/api/economic-events",
        params={"api_token": token, "fmt": "json", "from": start.isoformat(), "to": end.isoformat(), "country": "US"},
        request_tag="perme_eodhd_economic_calendar",
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


def _normalize_eodhd_economic_calendar_times(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            normalized.append(row)
            continue
        item = dict(row)
        raw_date = item.get("date")
        if not raw_date:
            normalized.append(item)
            continue
        try:
            value = str(raw_date).strip().replace("Z", "+00:00")
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            et_dt = dt.astimezone(ET)
            item["date"] = et_dt.strftime("%Y-%m-%d %H:%M ET")
            item["timezone"] = "ET"
        except Exception:
            pass
        normalized.append(item)
    return normalized


def collect_context(routine: str, mock: bool = False) -> dict[str, Any]:
    now = _now_et()
    resolved_routine = _routine_from_time(now) if routine == "auto" else routine
    economic_calendar = fetch_eodhd_economic_calendar(resolved_routine, now, mock=mock)
    economic_calendar = _normalize_eodhd_economic_calendar_times(economic_calendar)
    return {
        "generated_at_et": now.isoformat(timespec="seconds"),
        "routine": resolved_routine,
        "source_mode": "mock" if mock else "live",
        "benzinga_news": fetch_benzinga_news(resolved_routine, now, mock=mock),
        "benzinga_earnings": fetch_benzinga_earnings(resolved_routine, now, mock=mock),
        "eodhd_economic_calendar": economic_calendar,
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
        "If no flags apply, write None. under ## FLAGS. Do not mention buy/sell/stop/target. "
        "If any HIGH-impact event is listed in the raw data (e.g., NFP, CPI), you MUST explicitly label it a 'MASSIVE CATALYST' in the RISK FACTORS section and warn about extreme volatility and liquidity drain.\n\n"
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

def _markdown_section(text: str, heading: str) -> list[str]:
    lines = str(text or "").splitlines()
    target = heading.strip().lower()
    in_section = False
    found: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            if in_section:
                break
            in_section = stripped[3:].strip().lower() == target
            continue
        if in_section:
            found.append(line.rstrip())
    return found


def _clean_section_line(line: str) -> str:
    cleaned = line.strip()
    while cleaned.startswith(("-", "*", "•")):
        cleaned = cleaned[1:].strip()
    return cleaned


def _first_section_line(text: str, heading: str, default: str = "Unknown") -> str:
    for line in _markdown_section(text, heading):
        cleaned = _clean_section_line(line)
        if cleaned:
            return cleaned
    return default


def _section_block(text: str, heading: str) -> str:
    body = "\n".join(_markdown_section(text, heading)).strip()
    return f"## {heading}\n{body}" if body else f"## {heading}\nNone."




def _compact_lines(lines: list[str], limit: int = 3) -> str:
    cleaned: list[str] = []
    for line in lines or []:
        item = _clean_section_line(line)
        if item and item.lower() not in {"none", "none."}:
            cleaned.append(item)
        if len(cleaned) >= limit:
            break
    return " · ".join(cleaned) if cleaned else "No decisive macro driver isolated"


def _event_name(row: dict[str, Any]) -> str:
    for key in ("event", "name", "type", "title"):
        if row.get(key):
            return str(row.get(key))
    return "Macro event"


def _event_time(row: dict[str, Any]) -> str:
    raw = str(row.get("date") or row.get("datetime") or row.get("time") or "").strip()
    if not raw:
        return "time TBA"
    if " ET" in raw:
        return raw.replace("2026-", "")
    return raw


def _upcoming_macro_events(context: dict[str, Any] | None, limit: int = 3) -> str:
    rows = ((context or {}).get("eodhd_economic_calendar") or []) if isinstance(context, dict) else []
    events = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = _event_name(row)
        if not name:
            continue
        events.append(f"{name} {_event_time(row)}")
        if len(events) >= limit:
            break
    return " · ".join(events) if events else "No major scheduled event in current window"


def _regime_label(briefing: str, flags: list[str]) -> str:
    text = " ".join([" ".join(flags), _first_section_line(briefing, "REGIME", "")]).upper()
    if "RISK-OFF" in text or "RISK OFF" in text:
        return "RISK-OFF"
    if "RISK-ON" in text or "RISK ON" in text:
        return "RISK-ON"
    return "NEUTRAL"


SECTOR_HOLDING_TICKERS = {
    "TECH": {"AAPL", "MSFT", "GOOGL", "GOOG", "META", "AMZN", "SNOW", "CRWD", "ORCL", "NOW", "SYNA", "ALGM", "PLTR"},
    "SEMI": {"NVDA", "AMD", "AVGO", "SMCI", "MU", "TSM", "QCOM", "INTC", "AMAT", "LRCX", "KLAC", "ASML", "MRVL", "ARM", "ALGM", "SYNA"},
    "FINANCIALS": {"BAC", "JPM", "WFC", "C", "GS", "MS", "BOKF", "CVBF"},
    "ENERGY": {"XOM", "CVX"},
    "HEALTHCARE": {"JNJ", "MRK", "ABBV", "PFE", "LLY", "INCY"},
    "INDUSTRIALS": {"GE", "CAT", "BA", "MSM", "IRDM"},
    "CONSUMER_DISCRETIONARY": {"ABNB", "RL", "TSLA", "NKE", "HD", "TGT"},
    "CONSUMER_STAPLES": {"WMT", "COST"},
    "COMMUNICATIONS": {"GOOGL", "GOOG", "META", "NFLX", "DIS", "IRDM"},
    "MATERIALS": set(),
    "UTILITIES": set(),
}


def _open_holding_tickers() -> set[str]:
    # Use the canonical Atlas trade ledger. The legacy positions table is gone.
    db_path = "/Users/yasser/scripts/atlas.db"
    try:
        con = sqlite3.connect(db_path)
        rows = con.execute("SELECT ticker FROM trades WHERE status='OPEN'").fetchall()
        con.close()
        return {str(row[0] or "").upper() for row in rows if row and row[0]}
    except Exception:
        return set()


def _sector_holding_tickers(sector: str) -> list[str]:
    holdings = _open_holding_tickers()
    sector_set = SECTOR_HOLDING_TICKERS.get(str(sector or "").upper(), set())
    return sorted(holdings & sector_set)


def _sector_name_for_atlas(sector: str) -> str:
    sector = str(sector or "").upper()
    if sector in {"TECH", "SEMI"}:
        return "TECH/SEMI"
    return sector.replace("_", " ")


def _largest_sector_move(context: dict[str, Any] | None, direction: str) -> dict[str, Any] | None:
    rows = ((context or {}).get("massive_sector_etfs") or []) if isinstance(context, dict) else []
    candidates = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            pct = float(row.get("change_pct"))
        except Exception:
            continue
        if direction == "down" and pct < -2.0:
            candidates.append((pct, row))
        if direction == "up" and pct > 2.0:
            candidates.append((pct, row))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item[0])[0 if direction == "down" else -1][1]


def _macro_surprise_today(context: dict[str, Any] | None) -> str | None:
    today = _now_et().date().isoformat()
    rows = ((context or {}).get("eodhd_economic_calendar") or []) if isinstance(context, dict) else []
    for row in rows:
        if not isinstance(row, dict) or not _major_macro_event(row):
            continue
        actual = _actual_value(row)
        estimate = row.get("estimate") or row.get("Estimate") or row.get("forecast") or row.get("Forecast")
        if actual in (None, "") or estimate in (None, ""):
            continue
        if str(actual).strip() == str(estimate).strip():
            continue
        event_date = str(row.get("date") or "")
        if today not in event_date:
            continue
        return f"{_event_name(row)} surprise: actual {actual} vs estimate {estimate}; {_atlas_event_implication(row)}"
    return None


def _atlas_instruction(context: dict[str, Any] | None) -> str:
    downside = _largest_sector_move(context, "down")
    if downside:
        sector = str(downside.get("sector") or downside.get("ticker") or "sector").upper()
        pct = float(downside.get("change_pct"))
        if sector == "TECH":
            hold_tickers = sorted(set(_sector_holding_tickers("TECH")) | set(_sector_holding_tickers("SEMI")))
        else:
            hold_tickers = _sector_holding_tickers(sector)
        holders = ", ".join(hold_tickers) if hold_tickers else "No current HOLDING tickers in that sector"
        return f"Avoid new entries in {_sector_name_for_atlas(sector)} names. {holders} can hold if above stop. ({downside.get('ticker')} {pct:+.1f}%)"
    upside = _largest_sector_move(context, "up")
    if upside:
        sector = str(upside.get("sector") or upside.get("ticker") or "sector").upper()
        pct = float(upside.get("change_pct"))
        return f"Sector tailwind in {_sector_name_for_atlas(sector)}. Atlas may find entries there. ({upside.get('ticker')} {pct:+.1f}%)"
    surprise = _macro_surprise_today(context)
    if surprise:
        return surprise
    return "No actionable implication for current holdings."


def _format_event_time(row: dict[str, Any], fallback: datetime | None = None) -> str:
    raw = row.get("date") or row.get("datetime") or row.get("time")
    if raw:
        text = str(raw).strip()
        try:
            # EODHD rows are normalized earlier to strings like
            # "2026-07-02 05:57 ET". Preserve that scheduled event time;
            # do not fall back to the brief generation timestamp.
            match = re.search(r"\b(\d{1,2}):(\d{2})\s*(?:ET)?\b", text, re.I)
            if match:
                hour = int(match.group(1))
                minute = int(match.group(2))
                suffix = "AM" if hour < 12 else "PM"
                display_hour = hour % 12 or 12
                return f"{display_hour}:{minute:02d} {suffix} ET"
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ET)
            return dt.astimezone(ET).strftime("%-I:%M %p ET")
        except Exception:
            pass
    return "time not listed"


def _event_relevance(row: dict[str, Any]) -> str | None:
    impact = str(row.get("impact") or "").upper().strip()
    if impact in {"HIGH", "MEDIUM", "LOW"}:
        return impact

    name = _event_name(row).upper()
    if any(key in name for key in HIGH_MAIN_EVENT_KEYWORDS):
        return "HIGH"
    if any(key in name for key in MEDIUM_MAIN_EVENT_KEYWORDS):
        return "MEDIUM"
    if any(key in name for key in LOW_MAIN_EVENT_KEYWORDS):
        return "LOW"
    return None


def _held_earnings_events(context: dict[str, Any] | None, now_et: datetime) -> list[tuple[str, str]]:
    earnings = ((context or {}).get("benzinga_earnings") or []) if isinstance(context, dict) else []
    holdings = _open_holding_tickers()
    events: list[tuple[str, str]] = []
    for row in earnings:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or row.get("symbol") or "").upper()
        if not ticker or ticker not in holdings:
            continue
        timing = str(row.get("time") or "").upper()
        when = "after market close" if timing == "AMC" else "before the open" if timing == "BMO" else _format_event_time(row, now_et)
        events.append((f"{ticker} earnings", when))
    return events


def _main_event_to_watch(context: dict[str, Any] | None, now_et: datetime) -> tuple[str, str] | None:
    # Main watch item should come from the economic calendar. Held earnings are
    # rendered separately in the position-aware earnings paragraph.
    high_events: list[tuple[str, str]] = []
    medium_events: list[tuple[str, str]] = []
    rows = ((context or {}).get("eodhd_economic_calendar") or []) if isinstance(context, dict) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        relevance = _event_relevance(row)
        if relevance not in {"HIGH", "MEDIUM"}:
            continue
        event = (_event_name(row), _format_event_time(row, now_et))
        if relevance == "HIGH":
            high_events.append(event)
        else:
            medium_events.append(event)
    events = high_events or medium_events
    return events[0] if events else None


def _first_macro_event(context: dict[str, Any] | None, now_et: datetime) -> tuple[str, str] | None:
    """Return the highest-priority main event; ignore low-relevance calendar noise."""
    return _main_event_to_watch(context, now_et)


def _has_only_low_macro_events(context: dict[str, Any] | None) -> bool:
    rows = ((context or {}).get("eodhd_economic_calendar") or []) if isinstance(context, dict) else []
    saw_low = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        relevance = _event_relevance(row)
        if relevance in {"HIGH", "MEDIUM"}:
            return False
        if relevance == "LOW":
            saw_low = True
    return saw_low


def _sector_hot_sentence(context: dict[str, Any] | None) -> str | None:
    rows = ((context or {}).get("massive_sector_etfs") or []) if isinstance(context, dict) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").upper()
        sector = str(row.get("sector") or "").upper()
        overbought = bool(row.get("overbought"))
        if not (ticker or sector) or not overbought:
            continue
        try:
            pct = float(row.get("change_pct"))
        except Exception:
            pct = None
        try:
            rsi = float(row.get("rsi"))
        except Exception:
            rsi = None
        label = "Semis" if sector == "SEMI" or ticker == "SMH" else _sector_name_for_atlas(sector).title()
        parts = [f"{label} are running hot"]
        if ticker and pct is not None and rsi is not None:
            parts.append(f"{ticker} is up {pct:.1f}% with RSI at {rsi:.1f}, which puts it in overbought territory")
        elif ticker and pct is not None:
            parts.append(f"{ticker} is up {pct:.1f}%, which puts that group in extended territory")
        sentence = "⚠️ " + " — ".join(parts) + ". That does not mean it crashes today, but it means you do not chase anything in that space right now."
        holders = _sector_holding_tickers(sector)
        if holders:
            sentence += f" Your current exposure there: {', '.join(holders)}."
        return sentence
    return None


def _earnings_sentence(context: dict[str, Any] | None) -> str | None:
    earnings = ((context or {}).get("benzinga_earnings") or []) if isinstance(context, dict) else []
    holdings = _open_holding_tickers()
    for row in earnings:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or row.get("symbol") or "").upper()
        if not ticker:
            continue
        timing = str(row.get("time") or "").upper()
        when = "after market close" if timing == "AMC" else "before the open" if timing == "BMO" else "today"
        if ticker in holdings:
            return f"💼 One earnings event to flag: {ticker} reports {when} today. You are holding {ticker} — no action needed before the number, but be aware the stock could move sharply after close."
        return f"📅 One earnings event to flag: {ticker} reports {when} today. You are not holding it, so this is watch-list context rather than an immediate action item."
    return None


def _market_tone_sentence(briefing: str, context: dict[str, Any] | None, now_et: datetime, flags: list[str]) -> str:
    regime = _regime_label(briefing, flags)
    event = _first_macro_event(context, now_et)
    if regime == "RISK-OFF":
        base = "⚠️ Markets are on the defensive heading into the session."
    elif regime == "RISK-ON":
        base = "🟢 Markets have a constructive tone heading into the session."
    else:
        base = "📊 Markets are relatively calm heading into the session."
    if event:
        name, when = event
        display_name = "a Fed speaker" if name.lower() == "fed speaker" else name
        return f"{base} 📅 The main thing to watch today is {display_name} at {when}."
    if _has_only_low_macro_events(context):
        return f"{base} No major macro events today."
    return f"{base} No major macro events today."


def _final_risk_sentence(briefing: str, flags: list[str]) -> str:
    regime = _regime_label(briefing, flags)
    if regime == "RISK-OFF":
        return "⚠️ Nothing else is urgent for your other open positions. System is defensive — keep stops intact and avoid forcing new entries until the tape improves."
    if regime == "RISK-ON":
        return "🟢 Nothing urgent for your other open positions. System has a positive tilt, but entries still need Atlas confirmation."
    return "Nothing urgent for your other open positions. System is running neutral — no new entries blocked, but no strong tailwind either."


def _next_watch_sentence(context: dict[str, Any] | None, now_et: datetime) -> str:
    event = _first_macro_event(context, now_et)
    if event:
        name, when = event
        return f"📅 Next to watch: {name} at {when} today."
    return "📅 Next to watch: No major macro events today; normal Atlas gates and any fresh macro headlines."


def _perme_macro_prose(briefing: str, context: dict[str, Any] | None, now_et: datetime, flags: list[str]) -> str:
    paragraphs = [
        f"📍 Macro Pulse — {now_et.strftime('%H:%M')} ET",
        _market_tone_sentence(briefing, context, now_et, flags),
    ]
    hot = _sector_hot_sentence(context)
    if hot:
        paragraphs.append(hot)
    earnings = _earnings_sentence(context)
    if earnings:
        paragraphs.append(earnings)
    paragraphs.append(_final_risk_sentence(briefing, flags))
    paragraphs.append(_next_watch_sentence(context, now_et))
    return "\n\n".join(paragraphs)


def format_telegram_brief(briefing: str, routine: str, now_et: datetime, context: dict[str, Any] | None = None) -> str:
    flags_text = "\n".join(_clean_section_line(line) for line in _markdown_section(briefing, "FLAGS"))
    flags = parse_flags(flags_text)
    return _perme_macro_prose(briefing, context, now_et, flags)


def _first_sentence(text: str, limit: int = 120) -> str:
    clean = " ".join(str(text or "").split())
    match = re.search(r"(.+?[.!?])(?:\s|$)", clean)
    reason = match.group(1) if match else clean
    if len(reason) > limit:
        reason = reason[:limit].rstrip()
    return reason


def _extract_flag_values(briefing: str, prefix: str) -> list[str]:
    values: list[str] = []
    marker = prefix.strip().upper() + ":"
    for line in _markdown_section(briefing, "FLAGS"):
        text = str(line or "").strip()
        if text.upper().startswith(marker):
            value = text.split(":", 1)[1].strip().upper()
            if value and value not in values:
                values.append(value)
    return values


def _derive_latest_context(briefing: str, generated_at: datetime, ttl_minutes: int = 240) -> dict[str, Any]:
    regime_text = " ".join(_markdown_section(briefing, "REGIME"))
    regime_upper = regime_text.upper()
    if any(term in regime_upper for term in ("RISK-OFF", "RISK OFF", "PRESSURE", "PROFIT-TAKING", "PROFIT TAKING", "CAUTION")):
        sentiment = "RISK_OFF"
    elif any(term in regime_upper for term in ("MIXED", "COEXIST")):
        sentiment = "CAUTION"
    else:
        sentiment = "NEUTRAL"
    event_terms = re.compile(
        r"\b(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|JULY|AUG|SEP|SEPT|OCT|NOV|DEC|MON|TUE|WED|THU|FRI|SAT|SUN|ESTIMATE|PREVIOUS|AM|PM|A\.M\.|P\.M\.|\d{1,2}:\d{2})\b",
        re.I,
    )
    upcoming_events = []
    for line in _markdown_section(briefing, "EVIDENCE"):
        text = _clean_section_line(line)
        if text and event_terms.search(text):
            upcoming_events.append(text)
    return {
        "sentiment": sentiment,
        "reason": _first_sentence(regime_text),
        "cautious": sentiment in {"RISK_OFF", "CAUTION"},
        "suppressed_sectors": _extract_flag_values(briefing, "SECTOR_NOTE"),
        "ticker_notes": _extract_flag_values(briefing, "TICKER_NOTE"),
        "upcoming_events": upcoming_events,
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ttl_minutes": ttl_minutes,
    }


def write_latest_context(briefing: str, outbox: Path, generated_at: datetime) -> Path:
    outbox.mkdir(parents=True, exist_ok=True)
    payload = _derive_latest_context(briefing, generated_at=generated_at)
    path = outbox / "latest_context.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path



def _packet_event_severity(row: dict[str, Any]) -> str:
    impact = str(row.get("impact") or row.get("Impact") or "").upper()
    name = _event_name(row).upper()
    if impact == "HIGH" or any(k in name for k in HIGH_MAIN_EVENT_KEYWORDS):
        return "HIGH"
    if impact == "MEDIUM" or any(k in name for k in MEDIUM_MAIN_EVENT_KEYWORDS):
        return "MEDIUM"
    return "LOW"


def _packet_direction(context: dict[str, Any], severity: str) -> str:
    sectors = context.get("massive_sector_etfs") or []
    try:
        worst = min([float(r.get("change_pct")) for r in sectors if r.get("change_pct") is not None] or [0.0])
    except Exception:
        worst = 0.0
    if severity == "HIGH" or worst <= -1.0:
        return "RISK_OFF"
    return "NEUTRAL"


def _packet_sector(context: dict[str, Any]) -> str:
    sectors = context.get("massive_sector_etfs") or []
    if not sectors:
        return ""
    try:
        row = sorted(sectors, key=lambda r: abs(float(r.get("change_pct") or 0)), reverse=True)[0]
        return str(row.get("sector") or row.get("ticker") or "").upper()
    except Exception:
        return ""


def _packet_tickers(context: dict[str, Any]) -> list[str]:
    out = []
    for row in context.get("benzinga_earnings") or []:
        ticker = str(row.get("ticker") or row.get("symbol") or "").upper().strip()
        if ticker and ticker not in out:
            out.append(ticker)
    return out[:12]


def build_engine_packets_from_context(context: dict[str, Any], generated_at: datetime, ttl_minutes: int = 240) -> list[dict[str, Any]]:
    """Build schema-valid engine packets from structured provider facts only, never prose."""
    rows = [r for r in (context.get("eodhd_economic_calendar") or []) if isinstance(r, dict)]
    if not rows:
        rows = [{}]
    severity = "LOW"
    evidence_count = 0
    event_type = "CONTEXT"
    for row in rows:
        row_sev = _packet_event_severity(row)
        if row_sev == "HIGH":
            severity = "HIGH"
        elif row_sev == "MEDIUM" and severity != "HIGH":
            severity = "MEDIUM"
        if row:
            evidence_count += 1
            if event_type == "CONTEXT":
                event_type = _event_name(row).upper() or "MACRO_EVENT"
    packet = {
        "schema": "perme_engine_packet_v1",
        "generated_at_et": generated_at.astimezone(ET).isoformat(timespec="seconds"),
        "ttl_minutes": int(ttl_minutes),
        "severity": severity,
        "confidence": 0.85 if severity == "HIGH" else 0.65 if severity == "MEDIUM" else 0.5,
        "scope": "SECTOR" if _packet_sector(context) else "MARKET",
        "sector": _packet_sector(context),
        "tickers": _packet_tickers(context),
        "event_type": event_type,
        "direction": _packet_direction(context, severity),
        "evidence_count": max(1, evidence_count),
        "reason_code": "STRUCTURED_MACRO_FACTS",
        "allowed_actions": ["ANNOTATE", "REVIEW_NOW"],
        "forbidden_actions": ["BUY", "SELL", "CHANGE_STOP", "CHANGE_TARGET"],
    }
    return [packet]


def write_engine_packet(context: dict[str, Any], outbox: Path, generated_at: datetime) -> Path:
    path = Path(os.environ.get("PERME_ENGINE_PACKET_PATH") or os.environ.get("ATLAS_PERME_ENGINE_PACKET_PATH") or (outbox / "perme_engine_packet_v1.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)
    packets = build_engine_packets_from_context(context, generated_at=generated_at)
    if _validate_engine_packet is not None:
        for packet in packets:
            result = _validate_engine_packet(packet)
            if not result.ok:
                raise RuntimeError(f"engine packet validation failed: {result.error}")
    path.write_text("".join(json.dumps(p, sort_keys=True, separators=(",", ":")) + "\n" for p in packets), encoding="utf-8")
    return path

def _owner_dm_chat_id_var() -> str:
    return OWNER_DM_CHAT_ID_ENV


def _telegram_plain_chunks(message: str, limit: int = 3900) -> list[str]:
    text = str(message or "")
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    return chunks


def deliver_telegram_brief(message: str, dry_run: bool = False) -> None:
    """Send Perme macro brief through the Perme bot to the owner DM route."""
    owner_chat, bot_token, chat_var, bot_var = _perme_telegram_credentials()
    if dry_run:
        print("[perme] dry-run: Telegram delivery suppressed")
        print(f"PERME_TELEGRAM_ROUTE_CHAT_ID_VAR={chat_var}")
        print(f"PERME_TELEGRAM_BOT_TOKEN_VAR={bot_var}")
        return
    if not owner_chat or not bot_token:
        print(f"[perme] telegram brief skipped: {chat_var} or {bot_var} unset", file=sys.stderr)
        return
    import time as _time
    import traceback as _traceback
    _max_attempts = 3
    _attempt = 0
    _last_exc = None
    while _attempt < _max_attempts:
        try:
            for chunk in _telegram_plain_chunks(message):
                payload = json.dumps({"chat_id": owner_chat, "text": chunk}).encode("utf-8")
                req = Request(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(req, timeout=30) as resp:
                    resp.read()
            print("[perme] telegram brief owner_dm sent")
            _last_exc = None
            break
        except Exception as exc:
            _last_exc = exc
            _attempt += 1
            print(f"[perme] telegram send attempt {_attempt} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            if _attempt < _max_attempts:
                _time.sleep(5)
    if _last_exc is not None:
        print(f"[perme] telegram brief failed after {_max_attempts} attempts: {type(_last_exc).__name__}", file=sys.stderr)
        _traceback.print_exc(file=sys.stderr)


def _load_macro_event_state() -> set[str]:
    try:
        data = json.loads(MACRO_EVENT_STATE.read_text())
        return {str(x) for x in (data or [])}
    except Exception:
        return set()


def _save_macro_event_state(seen: set[str]) -> None:
    try:
        MACRO_EVENT_STATE.parent.mkdir(parents=True, exist_ok=True)
        MACRO_EVENT_STATE.write_text(json.dumps(sorted(seen), indent=2) + "\n")
    except Exception as exc:
        print(f"[perme] macro event state save skipped: {type(exc).__name__}: {exc}", file=sys.stderr)


def _major_macro_event(row: dict[str, Any]) -> bool:
    name = _event_name(row).upper()
    return any(key in name for key in MAJOR_MACRO_EVENT_KEYWORDS)


def _actual_value(row: dict[str, Any]) -> Any:
    for key in ("actual", "Actual", "value", "reported"):
        val = row.get(key)
        if val not in (None, "", "N/A"):
            return val
    return None


def _event_identity(row: dict[str, Any]) -> str:
    return "|".join(str(row.get(k) or "") for k in ("date", "event", "name", "type", "country"))


def _atlas_event_implication(row: dict[str, Any]) -> str:
    name = _event_name(row).upper()
    if "CPI" in name:
        return "Inflation surprise can reprice rates; avoid chasing rate-sensitive entries until Atlas confirms."
    if "NFP" in name or "NONFARM" in name or "ADP" in name:
        return "Labor surprise can move yields and banks; keep new entries gated and stops intact."
    if "ISM" in name:
        return "Growth surprise affects cyclicals; require live confirmation before new exposure."
    if "FED" in name or "FOMC" in name:
        return "Fed release can dominate tape; avoid discretionary entries around headline volatility."
    return "Treat as macro volatility input; do not override Atlas gates."


def _macro_event_brief(row: dict[str, Any], now_et: datetime) -> str:
    actual = _actual_value(row)
    estimate = row.get("estimate") or row.get("Estimate") or row.get("forecast") or row.get("Forecast") or "N/A"
    previous = row.get("previous") or row.get("Previous") or "N/A"
    return (
        f"📡 Perme Macro Event — {now_et.strftime('%Y-%m-%d %H:%M ET')}\n\n"
        f"Event: {_event_name(row)}\n"
        f"Actual: {actual}\n"
        f"Estimate: {estimate}\n"
        f"Previous: {previous}\n"
        f"Atlas: {_atlas_event_implication(row)}"
    )


def poll_macro_event_releases(dry_run: bool = False, mock_events: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    now_et = _now_et()
    rows = mock_events
    if rows is None:
        token = os.environ.get("EODHD_API_KEY") or os.environ.get("EODHD_TOKEN")
        if not token:
            return []
        data = eodhd_get_json(
            "https://eodhd.com/api/economic-events",
            params={"api_token": token, "fmt": "json", "from": now_et.date().isoformat(), "to": now_et.date().isoformat(), "country": "US"},
            request_tag="perme_macro_event_monitor",
        )
        rows = data if isinstance(data, list) else []
    seen = _load_macro_event_state()
    fired: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict) or not _major_macro_event(row) or _actual_value(row) is None:
            continue
        ident = _event_identity(row)
        if ident in seen:
            continue
        brief = _macro_event_brief(row, now_et)
        deliver_telegram_brief(brief, dry_run=dry_run)
        seen.add(ident)
        fired.append(row)
    if fired and not dry_run:
        _save_macro_event_state(seen)
    return fired


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Atlas Perme briefing engine")
    parser.add_argument("--routine", required=True, choices=["auto", "pre_market", "intraday", "post_market", "weekend", "weekend_afternoon", "sunday_evening", "macro_event_monitor"])
    parser.add_argument("--dry-run", action="store_true", help="Print diagnostics; still writes the Markdown file")
    parser.add_argument("--mock-data", action="store_true", help="Use deterministic mock API payloads for Gate 1")
    parser.add_argument("--output", default="", help="Optional explicit output path")
    args = parser.parse_args(argv)

    _load_env_file(ATLAS_ENV)
    if args.routine == "macro_event_monitor":
        fired = poll_macro_event_releases(dry_run=args.dry_run)
        print("PERME_RESULT_JSON=" + json.dumps({"routine": "macro_event_monitor", "fired_count": len(fired)}, sort_keys=True))
        return 0
    context = collect_context(args.routine, mock=args.mock_data)
    prompt = build_prompt(context)
    briefing = run_perme(prompt)
    generated_at = _now_et()
    path = Path(args.output).expanduser() if args.output else output_path(generated_at)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(briefing.rstrip() + "\n")
    output_bytes = path.stat().st_size
    latest_context_path = write_latest_context(briefing, path.parent, generated_at)
    engine_packet_path = write_engine_packet(context, path.parent, generated_at)
    if args.dry_run:
        print("[atlas_rag] dry-run: indexer suppressed")
    else:
        try:
            from atlas_rag_indexer import index_perme_briefs as index_new_briefs
            _rag_summary = index_new_briefs()
            print(f"[atlas_rag] INDEXED_NEW={_rag_summary.get('indexed_new')} TOTAL_AFTER={_rag_summary.get('total_after')}")
        except Exception as e:
            print(f"[atlas_rag] indexer error (non-fatal): {e}")
    routine = str(context.get("routine") or args.routine)
    telegram_message = format_telegram_brief(briefing, routine, generated_at, context=context)
    if args.dry_run:
        deliver_telegram_brief(telegram_message, dry_run=True)
    else:
        deliver_telegram_brief(telegram_message, dry_run=False)
    print("PERME_RESULT_JSON=" + json.dumps({
        "routine": routine,
        "source_mode": context.get("source_mode"),
        "output_path": str(path),
        "latest_context_path": str(latest_context_path),
        "engine_packet_path": str(engine_packet_path),
        "bytes": output_bytes,
        "news_count": len(context.get("benzinga_news") or []),
        "earnings_count": len(context.get("benzinga_earnings") or []),
        "economic_events_count": len(context.get("eodhd_economic_calendar") or []),
        "sector_count": len(context.get("massive_sector_etfs") or []),
    }, sort_keys=True))
    if args.dry_run:
        print("PERME_BRIEF_BEGIN")
        print(briefing)
        print("PERME_BRIEF_END")
        print("PERME_TELEGRAM_BRIEF_BEGIN")
        print(telegram_message)
        print("PERME_TELEGRAM_BRIEF_END")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
