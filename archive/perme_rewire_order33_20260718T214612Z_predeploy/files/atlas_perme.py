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
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from atlas_provider_guard import eodhd_get_json  # noqa: E402
from atlas_time import is_trading_day  # noqa: E402
import atlas_db  # noqa: E402
from atlas_report_authority import portfolio_context_tickers  # noqa: E402
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


# NYSE early-close days are valid trading sessions for Perme report eligibility.
# The shared Atlas full-holiday helper remains the primary gate; this exception
# prevents early-close sessions from being treated as full market holidays.
NYSE_EARLY_CLOSE_SESSION_DAYS_2026 = {
    date(2026, 7, 2),
    date(2026, 11, 27),
    date(2026, 12, 24),
}


def _is_nyse_session_day(day: date) -> bool:
    if day in NYSE_EARLY_CLOSE_SESSION_DAYS_2026:
        return day.weekday() < 5
    return bool(is_trading_day(day))


def _non_trading_day_reason(now_et: datetime) -> str | None:
    day = now_et.astimezone(ET).date() if now_et.tzinfo else now_et.date()
    if day.weekday() >= 5:
        return "WEEKEND"
    if not _is_nyse_session_day(day):
        return "NYSE_HOLIDAY"
    return None


def _perme_skip_non_trading_day_line(now_et: datetime, reason: str) -> str:
    day = now_et.astimezone(ET).date() if now_et.tzinfo else now_et.date()
    return f"PERME_SKIP_NON_TRADING_DAY date={day.isoformat()} reason={reason}"


def render_closed_day_diagnostic(now_et: datetime, reason: str) -> str:
    day = now_et.astimezone(ET).date() if now_et.tzinfo else now_et.date()
    return (
        f"Perme diagnostic only — market is closed on {day.isoformat()} "
        f"({reason}). No provider calls, Hermes invocation, RAG lookup, "
        "outbox write, macro-state write, or Telegram send was performed."
    )


def _routine_from_time(now_et: datetime) -> str:
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
        "If any HIGH-impact event is listed in the raw data (e.g., NFP, CPI), label it a 'HIGH-IMPACT CATALYST' in the RISK FACTORS section and warn about extreme volatility and liquidity drain. Never use provider names such as Massive as intensity adjectives.\n\n"
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
    return _sanitize_provider_label_leakage(cleaned)


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


# Semantic guardrails for human-facing Perme prose. These are report-rendering
# constraints only; they do not alter Atlas strategy, providers, schedules, DB,
# broker state, or engine packets. The classifier is generated from reusable
# sector membership sets; no ticker-specific control flow is permitted.
ISSUER_SECTOR_MEMBERS = {
    **{sector: frozenset(tickers) for sector, tickers in SECTOR_HOLDING_TICKERS.items()},
    "HEALTHCARE": frozenset(set(SECTOR_HOLDING_TICKERS.get("HEALTHCARE", set())) | {"UNH"}),
}

FINANCIAL_SECTOR = "FINANCIALS"
HEALTHCARE_SECTORS = {"HEALTHCARE", "PHARMACEUTICALS", "MEDTECH"}
SEMI_SECTORS = {"SEMI", "TECH"}


def _sanitize_provider_label_leakage(text: str) -> str:
    # Massive is a market-data provider name in Atlas; it must never read as a
    # severity adjective in Professor-facing prose.
    return re.sub(r"\bMASSIVE\s+CATALYST\b", "high-impact catalyst", str(text or ""), flags=re.I)


def _ticker_sector(ticker: str, metadata: dict[str, Any] | None = None) -> str | None:
    """Classify from normalized issuer metadata, then the reusable sector registry.

    Conflicting normalized metadata fails closed. There is deliberately no
    ticker-specific branch in this classifier.
    """
    ticker = str(ticker or "").upper().strip()
    if not ticker:
        return None
    metadata = metadata or {}
    normalized = set()
    for key in ("sector", "industry", "gic_sector", "gic_industry", "sic_description"):
        value = str(metadata.get(key) or "").upper()
        if any(term in value for term in ("HEALTH", "PHARMA", "MEDTECH", "MEDICAL")):
            normalized.add("HEALTHCARE")
        if any(term in value for term in ("FINANC", "BANK", "CAPITAL MARKETS")):
            normalized.add("FINANCIALS")
        if any(term in value for term in ("SEMICONDUCTOR", "CHIP")):
            normalized.add("SEMI")
        if any(term in value for term in ("TECHNOLOGY", "SOFTWARE", "HARDWARE")):
            normalized.add("TECH")
    if len(normalized) == 1:
        return next(iter(normalized))
    if len(normalized) > 1 and not normalized <= SEMI_SECTORS:
        return None
    if normalized <= SEMI_SECTORS and normalized:
        return "SEMI" if "SEMI" in normalized else "TECH"
    matches = [sector for sector, tickers in ISSUER_SECTOR_MEMBERS.items() if ticker in tickers]
    return matches[0] if len(set(matches)) == 1 else None


def _sector_label_for_ticker(ticker: str) -> str:
    sector = _ticker_sector(ticker)
    if sector == "HEALTHCARE":
        return "healthcare / pharmaceuticals / MedTech"
    if sector == "FINANCIALS":
        return "financials / banking"
    if sector == "SEMI":
        return "semiconductors"
    if sector:
        return sector.lower().replace("_", " ")
    return "DATA INCOMPLETE"


def _is_valid_bank_issuer(ticker: str) -> bool:
    return _ticker_sector(ticker) == FINANCIAL_SECTOR


def _authoritative_holding_set(context: dict[str, Any] | None = None) -> set[str]:
    if isinstance(context, dict):
        for key in ("authoritative_open_holdings", "open_holdings", "current_open_holdings"):
            raw = context.get(key)
            if raw:
                return {str(x).upper() for x in raw if str(x or "").strip()}
    return _open_holding_tickers()


def _bank_holdings(context: dict[str, Any] | None = None) -> list[str]:
    return sorted(t for t in _authoritative_holding_set(context) if _is_valid_bank_issuer(t))


def _semi_pressure_support(evidence: list[str], flags: list[str]) -> tuple[bool, bool, list[str]]:
    """Require direction words/numbers on the same evidence line as a named semi source."""
    names_re = re.compile(r"\b(?:SMH|SOXX|ASML|INTC|NVDA|AMD|TSM|MU|AMAT|LRCX|KLAC|QCOM|AVGO|MRVL|ARM|SYNA)\b", re.I)
    sector_re = re.compile(r"\b(?:SEMICONDUCTOR|SEMIS?|CHIP(?:-SECTOR)?|PHLX SEMICONDUCTOR)\b", re.I)
    negative_re = re.compile(r"\b(?:UNDER PRESSURE|PRESSURED|WEAK|WEAKNESS|DOWN|LOWER|SELLOFF|SELL-OFF|DE-RATING|DERATING|BELOW SUPPORT)\b|\b(?:SMH|SOXX)\b[^\n.;]*-\d", re.I)
    positive_re = re.compile(r"\b(?:REBOUND|STRENGTH|HIGHER|GAINED|UP|EXTENDS?|CAPACITY EXPANSION|READINESS PROGRESS|AI CUSTOMER DEMAND|OUTPERFORMANCE)\b|\b(?:SMH|SOXX)\b[^\n.;]*\+\d", re.I)
    named: set[str] = set()
    negative = False
    positive = False
    for line in evidence:
        if not (names_re.search(line) or sector_re.search(line)):
            continue
        named.update(x.upper() for x in names_re.findall(line))
        negative = negative or bool(negative_re.search(line))
        positive = positive or bool(positive_re.search(line))
    if negative and positive:
        return False, True, sorted(named)
    return negative, False, sorted(named)



def _open_holding_tickers() -> set[str]:
    # Portfolio context must include OPEN plus broker/cash-pending exposure;
    # never use status='OPEN' alone for Professor-facing context.
    try:
        open_rows = atlas_db.get_open_positions()
    except Exception:
        open_rows = []
    try:
        pending_rows = atlas_db.get_pending_broker_confirmation_trades()
    except Exception:
        pending_rows = []
    return portfolio_context_tickers(open_rows, pending_rows)


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


def _event_session_date(row: dict[str, Any]) -> str | None:
    raw = str(row.get("date") or row.get("datetime") or row.get("time") or "").strip()
    match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", raw)
    return match.group(1) if match else None


def _event_matches_report_focus(row: dict[str, Any], focus_text: str) -> bool:
    """Keep CPI/PPI events separated when the report is focused on one of them."""
    focus = str(focus_text or "").upper()
    name = _event_name(row).upper()
    focus_cpi = "CPI" in focus or "CONSUMER PRICE" in focus
    focus_ppi = "PPI" in focus or "PRODUCER PRICE" in focus
    if focus_cpi and not focus_ppi and ("PPI" in name or "PRODUCER PRICE" in name):
        return False
    if focus_ppi and not focus_cpi and ("CPI" in name or "CONSUMER PRICE" in name):
        return False
    return True


def _main_event_to_watch(context: dict[str, Any] | None, now_et: datetime, focus_text: str = "") -> tuple[str, str] | None:
    # Main watch item should come from the economic calendar. Held earnings are
    # rendered separately in the position-aware earnings paragraph. Only same-date
    # HIGH/MEDIUM events can appear in a market-session report; CPI/PPI are not
    # cross-filled from adjacent days or opposite inflation releases.
    high_events: list[tuple[str, str, str]] = []
    medium_events: list[tuple[str, str, str]] = []
    rows = ((context or {}).get("eodhd_economic_calendar") or []) if isinstance(context, dict) else []
    report_date = now_et.date().isoformat()
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        event_date = _event_session_date(row)
        if event_date and event_date != report_date:
            continue
        if not _event_matches_report_focus(row, focus_text):
            continue
        relevance = _event_relevance(row)
        if relevance not in {"HIGH", "MEDIUM"}:
            continue
        name = _event_name(row)
        when = _format_event_time(row, now_et)
        key = (name.upper(), when)
        if key in seen:
            continue
        seen.add(key)
        event = (name, when, name.upper())
        if relevance == "HIGH":
            high_events.append(event)
        else:
            medium_events.append(event)
    focus = str(focus_text or "").upper()
    def _score(item: tuple[str, str, str]) -> int:
        name_upper = item[2]
        if ("CPI" in focus or "CONSUMER PRICE" in focus) and ("CPI" in name_upper or "CONSUMER PRICE" in name_upper):
            return 0
        if ("PPI" in focus or "PRODUCER PRICE" in focus) and ("PPI" in name_upper or "PRODUCER PRICE" in name_upper):
            return 0
        return 1
    events = sorted(high_events, key=_score) or sorted(medium_events, key=_score)
    return (events[0][0], events[0][1]) if events else None


def _first_macro_event(context: dict[str, Any] | None, now_et: datetime, focus_text: str = "") -> tuple[str, str] | None:
    """Return the highest-priority same-session event; ignore low/stale calendar noise."""
    return _main_event_to_watch(context, now_et, focus_text)


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


def _repair_punctuation_spacing(text: str) -> str:
    """Deterministically repair sentence-boundary joins such as
    '335.12.Meanwhile' without changing decimal points like '335.12'."""
    repaired = re.sub(r"(?<=[.!?])(?=[A-Z])", " ", str(text or ""))
    repaired = re.sub(r"\s+([,.;:!?])", r"\1", repaired)
    repaired = re.sub(r"\s{2,}", " ", repaired)
    return repaired.strip()


def _clean_market_phrase(text: str, limit: int = 180) -> str:
    cleaned = _repair_punctuation_spacing(" ".join(str(text or "").replace("**", "").split()))
    cleaned = re.sub(r"\bRSI\s+(?:at\s+)?([0-9]+(?:\.[0-9]+)?)\b", r"RSI \1", cleaned, flags=re.I)
    if len(cleaned) > limit:
        cleaned = cleaned[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"
    return cleaned


def _brief_bullets(briefing: str, heading: str) -> list[str]:
    bullets: list[str] = []
    for line in _markdown_section(briefing, heading):
        cleaned = _clean_section_line(line)
        if cleaned and cleaned.lower() not in {"none", "none."}:
            bullets.append(cleaned)
    return bullets


def _first_matching_line(lines: list[str], terms: tuple[str, ...]) -> str | None:
    for line in lines:
        upper = line.upper()
        if any(term in upper for term in terms):
            return line
    return lines[0] if lines else None


def _market_tape_from_evidence(evidence: list[str]) -> str:
    # Unlike _first_matching_line(), this must not fall back to the first company
    # earnings sentence; a market-tape paragraph needs named index/sector evidence.
    for line in evidence:
        if any(term in line.upper() for term in ("SMH", "SOXX", "XLK", "NASDAQ", "S&P", "SPY", "DOW", "XLE", "XLF", "QQQ")):
            return _clean_market_phrase(line, 210)
    return ""


def _driver_from_evidence(evidence: list[str], risks: list[str]) -> str:
    driver = _first_matching_line(evidence, ("TRUMP", "TARIFF", "SANCTION", "CEASEFIRE", "WAR", "IRAN", "MIDDLE EAST", "HORMUZ", "TAIWAN", "CHINA", "EXPORT RESTRICTION", "FEDWATCH", "RATE-HIKE", "RATE HIKE", "VIX", "OIL", "GOLD", "DOLLAR", "YIELDS", "NASDAQ FUTURES", "SAMSUNG", "FED", "FOMC", "CPI", "NFP", "ADP", "AI", "SEMICONDUCTOR"))
    if not driver:
        driver = _first_matching_line(risks, ("MASSIVE CATALYST", "POLICY", "GEOPOLITICAL", "TARIFF", "SANCTION", "CEASEFIRE", "IRAN", "HORMUZ", "CHINA", "TAIWAN", "RATE", "FEDWATCH", "SEMICONDUCTOR", "ENERGY", "FED"))
    if not driver:
        return "No single driver is clean enough to overstate; keep the move framed as mixed macro/tape context."
    return _clean_market_phrase(driver, 220)


def _rotation_from_evidence(evidence: list[str], flags: list[str]) -> str:
    text = " ".join(evidence + flags).upper()
    winners = []
    stretched = []
    losers = []
    if "XLE" in text or "ENERGY" in text or "OIL" in text or "HORMUZ" in text or "IRAN" in text or "MIDDLE EAST" in text:
        winners.append("energy")
    if "GOLD" in text:
        winners.append("gold/safety")
    if "DOLLAR" in text or "USD" in text:
        winners.append("dollar defensives")
    if "FINANCIALS" in text or "XLF" in text:
        stretched.append("financials")
    if "HEALTHCARE" in text or "XLV" in text:
        stretched.append("healthcare")
    semi_pressure, semi_conflict, semi_names = _semi_pressure_support(evidence, flags)
    if semi_conflict:
        return "Semiconductor evidence is mixed, so no directional sector conclusion is warranted."
    if semi_pressure:
        losers.append("semiconductors")
    elif (semi_names or any(term in text for term in ("SEMI", "SEMICONDUCTOR", "CHIP"))) and not any(term in text for term in ("GAINED", "REBOUND", "STRENGTH", "HIGHER", "OUTPERFORMANCE", "CAPACITY EXPANSION", "READINESS PROGRESS")):
        return "Available evidence is not strong enough to make a directional semiconductor-sector call."
    # Tech/growth pressure also needs a named sector/index signal, not a generic flag.
    tech_named = any(term in text for term in ("XLK", "NASDAQ", "QQQ"))
    tech_negative = any(term in text for term in ("UNDER PRESSURE", "WEAK", "WEAKNESS", "DOWN", "LOWER", "FUTURES DOWN")) or bool(re.search(r"\b(?:XLK|QQQ)\b[^\n.;]*-\d", text))
    if tech_named and tech_negative:
        losers.append("tech/growth")
    if winners or stretched or losers:
        clauses = []
        if winners:
            clauses.append(f"money favored {', '.join(winners)}")
        if stretched:
            clauses.append(f"{', '.join(stretched)} looked stretched rather than fresh leadership")
        if losers:
            clauses.append(f"{', '.join(losers)} came under pressure")
        return "; ".join(clauses).capitalize() + "."
    return "Available evidence is not strong enough to make a directional sector call."


def _geopolitical_market_impact(evidence: list[str], flags: list[str]) -> str | None:
    text = " ".join(evidence + flags).upper()
    # Monetary-policy language alone is not geopolitical evidence.
    if not any(term in text for term in ("TRUMP", "TARIFF", "SANCTION", "CEASEFIRE", "WAR", "IRAN", "MIDDLE EAST", "HORMUZ", "CHINA", "TAIWAN", "EXPORT RESTRICTION", "ELECTION")):
        return None
    moved = []
    if "NASDAQ" in text or "FUTURES" in text:
        moved.append("equity futures / Nasdaq risk appetite")
    if "VIX" in text:
        moved.append("VIX volatility")
    if "OIL" in text or "HORMUZ" in text or "IRAN" in text or "MIDDLE EAST" in text:
        moved.append("oil/energy")
    if "GOLD" in text:
        moved.append("gold/safety bid")
    if "DOLLAR" in text or "USD" in text:
        moved.append("dollar")
    if "YIELD" in text or "FEDWATCH" in text or "RATE-HIKE" in text or "RATE HIKE" in text:
        moved.append("yields / rate-pricing")
    sectors = []
    if any(term in text for term in ("OIL", "IRAN", "HORMUZ", "MIDDLE EAST")):
        sectors.append("energy")
    if any(term in text for term in ("NASDAQ", "TECH", "CHIP", "TAIWAN", "EXPORT RESTRICTION")):
        sectors.append("tech/semis")
    if any(term in text for term in ("YIELD", "FEDWATCH", "RATE")):
        sectors.append("banks and high-duration growth")
    market = ", ".join(list(dict.fromkeys(moved))) if moved else "risk appetite"
    sector_text = ", ".join(list(dict.fromkeys(sectors))) if sectors else "broad index risk"
    return f"Political/geopolitical shock is market-relevant because it moved {market}. Sectors affected: {sector_text}. TFE should watch confirmation in price, volatility, rates, and sector breadth — context only, no trade instruction."


def _natural_join(items: list[str]) -> str:
    items = list(dict.fromkeys(str(x).strip() for x in items if str(x).strip()))
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + ", and " + items[-1]


def _portfolio_impact_from_flags(flags: list[str], context: dict[str, Any] | None = None) -> str:
    raw_tickers: list[str] = []
    earnings_tickers: list[str] = []
    sectors: list[str] = []
    for flag in flags:
        item = str(flag or "").strip()
        upper = item.upper()
        if upper.startswith("EARNINGS_RISK:"):
            ticker = item.split(":", 1)[1].strip().upper()
            raw_tickers.append(ticker)
            earnings_tickers.append(ticker)
        elif upper.startswith("TICKER_NOTE:"):
            raw_tickers.append(item.split(":", 1)[1].strip().upper())
        elif upper.startswith(("SECTOR_NOTE:", "SECTOR_OVERBOUGHT:")):
            sectors.append(item.split(":", 1)[1].strip().upper())
    holdings = _authoritative_holding_set(context)
    authority_state = str((context or {}).get("holding_authority_state") or "VALID").upper()
    if authority_state not in {"VALID", "FRESH"}:
        return "Portfolio relevance is DATA INCOMPLETE because the current holding set is unavailable or stale."
    current_bank_holdings = _bank_holdings(context)
    raw_tickers = list(dict.fromkeys(t for t in raw_tickers if t))[:8]
    earnings_tickers = list(dict.fromkeys(t for t in earnings_tickers if t))[:8]
    sectors = list(dict.fromkeys(s for s in sectors if s))[:4]
    sentences: list[str] = []
    held_earnings = [t for t in earnings_tickers if t in holdings]
    nonheld_earnings = [t for t in earnings_tickers if t not in holdings]
    unknown_earnings = [t for t in earnings_tickers if _ticker_sector(t) is None]
    held_financial = [t for t in held_earnings if _is_valid_bank_issuer(t)]
    held_nonfinancial = [t for t in held_earnings if t not in held_financial]
    if held_financial:
        sentences.append(f"{_natural_join(held_financial)} {'is' if len(held_financial) == 1 else 'are'} the portfolio's bank-earnings exposure.")
    elif current_bank_holdings and earnings_tickers:
        bank_subject = _natural_join(current_bank_holdings)
        sentences.append(f"{bank_subject} {'remains' if len(current_bank_holdings) == 1 else 'remain'} the portfolio's bank exposure.")
    if held_nonfinancial:
        descriptions = [f"{t} is a current {_sector_label_for_ticker(t)} holding reporting earnings" for t in held_nonfinancial]
        sentences.append(_capitalize_first(_natural_join(descriptions)) + ".")
    known_nonheld = [t for t in nonheld_earnings if t not in unknown_earnings]
    if known_nonheld:
        descriptions = [f"{t} is {_sector_label_for_ticker(t)} and is not a current portfolio holding" for t in known_nonheld]
        sentences.append(_capitalize_first(_natural_join(descriptions)) + ".")
    if unknown_earnings:
        sentences.append(f"Issuer classification is DATA INCOMPLETE for {_natural_join(unknown_earnings)}, so no sector or portfolio exposure is inferred.")
    held_notes = [t for t in raw_tickers if t in holdings and t not in earnings_tickers]
    if held_notes:
        sentences.append(f"Current portfolio context also includes {_natural_join(held_notes)}.")
    unknown_sectors = [s for s in sectors if s not in SECTOR_HOLDING_TICKERS]
    if unknown_sectors:
        sentences.append(f"Sector classification is DATA INCOMPLETE for {_natural_join(unknown_sectors)}.")
    if sentences:
        return " ".join(sentences)
    if not holdings:
        return "No current open holdings are available for portfolio commentary."
    return "Nothing in this report points directly to a current open holding."


def _perme_view_from_regime(briefing: str, flags: list[str]) -> str:
    regime = _regime_label(briefing, flags)
    regime_line = _first_section_line(briefing, "REGIME", "No decisive regime sentence supplied.")
    if regime == "RISK-OFF":
        prefix = "Cautious tape."
    elif regime == "RISK-ON":
        prefix = "Constructive tape."
    else:
        prefix = "Neutral tape."
    return f"{prefix} {_clean_market_phrase(regime_line, 185)}"


def _next_catalyst_from_brief(context: dict[str, Any] | None, now_et: datetime, evidence: list[str], risks: list[str]) -> str:
    focus_text = " ".join(evidence + risks)
    event = _first_macro_event(context, now_et, focus_text)
    if event:
        name, when = event
        return f"{name} at {when}. Translate the release into rates, liquidity, and sector impact."
    catalyst = _first_matching_line(evidence + risks, ("FOMC", "FED", "CPI", "NFP", "ADP", "AUCTION", "EIA", "EARNINGS"))
    if catalyst:
        return _clean_market_phrase(catalyst, 190)
    return "No major scheduled catalyst isolated; watch fresh macro headlines and Atlas/TFE confirmations."


def _readability_emoji(text: str, default: str = "⚠️") -> str:
    upper = str(text or "").upper()
    if any(term in upper for term in ("SMH", "SEMI", "SEMICONDUCTOR", "CHIP")) and any(term in upper for term in ("PRESSURE", "UNDER PRESSURE", "WEAK", "FALL", "DOWN")):
        return "🔻"
    if any(term in upper for term in ("NASDAQ", "FUTURES", "VIX", "RISK-OFF", "CAUTIOUS", "FALL", "DOWN", "PRESSURE", "WEAK")):
        return "📉"
    if any(term in upper for term in ("UP", "RISE", "JUMP", "HIGHER", "CONSTRUCTIVE", "FAVORED")) and not any(term in upper for term in ("VIX", "OIL SHOCK", "RISK")):
        return "📈"
    if any(term in upper for term in ("FED", "FEDWATCH", "YIELD", "RATE", "AUCTION")):
        return "🏦"
    if any(term in upper for term in ("OIL", "ENERGY", "HORMUZ", "IRAN", "MIDDLE EAST")):
        return "🛢️"
    if any(term in upper for term in ("DOLLAR", "USD", "FX")):
        return "💵"
    if any(term in upper for term in ("NASDAQ", "TECH", "GROWTH")):
        return "💻"
    if any(term in upper for term in ("AI", "ARTIFICIAL INTELLIGENCE")):
        return "🧠"
    if any(term in upper for term in ("SMH", "SEMI", "SEMICONDUCTOR", "CHIP")):
        return "🔻"
    if any(term in upper for term in ("DEFENSIVE", "DEFENSIVES", "HEALTHCARE", "STAPLES", "SAFETY")):
        return "🛡️"
    return default

def _scan_line(icon: str, text: str) -> str:
    return f"{icon} {text}"


def _dedupe_upcoming_earnings(text: str) -> str:
    paragraphs = str(text or "").split("\n\n")
    seen = False
    kept: list[str] = []
    for paragraph in paragraphs:
        if re.search(r"\bUpcoming earnings\b", paragraph, re.I):
            if seen:
                continue
            seen = True
        kept.append(paragraph)
    return "\n\n".join(kept)


def _closed_market_output_for_context(context: dict[str, Any] | None, now_et: datetime) -> str | None:
    if not isinstance(context, dict):
        return None
    reason = context.get("non_trading_day_reason") or context.get("market_closed_reason")
    if not reason:
        reason = _non_trading_day_reason(now_et) if context.get("force_market_closed_diagnostic") else None
    if reason:
        return render_closed_day_diagnostic(now_et, str(reason))
    return None


def _dominant_catalyst_items(context: dict[str, Any] | None, now_et: datetime, evidence: list[str], risks: list[str], flags: list[str]) -> list[str]:
    text = " ".join(evidence + risks + flags).upper()
    items: list[str] = []
    event = _first_macro_event(context, now_et, text)
    if event:
        items.append(event[0])
    if "FED" in text or "FOMC" in text:
        items.append("Fed speakers/policy risk")
    if any(term in text for term in ("IRAN", "HORMUZ", "MIDDLE EAST", "WAR", "CEASEFIRE")):
        items.append("US-Iran/Hormuz stress")
    earnings = [str(f).split(":", 1)[1].strip().upper() for f in flags if str(f).upper().startswith("EARNINGS_RISK:")]
    if earnings:
        bank = [t for t in earnings if _is_valid_bank_issuer(t)]
        non_bank = [t for t in earnings if not _is_valid_bank_issuer(t)]
        if bank:
            items.append("bank earnings: " + ", ".join(list(dict.fromkeys(bank))[:4]))
        if non_bank:
            items.append("earnings: " + ", ".join(f"{t} ({_sector_label_for_ticker(t)})" for t in list(dict.fromkeys(non_bank))[:4]))
    return list(dict.fromkeys(i for i in items if i))


def _dominant_catalyst_paragraph(context: dict[str, Any] | None, now_et: datetime, evidence: list[str], risks: list[str], flags: list[str]) -> str:
    items = _dominant_catalyst_items(context, now_et, evidence, risks, flags)
    if not items:
        return "No single headline is driving the tape; the moves reflect ordinary day-to-day positioning rather than a specific news trigger."
    if len(items) == 1:
        return f"The dominant catalyst is {items[0]}; the practical risk is headline-driven volatility rather than ordinary positioning."
    listed = ", ".join(items[:-1]) + " and " + items[-1]
    return f"This is not a quiet tape: {listed} are the main catalysts, so the practical risk is headline-driven volatility and fast sector repricing."


def _perme_macro_prose(briefing: str, context: dict[str, Any] | None, now_et: datetime, flags: list[str]) -> str:
    """Bloomberg/CNN market-desk style prose. Headline+tone, what moved, why it
    matters, portfolio relevance, next catalyst, Perme read — as natural, fluent,
    publishable paragraphs. No section labels, no slash-joined phrases, no raw
    list joins, no overloaded everything-at-once sentences, no awkward
    "the SMH"/"or FOMC Minutes"/"FedWatch, odds shifted" phrasing. English only.
    No jargon, no provenance labels, no buy/sell/stop/target language."""
    evidence = _brief_bullets(briefing, "EVIDENCE")
    risks = _brief_bullets(briefing, "RISK FACTORS")
    regime = _regime_label(briefing, flags)
    regime_text = _first_section_line(briefing, "REGIME", "")
    driver = _driver_from_evidence(evidence, risks)
    tape = _market_tape_from_evidence(evidence)
    rotation = _rotation_from_evidence(evidence, flags)
    portfolio = _portfolio_impact_from_flags(flags, context)
    perme_view = _perme_view_from_regime(briefing, flags)
    catalyst = _next_catalyst_from_brief(context, now_et, evidence, risks)
    geopolitical = _geopolitical_market_impact(evidence, flags)

    seen_abbrevs: set[str] = set()

    if regime == "RISK-OFF":
        headline = "Markets are leaning cautious."
    elif regime == "RISK-ON":
        headline = "Markets are leaning constructive."
    else:
        headline = "Markets are mixed, with no clear direction yet."

    driver_clean = _prep(driver, seen_abbrevs)
    tape_clean = _prep(tape, seen_abbrevs)
    rotation_clean = _apply_direct_phrase_fixes(_rewrite_sector_fund_tickers(_strip_role_jargon(rotation), seen_abbrevs), seen_abbrevs)

    fused = _compose_moved_sentence(driver_clean, tape_clean, rotation_clean, catalyst, regime_text)
    if fused:
        tone_paragraph = headline
        moved_paragraph = fused
    else:
        tone_paragraph = f"{headline} {driver_clean}".strip()
        if tape_clean.strip().rstrip(".") == driver_clean.strip().rstrip("."):
            moved_paragraph = _reconcile_moved("", rotation_clean).strip()
        else:
            moved_paragraph = _reconcile_moved(tape_clean, rotation_clean)
        moved_paragraph = _rewrite_rsi_reading(moved_paragraph, seen_abbrevs)
    if not tape_clean and rotation_clean in {
        "Available evidence is not strong enough to make a directional sector call.",
        "Available evidence is not strong enough to make a directional semiconductor-sector call.",
    }:
        moved_paragraph = rotation_clean

    if geopolitical:
        why_paragraph = _rewrite_why_it_matters(_prep(geopolitical, seen_abbrevs))
    else:
        why_paragraph = _dominant_catalyst_paragraph(context, now_et, evidence, risks, flags)

    portfolio_paragraph = _rewrite_portfolio_relevance(_prep(portfolio, seen_abbrevs))

    catalyst_paragraph = _rewrite_next_catalyst(_prep(catalyst, seen_abbrevs))
    perme_read_paragraph = _rewrite_tape_tone(_prep(perme_view, seen_abbrevs))
    if not perme_read_paragraph:
        perme_read_paragraph = "No strong read either way — this is background market context, not a trading decision."
    final_implication = _plain_english_implication(regime, _dominant_catalyst_items(context, now_et, evidence, risks, flags))

    paragraphs = [p for p in (tone_paragraph, moved_paragraph, why_paragraph, portfolio_paragraph, catalyst_paragraph, perme_read_paragraph, final_implication) if p]
    expanded = [_repair_punctuation_spacing(_capitalize_first(_deslash(re.sub(r",\s*,", ",", _expand_first_mentions(p, seen_abbrevs))))) for p in paragraphs]
    expanded = [p if p.endswith((".", "!", "?")) else p + "." for p in expanded]
    deduped: list[str] = []
    seen_clauses: set[str] = set()
    for paragraph in expanded:
        clauses = [c.strip() for c in re.split(r"(?<=[.!?])\s+", paragraph) if c.strip()]
        kept = []
        for clause in clauses:
            key = re.sub(r"\W+", " ", clause.lower()).strip()
            if key and key not in seen_clauses:
                kept.append(clause)
                seen_clauses.add(key)
        if kept:
            deduped.append(" ".join(kept))
    return "\n\n".join(deduped)


# ---------------------------------------------------------------------------
# P0H-6 Perme humanization: plain-language glossary + editorial rewrite helpers
# ---------------------------------------------------------------------------
_ABBREV_GLOSSARY: dict[str, str] = {
    "CPI": "the main US inflation report",
    "PPI": "a measure of wholesale-level inflation",
    "NONFARM PAYROLLS": "the monthly US jobs report",
    "NFP": "the monthly US jobs report",
    "ADP": "an early private read on the jobs market",
    "GDP": "the broadest measure of economic growth",
    "ISM": "a survey of factory and services activity",
    "PCE": "the Fed's preferred inflation gauge",
    "VIX": "Wall Street's volatility index",
    "RATE-HIKE": "an increase in the Fed's benchmark interest rate",
    "RATE HIKE": "an increase in the Fed's benchmark interest rate",
    "EIA": "the weekly US government report on oil and fuel inventories",
    "SPY": "the S&P 500 index fund",
    "QQQ": "the Nasdaq-100 index fund",
}

# Tokens handled as a direct phrase substitution instead of a "TOKEN (explanation)"
# or appositive pattern, because the appositive read unnatural for these specific
# terms per Prof's explicit correction (e.g. "or FOMC Minutes" -> "the Fed's FOMC
# minutes"; "FedWatch odds shifted" -> "the market's Fed-rate odds shifted").
_DIRECT_PHRASE_FIXES: list[tuple[re.Pattern, str, tuple[str, ...]]] = [
    (re.compile(r"\bFOMC\s+MINUTES\b", re.I), "the Fed's FOMC minutes", ("FOMC", "FOMC MINUTES")),
    # P0H-7: "FedWatch repricing" (with a leading preposition, e.g. "on FedWatch
    # repricing") is handled as its own full-phrase fix BEFORE the generic
    # "FedWatch odds"/bare "FedWatch" fixes below, per Prof's correction that
    # "the market's Fed-rate odds tracker repricing" is an awkward noun-pileup.
    # Rewritten into a plain verb clause: "..., as traders repriced the odds of
    # a Fed move." instead of stacking two nouns ("tracker" + "repricing").
    (re.compile(r"\s+on\s+FedWatch\s+repricing\b", re.I), ", with traders repricing the odds of a Fed move", ("FEDWATCH",)),
    (re.compile(r"\bFedWatch\s+repricing\b", re.I), "traders repricing the odds of a Fed move", ("FEDWATCH",)),
    (re.compile(r"\bFedWatch\s+odds\b", re.I), "the market's Fed-rate odds", ("FEDWATCH",)),
    (re.compile(r"\bFedWatch\b", re.I), "the market's Fed-rate odds tracker", ("FEDWATCH",)),
]

# Sector-fund tickers rewritten directly into plain sector-stock language rather
# than an appositive ("the semiconductor sector fund, the SMH,"), per Prof's
# correction: "the SMH" should read as "semiconductor stocks" (or, when a fund
# label is genuinely useful, "the SMH semiconductor ETF" — plain sector language is
# used here since these mentions are always describing the sector's move, not the
# fund product itself).
_SECTOR_FUND_TICKERS: dict[str, str] = {
    "SMH": "semiconductor stocks",
    "XLK": "technology stocks",
    "XLE": "energy stocks",
    "XLF": "financial stocks",
}


def _rewrite_sector_fund_tickers(text: str, seen: set[str]) -> str:
    """Rewrite bare sector-fund ticker mentions into plain sector-stock language,
    fixing subject-verb agreement (singular ticker subject -> plural sector noun)."""
    for ticker, phrase in _SECTOR_FUND_TICKERS.items():
        pattern = re.compile(r"\b" + re.escape(ticker) + r"\s+is\b", re.I)
        text = pattern.sub(phrase + " are", text)
        pattern_bare = re.compile(r"\b" + re.escape(ticker) + r"\b", re.I)
        if pattern_bare.search(text):
            text = pattern_bare.sub(phrase, text)
            seen.add(ticker)
    return text


def _apply_direct_phrase_fixes(text: str, seen: set[str]) -> str:
    """Apply direct phrase substitutions (FOMC minutes, FedWatch odds, ...) before
    generic glossary expansion runs, so these specific terms never hit the more
    generic 'explanation, or TOKEN,' appositive machinery and never produce
    duplicated-noun phrasing like 'FedWatch, odds shifted'."""
    for pattern, replacement, seen_tokens in _DIRECT_PHRASE_FIXES:
        if pattern.search(text):
            already_explained = seen_tokens[0] in seen
            text = pattern.sub(replacement if not already_explained else replacement.split(",")[-1].strip() or replacement, text)
            for token in seen_tokens:
                seen.add(token)
    return text


def _abbrev_pattern() -> re.Pattern:
    keys = sorted(_ABBREV_GLOSSARY.keys(), key=len, reverse=True)
    escaped = [re.escape(k) for k in keys]
    return re.compile(r"\b(" + "|".join(escaped) + r")\b", re.IGNORECASE)


_ABBREV_RE = _abbrev_pattern()

# Index/ETF tokens that read naturally as "<explanation>, the <TOKEN>, ..."
# (definite-article appositive). Sector-fund tickers (SMH/XLK/XLE/XLF) are
# deliberately excluded — they are handled by _rewrite_sector_fund_tickers()
# instead, per Prof's correction that "the SMH" reads unnaturally.
_DEFINITE_ARTICLE_TOKENS = {"VIX", "SPY", "QQQ"}


def _expand_first_mentions(text: str, seen: set[str]) -> str:
    """Explain each abbreviation in plain English first, on its first mention only.
    Index tokens (VIX, SPY, QQQ) use a definite-article appositive: 'Wall Street's
    volatility index, the VIX, rises...'. Other abbreviations use a lighter
    'or TOKEN' appositive. seen is a shared, mutable set across the whole message
    so an abbreviation already explained earlier is left as the bare token later."""
    def _replace(match: "re.Match[str]") -> str:
        token = match.group(1)
        key = token.upper()
        if key in seen:
            return token
        seen.add(key)
        explanation = _ABBREV_GLOSSARY.get(key)
        if not explanation:
            return token
        if key in _DEFINITE_ARTICLE_TOKENS:
            return f"{explanation}, the {token},"
        if key in {"CPI", "PPI"}:
            prefix = text[max(0, match.start() - 5):match.start()].lower()
            if prefix.endswith("core ") or prefix.endswith("headline "):
                return f"{token}, {explanation},"
        return f"{token}, {explanation},"

    return _ABBREV_RE.sub(_replace, text)


def _rewrite_rsi_reading(text: str, seen: set[str]) -> str:
    """Rewrite a raw 'RSI 72.5' / 'RSI at 72.5' fragment into flowing prose instead of
    abbreviation-expanding it inline. Marks RSI as already seen so the generic
    glossary expansion does not also fire on the same token."""
    def _replace(match: "re.Match[str]") -> str:
        seen.add("RSI")
        value = match.group(1)
        return f"a momentum reading (RSI) of {value}"

    return re.sub(r"\bRSI\s+(?:at\s+)?([0-9]+(?:\.[0-9]+)?)\b", _replace, text, flags=re.I)


_ROLE_DISCLAIMER_PATTERNS = (
    re.compile(r"\bTFE should\b.*?(?=[.!?]|$)", re.I),
    re.compile(r"—?\s*context only,?\s*no trade instruction\.?", re.I),
    re.compile(r"\.?\s*Context only\s*—\s*no execution instruction\.?", re.I),
    re.compile(r"⚖️.*?Context vs TFE action.*?(?=$)", re.I | re.S),
    re.compile(r"\[PROVIDER\]|\[LLM\]|\[FALLBACK\]|\[CACHE\]|\[RENDER-CALC\]", re.I),
)


def _strip_role_jargon(text: str) -> str:
    cleaned = text
    for pattern in _ROLE_DISCLAIMER_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" .;—-")
    return cleaned


_SECTOR_ALIASES = {
    "semiconductors": ("smh", "semiconductor", "chip", "semis"),
    "tech/growth": ("nasdaq", "tech", "xlk", "growth"),
    "energy": ("oil", "energy", "xle"),
    "financials": ("bank", "financial", "xlf"),
}

# Friendly noun each canonical sector reads as in fused, publishable prose.
_FRIENDLY_SECTOR_NOUN = {
    "semiconductors": "chip",
    "tech/growth": "growth",
    "energy": "energy",
    "financials": "bank",
}


def _sector_keys_in(text: str) -> set[str]:
    upper = text.upper()
    found = set()
    for canonical, aliases in _SECTOR_ALIASES.items():
        if any(alias.upper() in upper for alias in (canonical,) + aliases):
            found.add(canonical)
    return found


# Bare-slash pairs (e.g. "Hormuz/Iran", "gold/safety") where both sides are plain
# words with no surrounding spaces. Rewritten to "A and B" as a general safety net,
# distinct from the spaced " / " phrase-mapping used for mover/sector lists.
_BARE_SLASH_RE = re.compile(r"\b([A-Za-z][A-Za-z\-]*)/([A-Za-z][A-Za-z\-]*)\b")


def _deslash(text: str) -> str:
    """Rewrite any remaining bare slash-joined word pair into natural 'A and B'
    prose. Applied as a final safety-net pass on every paragraph so no raw slash
    survives regardless of which upstream helper produced it."""
    def _replace(match: "re.Match[str]") -> str:
        left, right = match.group(1), match.group(2)
        return f"{left} and {right}"

    return _BARE_SLASH_RE.sub(_replace, text)


def _humanize_rotation(text: str) -> str:
    """Rewrite the raw 'money favored X, Y; Z looked stretched; W, V came under
    pressure' template (from _rotation_from_evidence) into flowing market-desk
    prose instead of a semicolon-joined raw list, e.g. 'Money flowed into energy
    and gold, while chip and growth names came under pressure.'"""
    clauses = [c.strip(" .") for c in text.split(";") if c.strip(" .")]
    if not clauses:
        return text

    favored, stretched, pressured, other = [], [], [], []
    for clause in clauses:
        m = re.match(r"^money favored (.+)$", clause, re.I)
        if m:
            favored.append(m.group(1))
            continue
        m = re.match(r"^(.+?) looked stretched rather than fresh leadership$", clause, re.I)
        if m:
            stretched.append(m.group(1))
            continue
        m = re.match(r"^(.+?) came under pressure$", clause, re.I)
        if m:
            pressured.append(m.group(1))
            continue
        other.append(clause)

    def _friendly_join(raw_items: list[str], cap: int = 3) -> str:
        names = []
        for raw in raw_items:
            for part in raw.split(","):
                part = part.strip()
                if not part:
                    continue
                canonical = None
                for sector, aliases in _SECTOR_ALIASES.items():
                    if part.lower() == sector or part.lower() in aliases:
                        canonical = _FRIENDLY_SECTOR_NOUN[sector]
                        break
                if canonical:
                    names.append(canonical + " names" if canonical in ("chip", "growth", "bank") else canonical)
                else:
                    names.append(_deslash(part).replace("_", " "))
        names = list(dict.fromkeys(names))[:cap]
        if not names:
            return ""
        if len(names) == 1:
            return names[0]
        return ", ".join(names[:-1]) + " and " + names[-1]

    sentence_parts = []
    if favored:
        sentence_parts.append(f"Money flowed into {_friendly_join(favored)}")
    if stretched:
        prefix = "while" if sentence_parts else "Meanwhile,"
        sentence_parts.append(f"{prefix} {_friendly_join(stretched)} looked stretched rather than showing fresh leadership")
    if pressured:
        prefix = "while" if sentence_parts else "Meanwhile,"
        sentence_parts.append(f"{prefix} {_friendly_join(pressured)} came under pressure")
    for clause in other:
        sentence_parts.append(_deslash(clause))

    if not sentence_parts:
        return _deslash(text)
    result = " ".join(sentence_parts) + "."
    result = result[0].upper() + result[1:]
    return result


def _reconcile_moved(tape: str, rotation: str) -> str:
    """Avoid a flat contradiction like 'SMH is up' followed by 'semiconductors came
    under pressure' in the same paragraph — but only drop a rotation clause when it
    actually conflicts with the tape's direction for the SAME sector. A rotation
    clause about a different sector is not a contradiction and is kept. The
    surviving rotation clauses are then rewritten into flowing prose via
    _humanize_rotation() rather than left as a raw semicolon-joined list."""
    tape_sectors = _sector_keys_in(tape)
    tape_up = any(w in tape.lower() for w in ("up", "rise", "higher", "jump"))
    tape_down = any(w in tape.lower() for w in ("down", "fall", "pressure", "lower"))
    tape_dir = "up" if tape_up and not tape_down else ("down" if tape_down and not tape_up else None)

    kept_clauses = []
    for clause in re.split(r";\s*", rotation):
        clause = clause.strip(" .;")
        if not clause:
            continue
        clause_sectors = _sector_keys_in(clause)
        clause_up = any(w in clause.lower() for w in ("favored", "leadership"))
        clause_down = any(w in clause.lower() for w in ("pressure", "came under"))
        clause_dir = "up" if clause_up and not clause_down else ("down" if clause_down and not clause_up else None)
        overlap = tape_sectors & clause_sectors
        if overlap and tape_dir and clause_dir and tape_dir != clause_dir:
            continue
        kept_clauses.append(clause)

    rotation_kept = _humanize_rotation("; ".join(kept_clauses))
    parts = []
    for part in (tape, rotation_kept):
        part = str(part or "").strip()
        if not part:
            continue
        if parts and parts[-1] and not parts[-1].endswith((".", "!", "?")):
            parts[-1] += "."
        parts.append(part)
    return " ".join(parts)


def _fed_hint_from(*texts: str) -> str:
    joined = " ".join(texts).lower()
    if "fomc" in joined or "fed " in joined or joined.startswith("fed") or "federal reserve" in joined:
        return " ahead of the Fed update"
    return ""


def _compose_moved_sentence(driver: str, tape: str, rotation: str, catalyst: str, regime_text: str) -> str | None:
    """When oil/energy strength and chip/growth softness both appear together
    (with a Fed-related catalyst nearby), fuse them into one fluent market-desk
    sentence instead of two separate clause fragments, e.g. 'Oil's rebound pushed
    energy stocks higher, while chip and growth names stayed under pressure ahead
    of the Fed update.' Returns None when this specific pattern does not apply, so
    the caller can fall back to the generic tape/rotation reconciliation."""
    combined_tape_driver = f"{driver} {tape}".lower()
    if "oil" not in combined_tape_driver:
        return None
    oil_up = any(w in combined_tape_driver for w in ("up", "rise", "higher", "rebound", "jump"))
    if not oil_up:
        return None

    down_sectors = []
    for clause in re.split(r";\s*", rotation):
        clause = clause.strip(" .;")
        if not clause:
            continue
        if any(w in clause.lower() for w in ("pressure", "came under")):
            for sector in _sector_keys_in(clause):
                if sector in ("semiconductors", "tech/growth"):
                    down_sectors.append(sector)
    if not down_sectors:
        return None

    subject = "Oil's rebound" if "rebound" in combined_tape_driver else "Oil's advance"
    nouns = list(dict.fromkeys(_FRIENDLY_SECTOR_NOUN[s] for s in down_sectors))
    down_phrase = (" and ".join(nouns) + " names") if nouns else "growth names"
    fed_hint = _fed_hint_from(catalyst, regime_text)
    return f"{subject} pushed energy stocks higher, while {down_phrase} stayed under pressure{fed_hint}."


_MOVER_PHRASE_MAP = {
    "equity futures / nasdaq risk appetite": "stocks",
    "vix volatility": "volatility",
    "oil/energy": "oil",
    "gold/safety bid": "gold",
    "dollar": "the dollar",
    "yields / rate-pricing": "rates",
    # P0H-7: bare-slash movers ("oil/energy", "gold/safety bid") are already
    # de-slashed into "oil and energy" / "gold and safety bid" by the shared
    # _prep() pass that runs before this map is consulted, so the original
    # slash-joined keys above never match post-_prep() text. Add the
    # de-slashed forms as additional keys so these movers still collapse to
    # a single plain noun ("oil", "gold") instead of surviving as a two-word
    # literal inside the mover list.
    "oil and energy": "oil",
    "gold and safety bid": "gold",
}
_SECTOR_PHRASE_MAP = {
    "energy": "energy stocks",
    "tech/semis": "tech and chip stocks",
    "banks and high-duration growth": "banks and growth stocks",
}

# Cap on how many movers/sectors are named in one sentence before the phrasing is
# shortened, per Prof's correction that overloaded, everything-at-once sentences
# read as a system dump rather than editorial writing.
_MAX_LISTED_ITEMS = 3


def _humanize_list(items: list[str], phrase_map: dict[str, str], cap: int = _MAX_LISTED_ITEMS) -> str:
    parts = []
    for item in items:
        key = item.strip().lower()
        natural = phrase_map.get(key)
        if natural is None:
            natural = _deslash(item.strip().replace(" / ", " and "))
        parts.append(natural)
    parts = list(dict.fromkeys(p for p in parts if p))[:cap]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


# P0H-7: per-mover verb phrase, keyed by the canonical noun each mover already
# collapses to via _MOVER_PHRASE_MAP. Used so the "why it matters" paragraph
# reads as editorial prose ("stocks are softer, oil is firmer, and rates
# remain in focus") instead of a bare noun list ("stocks, oil and energy and
# rates"), per Prof's explicit correction and target-style example.
_MOVER_VERB_PHRASES: dict[str, str] = {
    "stocks": "stocks are softer",
    "volatility": "volatility is elevated",
    "oil": "oil is firmer",
    "gold": "gold is firmer",
    "the dollar": "the dollar is firmer",
    "rates": "rates remain in focus",
}

# Hand-written template sentence shapes for the most common mover
# combinations, so the frequent cases read as bespoke editorial sentences
# rather than a generic capped join. Keys are frozensets of canonical mover
# nouns (post _MOVER_PHRASE_MAP); order of clauses in the value is fixed to
# read naturally regardless of the order movers appeared in the source flags.
_MOVER_TEMPLATE_SHAPES: dict[frozenset, str] = {
    frozenset({"stocks", "oil", "rates"}): "stocks are softer, oil is firmer, and rates remain in focus",
    frozenset({"stocks", "volatility"}): "stocks are under pressure while volatility climbs",
    frozenset({"oil", "gold"}): "oil and gold are both firmer as traders reach for safety",
}


def _mover_sentence(movers_raw: list[str], cap: int = _MAX_LISTED_ITEMS) -> str:
    """Build the mover clause of the 'why it matters' paragraph. Tries a
    hand-written template shape first for common combinations; falls back to
    a generic verb-phrase join (still per-mover prose, never a bare noun
    list) for anything else."""
    canonical = []
    for item in movers_raw:
        key = item.strip().lower()
        natural = _MOVER_PHRASE_MAP.get(key)
        if natural is None:
            natural = _deslash(item.strip().replace(" / ", " and "))
        canonical.append(natural)
    canonical = list(dict.fromkeys(c for c in canonical if c))[:cap]
    if not canonical:
        return ""

    shape = _MOVER_TEMPLATE_SHAPES.get(frozenset(canonical))
    if shape:
        return shape

    verb_parts = [_MOVER_VERB_PHRASES.get(c, f"{c} is in focus") for c in canonical]
    if len(verb_parts) == 1:
        return verb_parts[0]
    return ", ".join(verb_parts[:-1]) + " and " + verb_parts[-1]


def _rewrite_why_it_matters(text: str) -> str:
    """Replace the robotic 'Political/geopolitical shock is market-relevant because
    it moved X. Sectors affected: Y.' template — and its raw slash-joined phrases —
    with plain, fully de-slashed, length-capped market-desk prose. Matches whether
    the leading 'Political/geopolitical' token has already been de-slashed to
    'Political and geopolitical' by an earlier _prep() pass or not.

    P0H-7: the mover clause is built via _mover_sentence(), which uses hand-written
    template shapes for common combinations and a per-mover verb-phrase join
    otherwise, instead of a bare noun list ("stocks, oil and energy and rates")."""
    match = re.match(
        r"^Political(?:/| and )geopolitical shock is market-relevant because it moved (.+?)\.\s*Sectors affected:\s*(.+?)\.?$",
        text,
        re.I,
    )
    if match:
        movers_raw = [m.strip() for m in match.group(1).split(",")]
        sectors_raw = [s.strip() for s in match.group(2).split(",")]
        movers_sentence = _mover_sentence(movers_raw)
        sectors_natural = _humanize_list(sectors_raw, _SECTOR_PHRASE_MAP, cap=2)
        return f"Geopolitical headlines are setting the market context — {movers_sentence} — with {sectors_natural} feeling it most directly."
    return _deslash(text.replace(" / ", " and "))


def _rewrite_portfolio_relevance(text: str) -> str:
    """Replace legacy portfolio prose without allowing non-holdings into portfolio membership."""
    if any(marker in text.lower() for marker in ("non-portfolio", "watch-list ticker context only", "current portfolio bank exposure", "not bank exposure", "data incomplete")):
        return text
    def _sector_adjective(raw: str) -> str:
        key = raw.strip().lower()
        for canonical, aliases in _SECTOR_ALIASES.items():
            if key == canonical or key in aliases:
                return _FRIENDLY_SECTOR_NOUN[canonical] + "-led"
        word = raw.strip().lower()
        if word.endswith("s") and len(word) > 4:
            word = word[:-1]
        return word + "-led"

    match = re.match(r"^watch (.+?);\s*earnings exposure:\s*(.+?)\.?$", text, re.I)
    if match:
        tickers, risk = match.group(1).strip(), match.group(2).strip()
        verb = "is" if "," not in tickers else "are"
        return f"In the portfolio, {tickers} {verb} the actual bank-earnings exposure today; {risk.lower()}"

    match = re.match(r"^watch (.+?);\s*sector context:\s*(.+?)\.?$", text, re.I)
    if match:
        tickers, sectors_raw = match.group(1).strip(), match.group(2).strip()
        sector_list = [s.strip() for s in sectors_raw.split(",") if s.strip()][:2]
        adjective = " and ".join(dict.fromkeys(_sector_adjective(s) for s in sector_list)) if sector_list else "sector"
        verb = "is" if "," not in tickers else "are"
        return f"In the portfolio, {tickers} {verb} linked to the {adjective} backdrop — nothing that calls for action on its own, but worth watching."
    match = re.match(r"^watch (.+?)\.?$", text, re.I)
    if match:
        tickers = match.group(1).strip()
        verb = "is" if "," not in tickers else "are"
        return f"In the portfolio, {tickers} {verb} in view for this backdrop — nothing urgent there, just one to keep on the radar."
    match = re.match(r"^sector context:\s*(.+?)\.?$", text, re.I)
    if match:
        sectors = match.group(1).strip()
        return f"None of the open positions are named directly, but {sectors.lower()} is the group to watch."
    if text.lower().startswith("no direct portfolio ticker flag"):
        return "Nothing in this flow points at the open positions directly, so treat this as background rather than a signal about any specific holding."
    return text


def _rewrite_next_catalyst(text: str) -> str:
    """Replace the robotic 'X at Y. Translate the release into rates, liquidity, and
    sector impact.' template with plain market-desk phrasing."""
    match = re.match(
        r"^(.+?) at (.+?)\.\s*Translate the release into rates, liquidity, and sector impact\.?$",
        text,
        re.I,
    )
    if match:
        name, when = match.group(1).strip().rstrip(","), match.group(2).strip()
        return f"Keep an eye on {name}, due at {when} — releases like this can move rates and shift sector leadership quickly."
    if text.lower().startswith("no major scheduled catalyst isolated"):
        return "Nothing major is scheduled right now — keep an eye on fresh headlines for anything that changes the picture."
    return text


def _plain_english_implication(regime: str, catalysts: list[str]) -> str:
    if catalysts:
        catalyst_text = ", ".join(catalysts[:3])
        return f"Plain-English implication: treat this as a catalyst-risk session led by {catalyst_text}; wait for price confirmation instead of reacting to the headline alone."
    if regime == "RISK-OFF":
        return "Plain-English implication: risk is tilted to the downside, so patience matters more than chasing early moves."
    if regime == "RISK-ON":
        return "Plain-English implication: the tape is supportive, but the setup still needs live confirmation before it matters for Atlas."
    return "Plain-English implication: there is no dominant catalyst, so this is background context unless a fresh headline changes the tape."


def _rewrite_tape_tone(text: str) -> str:
    """Replace the terse 'Cautious tape.' / 'Constructive tape.' / 'Neutral tape.'
    lead-in with a plain sentence."""
    replacements = {
        "Cautious tape.": "The overall tone is cautious.",
        "Constructive tape.": "The overall tone is constructive.",
        "Neutral tape.": "The overall tone is neutral, without a strong lean either way.",
    }
    for old, new in replacements.items():
        if text.startswith(old):
            return new + text[len(old):]
    return text


def _capitalize_first(text: str) -> str:
    for i, ch in enumerate(text):
        if ch.isalpha():
            return text[:i] + ch.upper() + text[i + 1:]
    return text


def _prep(text: str, seen: set[str]) -> str:
    """Standard pre-processing pipeline applied to every raw source fragment before
    its specific rewrite function runs: strip role jargon, apply the direct
    phrase fixes (FOMC minutes, FedWatch odds), rewrite bare sector-fund tickers
    into plain sector-stock language, then de-slash anything left over."""
    cleaned = _strip_role_jargon(text)
    cleaned = _apply_direct_phrase_fixes(cleaned, seen)
    cleaned = _rewrite_sector_fund_tickers(cleaned, seen)
    return _deslash(cleaned)


def format_telegram_brief(briefing: str, routine: str, now_et: datetime, context: dict[str, Any] | None = None) -> str:
    closed = _closed_market_output_for_context(context, now_et)
    if closed:
        return closed
    flags_text = "\n".join(_clean_section_line(line) for line in _markdown_section(briefing, "FLAGS"))
    flags = parse_flags(flags_text)
    return _dedupe_upcoming_earnings(_perme_macro_prose(briefing, context, now_et, flags))


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
    if dry_run:
        print("[perme] dry-run: Telegram delivery suppressed")
        print(f"PERME_TELEGRAM_ROUTE_CHAT_ID_VAR={_owner_dm_chat_id_var()}")
        print("PERME_TELEGRAM_BOT_TOKEN_VAR=PERME_ENV:TELEGRAM_BOT_TOKEN")
        return
    owner_chat, bot_token, chat_var, bot_var = _perme_telegram_credentials()
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

    gate_now = _now_et()
    closed_reason = _non_trading_day_reason(gate_now)
    if closed_reason:
        print(_perme_skip_non_trading_day_line(gate_now, closed_reason))
        return 0
    if args.routine in WEEKEND_ROUTINES:
        print(f"PERME_SKIP_RETIRED_ROUTINE routine={args.routine} date={gate_now.date().isoformat()}")
        return 0

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
