#!/usr/bin/env python3
"""
vault_client.py — Atlas -> The Vault REAL-TIME push (Option A)
==============================================================

This is the live-push companion to ``vault_sync.py``. Where ``vault_sync.py``
runs on a schedule and pushes the whole database, ``vault_client.py`` pushes a
SINGLE transaction to The Vault the instant Atlas records it, so the dashboard
updates in real time.

Design principles (deliberately conservative)
----------------------------------------------
* **Atlas stays the source of truth.** This module only ever PUSHES a copy of a
  row that Atlas has ALREADY written to ``atlas.db``. It never writes back to
  Atlas and never gates an Atlas write on the network.
* **Fire-and-forget. Never raises into Atlas.** Every public function swallows
  all exceptions (network down, bad token, timeout) and returns a bool. A Vault
  outage can NEVER break a buy/sell from being logged locally.
* **Idempotent.** It reuses the same ``/api/sync`` contract and ``sourceId``
  keys as ``vault_sync.py``, so the server upserts. If a real-time push fails,
  the next scheduled ``vault_sync.py`` run resends it — no data loss, no dupes.
* **Standard library only.** No pip install on the Mac Mini.
* **Disabled cleanly when unconfigured.** If ``VAULT_URL`` / ``VAULT_SYNC_TOKEN``
  are not set, pushes are silently skipped and Atlas runs exactly as before.

Configuration (env)
--------------------
    VAULT_URL          e.g. https://the-vault.manus.space
    VAULT_SYNC_TOKEN   the shared bearer token (same one vault_sync.py uses)
    VAULT_PUSH         optional; set to "0"/"false" to disable real-time push
    VAULT_PUSH_TIMEOUT optional; seconds (default 10) — kept short so a slow
                       network barely delays the Atlas command
    VAULT_PUSH_LOG     optional; path to append push outcomes (default: stderr)

Usage from atlas_db.py
----------------------
    import vault_client
    vault_client.push_trades([row_dict, ...])     # after open_trade/close_trade
    vault_client.push_signal(signal_row_dict)     # after log_signal
    vault_client.push_handoff(date_str, data_dict)# after update_handoff

The row dicts use the SAME column names as the Atlas tables; this module maps
them to the Vault payload shape exactly like vault_sync.py does.
"""

import json
import os
import queue
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone


# --------------------------------------------------------------------------- #
# Field mapping helpers — kept byte-for-byte compatible with vault_sync.py
# --------------------------------------------------------------------------- #
def to_epoch_ms(value):
    """Atlas timestamp -> Unix epoch ms (int) or None. Mirrors vault_sync.py."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return int(v if v > 1e12 else v * 1000)
    s = str(value).strip()
    if s == "":
        return None
    try:
        v = float(s)
        return int(v if v > 1e12 else v * 1000)
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    return None


def _f(v):
    try:
        return None if v is None or v == "" else float(v)
    except (ValueError, TypeError):
        return None


def _s(v):
    return None if v is None else str(v)


def _as_list(v):
    if isinstance(v, list):
        return [str(x).upper() for x in v]
    if isinstance(v, str) and v.strip():
        return [t.strip().upper() for t in v.replace(";", ",").split(",") if t.strip()]
    return []


# --------------------------------------------------------------------------- #
# Row -> Vault payload object builders (single row each)
# --------------------------------------------------------------------------- #
def map_trade(row):
    """Atlas trades row (dict) -> Vault trade object, or None if invalid."""
    entry_ms = to_epoch_ms(row.get("entry_at"))
    entry_price = _f(row.get("entry_price"))
    if row.get("id") is None or not row.get("ticker") or entry_price is None or entry_ms is None:
        return None
    return {
        "sourceId": int(row["id"]),
        "ticker": str(row["ticker"]).upper(),
        "status": (_s(row.get("status")) or "OPEN").upper(),
        "quantity": int(row.get("quantity") or 0),
        "entryPrice": entry_price,
        "entryAt": entry_ms,
        "exitPrice": _f(row.get("exit_price")),
        "exitAt": to_epoch_ms(row.get("exit_at")),
        "entryFees": _f(row.get("entry_fees")) or 0,
        "exitFees": _f(row.get("exit_fees")) or 0,
        "realizedPnl": _f(row.get("realized_pnl")),
        "realizedPnlPct": _f(row.get("realized_pnl_pct")),
        "notes": _s(row.get("notes")),
    }


def map_signal(row):
    """Atlas signals row (dict) -> Vault signal object, or None if invalid."""
    scanned_ms = to_epoch_ms(row.get("timestamp"))
    if row.get("id") is None or not row.get("ticker") or not row.get("signal") or scanned_ms is None:
        return None
    score = row.get("score")
    return {
        "sourceId": int(row["id"]),
        "ticker": str(row["ticker"]).upper(),
        "signal": str(row["signal"]).upper(),
        "score": None if score is None else str(score),
        "rvol": _f(row.get("rvol")),
        "entryPrice": _f(row.get("entry_price")),
        "stopLoss": _f(row.get("stop_loss")),
        "maxLossPerShare": _f(row.get("max_loss_per_share")),
        "atr": _f(row.get("atr")),
        "trendStack": _s(row.get("trend_stack")),
        "relativeStrength": _s(row.get("relative_strength")),
        "volume": _s(row.get("volume")),
        "catalyst": _s(row.get("catalyst")),
        "warnings": _s(row.get("warnings")),
        "scannedAt": scanned_ms,
    }


def map_position(row):
    """Atlas positions row (dict) -> Vault position object, or None if invalid."""
    opened_ms = to_epoch_ms(row.get("timestamp"))
    price = _f(row.get("price"))
    if row.get("id") is None or not row.get("ticker") or not row.get("action") or price is None or opened_ms is None:
        return None
    return {
        "sourceId": int(row["id"]),
        "ticker": str(row["ticker"]).upper(),
        "action": str(row["action"]).upper(),
        "price": price,
        "quantity": int(row.get("quantity") or 0),
        "status": (_s(row.get("status")) or "OPEN").upper(),
        "currentPrice": None,
        "openedAt": opened_ms,
    }


def map_handoff(date_str, data_dict):
    """(date, data dict) -> Vault handoff object, or None if invalid."""
    if not date_str:
        return None
    data_dict = data_dict or {}
    return {
        "date": str(date_str)[:10],
        "buyTickers": _as_list(data_dict.get("BUY")),
        "watchTickers": _as_list(data_dict.get("WATCH")),
        "lastScan": _s(data_dict.get("last_scan")),
    }


# --------------------------------------------------------------------------- #
# Config + transport
# --------------------------------------------------------------------------- #
def _enabled():
    if os.environ.get("VAULT_PUSH", "1").lower() in ("0", "false", "no", "off"):
        return False
    return bool(os.environ.get("VAULT_URL") and os.environ.get("VAULT_SYNC_TOKEN"))


def _log(msg):
    line = f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] vault_client: {msg}"
    path = os.environ.get("VAULT_PUSH_LOG")
    if path:
        try:
            with open(path, "a") as fh:
                fh.write(line + "\n")
            return
        except OSError:
            pass
    print(line, file=sys.stderr)


def _post(payload, timeout):
    url = os.environ["VAULT_URL"].rstrip("/") + "/api/sync"
    token = os.environ["VAULT_SYNC_TOKEN"]
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "Atlas-VaultSync/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


# A single ordered worker thread drains this queue. Serializing pushes this way
# guarantees they reach the Vault in CALL ORDER, so an earlier push (e.g. a lot
# at quantity 100) can never overwrite a later one (the same lot shrunk to 60).
# This removes the out-of-order race that independent daemon threads would have.
_push_q: "queue.Queue" = queue.Queue()
_worker_lock = threading.Lock()
_worker_started = False


def _do_post(payload, label, counts):
    timeout = float(os.environ.get("VAULT_PUSH_TIMEOUT", "10"))
    try:
        try:
            status, data = _post(payload, timeout)
        except Exception as e:  # noqa: BLE001 — retry timeout once, then let outer handler log
            if isinstance(e, TimeoutError) or "timed out" in repr(e).lower():
                time.sleep(1)
                status, data = _post(payload, timeout)
            else:
                raise
        if status == 200 and data.get("ok"):
            _log(f"pushed {label} {counts} synced={data.get('synced')}")
            return True
        _log(f"push {label} rejected: status={status} resp={data}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore") if hasattr(e, "read") else ""
        _log(f"push {label} HTTP {e.code}: {detail} (will retry on next scheduled sync)")
    except Exception as e:  # noqa: BLE001 — must never propagate into Atlas
        _log(f"push {label} failed: {e!r} (will retry on next scheduled sync)")
    return False


def _worker():
    while True:
        payload, label, counts = _push_q.get()
        try:
            _do_post(payload, label, counts)
        except Exception:  # noqa: BLE001 — worker must never die
            pass
        finally:
            _push_q.task_done()


def _ensure_worker():
    global _worker_started
    with _worker_lock:
        if not _worker_started:
            threading.Thread(target=_worker, name="vault-push", daemon=True).start()
            _worker_started = True


def _send(payload, label, blocking):
    """Enqueue a payload for ordered delivery. Returns True on success (blocking)."""
    if not _enabled():
        return False
    counts = {k: len(v) for k, v in payload.items() if isinstance(v, list)}
    if not any(counts.values()):
        return False

    if blocking:
        return _do_post(payload, label, counts)
    # Ordered async delivery: one worker drains the queue in FIFO (call) order,
    # so the Atlas command returns instantly but pushes never reorder.
    _ensure_worker()
    _push_q.put((payload, label, counts))
    return True


def flush(timeout=10):
    """Block until all queued pushes have been attempted (best-effort).

    Useful for short-lived scripts that would otherwise exit before the daemon
    worker drains the queue. Returns True if the queue emptied in time."""
    if not _worker_started:
        return True
    done = threading.Event()

    def waiter():
        _push_q.join()
        done.set()

    threading.Thread(target=waiter, daemon=True).start()
    return done.wait(timeout)


# --------------------------------------------------------------------------- #
# Public API — call these from atlas_db.py after a successful local write
# --------------------------------------------------------------------------- #
def push_trades(rows, blocking=False):
    objs = [o for o in (map_trade(r) for r in (rows or [])) if o]
    if not objs:
        return False
    return _send({"trades": objs}, "trades", blocking)


def push_signal(row, blocking=False):
    obj = map_signal(row)
    if not obj:
        return False
    return _send({"signals": [obj]}, "signal", blocking)


def push_positions(rows, blocking=False):
    objs = [o for o in (map_position(r) for r in (rows or [])) if o]
    if not objs:
        return False
    return _send({"positions": objs}, "positions", blocking)


def push_handoff(date_str, data_dict, blocking=False):
    obj = map_handoff(date_str, data_dict)
    if not obj:
        return False
    return _send({"handoff": [obj]}, "handoff", blocking)


if __name__ == "__main__":
    # Tiny smoke test: push a fake trade if configured, else explain.
    if not _enabled():
        print("vault_client: push disabled (set VAULT_URL + VAULT_SYNC_TOKEN to enable).")
        sys.exit(0)
    sample = {
        "id": 999999,
        "ticker": "TEST",
        "status": "OPEN",
        "quantity": 1,
        "entry_price": 1.23,
        "entry_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }
    ok = push_trades([sample], blocking=True)
    print("vault_client: smoke push", "OK" if ok else "FAILED (see log)")
