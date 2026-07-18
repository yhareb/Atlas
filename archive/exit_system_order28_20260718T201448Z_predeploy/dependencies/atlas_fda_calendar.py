#!/usr/bin/env python3
"""Selective FDA calendar provider/cache helper for Atlas Stage 1.

Stage 1 is metadata/discovery/report-only. This module never writes Atlas DB,
never performs notification/execution side effects, and never changes scores.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

FDA_ENDPOINT = "https://api.benzinga.com/api/v2.1/calendar/fda"
SOURCE_ENDPOINT = "benzinga_direct_fda_calendar_v2_1"
DEFAULT_CACHE_DIR = Path(os.environ.get("ATLAS_FDA_CACHE_DIR", "/tmp/atlas_fda_calendar_cache"))
DEFAULT_TTL_SECONDS = int(os.environ.get("ATLAS_FDA_CACHE_TTL_SECONDS", str(6 * 60 * 60)))
DEFAULT_WINDOW_DAYS = int(os.environ.get("ATLAS_FDA_WINDOW_DAYS", "60"))
DEFAULT_DISCOVERY_LIMIT = int(os.environ.get("ATLAS_FDA_DISCOVERY_LIMIT", "10"))
FDA_WATCHLIST_ENV = "ATLAS_FDA_WATCHLIST"
_STATS = {"endpoint_calls": 0, "cache_hits": 0, "cache_misses": 0, "last_row_count": 0, "last_ticker_count": 0}

FDA_RELEVANT_TERMS = (
    "biotech", "biotechnology", "pharma", "pharmaceutical", "drug", "therapeutic",
    "therapeutics", "medical device", "diagnostic", "diagnostics", "clinical",
    "life sciences", "genomics", "gene therapy", "cell therapy", "oncology", "healthcare",
    "medtech", "ind", "pdufa", "phase 1", "phase 2", "phase 3",
)
NON_FDA_BLOCK_TERMS = (
    "bank", "financial", "capital markets", "insurance", "semiconductor", "software", "saas",
    "internet", "consumer", "industrial", "transport", "energy", "materials", "retail",
    "automobile", "auto manufacturer", "restaurant", "media", "advertising",
)
ETF_PROXY_TERMS = ("etf", "fund", "index", "trust", "etn", "proxy")
BROAD_PROXY_TICKERS = {"SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLY", "XLI", "XLE", "XLP", "XLV", "XLC", "SMH", "SOXX", "VIX", "I:VIX"}
FDA_NEWS_KEYWORDS = (
    "fda", "pdufa", "clinical", "trial", "phase 1", "phase 2", "phase 3", "drug",
    "therapy", "therapeutic", "ind clearance", "new drug application", "510(k)",
    "breakthrough therapy", "orphan drug", "biologics license", "bla", "nda",
)
MATERIALITY_RANK = {
    "pdufa": 100, "approval": 95, "fda clearance": 90, "clearance": 85,
    "complete response": 80, "crl": 80, "phase 3": 75, "results": 70,
    "phase 2": 65, "ind": 60, "phase 1": 45, "publication": 30, "abstract": 20,
}


def key_status() -> str:
    return "SET" if os.environ.get("BENZINGA_API_KEY") else "MISSING"


def _today() -> _dt.date:
    return _dt.datetime.now(_dt.timezone.utc).date()


def _iso_from_epoch(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        raw = float(value)
        if raw > 10_000_000_000:
            raw = raw / 1000.0
        return _dt.datetime.fromtimestamp(raw, tz=_dt.timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def _safe_date(value: Any) -> str | None:
    if not value:
        return None
    s = str(value)[:10]
    try:
        _dt.date.fromisoformat(s)
        return s
    except Exception:
        return None


def _availability(row: dict[str, Any]) -> str | None:
    for key in ("created", "updated"):
        got = _iso_from_epoch(row.get(key))
        if got:
            return got
    for key in ("date", "target_date"):
        d = _safe_date(row.get(key))
        if d:
            return d + "T00:00:00Z"
    return None


def _drug_name(row: dict[str, Any]) -> str | None:
    drug = row.get("drug")
    if isinstance(drug, dict):
        return drug.get("name") or drug.get("drug_name") or drug.get("compound")
    return str(drug) if drug else None


def _company_symbols(row: dict[str, Any]) -> list[tuple[str | None, str]]:
    out: list[tuple[str | None, str]] = []
    companies = row.get("companies") or []
    if not isinstance(companies, list):
        return out
    for company in companies:
        if not isinstance(company, dict):
            continue
        cname = company.get("name") or company.get("company")
        securities = company.get("securities") or []
        if isinstance(securities, list):
            for sec in securities:
                if isinstance(sec, dict):
                    sym = str(sec.get("symbol") or sec.get("ticker") or "").upper().strip()
                    if sym:
                        out.append((cname, sym))
        sym = str(company.get("ticker") or company.get("symbol") or "").upper().strip()
        if sym:
            out.append((cname, sym))
    return sorted(set(out), key=lambda x: (x[1], x[0] or ""))


def materiality_score(event_type: Any, status: Any = None, outcome: Any = None) -> int:
    text = " ".join(str(x or "").lower() for x in (event_type, status, outcome))
    best = 0
    for key, score in MATERIALITY_RANK.items():
        if key in text:
            best = max(best, score)
    return best


def normalize_fda_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        rows = payload.get("fda") or payload.get("data") or payload.get("results") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []
    out: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        target_date = _safe_date(row.get("target_date") or row.get("date") or row.get("event_date"))
        availability = _availability(row)
        drug_name = _drug_name(row)
        event_type = row.get("event_type") or row.get("type") or row.get("status") or "FDA event"
        status = row.get("status")
        outcome = row.get("outcome")
        outcome_brief = row.get("outcome_brief") or row.get("notes") or row.get("commentary")
        source_id = str(row.get("id") or row.get("benzinga_id") or row.get("nic_number") or hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()[:16])
        pairs = _company_symbols(row)
        if not pairs:
            pairs = [(None, "")]
        for company, ticker in pairs:
            if not ticker:
                continue
            out.append({
                "ticker": ticker,
                "company": company,
                "drug": drug_name,
                "event_type": str(event_type) if event_type is not None else None,
                "target_date": target_date,
                "availability_date": availability,
                "created": row.get("created"),
                "updated": row.get("updated"),
                "status": str(status) if status is not None else None,
                "outcome": str(outcome) if outcome is not None else None,
                "outcome_brief": str(outcome_brief)[:500] if outcome_brief is not None else None,
                "source_endpoint": SOURCE_ENDPOINT,
                "source_id": source_id,
                "materiality_score": materiality_score(event_type, status, outcome or outcome_brief),
            })
    out.sort(key=lambda r: (r.get("target_date") or "9999-12-31", -int(r.get("materiality_score") or 0), r.get("ticker") or ""))
    return out


def build_ticker_index(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    idx: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        t = str(row.get("ticker") or "").upper().strip()
        if not t:
            continue
        idx.setdefault(t, []).append(row)
    for t in idx:
        idx[t].sort(key=lambda r: (r.get("target_date") or "9999-12-31", -int(r.get("materiality_score") or 0)))
    return idx


def _cache_paths(cache_dir: Path | str | None = None) -> dict[str, Path]:
    d = Path(cache_dir or DEFAULT_CACHE_DIR)
    return {
        "dir": d,
        "normalized": d / "fda_calendar_normalized.json",
        "index": d / "fda_calendar_ticker_index.json",
        "stats": d / "fda_calendar_stats.json",
    }


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def fetch_fda_calendar_window(days: int = DEFAULT_WINDOW_DAYS, start_date: _dt.date | None = None, fetcher: Callable[..., Any] | None = None) -> dict[str, Any]:
    key = os.environ.get("BENZINGA_API_KEY")
    if not key and fetcher is None:
        return {"status": "MISSING_KEY", "fda": [], "endpoint": SOURCE_ENDPOINT}
    start = start_date or _today()
    end = start + _dt.timedelta(days=int(days))
    params = {
        "token": key or "",
        "dateFrom": start.isoformat(),
        "dateTo": end.isoformat(),
        "pageSize": 100,
        "limit": 100,
    }
    _STATS["endpoint_calls"] += 1
    if fetcher is not None:
        return fetcher(FDA_ENDPOINT, params)
    url = FDA_ENDPOINT + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "AtlasFDAStage1/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    data = json.loads(body)
    if isinstance(data, dict):
        data.setdefault("endpoint", SOURCE_ENDPOINT)
        data.setdefault("status", "OK")
    return data


def load_or_refresh_fda_cache(cache_dir: Path | str | None = None, days: int = DEFAULT_WINDOW_DAYS, ttl_seconds: int = DEFAULT_TTL_SECONDS, force: bool = False, fetcher: Callable[..., Any] | None = None) -> dict[str, Any]:
    paths = _cache_paths(cache_dir)
    paths["dir"].mkdir(parents=True, exist_ok=True)
    now = time.time()
    stats = _read_json(paths["stats"]) or {}
    fresh = bool(paths["normalized"].exists() and paths["index"].exists() and stats.get("generated_epoch") and (now - float(stats["generated_epoch"]) <= ttl_seconds))
    if fresh and not force:
        _STATS["cache_hits"] += 1
        rows = _read_json(paths["normalized"]) or []
        index = _read_json(paths["index"]) or build_ticker_index(rows)
        return {"rows": rows, "index": index, "stats": stats, "from_cache": True}
    _STATS["cache_misses"] += 1
    payload = fetch_fda_calendar_window(days=days, fetcher=fetcher)
    rows = normalize_fda_rows(payload)
    index = build_ticker_index(rows)
    stats = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "generated_epoch": now,
        "source_endpoint": SOURCE_ENDPOINT,
        "key_status": key_status(),
        "row_count": len(rows),
        "ticker_count": len(index),
        "endpoint_calls_total": _STATS["endpoint_calls"],
        "window_days": int(days),
    }
    paths["normalized"].write_text(json.dumps(rows, indent=2, sort_keys=True, default=str) + "\n")
    paths["index"].write_text(json.dumps(index, indent=2, sort_keys=True, default=str) + "\n")
    paths["stats"].write_text(json.dumps(stats, indent=2, sort_keys=True, default=str) + "\n")
    _STATS["last_row_count"] = len(rows)
    _STATS["last_ticker_count"] = len(index)
    return {"rows": rows, "index": index, "stats": stats, "from_cache": False}


def _metadata_text(metadata: dict[str, Any] | None) -> str:
    if not isinstance(metadata, dict):
        return ""
    vals = []
    for k in ("sector", "industry", "type", "name", "description", "sic_description", "gic_sector", "gic_industry", "gic_subindustry"):
        vals.append(str(metadata.get(k) or ""))
    return " ".join(vals).lower()


def _watchlist_set(watchlist: list[str] | set[str] | tuple[str, ...] | None = None) -> set[str]:
    vals = set(str(x).upper().strip() for x in (watchlist or []) if str(x).strip())
    raw = os.environ.get(FDA_WATCHLIST_ENV, "")
    vals.update(x.strip().upper() for x in raw.replace(";", ",").split(",") if x.strip())
    return vals


def should_check_fda(ticker: str, metadata: dict[str, Any] | None = None, news_text: str | None = None, cache: dict[str, Any] | None = None, watchlist: list[str] | set[str] | tuple[str, ...] | None = None) -> dict[str, Any]:
    t = str(ticker or "").upper().strip()
    index = (cache or {}).get("index") or {}
    if not t:
        return {"ticker": t, "allowed": False, "reason_code": "FDA_CHECK_BLOCKED_MISSING_DATA"}
    if t in index and index.get(t):
        return {"ticker": t, "allowed": True, "reason_code": "FDA_CHECK_ALLOWED_CALENDAR_MATCH", "events": index.get(t, [])}
    if t in _watchlist_set(watchlist):
        return {"ticker": t, "allowed": True, "reason_code": "FDA_CHECK_ALLOWED_WATCHLIST", "events": []}
    text = _metadata_text(metadata)
    if t in BROAD_PROXY_TICKERS or any(term in text for term in ETF_PROXY_TERMS):
        return {"ticker": t, "allowed": False, "reason_code": "FDA_CHECK_BLOCKED_ETF_OR_PROXY", "events": []}
    if any(term in text for term in NON_FDA_BLOCK_TERMS):
        return {"ticker": t, "allowed": False, "reason_code": "FDA_CHECK_BLOCKED_NON_FDA_SECTOR", "events": []}
    if any(term in text for term in FDA_RELEVANT_TERMS):
        return {"ticker": t, "allowed": True, "reason_code": "FDA_CHECK_ALLOWED_HEALTHCARE_CLASSIFICATION", "events": []}
    ntext = str(news_text or "").lower()
    if any(term in ntext for term in FDA_NEWS_KEYWORDS):
        return {"ticker": t, "allowed": True, "reason_code": "FDA_CHECK_ALLOWED_RECENT_KEYWORD_NEWS", "events": []}
    if str((metadata or {}).get("fda_relevant") or "").lower() in {"1", "true", "yes"}:
        return {"ticker": t, "allowed": True, "reason_code": "FDA_CHECK_ALLOWED_METADATA_TAG", "events": []}
    return {"ticker": t, "allowed": False, "reason_code": "FDA_CHECK_BLOCKED_MISSING_DATA", "events": []}


def get_fda_metadata_for_ticker(ticker: str, metadata: dict[str, Any] | None = None, news_text: str | None = None, cache: dict[str, Any] | None = None, cache_dir: Path | str | None = None, watchlist: list[str] | set[str] | tuple[str, ...] | None = None) -> dict[str, Any] | None:
    cache = cache or load_or_refresh_fda_cache(cache_dir=cache_dir)
    gate = should_check_fda(ticker, metadata=metadata, news_text=news_text, cache=cache, watchlist=watchlist)
    if not gate.get("allowed"):
        return None
    events = gate.get("events") or []
    return {
        "ticker": str(ticker or "").upper().strip(),
        "fda_relevant": True,
        "fda_relevance_reason": gate.get("reason_code"),
        "fda_events": events,
        "fda_event_count": len(events),
        "fda_next_event": events[0] if events else None,
        "fda_source_endpoint": SOURCE_ENDPOINT if events else None,
    }


def discover_fda_tickers(days: int = DEFAULT_WINDOW_DAYS, limit: int = DEFAULT_DISCOVERY_LIMIT, cache_dir: Path | str | None = None, force_refresh: bool = False, cache: dict[str, Any] | None = None, fetcher: Callable[..., Any] | None = None) -> list[str]:
    cache = cache or load_or_refresh_fda_cache(cache_dir=cache_dir, days=days, force=force_refresh, fetcher=fetcher)
    rows = list(cache.get("rows") or [])
    rows.sort(key=lambda r: (r.get("target_date") or "9999-12-31", -int(r.get("materiality_score") or 0), r.get("ticker") or ""))
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        t = str(row.get("ticker") or "").upper().strip()
        if t and t not in seen:
            seen.add(t); out.append(t)
        if len(out) >= int(limit):
            break
    return out


def get_stats() -> dict[str, Any]:
    return dict(_STATS)


def reset_stats() -> None:
    for k in list(_STATS):
        _STATS[k] = 0
