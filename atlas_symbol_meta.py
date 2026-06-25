"""Shared ticker metadata helpers for Atlas reports.

Keeps report formatting names and explicit provider price-scale overrides out of
strategy logic. Network failures degrade to ticker-only labels.
"""
import json
import os
import re
import sqlite3
from functools import lru_cache

import requests

SCRIPTS_DIR = "/Users/yasser/scripts"
DB_PATH = f"{SCRIPTS_DIR}/atlas.db"
ENV_PATH = os.path.expanduser("~/.hermes/profiles/atlas/.env")
MASSIVE_BASE = "https://api.massive.com"

if os.path.exists(ENV_PATH):
    with open(ENV_PATH) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

MASSIVE_API_KEY = os.environ.get("MASSIVE_API_KEY")

# Explicit operational override: Prof. verified MU quotes are being delivered 10x
# by the provider feed (~$1,219 vs real ~$122). Keep this narrow; do not infer
# scaling for unrelated tickers without a reliable independent source.
PRICE_SCALE_OVERRIDES = {"MU": 0.1}

# Keep report labels concise and human-readable. Keys are normalized lowercase
# provider/legal names after comma/parenthesis truncation and whitespace cleanup.
COMMON_NAME_OVERRIDES = {
    "unitedhealth group incorporated": "UnitedHealth Group",
    "unitedhealth group inc": "UnitedHealth Group",
    "unitedhealth group": "UnitedHealth Group",
    "space exploration technologies": "SpaceX",
    "space exploration technologies corp": "SpaceX",
    "space exploration technologies corporation": "SpaceX",
    "clearwater analytics holdings": "Clearwater Analytics",
    "clearwater analytics holdings inc": "Clearwater Analytics",
    "alphabet inc": "Alphabet",
    "alphabet": "Alphabet",
    "meta platforms inc": "Meta Platforms",
    "meta platforms": "Meta Platforms",
    "micron technology inc": "Micron Technology",
    "micron technology": "Micron Technology",
    "applied materials inc": "Applied Materials",
    "applied materials": "Applied Materials",
}

# Ticker-specific overrides catch provider names that vary too much to match
# safely by raw legal-name text alone.
TICKER_NAME_OVERRIDES = {
    "ABBV": "AbbVie",
    "ARM": "Arm Holdings",
    "BLZE": "Backblaze",
    "CMC": "Commercial Metals",
    "CSCO": "Cisco Systems",
    "CWAN": "Clearwater Analytics",
    "DFTX": "Definium Therapeutics",
    "DRI": "Darden Restaurants",
    "FUL": "H.B. Fuller",
    "GE": "GE Aerospace",
    "JPM": "JPMorgan Chase",
    "MLKN": "MillerKnoll",
    "MRK": "Merck",
    "MU": "Micron Technology",
    "NOK": "Nokia",
    "SNX": "TD SYNNEX",
    "SPACE": "SpaceX",
    "SPACEX": "SpaceX",
    "SPCX": "SpaceX",
    "TECH": "Bio-Techne",
    "TSM": "Taiwan Semiconductor",
    "UNH": "UnitedHealth Group",
}


def _title_if_shouting(text):
    if text and text.upper() == text:
        return text.title()
    return text


def _clean_company_name(name, ticker=None):
    text = re.sub(r"\s+", " ", str(name or "")).strip()
    if not text:
        return None
    ticker = (ticker or "").upper()
    if ticker in TICKER_NAME_OVERRIDES:
        return TICKER_NAME_OVERRIDES[ticker]

    # First trim verbose jurisdiction/listing fragments, per Prof.'s instruction.
    text = re.split(r"\s*[,()]\s*", text, maxsplit=1)[0].strip()
    text = re.sub(r",?\s+(Class|Ordinary|Common)\s+(Stock|Shares?).*$", "", text, flags=re.I).strip()
    text = re.sub(r",?\s+Common Stock$", "", text, flags=re.I).strip()
    text = re.sub(r",?\s+Class [A-Z]$", "", text, flags=re.I).strip()
    text = re.sub(r",?\s+(Inc\.?|Incorporated|Corp\.?|Corporation|Holdings|PLC|Ltd\.?|Limited|Co\.?|Company|SA|N\.V\.|NV|AG)$", "", text, flags=re.I).strip()

    key = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    if key in COMMON_NAME_OVERRIDES:
        return COMMON_NAME_OVERRIDES[key]
    return _title_if_shouting(text) or None


def _name_from_mapping(item):
    if not isinstance(item, dict):
        return None
    for key in ("company_name", "company", "name", "issuer_name", "security_name"):
        value = item.get(key)
        if isinstance(value, str) and value.strip() and value.strip().upper() != str(item.get("ticker", "")).upper():
            return _clean_company_name(value, item.get("ticker") or item.get("symbol"))
    for key in ("details", "ticker_details", "meta"):
        value = item.get(key)
        if isinstance(value, dict):
            found = _name_from_mapping(value)
            if found:
                return found
    sig = item.get("signal_result") or item.get("signal_json")
    if isinstance(sig, str):
        try:
            sig = json.loads(sig)
        except Exception:
            sig = None
    if isinstance(sig, dict):
        found = _name_from_mapping(sig)
        if found:
            return found
    return None


@lru_cache(maxsize=512)
def _company_name_from_db(ticker):
    ticker = (ticker or "").upper()
    if not ticker:
        return None
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        rows = []
        try:
            rows += cur.execute(
                "SELECT signal_json FROM pending_pullbacks WHERE ticker=? ORDER BY updated_at DESC LIMIT 1",
                (ticker,),
            ).fetchall()
        except Exception:
            pass
        con.close()
        for (payload,) in rows:
            try:
                data = json.loads(payload or "{}")
            except Exception:
                data = {}
            found = _name_from_mapping(data)
            if found:
                return found
    except Exception:
        return None
    return None


@lru_cache(maxsize=512)
def _company_name_from_massive(ticker):
    ticker = (ticker or "").upper()
    if not ticker or not MASSIVE_API_KEY:
        return None
    try:
        r = requests.get(
            f"{MASSIVE_BASE}/v3/reference/tickers/{ticker}",
            params={"apiKey": MASSIVE_API_KEY},
            headers={"Accept": "application/json"},
            timeout=5,
        )
        if r.status_code != 200:
            return None
        row = (r.json() or {}).get("results") or {}
        return _clean_company_name(row.get("name"), ticker)
    except Exception:
        return None


def company_name(ticker, item=None):
    ticker = (ticker or "").upper()
    if ticker in TICKER_NAME_OVERRIDES:
        return TICKER_NAME_OVERRIDES[ticker]
    return _name_from_mapping(item) or _company_name_from_db(ticker) or _company_name_from_massive(ticker)


def ticker_label(ticker, item=None):
    ticker = (ticker or "?").upper()
    name = company_name(ticker, item=item)
    return f"{ticker} ({name})" if name else ticker


def normalize_price(ticker, price):
    if price in (None, ""):
        return None
    try:
        value = float(price)
    except Exception:
        return None
    factor = PRICE_SCALE_OVERRIDES.get((ticker or "").upper())
    if factor:
        return value * factor
    return value


def normalize_snapshot_fields(ticker, payload):
    """Return a shallow copy of a Massive snapshot ticker payload with price fields normalized."""
    if not isinstance(payload, dict):
        return payload
    out = dict(payload)
    for section, keys in (("lastTrade", ("p",)), ("min", ("c", "h", "l", "o")), ("day", ("c", "h", "l", "o")), ("prevDay", ("c", "h", "l", "o"))):
        if isinstance(out.get(section), dict):
            child = dict(out[section])
            for key in keys:
                if key in child and child[key] not in (None, ""):
                    fixed = normalize_price(ticker, child[key])
                    if fixed is not None:
                        child[key] = fixed
            out[section] = child
    for key in ("todaysChange",):
        if key in out and out[key] not in (None, ""):
            fixed = normalize_price(ticker, out[key])
            if fixed is not None:
                out[key] = fixed
    return out
