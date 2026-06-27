#!/usr/bin/env python3
"""Gate 2 Atlas scan timing harness.

Runs a complete atlas_manage.py dry-run scan against an isolated temporary DB
copy so production DB and Telegram are untouched. Exits 1 if wall time > 8 min.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import types
from pathlib import Path
from types import SimpleNamespace

SCRIPTS_DIR = Path("/Users/yasser/scripts")
PROD_DB = SCRIPTS_DIR / "atlas.db"
MAX_SECONDS = 8 * 60


def _counts(db_path: Path) -> dict[str, int]:
    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    out: dict[str, int] = {}
    for table in ("trades", "pending_pullbacks", "signals"):
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        out[table] = int(cur.fetchone()[0])
    con.close()
    return out


def _install_mock_telegram() -> None:
    os.environ["ATLAS_DISABLE_TELEGRAM"] = "1"
    os.environ["ATLAS_MOCK_TELEGRAM"] = "1"

    mock_notify = types.ModuleType("atlas_notify")

    def send_telegram(message, label="atlas", parse_mode="Markdown", print_fallback=True):
        text = str(message or "")
        print(f"[MOCK_TELEGRAM] label={label} chars={len(text)}")
        if print_fallback:
            print(text[:1200])
        return True

    setattr(mock_notify, "send_telegram", send_telegram)
    setattr(mock_notify, "send_message", send_telegram)
    sys.modules["atlas_notify"] = mock_notify


def main() -> int:
    parser = argparse.ArgumentParser(description="Atlas Gate 2 scan timing harness")
    parser.add_argument("--max-seconds", type=float, default=MAX_SECONDS)
    parser.add_argument("--db", default="", help="Optional staging DB to copy from; defaults to production DB")
    parser.add_argument("--keep-db", action="store_true", help="Keep isolated temp DB for inspection")
    args = parser.parse_args()

    sys.path.insert(0, str(SCRIPTS_DIR))
    _install_mock_telegram()

    source_db = Path(args.db).expanduser() if args.db else PROD_DB
    if not source_db.exists():
        raise SystemExit(f"source DB not found: {source_db}")

    temp_dir = Path(tempfile.mkdtemp(prefix="atlas_scan_timing_"))
    temp_db = temp_dir / "atlas_timing.db"
    shutil.copy2(source_db, temp_db)

    source_before = _counts(source_db)
    temp_before = _counts(temp_db)

    import atlas_db  # noqa: WPS433 - intentional runtime staging patch
    import atlas_account as acct  # noqa: WPS433

    atlas_db.DB_PATH = str(temp_db)
    atlas_db._vault = None
    atlas_db._atlas_log_db_event = None
    acct.DB_PATH = str(temp_db)

    def _noop(*_args, **_kwargs):
        return None

    # Timing harness is no-write: suppress ledger/signal/handoff mutations even on the temp DB.
    for name in (
        "log_signal", "update_handoff", "open_trade", "close_trade",
        "upsert_pending_pullback", "expire_pending_pullback", "mark_pending_pullback_filled",
        "delete_pending_pullback", "confirm_trade_fill", "void_pending_fill_trade",
    ):
        if hasattr(atlas_db, name):
            setattr(atlas_db, name, _noop)

    import atlas_manage  # noqa: WPS433

    atlas_manage._atlas_log_signal = None

    scan_args = SimpleNamespace(tickers=[], file=None, live=False, exits_only=False, json=False)
    print(f"[GATE2] source_db={source_db}")
    print(f"[GATE2] isolated_db={temp_db}")
    print(f"[GATE2] max_seconds={args.max_seconds:.1f}")
    print(f"[GATE2] source_counts_before={json.dumps(source_before, sort_keys=True)}")
    print(f"[GATE2] temp_counts_before={json.dumps(temp_before, sort_keys=True)}")

    start = time.perf_counter()
    summary = atlas_manage.run(scan_args)
    elapsed = time.perf_counter() - start

    source_after = _counts(source_db)
    temp_after = _counts(temp_db)
    critical_tables = ("trades", "pending_pullbacks")
    source_critical_counts_unchanged = all(source_before[t] == source_after[t] for t in critical_tables)
    result = {
        "elapsed_seconds": round(elapsed, 3),
        "max_seconds": float(args.max_seconds),
        "under_limit": elapsed <= args.max_seconds,
        "candidate_count": len(summary.get("candidates") or []),
        "scanned_count": summary.get("scanned_count"),
        "result": summary.get("result"),
        "source_counts_before": source_before,
        "source_counts_after": source_after,
        "source_counts_unchanged": source_before == source_after,
        "source_critical_counts_unchanged": source_critical_counts_unchanged,
        "gate1_critical_tables": list(critical_tables),
        "temp_counts_before": temp_before,
        "temp_counts_after": temp_after,
        "isolated_db": str(temp_db),
    }
    print("GATE2_RESULT_JSON=" + json.dumps(result, sort_keys=True, default=str))
    print(f"[GATE2] elapsed_seconds={elapsed:.3f}")

    if not args.keep_db:
        shutil.rmtree(temp_dir, ignore_errors=True)
    else:
        print(f"[GATE2] kept isolated DB at {temp_db}")

    if elapsed > args.max_seconds:
        print(f"[GATE2] FAIL: scan exceeded {args.max_seconds:.1f}s", file=sys.stderr)
        return 1
    if not source_critical_counts_unchanged:
        print("[GATE2] FAIL: source DB critical counts changed (trades/pending_pullbacks)", file=sys.stderr)
        return 1
    print("[GATE2] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
