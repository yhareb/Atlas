#!/usr/bin/env python3
"""
vault_sync.py — Atlas Mac Mini -> The Vault sync agent
======================================================

Reads the local Atlas SQLite database (atlas.db) and pushes signals,
positions, and the latest end-of-day handoff to The Vault web dashboard
via its token-protected /api/sync endpoint.

This script is mapped to the ACTUAL Atlas schema defined in atlas_db.py:

    signals(id, timestamp, ticker, signal, score, rvol, entry_price,
            stop_loss, max_loss_per_share, atr, trend_stack,
            relative_strength, volume, catalyst, warnings)

    positions(id, timestamp, ticker, action, price, quantity, status)

    handoff(id, date UNIQUE, data)   -- data is a JSON blob:
            {"date": "...", "BUY": [...], "WATCH": [...], "last_scan": "..."}

    trades(id, ticker, status, quantity, entry_price, entry_at, exit_price,
           exit_at, entry_fees, exit_fees, realized_pnl, realized_pnl_pct,
           parent_id, notes, updated_at)   -- one row per LOT; FIFO partial
           sells split lots and realize P&L on the closed shares.

Design notes
------------
* Standard library ONLY (sqlite3, json, urllib, ...). No pip install needed.
* Opens atlas.db READ-ONLY (mode=ro): it can never modify your Atlas data.
* Idempotent: the Vault server upserts signals/positions by their Atlas row
  `id` (sent as `sourceId`) and the handoff by `date`. Re-running never
  duplicates rows.

Usage
-----
    export VAULT_URL="https://the-vault.manus.space"
    export VAULT_SYNC_TOKEN="vault_atlas_..."
    export ATLAS_DB="/Users/yasser/scripts/atlas.db"
    python3 vault_sync.py

Flags:
    --dry-run        Print the JSON payload instead of sending it.
    --db PATH        Override ATLAS_DB (default /Users/yasser/scripts/atlas.db).
    --url URL        Override VAULT_URL.
    --token TOKEN    Override VAULT_SYNC_TOKEN.
    --since-days N   Only sync signals from the last N days (default 7).
"""

import argparse
import json
import os
import re
import socket
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

DEFAULT_DB = "/Users/yasser/scripts/atlas.db"
DEFAULT_CURSOR_FILE = "/tmp/vault_sync_cursor.txt"
DEFAULT_LOG_PATH = "/Users/yasser/scripts/vault_sync.log"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def to_epoch_ms(value):
    """Convert an Atlas timestamp to Unix epoch milliseconds (int) or None.

    Atlas stores `timestamp DATETIME DEFAULT CURRENT_TIMESTAMP`, i.e. SQLite's
    'YYYY-MM-DD HH:MM:SS' in UTC. We also handle ISO strings and raw epochs.
    """
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
        "%Y-%m-%d %H:%M:%S",          # SQLite CURRENT_TIMESTAMP (UTC)
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


def table_exists(conn, name):
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    )
    return cur.fetchone() is not None


def max_epoch_ms(*values):
    epochs = [to_epoch_ms(v) for v in values]
    epochs = [v for v in epochs if v is not None]
    return max(epochs) if epochs else None


def read_cursor_ms(cursor_file, log_path=DEFAULT_LOG_PATH):
    """Return (epoch_ms, source_label) for incremental sync high-water mark.

    Primary source is the cursor file written after successful syncs. On first
    deployment, fall back to the last successful line in vault_sync.log so the
    first fixed run does not resend the historical 6k+ row payload.
    """
    if cursor_file and os.path.exists(cursor_file):
        raw = open(cursor_file, "r", encoding="utf-8").read().strip().splitlines()[0].strip()
        ms = to_epoch_ms(raw)
        if ms is not None:
            return ms, f"cursor:{cursor_file}"
        print(f"[warn] invalid cursor in {cursor_file!r}: {raw!r}; falling back", file=sys.stderr)

    if log_path and os.path.exists(log_path):
        last = None
        with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = re.match(r"\[([^\]]+)\] OK ", line)
                if m:
                    last = m.group(1)
        if last:
            ms = to_epoch_ms(last)
            if ms is not None:
                return ms, f"last-ok-log:{log_path}"

    return None, "none"


def write_cursor(cursor_file, stamp):
    if not cursor_file:
        return
    tmp = f"{cursor_file}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(stamp + "\n")
    os.replace(tmp, cursor_file)


# --------------------------------------------------------------------------- #
# Atlas schema -> Vault payload
# --------------------------------------------------------------------------- #
def build_signals(conn, cursor_ms, since_days):
    """signals table -> Vault signal objects newer than cursor_ms."""
    if not table_exists(conn, "signals"):
        print("[warn] no 'signals' table; skipping.", file=sys.stderr)
        return []

    cutoff_ms = cursor_ms
    if cutoff_ms is None:
        cutoff_ms = int(datetime.now(timezone.utc).timestamp() * 1000) - since_days * 86400_000
    cur = conn.execute(
        """
        SELECT id, timestamp, ticker, signal, score, rvol, entry_price,
               stop_loss, max_loss_per_share, atr, trend_stack,
               relative_strength, volume, catalyst, warnings
        FROM signals
        ORDER BY timestamp DESC
        """
    )
    out = []
    for r in cur.fetchall():
        scanned_ms = to_epoch_ms(r["timestamp"])
        if r["id"] is None or not r["ticker"] or not r["signal"] or scanned_ms is None:
            continue
        if scanned_ms < cutoff_ms:
            continue
        # Atlas `score` is an INTEGER (e.g. 4). The Vault stores score as text
        # so it can render values like "4/4"; we send the raw number as a string.
        score = r["score"]
        out.append(
            {
                "sourceId": int(r["id"]),
                "ticker": str(r["ticker"]).upper(),
                "signal": str(r["signal"]).upper(),
                "score": None if score is None else str(score),
                "rvol": _f(r["rvol"]),
                "entryPrice": _f(r["entry_price"]),
                "stopLoss": _f(r["stop_loss"]),
                "maxLossPerShare": _f(r["max_loss_per_share"]),
                "atr": _f(r["atr"]),
                "trendStack": _s(r["trend_stack"]),
                "relativeStrength": _s(r["relative_strength"]),
                "volume": _s(r["volume"]),
                "catalyst": _s(r["catalyst"]),
                "warnings": _s(r["warnings"]),
                "scannedAt": scanned_ms,
            }
        )
    return out


def build_positions(conn, cursor_ms):
    """OPEN trades -> Vault position objects.

    `trades` is the authoritative Atlas position ledger. The legacy `positions`
    table is intentionally ignored because it is stale/non-authoritative.
    """
    if not table_exists(conn, "trades"):
        print("[warn] no 'trades' table; skipping positions payload.", file=sys.stderr)
        return []

    cur = conn.execute(
        """
        SELECT id, ticker, quantity, entry_price, entry_at, status, current_price
        FROM trades
        WHERE status = 'OPEN'
        ORDER BY entry_at DESC, id DESC
        """
    )
    out = []
    for r in cur.fetchall():
        opened_ms = to_epoch_ms(r["entry_at"])
        if cursor_ms is not None and (opened_ms is None or opened_ms <= cursor_ms):
            continue
        price = _f(r["entry_price"])
        if r["id"] is None or not r["ticker"] or price is None or opened_ms is None:
            continue
        out.append(
            {
                "sourceId": int(r["id"]),
                "ticker": str(r["ticker"]).upper(),
                "action": "BUY",
                "price": price,
                "quantity": int(r["quantity"] or 0),
                "status": (_s(r["status"]) or "OPEN").upper(),
                "currentPrice": _f(r["current_price"]),
                "openedAt": opened_ms,
            }
        )
    return out


def build_handoff(conn, cursor_ms):
    """handoff table (latest row) -> Vault handoff objects (list of one).

    Atlas stores a JSON blob in `data`:
        {"date": "2026-06-20", "BUY": ["NVDA"], "WATCH": ["AMD"],
         "last_scan": "2026-06-20T16:05:00"}
    """
    if not table_exists(conn, "handoff"):
        print("[warn] no 'handoff' table; skipping.", file=sys.stderr)
        return []

    cur = conn.execute(
        "SELECT date, data FROM handoff ORDER BY date DESC LIMIT 1"
    )
    r = cur.fetchone()
    if r is None or not r["date"]:
        return []
    handoff_ms = to_epoch_ms(str(r["date"])[:10])
    if cursor_ms is not None and handoff_ms is not None and handoff_ms <= cursor_ms:
        return []

    payload = {}
    if r["data"]:
        try:
            payload = json.loads(r["data"])
        except (json.JSONDecodeError, TypeError):
            payload = {}

    def as_list(v):
        if isinstance(v, list):
            return [str(x).upper() for x in v]
        if isinstance(v, str) and v.strip():
            return [t.strip().upper() for t in v.replace(";", ",").split(",") if t.strip()]
        return []

    return [
        {
            "date": str(r["date"])[:10],
            "buyTickers": as_list(payload.get("BUY")),
            "watchTickers": as_list(payload.get("WATCH")),
            "lastScan": _s(payload.get("last_scan")),
        }
    ]


def build_trades(conn, cursor_ms):
    """trades table -> Vault trade objects (one row per lot).

    Maps the Atlas `trades` ledger (added in atlas_db.py): each row is a lot
    with entry/exit price, quantity, fees, and realized P&L. CLOSED rows carry
    realized P&L; OPEN rows leave exit/realized fields null.
    """
    if not table_exists(conn, "trades"):
        print("[warn] no 'trades' table; skipping.", file=sys.stderr)
        return []

    cur = conn.execute(
        """
        SELECT id, ticker, status, quantity, entry_price, entry_at,
               exit_price, exit_at, entry_fees, exit_fees,
               realized_pnl, realized_pnl_pct, notes, updated_at
        FROM trades
        ORDER BY COALESCE(updated_at, exit_at, entry_at) DESC, id DESC
        """
    )
    out = []
    for r in cur.fetchall():
        entry_ms = to_epoch_ms(r["entry_at"])
        changed_ms = max_epoch_ms(r["updated_at"], r["exit_at"], r["entry_at"])
        if cursor_ms is not None and (changed_ms is None or changed_ms <= cursor_ms):
            continue
        entry_price = _f(r["entry_price"])
        if r["id"] is None or not r["ticker"] or entry_price is None or entry_ms is None:
            continue
        out.append(
            {
                "sourceId": int(r["id"]),
                "ticker": str(r["ticker"]).upper(),
                "status": (_s(r["status"]) or "OPEN").upper(),
                "quantity": int(r["quantity"] or 0),
                "entryPrice": entry_price,
                "entryAt": entry_ms,
                "exitPrice": _f(r["exit_price"]),
                "exitAt": to_epoch_ms(r["exit_at"]),
                "entryFees": _f(r["entry_fees"]) or 0,
                "exitFees": _f(r["exit_fees"]) or 0,
                "realizedPnl": _f(r["realized_pnl"]),
                "realizedPnlPct": _f(r["realized_pnl_pct"]),
                "notes": _s(r["notes"]),
            }
        )
    return out


# --------------------------------------------------------------------------- #
# Transport
# --------------------------------------------------------------------------- #
def post_payload(url, token, payload, timeout=30):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url.rstrip("/") + "/api/sync",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "Atlas-VaultSync/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Sync Atlas atlas.db to The Vault.")
    ap.add_argument("--db", default=os.environ.get("ATLAS_DB", DEFAULT_DB))
    ap.add_argument("--url", default=os.environ.get("VAULT_URL", ""))
    ap.add_argument("--token", default=os.environ.get("VAULT_SYNC_TOKEN", ""))
    ap.add_argument("--since-days", type=int, default=7)
    ap.add_argument("--cursor-file", default=os.environ.get("VAULT_SYNC_CURSOR", DEFAULT_CURSOR_FILE))
    ap.add_argument("--log-path", default=os.environ.get("VAULT_SYNC_LOG", DEFAULT_LOG_PATH))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.dry_run:
        if not args.url:
            sys.exit("ERROR: VAULT_URL (or --url) is required.")
        if not args.token:
            sys.exit("ERROR: VAULT_SYNC_TOKEN (or --token) is required.")
    if not os.path.exists(args.db):
        sys.exit(f"ERROR: Atlas DB not found at {args.db}")

    run_started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cursor_ms, cursor_source = read_cursor_ms(args.cursor_file, args.log_path)
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        payload = {
            "signals": build_signals(conn, cursor_ms, args.since_days),
            "positions": build_positions(conn, cursor_ms),
            "handoff": build_handoff(conn, cursor_ms),
            "trades": build_trades(conn, cursor_ms),
        }
    finally:
        conn.close()

    counts = {k: len(v) for k, v in payload.items()}

    if args.dry_run:
        print(json.dumps(payload, indent=2))
        print(f"[cursor] source={cursor_source} since_ms={cursor_ms}", file=sys.stderr)
        print(f"[dry-run] would send {counts}", file=sys.stderr)
        return

    try:
        status, data = post_payload(args.url, args.token, payload)
    except (socket.timeout, TimeoutError) as e:
        print(f"ERROR: sync timed out posting to Vault: {e}", file=sys.stderr)
        return
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        sys.exit(f"ERROR: sync failed HTTP {e.code}: {detail}")
    except urllib.error.URLError as e:
        sys.exit(f"ERROR: could not reach Vault: {e.reason}")

    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if status == 200 and data.get("ok"):
        write_cursor(args.cursor_file, run_started)
        print(f"[{stamp}] OK read={counts} synced={data.get('synced')} cursor={run_started}")
    else:
        sys.exit(f"[{stamp}] FAILED status={status} resp={data}")


if __name__ == "__main__":
    main()
