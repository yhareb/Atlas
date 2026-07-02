#!/usr/bin/env python3
"""atlas_provider_guard.py — resilient provider API wrappers for Atlas.

Staging-only module until explicitly deployed. No Telegram configuration is read
or touched here. Callers pass URLs/params and treat a returned None as a
provider miss/suppressed ticker.
"""

from __future__ import annotations

import json
import os
import time
from json.decoder import JSONDecodeError
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import requests

MASSIVE_TIMEOUT_SECONDS = 30
MASSIVE_RETRY_BACKOFF_SECONDS = (2,)
EODHD_LOW_REMAINING_THRESHOLD = 50
EODHD_LOW_REMAINING_SLEEP_SECONDS = 1
EODHD_429_SLEEP_SECONDS = 60
BENZINGA_UNCOVERED_PATH = Path(
    os.environ.get(
        "ATLAS_BENZINGA_UNCOVERED_FILE",
        os.path.expanduser("~/scripts/benzinga_uncovered.json"),
    )
)
BENZINGA_UNCOVERED = set()


def _log(message: str) -> None:
    print(f"[provider_guard] {message}", flush=True)


def _ticker(ticker: Optional[str]) -> str:
    return str(ticker or "").strip().upper()


def _load_benzinga_uncovered() -> None:
    global BENZINGA_UNCOVERED
    try:
        if not BENZINGA_UNCOVERED_PATH.exists():
            return
        data = json.loads(BENZINGA_UNCOVERED_PATH.read_text())
        if isinstance(data, list):
            BENZINGA_UNCOVERED.update(_ticker(x) for x in data if _ticker(x))
        elif isinstance(data, dict):
            rows = data.get("tickers") or data.get("BENZINGA_UNCOVERED") or []
            BENZINGA_UNCOVERED.update(_ticker(x) for x in rows if _ticker(x))
    except Exception as exc:
        _log(f"benzinga uncovered load skipped: {type(exc).__name__}: {exc}")


def _persist_benzinga_uncovered() -> None:
    try:
        BENZINGA_UNCOVERED_PATH.parent.mkdir(parents=True, exist_ok=True)
        BENZINGA_UNCOVERED_PATH.write_text(
            json.dumps(sorted(BENZINGA_UNCOVERED), indent=2) + "\n"
        )
    except Exception as exc:
        _log(f"benzinga uncovered persist skipped: {type(exc).__name__}: {exc}")


def mark_benzinga_uncovered(ticker: Optional[str]) -> None:
    t = _ticker(ticker)
    if not t:
        return
    if t not in BENZINGA_UNCOVERED:
        BENZINGA_UNCOVERED.add(t)
        _persist_benzinga_uncovered()
    _log(f"benzinga uncovered ticker skipped: {t}")


def reset_benzinga_uncovered_for_tests() -> None:
    """Test helper only; production callers should not use this."""
    BENZINGA_UNCOVERED.clear()


def _safe_json(response: requests.Response) -> Any:
    return response.json()


def massive_get_json(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = MASSIVE_TIMEOUT_SECONDS,
    session: Any = requests,
    sleep_fn: Callable[[float], None] = time.sleep,
    request_tag: str = "massive",
) -> Optional[Any]:
    """GET JSON from Massive with 20s timeout and retry on ReadTimeout/5xx.

    Attempts: initial request + 2 retries. Backoff: 1s, then 2s.
    Returns None after all attempts fail so callers suppress stale output.
    """
    attempts = 1 + len(MASSIVE_RETRY_BACKOFF_SECONDS)
    last_error: Optional[str] = None
    for attempt in range(1, attempts + 1):
        try:
            response = session.get(url, params=params or {}, headers=headers, timeout=timeout)
            status = getattr(response, "status_code", None)
            if status is not None and 500 <= int(status) <= 599:
                last_error = f"HTTP {status}"
                if attempt < attempts:
                    backoff = MASSIVE_RETRY_BACKOFF_SECONDS[attempt - 1]
                    _log(f"{request_tag} {last_error}; retry {attempt}/2 in {backoff}s")
                    sleep_fn(backoff)
                    continue
                _log(f"{request_tag} failed after 2 retries: {last_error}")
                return None
            if status is not None and int(status) != 200:
                _log(f"{request_tag} non-200 HTTP {status}; suppressing")
                return None
            return response.json()
        except requests.exceptions.ReadTimeout as exc:
            last_error = f"ReadTimeout: {exc}"
            if attempt < attempts:
                backoff = MASSIVE_RETRY_BACKOFF_SECONDS[attempt - 1]
                _log(f"{request_tag} read timeout; retry {attempt}/2 in {backoff}s")
                sleep_fn(backoff)
                continue
            _log(f"{request_tag} failed after 2 retries: {last_error}")
            return None
        except requests.exceptions.RequestException as exc:
            _log(f"{request_tag} request failed: {type(exc).__name__}: {exc}")
            return None
        except (JSONDecodeError, ValueError) as exc:
            _log(f"{request_tag} invalid JSON: {type(exc).__name__}: {exc}")
            return None
    _log(f"{request_tag} failed after 2 retries: {last_error or 'unknown error'}")
    return None


def benzinga_get_json(
    ticker: Optional[str],
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = MASSIVE_TIMEOUT_SECONDS,
    session: Any = requests,
    request_tag: str = "benzinga",
) -> Optional[Any]:
    """GET Benzinga JSON with uncovered-ticker persistence and JSON guard."""
    t = _ticker(ticker)
    if t in BENZINGA_UNCOVERED:
        _log(f"{request_tag} skipped uncovered ticker: {t}")
        return None
    try:
        response = session.get(url, params=params or {}, headers=headers, timeout=timeout)
        status = getattr(response, "status_code", None)
        if status is not None and int(status) != 200:
            _log(f"{request_tag} {t or '?'} HTTP {status}; suppressing")
            return None
        # Guard against empty response bodies for micro/nano-caps
        if not response.text or not response.text.strip():
            mark_benzinga_uncovered(t)
            return None
        return response.json()
    except JSONDecodeError:
        mark_benzinga_uncovered(t)
        return None
    except ValueError:
        # requests may raise requests.exceptions.JSONDecodeError, a ValueError subclass.
        mark_benzinga_uncovered(t)
        return None
    except requests.exceptions.RequestException as exc:
        _log(f"{request_tag} {t or '?'} request failed: {type(exc).__name__}: {exc}")
        return None


def eodhd_get_json(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = MASSIVE_TIMEOUT_SECONDS,
    session: Any = requests,
    sleep_fn: Callable[[float], None] = time.sleep,
    request_tag: str = "eodhd",
) -> Optional[Any]:
    """GET EODHD JSON with rate-limit awareness and one retry on HTTP 429."""
    for attempt in (1, 2):
        try:
            response = session.get(url, params=params or {}, headers=headers, timeout=timeout)
            status = int(getattr(response, "status_code", 0) or 0)
            remaining = getattr(response, "headers", {}).get("X-RateLimit-Remaining")
            if status == 429 and attempt == 1:
                _log(f"{request_tag} HTTP 429; retrying once after {EODHD_429_SLEEP_SECONDS}s")
                sleep_fn(EODHD_429_SLEEP_SECONDS)
                continue
            if status != 200:
                _log(f"{request_tag} HTTP {status}; suppressing")
                return None
            data = response.json()
            try:
                if remaining is not None and int(remaining) < EODHD_LOW_REMAINING_THRESHOLD:
                    _log(f"{request_tag} low rate-limit remaining={remaining}; sleeping {EODHD_LOW_REMAINING_SLEEP_SECONDS}s")
                    sleep_fn(EODHD_LOW_REMAINING_SLEEP_SECONDS)
            except Exception:
                pass
            return data
        except requests.exceptions.RequestException as exc:
            _log(f"{request_tag} request failed: {type(exc).__name__}: {exc}")
            return None
        except (JSONDecodeError, ValueError) as exc:
            _log(f"{request_tag} invalid JSON: {type(exc).__name__}: {exc}")
            return None
    return None


_load_benzinga_uncovered()
