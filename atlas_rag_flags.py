#!/usr/bin/env python3
"""Pure Perme/RAG flag helpers for Atlas reports.

Perme is annotation-only in Phase 1. These helpers never block, suppress,
force-sell, modify scores, or touch DB/Telegram/network state.
"""
from __future__ import annotations

import re
from typing import Iterable

GLOBAL_FLAGS = {"RISK-OFF", "RISK_OFF", "FED_DAY", "FOMC_DAY", "CPI_DAY"}
TICKER_PREFIXES = {"TICKER_NOTE", "EARNINGS_RISK", "CATALYST_NOTE"}
SECTOR_PREFIXES = {"SECTOR_NOTE", "SECTOR_OVERBOUGHT", "SECTOR_RISK"}


def _clean_flag(flag) -> str:
    text = str(flag or "").strip()
    text = re.sub(r"\s+", " ", text)
    if ":" in text:
        left, right = text.split(":", 1)
        return f"{left.strip().upper()}: {right.strip().upper()}"
    return text.upper()


def normalize_flags(flags) -> list[str]:
    """Uppercase/strip flags and preserve first-seen order."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in flags or []:
        flag = _clean_flag(raw)
        if not flag or flag in seen:
            continue
        seen.add(flag)
        out.append(flag)
    return out


def _split_flag(flag: str) -> tuple[str, str]:
    if ":" not in str(flag or ""):
        return str(flag or "").strip().upper(), ""
    left, right = str(flag).split(":", 1)
    return left.strip().upper(), right.strip().upper()


def _contains_token(value: str, token: str) -> bool:
    if not value or not token:
        return False
    parts = re.split(r"[^A-Z0-9.]+", value.upper())
    return token.upper() in {p for p in parts if p}


def flags_for_ticker(flags, ticker, sector=None) -> list[str]:
    """Return global + ticker/sector-specific flags relevant to ticker.

    This is annotation-only. It never returns block/force-sell instructions.
    """
    ticker = str(ticker or "").strip().upper()
    sector = str(sector or "").strip().upper()
    relevant: list[str] = []
    for flag in normalize_flags(flags):
        prefix, value = _split_flag(flag)
        if prefix in GLOBAL_FLAGS and not value:
            relevant.append(flag)
        elif prefix in TICKER_PREFIXES and ticker and _contains_token(value, ticker):
            relevant.append(flag)
        elif prefix in SECTOR_PREFIXES and sector and _contains_token(value, sector):
            relevant.append(flag)
    return relevant


def _note_for_flag(flag: str, ticker: str = "", sector: str | None = None) -> str:
    prefix, value = _split_flag(flag)
    if prefix in {"RISK-OFF", "RISK_OFF"}:
        return "macro risk-off context"
    if prefix == "FED_DAY":
        return "Fed day volatility risk"
    if prefix == "FOMC_DAY":
        return "FOMC day volatility risk"
    if prefix == "CPI_DAY":
        return "CPI day volatility risk"
    if prefix == "EARNINGS_RISK":
        return f"earnings risk flagged for {ticker or value}".strip()
    if prefix == "SECTOR_OVERBOUGHT":
        return f"sector overbought context: {value}" if value else "sector overbought context"
    if prefix == "SECTOR_NOTE":
        return f"sector note: {value}" if value else "sector note"
    if prefix == "SECTOR_RISK":
        return f"sector risk: {value}" if value else "sector risk"
    if prefix == "TICKER_NOTE":
        return f"ticker note: {value}" if value else "ticker note"
    if prefix == "CATALYST_NOTE":
        return f"catalyst note: {value}" if value else "catalyst note"
    return flag


def annotation_for_ticker(flags, ticker, sector=None) -> dict:
    """Build a human-readable Perme annotation for ticker.

    Return shape: {"has_note": bool, "note": str, "flags": list[str]}.
    Phase 1 is annotator-only: no block, no suppression, no force-sell fields.
    """
    relevant = flags_for_ticker(flags, ticker, sector=sector)
    notes: list[str] = []
    seen: set[str] = set()
    for flag in relevant:
        note = _note_for_flag(flag, str(ticker or "").upper(), sector)
        if note and note not in seen:
            seen.add(note)
            notes.append(note)
    return {"has_note": bool(notes), "note": "; ".join(notes), "flags": relevant}
