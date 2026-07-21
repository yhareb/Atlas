import sqlite3
import json
import os
import re
import hashlib
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime

DB_PATH = os.environ.get("ATLAS_DB", "/Users/yasser/scripts/atlas.db")

try:
    from atlas_audit import log_db_event as _atlas_log_db_event
except Exception:
    _atlas_log_db_event = None


def _audit_db_event(table_name, operation, row_id=None, ticker=None, source_function=None, metadata=None):
    try:
        if not _atlas_log_db_event:
            return
        _atlas_log_db_event(
            table_name=table_name,
            operation=operation,
            row_id=None if row_id is None else str(row_id),
            ticker=(ticker or None),
            source_function=source_function,
            metadata=metadata,
        )
    except Exception:
        pass


def _post_commit_canonical_refresh(transition, trade_id=None, ticker=None):
    """Post-commit only; governed refresh failure is explicit and fail-closed."""
    if os.environ.get("ATLAS_CANONICAL_POST_COMMIT_REFRESH") != "1":
        return None
    from atlas_holding_state_truth_maintenance import governed_refresh_once
    return governed_refresh_once(
        reason="POST_COMMIT_" + transition,
        run_id="post-commit-%s-%s" % (transition.lower(), trade_id or "na"),
        trigger="REGISTRATION_EVENT",
        context={"transition": transition, "trade_id": trade_id, "ticker": ticker, "source": "atlas_db"},
    )


def _fetch_trade_rows(ids):
    """Read specific trade lots by id as dicts."""
    ids = [int(i) for i in (ids or []) if i is not None]
    if not ids:
        return []
    conn = get_connection()
    cursor = conn.cursor()
    placeholders = ",".join("?" for _ in ids)
    cursor.execute(f'''
        SELECT id, ticker, status, quantity, entry_price, entry_at,
               exit_price, exit_at, entry_fees, exit_fees,
               realized_pnl, realized_pnl_pct, parent_id,
               stop_loss, entry_atr14, risk_pct, target_price, manual_stop_lock, notes, updated_at
        FROM trades WHERE id IN ({placeholders})
    ''', ids)
    cols = [d[0] for d in cursor.description]
    rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
    conn.close()
    return rows


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def migrate_exit_policy_schema(conn=None):
    """Add ORDER #25 state/events without rewriting existing accounting rows."""
    owned = conn is None
    conn = conn or get_connection()
    conn.execute("""CREATE TABLE IF NOT EXISTS exit_policy_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL,
        trade_id INTEGER NOT NULL, lot_id INTEGER, stage TEXT,
        occurred_at TEXT NOT NULL, payload_json TEXT NOT NULL,
        idempotency_key TEXT NOT NULL UNIQUE, policy_version TEXT NOT NULL,
        FOREIGN KEY(trade_id) REFERENCES trades(id), FOREIGN KEY(lot_id) REFERENCES position_lots(id))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_exit_policy_trade ON exit_policy_events(trade_id,id)")
    if owned:
        conn.commit(); conn.close()


def get_exit_policy_projection(trade_id, current_quantity=None):
    """Derive current ladder state from events instead of nonexistent trade fields."""
    conn = get_connection(); migrate_exit_policy_schema(conn)
    rows = conn.execute("SELECT id,event_type,stage,payload_json,registration_id FROM exit_policy_events WHERE trade_id=? ORDER BY id", (int(trade_id),)).fetchall()
    conn.close()
    original = Decimal(str(current_quantity or 0)); completed = set(); reversed_regs=set()
    for _id, typ, stage, raw, reg in rows:
        if typ == "REVERSAL":
            try: reversed_regs.add(json.loads(raw or "{}").get("reverses_registration"))
            except Exception: pass
    for _id, typ, stage, raw, reg in rows:
        if typ == "REVERSAL" or reg in reversed_regs: continue
        try: payload = json.loads(raw or "{}")
        except Exception: payload = {}
        if typ in ("BROKER_PARTIAL_SELL_FILLED", "BROKER_SELL_FILLED"):
            original += Decimal(str(payload.get("filled_quantity") or 0))
        if typ == "EXIT_STAGE_COMPLETED" and stage:
            completed.add(str(stage))
    return {"original_quantity": str(original),
            "stage_1_state": "FILLED" if "STAGE_1" in completed else "PENDING",
            "stage_2_state": "FILLED" if "STAGE_2" in completed else "PENDING",
            "runner_state": "ACTIVE" if "STAGE_2" in completed else "INACTIVE",
            "event_count": len(rows)}


# --------------------------------------------------------------------------- #
# P0L-9 STAGING-ONLY additive dual-write bookkeeping layer.
#
# Legacy tables (trades, cash_ledger, account) remain the SOLE system of
# record. Every function below fires strictly AFTER the corresponding legacy
# write has already committed successfully. A failure anywhere in this layer
# is caught, logged, and swallowed -- it can NEVER raise into the legacy
# write path and can NEVER roll back a legacy commit. This is telemetry, not
# an authority.
#
# All money uses Decimal(str(x)) exclusively (never Decimal(x) on a float,
# never float arithmetic) before conversion to integer cents/micros/scaled
# quantity, per the P0L-3 precision design.
# --------------------------------------------------------------------------- #
from decimal import Decimal, ROUND_HALF_UP as _ROUND_HALF_UP

_BK_QUANTITY_SCALE = 100_000_000  # 10^8
_BK_PRICE_SCALE = 1_000_000       # 10^6


def _bk_to_cents(x):
    d = Decimal(str(x))
    return int((d * 100).to_integral_value(rounding=_ROUND_HALF_UP))


def _bk_to_quantity_scaled(x):
    d = Decimal(str(x))
    return int((d * _BK_QUANTITY_SCALE).to_integral_value(rounding=_ROUND_HALF_UP)), str(d)


def _bk_to_price_micros(x):
    d = Decimal(str(x))
    return int((d * _BK_PRICE_SCALE).to_integral_value(rounding=_ROUND_HALF_UP)), str(d)


def _bk_emit_event(cursor, event_type, ticker=None, lot_id=None, occurred_at=None,
                    effective_at=None, payload=None, source="dual_write",
                    prof_approved=0, idempotency_key=None, legacy_trades_id=None,
                    legacy_cash_ledger_id=None, supersedes_id=None,
                    linked_reversal_id=None, evidence_id=None):
    """Insert a portfolio_event_journal row. Idempotent: if idempotency_key
    already exists, returns the existing event's id instead of raising."""
    occurred_at = occurred_at or _now()
    effective_at = effective_at or occurred_at
    try:
        cursor.execute(
            """INSERT INTO portfolio_event_journal
               (event_type, ticker, lot_id, occurred_at, effective_at,
                payload_json, source, evidence_id, prof_approved,
                idempotency_key, legacy_trades_id, legacy_cash_ledger_id,
                supersedes_id, linked_reversal_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (event_type, ticker, lot_id, occurred_at, effective_at,
             json.dumps(payload or {}), source, evidence_id, prof_approved,
             idempotency_key, legacy_trades_id, legacy_cash_ledger_id,
             supersedes_id, linked_reversal_id),
        )
        return cursor.lastrowid, False
    except sqlite3.IntegrityError:
        # idempotency_key UNIQUE collision -- duplicate retry, not an error.
        row = cursor.execute(
            "SELECT id FROM portfolio_event_journal WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        if row:
            cursor.execute(
                """INSERT INTO portfolio_event_journal
                   (event_type, occurred_at, effective_at, payload_json, source, idempotency_key)
                   VALUES (?,?,?,?,?,NULL)""",
                ("IDEMPOTENT_DUPLICATE_REJECTED", _now(), _now(),
                 json.dumps({"original_event_id": row[0], "rejected_key": idempotency_key}),
                 "dual_write_idempotency_guard"),
            )
            return row[0], True
        raise


def _bk_emit_posting(cursor, event_id, account, posting_kind, amount_cents,
                      reason=None, legacy_cash_ledger_id=None):
    cursor.execute(
        """INSERT INTO ledger_postings
           (event_id, account, posting_kind, amount_cents, reason, legacy_cash_ledger_id)
           VALUES (?,?,?,?,?,?)""",
        (event_id, account, posting_kind, amount_cents, reason, legacy_cash_ledger_id),
    )


def _bk_emit_invariant(cursor, name, mode, subject_type, subject_id, passed, detail):
    cursor.execute(
        """INSERT INTO invariant_checks
           (invariant_name, mode, subject_type, subject_id, passed, detail)
           VALUES (?,?,?,?,?,?)""",
        (name, mode, subject_type, subject_id, 1 if passed else 0, detail),
    )


def _bk_safe(fn, *args, **kwargs):
    """Run a dual-write function in its OWN connection/transaction. Any
    failure is caught and logged; it never propagates and never touches the
    already-committed legacy write."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        fn(cur, *args, **kwargs)
        conn.commit()
        conn.close()
        return True
    except Exception as e:  # noqa: BLE001 -- bookkeeping must never break trading
        try:
            conn.rollback()
            conn.close()
        except Exception:
            pass
        print(f"[dual_write] non-fatal bookkeeping failure in {fn.__name__}: {e}")
        return False


def _dualwrite_buy_fill(cur, trade_id, ticker, quantity, entry_price,
                         cash_amount_signed, cash_ledger_id, broker_ref=None,
                         stop_loss=None, target_price=None):
    """event_type=BROKER_BUY_FILLED, 2-leg posting: CASH / POSITION:<TICKER>."""
    idem_key = f"live_trade_{trade_id}_buy"
    buy_cents = abs(_bk_to_cents(cash_amount_signed))
    ev_id, is_dup = _bk_emit_event(
        cur, "BROKER_BUY_FILLED", ticker=ticker,
        occurred_at=_now(), payload={"trade_id": trade_id, "quantity": str(quantity),
                                       "entry_price": str(entry_price), "broker_ref": broker_ref},
        source="dual_write_confirm_trade_fill", idempotency_key=idem_key,
        legacy_trades_id=trade_id, legacy_cash_ledger_id=cash_ledger_id,
    )
    if is_dup:
        return ev_id
    _bk_emit_posting(cur, ev_id, "CASH", "PRINCIPAL", -buy_cents,
                      f"Broker buy fill trade {trade_id}", legacy_cash_ledger_id=cash_ledger_id)
    _bk_emit_posting(cur, ev_id, f"POSITION:{ticker}", "PRINCIPAL", buy_cents,
                      f"Broker buy fill trade {trade_id}", legacy_cash_ledger_id=cash_ledger_id)
    qty_scaled, qty_text = _bk_to_quantity_scaled(quantity)
    price_micros, price_text = _bk_to_price_micros(entry_price)
    stop_micros, stop_text = (_bk_to_price_micros(stop_loss) if stop_loss is not None else (None, None))
    target_micros, target_text = (_bk_to_price_micros(target_price) if target_price is not None else (None, None))
    cur.execute(
        """INSERT INTO position_lots
           (ticker, status, quantity_text, quantity_scaled, quantity_scale,
            quantity_source, entry_price_micros, entry_price_decimal_text,
            entry_event_id, stop_loss_micros, stop_loss_decimal_text,
            target_price_micros, target_price_decimal_text,
            cost_basis_cents, cost_basis_source, legacy_trades_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (ticker, "OPEN", qty_text, qty_scaled, _BK_QUANTITY_SCALE,
         "broker_fill", price_micros, price_text,
         ev_id, stop_micros, stop_text,
         target_micros, target_text,
         buy_cents, "broker_amount", trade_id),
    )
    return ev_id


def _dualwrite_sell_fill(cur, trade_id, ticker, quantity, exit_price,
                          cash_amount, cash_ledger_id, buy_cost_basis_cents,
                          broker_ref=None):
    """event_type=BROKER_SELL_FILLED, 3-leg posting: CASH / POSITION / REALIZED_PNL."""
    idem_key = f"live_trade_{trade_id}_sell"
    sell_cents = _bk_to_cents(cash_amount)
    ev_id, is_dup = _bk_emit_event(
        cur, "BROKER_SELL_FILLED", ticker=ticker,
        occurred_at=_now(), payload={"trade_id": trade_id, "quantity": str(quantity),
                                       "exit_price": str(exit_price), "broker_ref": broker_ref},
        source="dual_write_close_trade_broker_confirmed", idempotency_key=idem_key,
        legacy_trades_id=trade_id, legacy_cash_ledger_id=cash_ledger_id,
    )
    if is_dup:
        return ev_id
    realized_cents = sell_cents - buy_cost_basis_cents
    _bk_emit_posting(cur, ev_id, "CASH", "PRINCIPAL", sell_cents,
                      f"Broker sell fill trade {trade_id}", legacy_cash_ledger_id=cash_ledger_id)
    _bk_emit_posting(cur, ev_id, f"POSITION:{ticker}", "PRINCIPAL", -buy_cost_basis_cents,
                      f"Broker sell fill trade {trade_id}", legacy_cash_ledger_id=cash_ledger_id)
    _bk_emit_posting(cur, ev_id, "REALIZED_PNL", "REALIZED_PNL", -realized_cents,
                      f"Realized P/L offset trade {trade_id}", legacy_cash_ledger_id=cash_ledger_id)
    exit_micros, exit_text = _bk_to_price_micros(exit_price)
    cur.execute(
        """UPDATE position_lots SET exit_price_micros=?, exit_price_decimal_text=?,
               exit_event_id=?, status='CLOSED', realized_pnl_cents=?, last_rebuilt_at=?
           WHERE legacy_trades_id=?""",
        (exit_micros, exit_text, ev_id, realized_cents, _now(), trade_id),
    )
    balance = cur.execute(
        "SELECT SUM(amount_cents) FROM ledger_postings WHERE event_id=?", (ev_id,)
    ).fetchone()[0]
    _bk_emit_invariant(cur, "ledger_postings_balance_zero", "WARN", "event", ev_id,
                        balance == 0, f"event {ev_id} postings sum to {balance} cents")
    return ev_id


def record_manual_cash_correction(amount, reason, prof_approved=1):
    """Legacy-first manual correction helper: writes cash_ledger via the
    existing _append_cash_ledger() path, commits, THEN (non-fatally) emits
    the MANUAL_CORRECTION dual-write event + balanced MANUAL_ADJUSTMENT
    postings. Mirrors the ad hoc P0K-2/P0K-3 pattern as a reusable function."""
    conn = get_connection()
    cursor = conn.cursor()
    balance_after = _append_cash_ledger(cursor, amount, reason)
    conn.commit()
    cash_ledger_id = cursor.execute(
        "SELECT id FROM cash_ledger ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    conn.close()

    def _emit(cur):
        idem_key = f"live_cash_{cash_ledger_id}_manual_adjustment"
        amt_cents = _bk_to_cents(amount)
        ev_id, is_dup = _bk_emit_event(
            cur, "MANUAL_CORRECTION", occurred_at=_now(),
            payload={"reason": reason, "cash_ledger_id": cash_ledger_id},
            source="dual_write_record_manual_cash_correction",
            prof_approved=1 if prof_approved else 0,
            idempotency_key=idem_key, legacy_cash_ledger_id=cash_ledger_id,
        )
        if is_dup:
            return
        _bk_emit_posting(cur, ev_id, "CASH", "MANUAL_ADJUSTMENT", amt_cents,
                          reason, legacy_cash_ledger_id=cash_ledger_id)
        _bk_emit_posting(cur, ev_id, "SUSPENSE:MANUAL_ADJUSTMENT", "MANUAL_ADJUSTMENT", -amt_cents,
                          "Manual adjustment offset", legacy_cash_ledger_id=cash_ledger_id)

    _bk_safe(_emit)
    return balance_after


def _dualwrite_valuation_mark(cur, ticker, price, price_source=None, is_fallback=None, legacy_trades_id=None):
    """Insert a valuation_marks row with EXPLICIT, conservative provenance.

    P0L-10 hardening: missing/unknown provenance must NEVER be silently
    treated as a live price. If the caller does not supply price_source,
    this function records 'stale_cache' (not 'live_provider') and forces
    is_fallback=1. If the caller supplies a price_source but omits
    is_fallback, is_fallback is derived from price_source itself
    (live_provider -> 0, anything else -> 1) rather than defaulting to 0.
    A caller-supplied price_source is always preserved verbatim.

    P0L-18 hardening: defensive lot-attribution guard. A valuation mark may
    ONLY attach to a position_lots row that (a) matches legacy_trades_id,
    (b) matches the given ticker (case-insensitive), AND (c) has
    status='OPEN'. This closes the P0L-17 bug where a caller-supplied
    legacy_trades_id that did not actually correspond to the intended
    ticker's currently-open lot (e.g. a stale/loop-index id that happened
    to collide with an unrelated CLOSED lot from a different ticker) could
    silently attach a live price mark to the wrong, already-closed position.
    If no lot satisfies all three conditions, the insert is skipped and a
    WARN invariant is logged instead -- never a best-effort/partial match.
    """
    if price_source is None:
        price_source = "stale_cache"
        is_fallback = 1
        provenance_missing = True
    else:
        provenance_missing = False
        if is_fallback is None:
            is_fallback = 0 if price_source == "live_provider" else 1
    is_fallback = 1 if is_fallback else 0

    price_micros, price_text = _bk_to_price_micros(price)
    ticker_norm = (ticker or "").upper().strip()
    lot_row = cur.execute(
        """SELECT id FROM position_lots
           WHERE legacy_trades_id=? AND UPPER(ticker)=? AND status='OPEN'
           ORDER BY id DESC LIMIT 1""",
        (legacy_trades_id, ticker_norm),
    ).fetchone()
    if lot_row is None:
        # P0L-18: no lot satisfies legacy_trades_id + ticker + status='OPEN'
        # together -- do NOT fall back to a legacy_trades_id-only or
        # ticker-only match, since either alone is exactly the class of
        # mismatch that caused the P0L-17 bug. Skip and log WARN instead.
        _bk_emit_invariant(
            cur, "valuation_mark_lot_mismatch", "WARN", "event", legacy_trades_id or 0, False,
            "No OPEN position_lots row found matching legacy_trades_id=%s AND ticker=%s "
            "-- valuation mark for price=%s skipped rather than risk attaching to an "
            "unrelated or closed lot (P0L-18 defensive guard)." % (legacy_trades_id, ticker_norm, price_text),
        )
        return None
    lot_id = lot_row[0]
    cur.execute(
        """INSERT INTO valuation_marks
           (lot_id, price_micros, price_decimal_text, price_source, is_fallback, marked_at)
           VALUES (?,?,?,?,?,?)""",
        (lot_id, price_micros, price_text, price_source, is_fallback, _now()),
    )
    mark_id = cur.lastrowid
    if is_fallback:
        detail = (
            f"valuation_mark id={mark_id} lot_id={lot_id} ticker={ticker_norm} used non-live "
            f"price_source='{price_source}'"
            + (" (provenance was MISSING from caller -- defaulted conservatively, never live_provider)"
               if provenance_missing else "")
        )
        _bk_emit_invariant(cur, "fallback_price_used", "WARN", "lot", lot_id, False, detail)
    return mark_id


# --------------------------------------------------------------------------- #
# Schema / migration
# --------------------------------------------------------------------------- #
def init_db():
    """Create tables if missing and run safe, idempotent migrations.

    IMPORTANT: This never drops or rewrites existing data. The original
    signals / positions / handoff tables are left exactly as they were. The
    new `trades` table is added, and any existing `positions` rows are
    backfilled into it so no historical trade is lost.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Signals table (every scan result) -- unchanged.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            ticker TEXT,
            signal TEXT,
            score INTEGER,
            rvol REAL,
            entry_price REAL,
            stop_loss REAL,
            max_loss_per_share REAL,
            atr REAL,
            trend_stack TEXT,
            relative_strength TEXT,
            volume TEXT,
            catalyst TEXT,
            warnings TEXT
        )
    ''')

    # Legacy `positions` table intentionally not created anymore.
    # `trades` is the authoritative open-position / P&L ledger.

    # Handoff table (latest state snapshot) -- unchanged.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS handoff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE,
            data TEXT
        )
    ''')

    # Pending pullback limits. One WAITING row per ticker survives restarts.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_pullbacks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'WAITING',
            score TEXT,
            signal TEXT,
            signal_json TEXT,
            armed_at DATETIME NOT NULL,
            expires_at DATE NOT NULL,
            ema10 REAL NOT NULL,
            trigger_price REAL NOT NULL,
            reference_price REAL NOT NULL,
            pct_over_ema REAL NOT NULL,
            filled_at DATETIME,
            expired_at DATETIME,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_pending_pullbacks_status ON pending_pullbacks(status, expires_at)"
    )

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ema_retry_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'WAITING',
            score TEXT,
            signal TEXT,
            signal_json TEXT,
            reason TEXT,
            first_seen_at DATETIME NOT NULL,
            last_seen_at DATETIME NOT NULL
        )
    ''')
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ema_retry_status ON ema_retry_candidates(status, last_seen_at)"
    )

    # NEW: trades table -- one row per LOT.
    #
    # A "lot" is a quantity of shares bought together. When you sell, we close
    # shares FIFO from the oldest open lot(s). A partial sell SPLITS a lot:
    # the sold shares become a CLOSED lot with realized P&L, and the remaining
    # shares stay OPEN as their own lot. This matches real brokerage accounting.
    #
    #   status        : 'OPEN' | 'CLOSED'
    #   quantity      : shares in THIS lot
    #   entry_price   : per-share buy price
    #   entry_at      : buy timestamp (UTC, 'YYYY-MM-DD HH:MM:SS')
    #   exit_price    : per-share sell price (NULL while open)
    #   exit_at       : sell timestamp (NULL while open)
    #   entry_fees    : fees attributed to the buy side of this lot
    #   exit_fees     : fees attributed to the sell side of this lot
    #   realized_pnl  : (exit_price-entry_price)*qty - entry_fees - exit_fees (NULL while open)
    #   realized_pnl_pct : realized_pnl / (entry_price*qty) * 100 (NULL while open)
    #   parent_id     : if this lot was split off another lot, the original lot id
    #   notes         : free text
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN',
            quantity REAL NOT NULL,
            entry_price REAL NOT NULL,
            entry_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            exit_price REAL,
            exit_at DATETIME,
            entry_fees REAL DEFAULT 0,
            exit_fees REAL DEFAULT 0,
            realized_pnl REAL,
            realized_pnl_pct REAL,
            parent_id INTEGER,
            notes TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_trades_ticker_status ON trades(ticker, status)"
    )

    cursor.execute("PRAGMA table_info(trades)")
    _trade_cols = {row[1] for row in cursor.fetchall()}
    for _col, _ddl in {
        "stop_loss": "ALTER TABLE trades ADD COLUMN stop_loss REAL",
        "entry_atr14": "ALTER TABLE trades ADD COLUMN entry_atr14 REAL",
        "risk_pct": "ALTER TABLE trades ADD COLUMN risk_pct REAL",
        "target_price": "ALTER TABLE trades ADD COLUMN target_price REAL",
        "broker_ref": "ALTER TABLE trades ADD COLUMN broker_ref TEXT DEFAULT NULL",
        "manual_stop_lock": "ALTER TABLE trades ADD COLUMN manual_stop_lock INTEGER DEFAULT 0",
    }.items():
        if _col not in _trade_cols:
            cursor.execute(_ddl)

    conn.commit()

    conn.close()


def _table_has_rows(cursor, table):
    cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,))
    if cursor.fetchone() is None:
        return False
    safe_table = '"' + str(table).replace('"', '""') + '"'
    cursor.execute(f"SELECT COUNT(*) FROM {safe_table}")
    return cursor.fetchone()[0] > 0


# --------------------------------------------------------------------------- #
# Signals (unchanged API)
# --------------------------------------------------------------------------- #
def get_max_signal_id():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(id) FROM signals")
    row = cursor.fetchone()
    conn.close()
    return int(row[0] or 0)


def log_signal(ticker, signal, score, rvol, entry_price, stop_loss, max_loss_per_share, atr, trend_stack, relative_strength, volume, catalyst, warnings):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO signals (ticker, signal, score, rvol, entry_price, stop_loss, max_loss_per_share, atr, trend_stack, relative_strength, volume, catalyst, warnings)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (ticker, signal, score, rvol, entry_price, stop_loss, max_loss_per_share, atr, trend_stack, relative_strength, volume, catalyst, warnings))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    _audit_db_event("signals", "INSERT", new_id, ticker, "log_signal")



# --------------------------------------------------------------------------- #
# Legacy position logger compatibility shim
# --------------------------------------------------------------------------- #
def log_position(ticker, action, price, quantity=0, status='OPEN'):
    """Compatibility shim: route legacy position writes to trades only.

    The legacy `positions` table is intentionally non-authoritative and should
    not be recreated or written. Open positions live in `trades`.
    """
    if str(action).upper() == "SELL":
        close_trade(ticker, price, quantity=quantity)
    else:
        open_trade(ticker, price, quantity=quantity, status=status)


# --------------------------------------------------------------------------- #
# Trades ledger (NEW — source of truth for P&L and history)
# --------------------------------------------------------------------------- #
def _now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def open_trade(ticker, entry_price, quantity, fees=0.0, notes=None, entry_at=None,
               stop_loss=None, risk_pct=None, target_price=None, status="PENDING_FILL",
               entry_atr14=None):
    """Open a new lot. Returns the new trade id."""
    ticker = (ticker or "").upper()
    quantity = int(quantity or 0)
    entry_price = float(entry_price)
    status = str(status or "PENDING_FILL").upper()
    if status not in ("PENDING_FILL", "OPEN"):
        raise ValueError("open_trade status must be PENDING_FILL or OPEN")
    if target_price is None and stop_loss is not None:
        risk = entry_price - float(stop_loss)
        if risk > 0:
            target_price = round(entry_price + (2 * risk), 2)
    if not ticker or quantity <= 0 or entry_price <= 0:
        raise ValueError("open_trade requires ticker, positive quantity, positive entry_price")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO trades (ticker, status, quantity, entry_price, entry_at,
                            entry_fees, stop_loss, entry_atr14, risk_pct, target_price, manual_stop_lock, notes, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (ticker, status, quantity, entry_price, entry_at or _now(), float(fees or 0),
          None if stop_loss is None else float(stop_loss),
          None if entry_atr14 is None else float(entry_atr14),
          None if risk_pct is None else float(risk_pct),
          None if target_price is None else float(target_price), 0, notes, _now()))
    trade_id = cursor.lastrowid
    conn.commit()
    conn.close()
    _audit_db_event("trades", "INSERT", trade_id, ticker, "open_trade")
    return trade_id


def _latest_cash_balance(cursor):
    row = cursor.execute("SELECT balance_after FROM cash_ledger ORDER BY id DESC LIMIT 1").fetchone()
    if row:
        return float(row[0])
    row = cursor.execute("SELECT starting_cash FROM account WHERE id = 1").fetchone()
    return float(row[0]) if row else 0.0


def _append_cash_ledger(cursor, amount, reason):
    amount = float(amount)
    balance_after = round(_latest_cash_balance(cursor) + amount, 2)
    cursor.execute(
        "INSERT INTO cash_ledger (amount, reason, balance_after) VALUES (?, ?, ?)",
        (amount, reason, balance_after),
    )
    ledger_id = cursor.lastrowid
    _audit_db_event("cash_ledger", "INSERT", ledger_id, None, "_append_cash_ledger", {"reason": reason, "amount": amount})
    return balance_after


def _planned_stop_from_notes(notes):
    """Extract the engine-planned stop from trade notes when present."""
    if not notes:
        return None
    match = re.search(r"(?:^|[;|,\s])stop\s+\$?([0-9]+(?:\.[0-9]+)?)", str(notes), re.IGNORECASE)
    if not match:
        return None
    try:
        return float(match.group(1))
    except Exception:
        return None


def _preserved_fill_stop(stop_loss, broker_price, notes):
    """Preserve/correct planned stop during broker fill confirmation.

    Fill confirmation may change quantity/entry/fees, but it must not turn the
    structured stop into the broker fill price. If an existing stop is missing
    or invalid at/above fill, recover the planned stop from the original notes.
    """
    planned = _planned_stop_from_notes(notes)
    current = None if stop_loss is None else float(stop_loss)
    price = float(broker_price)
    if planned is not None and planned < price and (current is None or current >= price):
        return planned
    return current


def confirm_trade_fill(trade_id, broker_qty, broker_price, broker_fees, broker_ref=None):
    """Flip a PENDING_FILL trade to OPEN using confirmed broker fill details."""
    trade_id = int(trade_id)
    broker_qty = float(broker_qty)
    broker_price = float(broker_price)
    broker_fees = float(broker_fees or 0.0)
    broker_ref = str(broker_ref or "").strip()
    if broker_qty <= 0 or broker_price <= 0:
        raise ValueError("confirm_trade_fill requires positive broker_qty and broker_price")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ticker, status, stop_loss, target_price, notes
        FROM trades WHERE id = ?
    """, (trade_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Trade id {trade_id} not found")
    ticker, status, stop_loss, target_price, notes = row
    if status != "PENDING_FILL":
        conn.close()
        raise ValueError(f"Trade id {trade_id} is {status}, not PENDING_FILL")
    stop_loss = _preserved_fill_stop(stop_loss, broker_price, notes)
    if target_price is None and stop_loss is not None:
        risk = broker_price - float(stop_loss)
        if risk > 0:
            target_price = round(broker_price + (2 * risk), 2)
    fill_note = f"Broker fill confirmed ref {broker_ref}" if broker_ref else "Broker fill confirmed"
    notes = (notes or "").rstrip()
    notes = f"{notes} | {fill_note}" if notes else fill_note
    cursor.execute("""
        UPDATE trades
        SET status='OPEN', quantity=?, entry_price=?, entry_fees=?,
            stop_loss=?, target_price=?, broker_ref=?, notes=?, updated_at=?
        WHERE id=? AND status='PENDING_FILL'
    """, (broker_qty, broker_price, broker_fees,
          None if stop_loss is None else float(stop_loss),
          None if target_price is None else float(target_price),
          broker_ref or None, notes, _now(), trade_id))
    if cursor.rowcount != 1:
        conn.rollback(); conn.close()
        raise RuntimeError(f"Failed to confirm trade id {trade_id}")
    debit = -(broker_qty * broker_price + broker_fees)
    _append_cash_ledger(cursor, debit, f"Broker fill {ticker} {broker_ref}: {broker_qty} sh @ {broker_price} plus fees {broker_fees}")
    conn.commit()
    _bk_cash_ledger_id = cursor.execute("SELECT id FROM cash_ledger ORDER BY id DESC LIMIT 1").fetchone()[0]
    conn.close()

    # P0L-9 STAGING dual-write: fires only after the legacy commit above.
    # Never fatal -- failures here cannot undo or block the legacy write.
    _bk_safe(_dualwrite_buy_fill, trade_id, ticker, broker_qty, broker_price,
             debit, _bk_cash_ledger_id, broker_ref=broker_ref,
             stop_loss=stop_loss, target_price=target_price)
    _audit_db_event("trades", "UPDATE", trade_id, ticker, "confirm_trade_fill")
    _post_commit_canonical_refresh("OPEN", trade_id, ticker)
    return _fetch_trade_rows([trade_id])[0]


def get_pending_fill_trades():
    """Return engine-approved trades awaiting manual broker confirmation."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, ticker, status, quantity, entry_price, entry_at,
               exit_price, exit_at, entry_fees, exit_fees,
               realized_pnl, realized_pnl_pct, parent_id,
               stop_loss, risk_pct, target_price, manual_stop_lock, notes, updated_at
        FROM trades WHERE status = 'PENDING_FILL'
        ORDER BY entry_at ASC, id ASC
    ''')
    cols = [d[0] for d in cursor.description]
    rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
    conn.close()
    return rows


def close_trade(ticker, exit_price, quantity=None, fees=0.0, exit_at=None):
    """Legacy FIFO close path for non-broker-backed rows only.

    Broker-backed positions must close through close_trade_broker_confirmed(),
    which requires confirmed sell evidence and posts the matching cash credit.
    Fractional quantities are preserved with Decimal arithmetic.
    """
    ticker = (ticker or "").upper()
    exit_price = float(exit_price)
    exit_at = exit_at or _now()

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, quantity, entry_price, entry_at, entry_fees, stop_loss, risk_pct, target_price
        FROM trades
        WHERE ticker = ? AND status = 'OPEN'
        ORDER BY entry_at ASC, id ASC
    ''', (ticker,))
    open_lots = cursor.fetchall()
    cursor.execute(
        "SELECT COUNT(*) FROM trades WHERE ticker=? AND status='OPEN' AND COALESCE(broker_ref,'') != ''",
        (ticker,),
    )
    if cursor.fetchone()[0]:
        conn.close()
        raise PermissionError(
            f"Broker-backed {ticker} requires close_trade_broker_confirmed() with confirmed sell evidence"
        )

    total_open = sum(Decimal(str(r[1])) for r in open_lots)
    if total_open == 0:
        conn.close()
        raise ValueError(f"No open shares of {ticker} to close.")

    shares_to_close = Decimal(str(quantity)) if quantity not in (None, 0) else total_open
    if shares_to_close > total_open:
        # Don't oversell; clamp to what's open and note it.
        shares_to_close = total_open

    total_sell_fee = float(fees or 0)
    closed_ids = []
    remaining = shares_to_close

    for lot_id, lot_qty, entry_price, entry_at, entry_fee, stop_loss, risk_pct, target_price in open_lots:
        if remaining <= 0:
            break
        lot_qty = Decimal(str(lot_qty))
        entry_price = Decimal(str(entry_price))
        entry_fee = Decimal(str(entry_fee or 0))

        take = min(remaining, lot_qty)
        # Proportional fees for the portion being closed.
        sell_fee_share = Decimal(str(total_sell_fee)) * (take / shares_to_close) if shares_to_close else Decimal("0")
        entry_fee_share = entry_fee * (take / lot_qty) if lot_qty else Decimal("0")

        gross = (Decimal(str(exit_price)) - entry_price) * take
        realized = gross - entry_fee_share - sell_fee_share
        cost_basis = entry_price * take
        realized_pct = (realized / cost_basis * Decimal("100")) if cost_basis else None

        if take == lot_qty:
            # Close the whole lot in place.
            cursor.execute('''
                UPDATE trades
                SET status='CLOSED', exit_price=?, exit_at=?, exit_fees=?,
                    entry_fees=?, realized_pnl=?, realized_pnl_pct=?, updated_at=?
                WHERE id=?
            ''', (exit_price, exit_at, float(sell_fee_share), float(entry_fee_share),
                  float(realized), None if realized_pct is None else float(realized_pct), _now(), lot_id))
            closed_ids.append(lot_id)
        else:
            # SPLIT: shrink the open lot, create a new CLOSED child lot.
            new_open_qty = lot_qty - take
            new_entry_fee = entry_fee - entry_fee_share
            cursor.execute('''
                UPDATE trades SET quantity=?, entry_fees=?, updated_at=? WHERE id=?
            ''', (float(new_open_qty), float(new_entry_fee), _now(), lot_id))
            cursor.execute('''
                INSERT INTO trades (ticker, status, quantity, entry_price, entry_at,
                                    exit_price, exit_at, entry_fees, exit_fees,
                                    realized_pnl, realized_pnl_pct, parent_id,
                                    stop_loss, risk_pct, target_price, manual_stop_lock, notes, updated_at)
                VALUES (?, 'CLOSED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            ''', (ticker, float(take), float(entry_price), entry_at, exit_price, exit_at,
                  float(entry_fee_share), float(sell_fee_share), float(realized),
                  None if realized_pct is None else float(realized_pct), lot_id,
                  stop_loss, risk_pct, target_price,
                  f"Partial close split from lot #{lot_id}.", _now()))
            closed_ids.append(cursor.lastrowid)

        remaining -= take

    # Lots affected by this sell: the CLOSED lots we created/closed, plus any
    # parent lots whose quantity shrank from a partial split (their ids are the
    # open-lot ids we iterated).
    affected_ids = list(closed_ids) + [int(r[0]) for r in open_lots]

    conn.commit()
    conn.close()
    for _closed_id in closed_ids:
        _audit_db_event("trades", "UPDATE", _closed_id, ticker, "close_trade")
    for _affected_id in set(affected_ids) - set(closed_ids):
        _audit_db_event("trades", "UPDATE", _affected_id, ticker, "close_trade")

    _post_commit_canonical_refresh("CLOSE", closed_ids[-1] if closed_ids else None, ticker)
    return closed_ids


def close_trade_broker_confirmed(ticker, trade_id, exit_price, quantity, fees, broker_ref,
                                 realized_pnl=None, realized_pnl_pct=None, exit_at=None, *, stage_id=None):
    """Atomically apply an exact-lot full or partial broker-confirmed eToro fill."""
    ticker, trade_id = (ticker or "").upper(), int(trade_id)
    px, qty, fee = Decimal(str(exit_price)), Decimal(str(quantity)), Decimal(str(fees or 0))
    broker_ref, exit_at = str(broker_ref or "").strip(), exit_at or _now()
    if not ticker or trade_id <= 0 or px <= 0 or qty <= 0 or not broker_ref:
        raise ValueError("ticker/trade/positive fill/broker_ref required")
    con = get_connection(); cur = con.cursor()
    try:
        migrate_exit_policy_schema(con)
        row = cur.execute("""SELECT ticker,status,quantity,entry_price,entry_at,entry_fees,stop_loss,
          entry_atr14,risk_pct,target_price,manual_stop_lock,notes FROM trades WHERE id=?""", (trade_id,)).fetchone()
        if not row: raise ValueError("trade not found")
        dbticker,status,openq,entry,entry_at,entryfees,stop,atr,risk,target,lock,notes=row
        openq, entry, total_entry_fee = Decimal(str(openq)), Decimal(str(entry)), Decimal(str(entryfees or 0))
        if dbticker.upper()!=ticker or status!='OPEN': raise ValueError("explicit OPEN trade/ticker mismatch")
        if qty > openq: raise ValueError("overfill")
        idem=f"broker_sell:{trade_id}:{stage_id or 'FULL'}:{broker_ref}"
        if cur.execute("SELECT 1 FROM exit_policy_events WHERE idempotency_key=?",(idem,)).fetchone(): raise ValueError("duplicate broker receipt")
        lots=cur.execute("SELECT id,quantity_scale,cost_basis_cents,entry_event_id,entry_price_micros,entry_price_decimal_text,stop_loss_micros,stop_loss_decimal_text,target_price_micros,target_price_decimal_text FROM position_lots WHERE legacy_trades_id=? AND status='OPEN'",(trade_id,)).fetchall()
        if len(lots)!=1: raise ValueError("position lot missing or ambiguous")
        lot=lots[0]; lot_id=lot[0]
        sold_entry_fee=total_entry_fee*qty/openq; remaining=openq-qty
        computed=(px-entry)*qty-sold_entry_fee-fee
        realized=Decimal(str(realized_pnl)) if realized_pnl is not None else computed
        rpct=Decimal(str(realized_pnl_pct)) if realized_pnl_pct is not None else realized/(entry*qty)*100
        note=((notes or "")+f" | Broker confirmed sell {broker_ref}").strip(" |")
        partial=remaining>0
        if partial:
            cur.execute("UPDATE trades SET quantity=?,entry_fees=?,updated_at=? WHERE id=? AND status='OPEN'",(float(remaining),float(total_entry_fee-sold_entry_fee),_now(),trade_id))
            cur.execute("""INSERT INTO trades(ticker,status,quantity,entry_price,entry_at,exit_price,exit_at,entry_fees,exit_fees,realized_pnl,realized_pnl_pct,parent_id,stop_loss,entry_atr14,risk_pct,target_price,broker_ref,manual_stop_lock,notes,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(ticker,'CLOSED',float(qty),float(entry),entry_at,float(px),exit_at,float(sold_entry_fee),float(fee),float(realized),float(rpct),trade_id,stop,atr,risk,target,broker_ref,lock,note,_now()))
            closed_id=cur.lastrowid
        else:
            cur.execute("UPDATE trades SET status='CLOSED',exit_price=?,exit_at=?,exit_fees=?,realized_pnl=?,realized_pnl_pct=?,broker_ref=?,notes=?,updated_at=? WHERE id=? AND status='OPEN'",(float(px),exit_at,float(fee),float(realized),float(rpct),broker_ref,note,_now(),trade_id)); closed_id=trade_id
        credit=(px*qty-fee).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
        _append_cash_ledger(cur,float(credit),f"Broker sell {ticker} {broker_ref}: {qty} @ {px}")
        cash_id=cur.execute("SELECT last_insert_rowid()").fetchone()[0]
        payload={"trade_id":trade_id,"closed_trade_id":closed_id,"stage":stage_id,"original_quantity":str(openq),"filled_quantity":str(qty),"remaining_quantity":str(remaining),"broker_ref":broker_ref}
        semantic="BROKER_PARTIAL_SELL_FILLED" if partial else "BROKER_SELL_FILLED"
        ev,_=_bk_emit_event(cur,"BROKER_SELL_FILLED",ticker=ticker,lot_id=lot_id,occurred_at=exit_at,payload={**payload,"semantic_event_type":semantic},source="atomic_exit_policy_fill",idempotency_key=idem,legacy_trades_id=closed_id,legacy_cash_ledger_id=cash_id)
        cashc,basis=_bk_to_cents(credit),_bk_to_cents(entry*qty+sold_entry_fee); pnl=cashc-basis
        _bk_emit_posting(cur,ev,"CASH","PRINCIPAL",cashc,"Confirmed sell",cash_id); _bk_emit_posting(cur,ev,f"POSITION:{ticker}","PRINCIPAL",-basis,"Cost basis",cash_id); _bk_emit_posting(cur,ev,"REALIZED_PNL","REALIZED_PNL",-pnl,"P/L",cash_id)
        if partial:
            scaled,text=_bk_to_quantity_scaled(remaining); cur.execute("UPDATE position_lots SET quantity_text=?,quantity_scaled=?,cost_basis_cents=?,last_rebuilt_at=? WHERE id=?",(text,scaled,lot[2]-basis,_now(),lot_id))
            sscaled,stext=_bk_to_quantity_scaled(qty); pmic,ptext=_bk_to_price_micros(px)
            cur.execute("""INSERT INTO position_lots(ticker,status,quantity_text,quantity_scaled,quantity_scale,quantity_source,entry_price_micros,entry_price_decimal_text,entry_event_id,exit_price_micros,exit_price_decimal_text,exit_event_id,stop_loss_micros,stop_loss_decimal_text,target_price_micros,target_price_decimal_text,cost_basis_cents,cost_basis_source,realized_pnl_cents,currency,legacy_trades_id,last_rebuilt_at) VALUES(?,'CLOSED',?,?,?,'broker_fill',?,?,?,?,?,?,?,?,?,?,?,?,?,'USD',?,?)""",(ticker,stext,sscaled,lot[1],lot[4],lot[5],lot[3],pmic,ptext,ev,lot[6],lot[7],lot[8],lot[9],basis,'broker_amount',pnl,closed_id,_now()))
        else: cur.execute("UPDATE position_lots SET status='CLOSED',exit_event_id=?,realized_pnl_cents=?,last_rebuilt_at=? WHERE id=?",(ev,pnl,_now(),lot_id))
        cur.execute("INSERT INTO exit_policy_events(event_type,trade_id,lot_id,stage,occurred_at,payload_json,idempotency_key,policy_version) VALUES(?,?,?,?,?,?,?,'atlas_exit_policy.v1')",(semantic,trade_id,lot_id,stage_id,exit_at,json.dumps(payload,sort_keys=True),idem))
        if stage_id: cur.execute("INSERT INTO exit_policy_events(event_type,trade_id,lot_id,stage,occurred_at,payload_json,idempotency_key,policy_version) VALUES('EXIT_STAGE_COMPLETED',?,?,?,?,?,?,'atlas_exit_policy.v1')",(trade_id,lot_id,stage_id,exit_at,json.dumps(payload,sort_keys=True),f"completed:{idem}"))
        con.commit()
    except Exception:
        con.rollback(); con.close(); raise
    con.close()
    _post_commit_canonical_refresh("CLOSE", closed_id, ticker)
    return {"parent":_fetch_trade_rows([trade_id])[0],"closed":_fetch_trade_rows([closed_id])[0],"partial":partial,"event_id":ev,"remaining_quantity":str(remaining)}


def get_trades(status=None, limit=500):
    """Return trade lots, newest activity first. Optional status filter."""
    conn = get_connection()
    cursor = conn.cursor()
    if status:
        cursor.execute('''
            SELECT id, ticker, status, quantity, entry_price, entry_at,
                   exit_price, exit_at, entry_fees, exit_fees,
                   realized_pnl, realized_pnl_pct, parent_id,
                   stop_loss, entry_atr14, risk_pct, target_price, manual_stop_lock, notes, updated_at
            FROM trades WHERE status = ?
            ORDER BY COALESCE(exit_at, entry_at) DESC, id DESC LIMIT ?
        ''', (status.upper(), limit))
    else:
        cursor.execute('''
            SELECT id, ticker, status, quantity, entry_price, entry_at,
                   exit_price, exit_at, entry_fees, exit_fees,
                   realized_pnl, realized_pnl_pct, parent_id,
                   stop_loss, entry_atr14, risk_pct, target_price, manual_stop_lock, notes, updated_at
            FROM trades
            ORDER BY COALESCE(exit_at, entry_at) DESC, id DESC LIMIT ?
        ''', (limit,))
    cols = [d[0] for d in cursor.description]
    rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
    conn.close()
    return rows


def get_pending_broker_confirmation_trades(limit=500):
    """P0M-1 READ-ONLY report helper.

    Returns CLOSED trades where Atlas detected a sell/stop-hit but the
    broker-side fill has not yet been confirmed and no matching
    cash_ledger sell credit has been posted. Used only by report
    builders (atlas_intraday.py / atlas_eod_positions.py) to surface a
    visibility gap -- does NOT change trade status lifecycle, does NOT
    write to the DB, and is not consulted by any strategy/TFE/stop/
    target/exit logic.

    Filter (per P0M-1 design, both required):
      - broker_ref IS NOT NULL  -- excludes rows that never had a real
        broker-confirmed entry (e.g. AAPL/PBXT/IBXT backfill artifacts)
      - entry_price != exit_price -- excludes zero-duration/zero-move
        backfill artifacts (same defensive signal as above, belt & suspenders)

    A trade is "pending broker confirmation" if, after passing the
    filter above, it has no BROKER_SELL_FILLED event in
    portfolio_event_journal AND no cash_ledger row whose reason text
    references a "Broker sell <TICKER>" credit for that trade.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, ticker, status, quantity, entry_price, entry_at,
               exit_price, exit_at, entry_fees, exit_fees,
               realized_pnl, realized_pnl_pct, parent_id,
               stop_loss, risk_pct, target_price, manual_stop_lock, notes,
               updated_at, broker_ref
        FROM trades
        WHERE status = 'CLOSED'
          AND broker_ref IS NOT NULL
          AND broker_ref != ''
          AND entry_price IS NOT NULL
          AND exit_price IS NOT NULL
          AND entry_price != exit_price
        ORDER BY COALESCE(exit_at, entry_at) DESC, id DESC
        LIMIT ?
    ''', (limit,))
    cols = [d[0] for d in cursor.description]
    candidates = [dict(zip(cols, r)) for r in cursor.fetchall()]

    if not candidates:
        conn.close()
        return []

    ids = [c["id"] for c in candidates]
    placeholders = ",".join("?" for _ in ids)

    confirmed_ids = set()
    try:
        cursor.execute(f'''
            SELECT DISTINCT legacy_trades_id FROM portfolio_event_journal
            WHERE event_type = 'BROKER_SELL_FILLED'
              AND legacy_trades_id IN ({placeholders})
        ''', ids)
        confirmed_ids.update(r[0] for r in cursor.fetchall() if r[0] is not None)
    except Exception:
        pass  # bookkeeping tables may be absent in older DBs; report degrades to trades-only check

    tickers = list({str(c["ticker"] or "").upper() for c in candidates if c.get("ticker")})
    credited_tickers = set()
    if tickers:
        like_clauses = " OR ".join(["reason LIKE ?" for _ in tickers])
        like_params = [f"Broker sell {t}%" for t in tickers]
        try:
            cursor.execute(f"SELECT DISTINCT reason FROM cash_ledger WHERE {like_clauses}", like_params)
            for (reason,) in cursor.fetchall():
                for t in tickers:
                    if reason and reason.upper().startswith(f"BROKER SELL {t}"):
                        credited_tickers.add(t)
        except Exception:
            pass

    conn.close()

    pending = []
    for c in candidates:
        tk = str(c.get("ticker") or "").upper()
        if c["id"] in confirmed_ids:
            continue
        if tk in credited_tickers:
            continue
        pending.append(c)
    return pending


def update_trade_stop(trade_id, stop_loss):
    """Raise/persist the structured stop on one trade lot. Never lowers it."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT entry_price, stop_loss, target_price FROM trades WHERE id=? AND status='OPEN'", (int(trade_id),))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return 0
    entry_price, current, target_price = row
    new_stop = float(stop_loss)
    if current is not None and float(current) >= new_stop:
        conn.close()
        return 0
    computed_target = None
    if target_price is None and current is not None:
        risk = float(entry_price) - float(current)
        if risk > 0:
            computed_target = round(float(entry_price) + (2 * risk), 2)
    if computed_target is None:
        cursor.execute("UPDATE trades SET stop_loss=?, updated_at=? WHERE id=? AND status='OPEN'", (new_stop, _now(), int(trade_id)))
    else:
        cursor.execute("UPDATE trades SET stop_loss=?, target_price=?, updated_at=? WHERE id=? AND status='OPEN'", (new_stop, computed_target, _now(), int(trade_id)))
    conn.commit()
    changed = cursor.rowcount
    conn.close()
    if changed:
        _audit_db_event("trades", "UPDATE", int(trade_id), None, "update_trade_stop")
    return changed


def update_trade_stop_with_event(trade_id, stop_loss, *, trail_reason, cycle_id,
                                 calculation_timestamp=None):
    """Atomically raise an OPEN lot stop and append its authorizing event."""
    allowed = {"PEAK_1R_BREAKEVEN", "PEAK_2R_LOCK_1R", "REGIME_RISK_OFF_BREAKEVEN", "BREAKEVEN_STOP_RAISED", "RUNNER_STOP_RAISED"}
    if trail_reason not in allowed:
        raise ValueError("unapproved trailing-stop reason")
    conn = get_connection(); cursor = conn.cursor()
    ticker = None
    try:
        cursor.execute("BEGIN IMMEDIATE")
        row = cursor.execute("SELECT ticker,entry_price,stop_loss FROM trades WHERE id=? AND status='OPEN'", (int(trade_id),)).fetchone()
        if not row:
            conn.rollback(); return 0
        ticker, entry_price, old_stop = row
        new_stop = round(float(stop_loss), 2)
        if old_stop is None or round(float(old_stop), 2) >= new_stop:
            conn.rollback(); return 0
        stamp = calculation_timestamp or _now()
        payload = {"trade_id": int(trade_id), "ticker": str(ticker).upper(),
                   "old_stop": round(float(old_stop), 2), "new_stop": new_stop,
                   "trail_reason": trail_reason, "entry_price": float(entry_price),
                   "calculation_timestamp": stamp, "cycle_id": str(cycle_id)}
        material = f"{trade_id}|{payload['old_stop']:.2f}|{new_stop:.2f}|{trail_reason}|{cycle_id}"
        key = "trailing-stop:" + hashlib.sha256(material.encode()).hexdigest()
        cursor.execute("UPDATE trades SET stop_loss=?,updated_at=? WHERE id=? AND status='OPEN' AND stop_loss=?",
                       (new_stop, _now(), int(trade_id), old_stop))
        if cursor.rowcount != 1:
            raise RuntimeError("concurrent stop update")
        _bk_emit_event(cursor, "MANUAL_CORRECTION", ticker=ticker, occurred_at=stamp,
                       effective_at=stamp, payload=payload,
                       source="atlas_portfolio.py:trailing_stop", prof_approved=0,
                       idempotency_key=key, legacy_trades_id=int(trade_id))
        conn.commit()
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()
    _audit_db_event("trades", "UPDATE", int(trade_id), ticker, "update_trade_stop_with_event")
    return 1


def set_manual_stop_lock(trade_id, locked=True):
    """Set or clear manual stop-lock on one OPEN trade lot."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE trades SET manual_stop_lock=?, updated_at=? WHERE id=? AND status='OPEN'",
        (1 if locked else 0, _now(), int(trade_id)),
    )
    conn.commit()
    changed = cursor.rowcount
    conn.close()
    if changed:
        _audit_db_event("trades", "UPDATE", int(trade_id), None, "set_manual_stop_lock")
    return changed


def get_trade(trade_id):
    rows = _fetch_trade_rows([int(trade_id)])
    return rows[0] if rows else None


def get_realized_pnl():
    """Aggregate realized P&L across all CLOSED lots."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COALESCE(SUM(realized_pnl), 0),
               COUNT(*),
               COALESCE(SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END), 0)
        FROM trades WHERE status = 'CLOSED' AND realized_pnl IS NOT NULL
    ''')
    total, closed_count, winners = cursor.fetchone()
    conn.close()
    win_rate = (winners / closed_count * 100) if closed_count else 0
    return {
        "realized_pnl": round(total, 2),
        "closed_trades": closed_count,
        "winners": winners,
        "win_rate_pct": round(win_rate, 1),
    }


def get_open_positions():
    """Backward-compatible: open positions for the /positions command.

    Now sourced from the trades ledger so it reflects splits correctly, with
    the same dict shape the existing SKILL.md command expects.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT ticker, quantity, entry_price, entry_at, stop_loss, risk_pct, target_price, manual_stop_lock
        FROM trades WHERE status = 'OPEN'
        ORDER BY entry_at ASC, id ASC
    ''')
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "ticker": r[0],
            "action": "BUY",
            "price": r[2],
            "quantity": r[1],
            "timestamp": r[3],
            "stop_loss": r[4],
            "risk_pct": r[5],
            "target_price": r[6],
            "manual_stop_lock": int(r[7] or 0),
        }
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# Pending pullback limits (restart-safe entry state)
# --------------------------------------------------------------------------- #
def _pending_row_to_dict(row):
    if not row:
        return None
    keys = [
        "id", "ticker", "status", "score", "signal", "signal_json", "armed_at",
        "expires_at", "ema10", "trigger_price", "reference_price", "pct_over_ema",
        "filled_at", "expired_at", "updated_at",
    ]
    d = dict(zip(keys, row))
    try:
        d["signal_result"] = json.loads(d.get("signal_json") or "{}")
    except Exception:
        d["signal_result"] = {}
    return d


def upsert_pending_pullback(ticker, score, signal, signal_result, ema10, trigger_price,
                            reference_price, pct_over_ema, armed_at=None, expires_at=None):
    ticker = (ticker or "").upper()
    if not ticker:
        raise ValueError("ticker required")
    armed_at = armed_at or _now()
    if not expires_at:
        raise ValueError("expires_at required")
    payload = json.dumps(signal_result or {}, default=str)
    conn = get_connection()
    cursor = conn.cursor()
    existing_id = cursor.execute("SELECT id FROM pending_pullbacks WHERE ticker=?", (ticker,)).fetchone()
    cursor.execute("""
        INSERT INTO pending_pullbacks
            (ticker, status, score, signal, signal_json, armed_at, expires_at,
             ema10, trigger_price, reference_price, pct_over_ema, updated_at)
        VALUES (?, 'WAITING', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticker) DO UPDATE SET
            status='WAITING', score=excluded.score, signal=excluded.signal,
            signal_json=excluded.signal_json, armed_at=excluded.armed_at,
            expires_at=excluded.expires_at, ema10=excluded.ema10,
            trigger_price=excluded.trigger_price,
            reference_price=excluded.reference_price,
            pct_over_ema=excluded.pct_over_ema,
            filled_at=NULL, expired_at=NULL, updated_at=excluded.updated_at
    """, (ticker, str(score or ""), str(signal or ""), payload, armed_at, expires_at,
          float(ema10), float(trigger_price), float(reference_price), float(pct_over_ema), _now()))
    pending_id = cursor.execute("SELECT id FROM pending_pullbacks WHERE ticker=?", (ticker,)).fetchone()
    conn.commit()
    conn.close()
    _audit_db_event("pending_pullbacks", "UPDATE" if existing_id else "INSERT", pending_id[0] if pending_id else None, ticker, "upsert_pending_pullback")
    return get_pending_pullback(ticker)


def get_pending_pullback(ticker, include_inactive=False):
    ticker = (ticker or "").upper()
    conn = get_connection()
    cursor = conn.cursor()
    where = "ticker = ?" if include_inactive else "ticker = ? AND status = 'WAITING'"
    cursor.execute(f"""
        SELECT id, ticker, status, score, signal, signal_json, armed_at, expires_at,
               ema10, trigger_price, reference_price, pct_over_ema,
               filled_at, expired_at, updated_at
        FROM pending_pullbacks WHERE {where}
        ORDER BY updated_at DESC LIMIT 1
    """, (ticker,))
    row = cursor.fetchone()
    conn.close()
    return _pending_row_to_dict(row)


def get_pending_pullbacks(status="WAITING"):
    conn = get_connection()
    cursor = conn.cursor()
    if status:
        cursor.execute("""
            SELECT id, ticker, status, score, signal, signal_json, armed_at, expires_at,
                   ema10, trigger_price, reference_price, pct_over_ema,
                   filled_at, expired_at, updated_at
            FROM pending_pullbacks WHERE status = ?
            ORDER BY armed_at ASC, id ASC
        """, (status,))
    else:
        cursor.execute("""
            SELECT id, ticker, status, score, signal, signal_json, armed_at, expires_at,
                   ema10, trigger_price, reference_price, pct_over_ema,
                   filled_at, expired_at, updated_at
            FROM pending_pullbacks
            ORDER BY updated_at DESC, id DESC
        """)
    rows = cursor.fetchall()
    conn.close()
    return [_pending_row_to_dict(r) for r in rows]


def get_latest_signal(ticker, as_of=None):
    """
    P0O-17: read-only helper for pullback fill-time revalidation.
    Returns the freshest `signals` row for `ticker` (optionally as of a given
    timestamp string) as a dict, or None if no row exists. Pure read, no
    side effects, no writes. Used exclusively to re-validate a pending
    pullback's live signal state at fill time -- does not touch, replace,
    or duplicate any existing signal-scoring logic.
    """
    ticker = (ticker or "").upper()
    conn = get_connection()
    cursor = conn.cursor()
    if as_of:
        cursor.execute("""
            SELECT id, timestamp, ticker, signal, score, rvol, entry_price,
                   stop_loss, max_loss_per_share, atr, trend_stack,
                   relative_strength, volume, catalyst, warnings
            FROM signals
            WHERE ticker = ? AND timestamp <= ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (ticker, as_of))
    else:
        cursor.execute("""
            SELECT id, timestamp, ticker, signal, score, rvol, entry_price,
                   stop_loss, max_loss_per_share, atr, trend_stack,
                   relative_strength, volume, catalyst, warnings
            FROM signals
            WHERE ticker = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (ticker,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    cols = ["id", "timestamp", "ticker", "signal", "score", "rvol", "entry_price",
            "stop_loss", "max_loss_per_share", "atr", "trend_stack",
            "relative_strength", "volume", "catalyst", "warnings"]
    return dict(zip(cols, row))


def mark_pending_pullback_filled(ticker):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE pending_pullbacks
        SET status='FILLED', filled_at=?, updated_at=?
        WHERE ticker=? AND status='WAITING'
    """, (_now(), _now(), (ticker or "").upper()))
    conn.commit()
    changed = cursor.rowcount
    conn.close()
    if changed:
        _audit_db_event("pending_pullbacks", "UPDATE", None, (ticker or "").upper(), "mark_pending_pullback_filled")
    return changed


def expire_pending_pullback(ticker):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE pending_pullbacks
        SET status='EXPIRED', expired_at=?, updated_at=?
        WHERE ticker=? AND status='WAITING'
    """, (_now(), _now(), (ticker or "").upper()))
    conn.commit()
    changed = cursor.rowcount
    conn.close()
    if changed:
        _audit_db_event("pending_pullbacks", "UPDATE", None, (ticker or "").upper(), "expire_pending_pullback")
    return changed


def delete_pending_pullback(ticker):
    conn = get_connection()
    cursor = conn.cursor()
    _ticker = (ticker or "").upper()
    cursor.execute("DELETE FROM pending_pullbacks WHERE ticker=?", (_ticker,))
    conn.commit()
    changed = cursor.rowcount
    conn.close()
    if changed:
        _audit_db_event("pending_pullbacks", "DELETE", None, _ticker, "delete_pending_pullback")
    return changed


# --------------------------------------------------------------------------- #
# EMA retry candidates (restart-safe insufficient-EMA state)
# --------------------------------------------------------------------------- #
def upsert_ema_retry(ticker, score, signal, signal_result, reason):
    ticker = (ticker or "").upper()
    if not ticker:
        raise ValueError("ticker required")
    payload = json.dumps(signal_result or {}, default=str)
    now = _now()
    conn = get_connection()
    cursor = conn.cursor()
    existing_id = cursor.execute("SELECT id FROM ema_retry_candidates WHERE ticker=?", (ticker,)).fetchone()
    cursor.execute("""
        INSERT INTO ema_retry_candidates
            (ticker, status, score, signal, signal_json, reason, first_seen_at, last_seen_at)
        VALUES (?, 'WAITING', ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticker) DO UPDATE SET
            status='WAITING', score=excluded.score, signal=excluded.signal,
            signal_json=excluded.signal_json, reason=excluded.reason, last_seen_at=excluded.last_seen_at
    """, (ticker, str(score or ""), str(signal or ""), payload, str(reason or ""), now, now))
    retry_id = cursor.execute("SELECT id FROM ema_retry_candidates WHERE ticker=?", (ticker,)).fetchone()
    conn.commit()
    conn.close()
    _audit_db_event("ema_retry_candidates", "UPDATE" if existing_id else "INSERT", retry_id[0] if retry_id else None, ticker, "upsert_ema_retry")
    return get_ema_retry_candidates(ticker=ticker)[0]


def get_ema_retry_candidates(status="WAITING", ticker=None):
    conn = get_connection()
    cursor = conn.cursor()
    if ticker:
        cursor.execute("""
            SELECT id, ticker, status, score, signal, signal_json, reason, first_seen_at, last_seen_at
            FROM ema_retry_candidates WHERE ticker=? AND (? IS NULL OR status=?)
            ORDER BY last_seen_at DESC
        """, ((ticker or "").upper(), status, status))
    elif status:
        cursor.execute("""
            SELECT id, ticker, status, score, signal, signal_json, reason, first_seen_at, last_seen_at
            FROM ema_retry_candidates WHERE status=? ORDER BY first_seen_at ASC, id ASC
        """, (status,))
    else:
        cursor.execute("""
            SELECT id, ticker, status, score, signal, signal_json, reason, first_seen_at, last_seen_at
            FROM ema_retry_candidates ORDER BY last_seen_at DESC, id DESC
        """)
    rows = cursor.fetchall()
    conn.close()
    keys = ["id", "ticker", "status", "score", "signal", "signal_json", "reason", "first_seen_at", "last_seen_at"]
    out = []
    for row in rows:
        d = dict(zip(keys, row))
        try:
            d["signal_result"] = json.loads(d.get("signal_json") or "{}")
        except Exception:
            d["signal_result"] = {}
        out.append(d)
    return out


def delete_ema_retry(ticker):
    conn = get_connection()
    cursor = conn.cursor()
    _ticker = (ticker or "").upper()
    cursor.execute("DELETE FROM ema_retry_candidates WHERE ticker=?", (_ticker,))
    conn.commit()
    changed = cursor.rowcount
    conn.close()
    if changed:
        _audit_db_event("ema_retry_candidates", "DELETE", None, _ticker, "delete_ema_retry")
    return changed


# --------------------------------------------------------------------------- #
# Handoff (unchanged API)
# --------------------------------------------------------------------------- #
def update_handoff(date_str, data_dict):
    conn = get_connection()
    cursor = conn.cursor()
    data_json = json.dumps(data_dict)
    existing_id = cursor.execute("SELECT id FROM handoff WHERE date=?", (date_str,)).fetchone()
    cursor.execute('''
        INSERT INTO handoff (date, data)
        VALUES (?, ?)
        ON CONFLICT(date) DO UPDATE SET data=excluded.data
    ''', (date_str, data_json))
    handoff_id = cursor.execute("SELECT id FROM handoff WHERE date=?", (date_str,)).fetchone()
    conn.commit()
    conn.close()
    _audit_db_event("handoff", "UPDATE" if existing_id else "INSERT", handoff_id[0] if handoff_id else None, None, "update_handoff", {"date": date_str})


def get_handoff(date_str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT data FROM handoff WHERE date = ?', (date_str,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return None


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")


# --------------------------------------------------------------------------- #
# STAGED Professor hold override lifecycle helpers (P0 override stage).
# --------------------------------------------------------------------------- #
def ensure_manual_override_schema(conn=None):
    own = conn is None
    conn = conn or get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS manual_trade_overrides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            override_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            reason TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT DEFAULT 'Prof',
            deactivated_at DATETIME,
            deactivated_reason TEXT,
            source_message TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_manual_trade_overrides_active ON manual_trade_overrides(trade_id, ticker, override_type, status)")
    if own:
        conn.commit(); conn.close()


def has_active_manual_hold_override(trade_id=None, ticker=None):
    conn = get_connection(); ensure_manual_override_schema(conn); cur = conn.cursor()
    params=[]
    where=["override_type='PROFESSOR_HOLD_OVERRIDE'", "status='ACTIVE'", "deactivated_at IS NULL"]
    if trade_id is not None:
        where.append("trade_id=?"); params.append(int(trade_id))
    if ticker:
        where.append("upper(ticker)=?"); params.append(str(ticker).upper())
    if trade_id is None and not ticker:
        conn.close(); return False
    cur.execute(f"SELECT 1 FROM manual_trade_overrides WHERE {' AND '.join(where)} LIMIT 1", params)
    ok = cur.fetchone() is not None
    conn.close(); return ok


def get_active_manual_hold_overrides():
    conn = get_connection(); ensure_manual_override_schema(conn); cur = conn.cursor()
    cur.execute("SELECT * FROM manual_trade_overrides WHERE override_type='PROFESSOR_HOLD_OVERRIDE' AND status='ACTIVE' AND deactivated_at IS NULL ORDER BY created_at DESC, id DESC")
    cols=[d[0] for d in cur.description]
    rows=[dict(zip(cols,r)) for r in cur.fetchall()]
    conn.close(); return rows


def create_manual_hold_override(trade_id, ticker, reason=None, source_message=None):
    conn = get_connection(); ensure_manual_override_schema(conn); cur = conn.cursor()
    ticker=str(ticker or '').upper(); trade_id=int(trade_id)
    cur.execute("UPDATE manual_trade_overrides SET status='INACTIVE', deactivated_at=CURRENT_TIMESTAMP, deactivated_reason='superseded by new active override' WHERE trade_id=? AND override_type='PROFESSOR_HOLD_OVERRIDE' AND status='ACTIVE'", (trade_id,))
    cur.execute("INSERT INTO manual_trade_overrides (trade_id,ticker,override_type,status,reason,created_by,source_message) VALUES (?,?,'PROFESSOR_HOLD_OVERRIDE','ACTIVE',?,'Prof',?)", (trade_id,ticker,reason,source_message))
    oid=cur.lastrowid
    try:
        _bk_emit_event(cur, 'PROFESSOR_HOLD_OVERRIDE_ACTIVE', ticker=ticker, occurred_at=_now(), effective_at=_now(), payload={'trade_id': trade_id, 'reason': reason, 'source_message': source_message}, source='prof_manual_override', prof_approved=1, idempotency_key=f'prof_hold_override_{ticker}_{trade_id}_{oid}', legacy_trades_id=trade_id)
    except Exception:
        pass
    conn.commit(); conn.close(); return oid


def deactivate_manual_hold_override(trade_id=None, ticker=None, reason=None):
    conn = get_connection(); ensure_manual_override_schema(conn); cur = conn.cursor()
    params=[]; where=["override_type='PROFESSOR_HOLD_OVERRIDE'", "status='ACTIVE'", "deactivated_at IS NULL"]
    if trade_id is not None:
        where.append('trade_id=?'); params.append(int(trade_id))
    if ticker:
        where.append('upper(ticker)=?'); params.append(str(ticker).upper())
    cur.execute(f"UPDATE manual_trade_overrides SET status='INACTIVE', deactivated_at=CURRENT_TIMESTAMP, deactivated_reason=? WHERE {' AND '.join(where)}", [reason]+params)
    changed=cur.rowcount
    conn.commit(); conn.close(); return changed


def get_pending_broker_confirmation_trades(limit=500):
    """Staged lifecycle-safe helper: pending requires BROKER_SELL_SUBMITTED, not local CLOSED alone."""
    conn = get_connection(); ensure_manual_override_schema(conn); cur = conn.cursor()
    cur.execute("""
        SELECT id, ticker, status, quantity, entry_price, entry_at,
               exit_price, exit_at, entry_fees, exit_fees,
               realized_pnl, realized_pnl_pct, parent_id,
               stop_loss, risk_pct, target_price, manual_stop_lock, notes,
               updated_at, broker_ref
        FROM trades
        WHERE broker_ref IS NOT NULL AND broker_ref != ''
          AND entry_price IS NOT NULL AND exit_price IS NOT NULL AND entry_price != exit_price
        ORDER BY COALESCE(exit_at, entry_at) DESC, id DESC LIMIT ?
    """, (limit,))
    cols=[d[0] for d in cur.description]
    candidates=[dict(zip(cols,r)) for r in cur.fetchall()]
    if not candidates:
        conn.close(); return []
    ids=[c['id'] for c in candidates]
    ph=','.join('?' for _ in ids)
    submitted=set(); confirmed=set()
    try:
        cur.execute(f"SELECT DISTINCT legacy_trades_id FROM portfolio_event_journal WHERE event_type='BROKER_SELL_SUBMITTED' AND legacy_trades_id IN ({ph})", ids)
        submitted.update(r[0] for r in cur.fetchall() if r[0] is not None)
        cur.execute(f"SELECT DISTINCT legacy_trades_id FROM portfolio_event_journal WHERE event_type='BROKER_SELL_FILLED' AND legacy_trades_id IN ({ph})", ids)
        confirmed.update(r[0] for r in cur.fetchall() if r[0] is not None)
    except Exception:
        pass
    active_override_ids=set()
    try:
        cur.execute(f"SELECT DISTINCT trade_id FROM manual_trade_overrides WHERE override_type='PROFESSOR_HOLD_OVERRIDE' AND status='ACTIVE' AND deactivated_at IS NULL AND trade_id IN ({ph})", ids)
        active_override_ids.update(r[0] for r in cur.fetchall() if r[0] is not None)
    except Exception:
        pass
    tickers=list({str(c['ticker'] or '').upper() for c in candidates if c.get('ticker')})
    credited_tickers=set()
    if tickers:
        like=' OR '.join(['reason LIKE ?' for _ in tickers])
        try:
            cur.execute(f"SELECT DISTINCT reason FROM cash_ledger WHERE {like}", [f'Broker sell {t}%' for t in tickers])
            for (reason,) in cur.fetchall():
                for t in tickers:
                    if reason and reason.upper().startswith(f'BROKER SELL {t}'):
                        credited_tickers.add(t)
        except Exception:
            pass
    conn.close()
    out=[]
    for c in candidates:
        tk=str(c.get('ticker') or '').upper()
        if c['id'] in active_override_ids: continue
        if c['id'] not in submitted: continue
        if c['id'] in confirmed: continue
        if tk in credited_tickers: continue
        out.append(c)
    return out


# --- P0B1/P0B3 broker screenshot intake governance helpers ---
from decimal import Decimal, ROUND_HALF_UP

P0B1_APPROVE_TARGET_PHRASE = "Approve official Atlas target update"
P0B1_APPROVE_STOP_PHRASE = "Approve official Atlas stop update"


def _p0b1_decimal(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace("$", "").replace(",", "").strip())
    except Exception:
        return None


def _p0b1_price_micros(value):
    dec = _p0b1_decimal(value)
    if dec is None:
        return None, None
    return int((dec * Decimal("1000000")).to_integral_value(rounding=ROUND_HALF_UP)), format(dec, "f")


def _p0b1_cents(value):
    dec = _p0b1_decimal(value)
    if dec is None:
        return None, None
    return int((dec * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP)), format(dec, "f")


def _p0b1_quantity_scaled(value):
    dec = _p0b1_decimal(value)
    if dec is None:
        return None, None, None
    scale = 8
    return int((dec * (Decimal(10) ** scale)).to_integral_value(rounding=ROUND_HALF_UP)), scale, format(dec, "f")


def _p0b1_money(value):
    dec = _p0b1_decimal(value)
    return "N/A" if dec is None else f"${dec.quantize(Decimal('0.01'))}"


def broker_tp_sl_mismatch_warnings(*, ticker=None, legacy_trades_id=None,
                                   broker_take_profit_display=None,
                                   broker_stop_display=None,
                                   atlas_target=None, atlas_stop=None,
                                   tolerance=Decimal("0.01")):
    """Return broker-vs-Atlas TP/SL mismatch warnings without mutating model fields."""
    conn = get_connection(); cur = conn.cursor()
    if (atlas_target is None or atlas_stop is None) and legacy_trades_id is not None:
        cur.execute("SELECT ticker, target_price, stop_loss FROM trades WHERE id=?", (int(legacy_trades_id),))
        row = cur.fetchone()
        if row:
            ticker = ticker or row[0]
            atlas_target = row[1] if atlas_target is None else atlas_target
            atlas_stop = row[2] if atlas_stop is None else atlas_stop
    elif (atlas_target is None or atlas_stop is None) and ticker:
        cur.execute("SELECT id, target_price, stop_loss FROM trades WHERE ticker=? AND status='OPEN' ORDER BY entry_at ASC, id ASC LIMIT 1", (str(ticker).upper(),))
        row = cur.fetchone()
        if row:
            legacy_trades_id = legacy_trades_id or row[0]
            atlas_target = row[1] if atlas_target is None else atlas_target
            atlas_stop = row[2] if atlas_stop is None else atlas_stop
    conn.close()
    warnings=[]
    btp=_p0b1_decimal(broker_take_profit_display); at=_p0b1_decimal(atlas_target)
    if btp is not None and at is not None and abs(btp-at) > tolerance:
        warnings.append({"code":"BROKER_TP_DIFFERS_FROM_ATLAS_TARGET","ticker":ticker,"broker":format(btp,"f"),"atlas":format(at,"f")})
    bsl=_p0b1_decimal(broker_stop_display); astop=_p0b1_decimal(atlas_stop)
    if bsl is not None and astop is not None and abs(bsl-astop) > tolerance:
        warnings.append({"code":"BROKER_SL_DIFFERS_FROM_ATLAS_STOP","ticker":ticker,"broker":format(bsl,"f"),"atlas":format(astop,"f")})
    return warnings


def render_broker_display_warning_lines(snapshot):
    """Render operator warning lines for broker-display TP/SL mismatch rows."""
    ticker = str((snapshot or {}).get("ticker") or "?").upper()
    lines=[]
    warning_text = str((snapshot or {}).get("warning_text") or "")
    if "BROKER_TP_DIFFERS_FROM_ATLAS_TARGET" in warning_text:
        lines.append(f"⚠️ {ticker} broker TP {_p0b1_money((snapshot or {}).get('broker_take_profit_display_text'))} differs from Atlas target {_p0b1_money((snapshot or {}).get('atlas_target_text_at_ingest'))} — BROKER_TP_DIFFERS_FROM_ATLAS_TARGET. Broker display only; no Atlas target update without approval phrase.")
    if "BROKER_SL_DIFFERS_FROM_ATLAS_STOP" in warning_text:
        lines.append(f"⚠️ {ticker} broker SL {_p0b1_money((snapshot or {}).get('broker_stop_display_text'))} differs from Atlas stop {_p0b1_money((snapshot or {}).get('atlas_stop_text_at_ingest'))} — BROKER_SL_DIFFERS_FROM_ATLAS_STOP. Broker display only; no Atlas stop update without approval phrase.")
    return lines


def record_broker_position_display_snapshot(*, ticker, broker_ref=None, shares=None,
                                            broker_entry=None, broker_current=None,
                                            broker_take_profit_display=None,
                                            broker_stop_display=None,
                                            broker_pl=None, broker_value=None,
                                            legacy_trades_id=None, lot_id=None,
                                            evidence_id=None, source_filename=None):
    """Append broker display snapshot only; never mutates trades target/stop/risk fields."""
    ticker = str(ticker or "").upper().strip()
    if not ticker:
        raise ValueError("ticker required")
    conn = get_connection(); cur = conn.cursor()
    atlas_target = atlas_stop = None
    if legacy_trades_id is None:
        cur.execute("SELECT id, target_price, stop_loss FROM trades WHERE ticker=? AND status='OPEN' ORDER BY entry_at ASC, id ASC LIMIT 1", (ticker,))
        row = cur.fetchone()
        if row:
            legacy_trades_id, atlas_target, atlas_stop = row
    else:
        cur.execute("SELECT target_price, stop_loss FROM trades WHERE id=?", (int(legacy_trades_id),))
        row=cur.fetchone()
        if row:
            atlas_target, atlas_stop = row
    shares_scaled, shares_scale, shares_text = _p0b1_quantity_scaled(shares)
    broker_entry_micros, broker_entry_text = _p0b1_price_micros(broker_entry)
    broker_current_micros, broker_current_text = _p0b1_price_micros(broker_current)
    broker_tp_micros, broker_tp_text = _p0b1_price_micros(broker_take_profit_display)
    broker_sl_micros, broker_sl_text = _p0b1_price_micros(broker_stop_display)
    broker_pl_cents, broker_pl_text = _p0b1_cents(broker_pl)
    broker_value_cents, broker_value_text = _p0b1_cents(broker_value)
    atlas_target_micros, atlas_target_text = _p0b1_price_micros(atlas_target)
    atlas_stop_micros, atlas_stop_text = _p0b1_price_micros(atlas_stop)
    warnings = broker_tp_sl_mismatch_warnings(ticker=ticker, legacy_trades_id=legacy_trades_id,
        broker_take_profit_display=broker_take_profit_display, broker_stop_display=broker_stop_display,
        atlas_target=atlas_target, atlas_stop=atlas_stop)
    warning_codes = ",".join(w["code"] for w in warnings)
    target_warn = int(any(w["code"] == "BROKER_TP_DIFFERS_FROM_ATLAS_TARGET" for w in warnings))
    stop_warn = int(any(w["code"] == "BROKER_SL_DIFFERS_FROM_ATLAS_STOP" for w in warnings))
    cur.execute("""INSERT INTO broker_position_display_snapshots
        (legacy_trades_id, lot_id, ticker, broker_ref, shares_text, shares_scaled, shares_scale,
         broker_entry_micros, broker_entry_text, broker_current_micros, broker_current_text,
         broker_take_profit_display_micros, broker_take_profit_display_text,
         broker_stop_display_micros, broker_stop_display_text,
         broker_pl_cents, broker_pl_text, broker_value_cents, broker_value_text,
         atlas_target_micros_at_ingest, atlas_target_text_at_ingest,
         atlas_stop_micros_at_ingest, atlas_stop_text_at_ingest,
         target_diff_warning, stop_diff_warning, warning_text, evidence_id, source_filename)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (legacy_trades_id, lot_id, ticker, broker_ref, shares_text, shares_scaled, shares_scale,
         broker_entry_micros, broker_entry_text, broker_current_micros, broker_current_text,
         broker_tp_micros, broker_tp_text, broker_sl_micros, broker_sl_text,
         broker_pl_cents, broker_pl_text, broker_value_cents, broker_value_text,
         atlas_target_micros, atlas_target_text, atlas_stop_micros, atlas_stop_text,
         target_warn, stop_warn, warning_codes, evidence_id, source_filename))
    snapshot_id = cur.lastrowid
    conn.commit(); conn.close()
    return {"id": snapshot_id, "ticker": ticker, "legacy_trades_id": legacy_trades_id, "warnings": warnings, "warning_text": warning_codes}


def approve_official_atlas_target_update(trade_id, new_target_price, approval_phrase):
    if approval_phrase != P0B1_APPROVE_TARGET_PHRASE:
        raise PermissionError("Exact phrase required: Approve official Atlas target update")
    conn=get_connection(); cur=conn.cursor()
    cur.execute("UPDATE trades SET target_price=?, updated_at=? WHERE id=?", (float(new_target_price), _now(), int(trade_id)))
    changed=cur.rowcount; conn.commit(); conn.close()
    return changed


def approve_official_atlas_stop_update(trade_id, new_stop_loss, approval_phrase):
    if approval_phrase != P0B1_APPROVE_STOP_PHRASE:
        raise PermissionError("Exact phrase required: Approve official Atlas stop update")
    conn=get_connection(); cur=conn.cursor()
    cur.execute("UPDATE trades SET stop_loss=?, updated_at=? WHERE id=?", (float(new_stop_loss), _now(), int(trade_id)))
    changed=cur.rowcount; conn.commit(); conn.close()
    return changed

# --- end P0B1/P0B3 helpers ---
