#!/usr/bin/env python3
"""Fail-silent PostgreSQL audit helpers for Atlas.

Audit logging must never affect trading. All runtime log helpers swallow all
exceptions and return False on failure. Setup/CLI commands print status for
operator verification, but the imported functions are always no-op safe.
"""

import argparse
import datetime as _dt
import json
import os
from pathlib import Path
import sys

_VENDOR = Path(__file__).resolve().parent / ".atlas_audit_vendor"
if _VENDOR.exists():
    sys.path.insert(0, str(_VENDOR))

try:
    import psycopg
    from psycopg.types.json import Jsonb
except Exception:
    psycopg = None
    Jsonb = None

DB_NAME = os.environ.get("ATLAS_AUDIT_DB", "atlas_ops")
CONNECT_TIMEOUT = float(os.environ.get("ATLAS_AUDIT_CONNECT_TIMEOUT", "0.3"))
STATEMENT_TIMEOUT_MS = int(os.environ.get("ATLAS_AUDIT_STATEMENT_TIMEOUT_MS", "300"))


def _jsonb(value):
    if value is None:
        value = {}
    if not isinstance(value, (dict, list)):
        value = {"value": value}
    return Jsonb(value) if Jsonb is not None else json.dumps(value)


def _connect():
    if psycopg is None:
        return None
    return psycopg.connect(
        dbname=DB_NAME,
        connect_timeout=CONNECT_TIMEOUT,
        options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
    )


def setup_schema():
    """Create Atlas audit schema. Returns True on success, False on failure."""
    if psycopg is None:
        return False
    try:
        with _connect() as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ops_api_calls (
                        id BIGSERIAL PRIMARY KEY,
                        ts TIMESTAMPTZ NOT NULL DEFAULT now(),
                        provider TEXT NOT NULL,
                        file_path TEXT,
                        function_name TEXT,
                        endpoint TEXT NOT NULL,
                        method TEXT NOT NULL DEFAULT 'GET',
                        http_status INTEGER,
                        latency_ms INTEGER,
                        ok BOOLEAN,
                        error TEXT,
                        request_tag TEXT,
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ops_signals (
                        id BIGSERIAL PRIMARY KEY,
                        ts TIMESTAMPTZ NOT NULL DEFAULT now(),
                        market_date DATE,
                        run_id TEXT,
                        ticker TEXT NOT NULL,
                        action TEXT NOT NULL,
                        reason TEXT,
                        score TEXT,
                        pillars INTEGER,
                        live BOOLEAN,
                        source TEXT,
                        entry NUMERIC,
                        stop NUMERIC,
                        target NUMERIC,
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ops_code_changes (
                        id BIGSERIAL PRIMARY KEY,
                        ts TIMESTAMPTZ NOT NULL DEFAULT now(),
                        work_order TEXT,
                        file_path TEXT NOT NULL,
                        backup_path TEXT,
                        change_summary TEXT,
                        verification TEXT,
                        operator TEXT NOT NULL DEFAULT 'AtlasOps',
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ops_db_events (
                        id BIGSERIAL PRIMARY KEY,
                        ts TIMESTAMPTZ NOT NULL DEFAULT now(),
                        db_path TEXT NOT NULL DEFAULT '/Users/yasser/scripts/atlas.db',
                        table_name TEXT NOT NULL,
                        operation TEXT NOT NULL,
                        row_id TEXT,
                        ticker TEXT,
                        source_function TEXT,
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb
                    )
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ops_api_calls_ts ON ops_api_calls (ts DESC)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ops_api_calls_provider_ts ON ops_api_calls (provider, ts DESC)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ops_api_calls_status_ts ON ops_api_calls (http_status, ts DESC)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ops_api_calls_endpoint_ts ON ops_api_calls (endpoint, ts DESC)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ops_signals_ts ON ops_signals (ts DESC)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ops_signals_market_ticker ON ops_signals (market_date, ticker)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ops_signals_action_ts ON ops_signals (action, ts DESC)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ops_code_changes_ts ON ops_code_changes (ts DESC)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ops_code_changes_file_ts ON ops_code_changes (file_path, ts DESC)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ops_code_changes_work_order_ts ON ops_code_changes (work_order, ts DESC)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ops_db_events_ts ON ops_db_events (ts DESC)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ops_db_events_table_ts ON ops_db_events (table_name, ts DESC)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ops_db_events_operation_ts ON ops_db_events (operation, ts DESC)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ops_db_events_ticker_ts ON ops_db_events (ticker, ts DESC)")
        return True
    except Exception:
        return False


def log_api_call(provider, file, function, endpoint, http_status, latency_ms, ok, error=None, metadata=None):
    try:
        if psycopg is None:
            return False
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ops_api_calls
                    (provider, file_path, function_name, endpoint, http_status, latency_ms, ok, error, metadata)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (provider, file, function, endpoint, http_status, latency_ms, ok, error, _jsonb(metadata)),
                )
        return True
    except Exception:
        return False


def log_signal(ticker, action, reason, score=None, pillars=None, live=None, source=None,
               entry=None, stop=None, target=None, market_date=None, run_id=None, metadata=None):
    try:
        if psycopg is None:
            return False
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ops_signals
                    (market_date, run_id, ticker, action, reason, score, pillars, live, source, entry, stop, target, metadata)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (market_date, run_id, ticker, action, reason, score, pillars, live, source,
                     entry, stop, target, _jsonb(metadata)),
                )
        return True
    except Exception:
        return False


def log_code_change(work_order, file_path, backup_path, change_summary=None, verification=None,
                    operator='AtlasOps', metadata=None):
    try:
        if psycopg is None:
            return False
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ops_code_changes
                    (work_order, file_path, backup_path, change_summary, verification, operator, metadata)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (work_order, file_path, backup_path, change_summary, verification, operator, _jsonb(metadata)),
                )
        return True
    except Exception:
        return False


def log_db_event(table_name, operation, row_id=None, ticker=None, source_function=None, metadata=None):
    try:
        if psycopg is None:
            return False
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ops_db_events
                    (table_name, operation, row_id, ticker, source_function, metadata)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    """,
                    (table_name, operation, None if row_id is None else str(row_id), ticker,
                     source_function, _jsonb(metadata)),
                )
        return True
    except Exception:
        return False


def retention_cleanup(now=None):
    """Delete old audit rows. Returns True on success, False on failure."""
    if psycopg is None:
        return False
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ops_api_calls WHERE ts < now() - interval '90 days'")
                cur.execute("DELETE FROM ops_signals WHERE ts < now() - interval '90 days'")
                cur.execute("DELETE FROM ops_db_events WHERE ts < now() - interval '90 days'")
                cur.execute("DELETE FROM ops_code_changes WHERE ts < now() - interval '180 days'")
        return True
    except Exception:
        return False


def _cli():
    parser = argparse.ArgumentParser(description="Atlas PostgreSQL audit helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("setup-schema")
    sub.add_parser("retention")

    code = sub.add_parser("code-change")
    code.add_argument("--file", required=True)
    code.add_argument("--work-order", required=True)
    code.add_argument("--backup", required=True)
    code.add_argument("--summary", default=None)
    code.add_argument("--verification", default=None)
    code.add_argument("--operator", default="AtlasOps")

    args = parser.parse_args()
    if args.cmd == "setup-schema":
        ok = setup_schema()
        print("SETUP_SCHEMA_OK" if ok else "SETUP_SCHEMA_FAILED")
        return 0 if ok else 1
    if args.cmd == "retention":
        ok = retention_cleanup()
        print("RETENTION_OK" if ok else "RETENTION_FAILED")
        return 0 if ok else 1
    if args.cmd == "code-change":
        ok = log_code_change(
            args.work_order, args.file, args.backup,
            change_summary=args.summary, verification=args.verification,
            operator=args.operator,
            metadata={"cli": True, "logged_at": _dt.datetime.now(_dt.timezone.utc).isoformat()},
        )
        print("CODE_CHANGE_LOGGED" if ok else "CODE_CHANGE_LOG_FAILED")
        return 0 if ok else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
