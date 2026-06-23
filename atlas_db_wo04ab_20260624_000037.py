import sqlite3
import json
import os
from datetime import datetime

DB_PATH = "/Users/yasser/scripts/atlas.db"

# --------------------------------------------------------------------------- #
# Real-time push to The Vault (Option A).
#
# Atlas remains the SINGLE SOURCE OF TRUTH. After Atlas writes a row locally,
# it also pushes a copy to The Vault so the dashboard updates instantly. The
# push is fire-and-forget and can NEVER raise into Atlas: if vault_client is
# missing, unconfigured, or the network is down, Atlas keeps working exactly as
# before and the scheduled vault_sync.py re-sends the row later (idempotent).
# --------------------------------------------------------------------------- #
try:
    import vault_client as _vault
except Exception:  # noqa: BLE001 — Atlas must run even without the pusher present
    _vault = None

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


def _safe_push(fn_name, *args):
    """Invoke a vault_client.push_* function, swallowing every error."""
    if _vault is None:
        return
    try:
        getattr(_vault, fn_name)(*args)
    except Exception:  # noqa: BLE001 — never let a push break an Atlas write
        pass


def _fetch_trade_rows(ids):
    """Read specific trade lots by id as dicts (for pushing to the Vault)."""
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
               stop_loss, risk_pct, target_price, notes, updated_at
        FROM trades WHERE id IN ({placeholders})
    ''', ids)
    cols = [d[0] for d in cursor.description]
    rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
    conn.close()
    return rows


def get_connection():
    return sqlite3.connect(DB_PATH)


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

    # Positions table (legacy log of buy/sell actions) -- unchanged.
    # Kept for backward compatibility; `trades` is now the source of truth
    # for P&L and history.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            ticker TEXT,
            action TEXT, -- e.g., 'BUY', 'SELL'
            price REAL,
            quantity INTEGER,
            status TEXT DEFAULT 'OPEN' -- 'OPEN', 'CLOSED'
        )
    ''')

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
            quantity INTEGER NOT NULL,
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
        "risk_pct": "ALTER TABLE trades ADD COLUMN risk_pct REAL",
        "target_price": "ALTER TABLE trades ADD COLUMN target_price REAL",
    }.items():
        if _col not in _trade_cols:
            cursor.execute(_ddl)

    conn.commit()

    # Backfill: migrate legacy `positions` rows into `trades` exactly once.
    _backfill_positions_into_trades(conn)

    conn.close()


def _table_has_rows(cursor, table):
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    return cursor.fetchone()[0] > 0


def _backfill_positions_into_trades(conn):
    """One-time, idempotent migration of legacy positions -> trades.

    We only backfill if `trades` is empty AND `positions` has data, so running
    init_db() repeatedly never duplicates anything. Each legacy BUY row becomes
    an OPEN trade lot; legacy SELL rows are recorded as CLOSED lots with no
    matched entry (we cannot reconstruct the original buy price), so realized
    P&L is left NULL and a note explains it is a legacy import.
    """
    cursor = conn.cursor()

    # Guard: skip if trades already has data (already migrated).
    cursor.execute("SELECT COUNT(*) FROM trades")
    if cursor.fetchone()[0] > 0:
        return
    # Guard: nothing to migrate.
    if not _table_has_rows(cursor, "positions"):
        return

    cursor.execute(
        "SELECT id, timestamp, ticker, action, price, quantity, status FROM positions ORDER BY id ASC"
    )
    legacy = cursor.fetchall()
    for _id, ts, ticker, action, price, qty, status in legacy:
        ticker = (ticker or "").upper()
        action = (action or "BUY").upper()
        qty = int(qty or 0)
        price = float(price or 0)
        if not ticker or qty <= 0 or price <= 0:
            continue
        if action == "SELL":
            # Legacy sell with no matched buy: store as closed, P&L unknown.
            cursor.execute('''
                INSERT INTO trades (ticker, status, quantity, entry_price, entry_at,
                                    exit_price, exit_at, realized_pnl, realized_pnl_pct, notes)
                VALUES (?, 'CLOSED', ?, ?, ?, ?, ?, NULL, NULL, ?)
            ''', (ticker, qty, price, ts, price, ts,
                  "Legacy SELL imported from positions; original entry unknown."))
        else:
            # Legacy buy -> open lot.
            cursor.execute('''
                INSERT INTO trades (ticker, status, quantity, entry_price, entry_at, notes)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (ticker, status or "OPEN", qty, price, ts,
                  "Imported from legacy positions table."))
    conn.commit()


# --------------------------------------------------------------------------- #
# Signals (unchanged API)
# --------------------------------------------------------------------------- #
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

    # Real-time push to the Vault (fire-and-forget; never raises).
    _safe_push("push_signal", {
        "id": new_id, "timestamp": _now(), "ticker": ticker, "signal": signal,
        "score": score, "rvol": rvol, "entry_price": entry_price,
        "stop_loss": stop_loss, "max_loss_per_share": max_loss_per_share,
        "atr": atr, "trend_stack": trend_stack, "relative_strength": relative_strength,
        "volume": volume, "catalyst": catalyst, "warnings": warnings,
    })


# --------------------------------------------------------------------------- #
# Legacy positions (kept so existing /positions command keeps working)
# --------------------------------------------------------------------------- #
def log_position(ticker, action, price, quantity=0, status='OPEN'):
    """Legacy logger. Still writes to `positions` for backward compatibility,
    AND routes into the new trades ledger so history/P&L stays correct.

    - action BUY  -> opens a trade lot
    - action SELL -> closes shares FIFO and realizes P&L
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO positions (ticker, action, price, quantity, status)
        VALUES (?, ?, ?, ?, ?)
    ''', (ticker, action, price, quantity, status))
    position_id = cursor.lastrowid
    conn.commit()
    conn.close()
    _audit_db_event("positions", "INSERT", position_id, ticker, "log_position")

    # Mirror into the trades ledger.
    if str(action).upper() == "SELL":
        close_trade(ticker, price, quantity=quantity)
    else:
        open_trade(ticker, price, quantity=quantity)


# --------------------------------------------------------------------------- #
# Trades ledger (NEW — source of truth for P&L and history)
# --------------------------------------------------------------------------- #
def _now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def open_trade(ticker, entry_price, quantity, fees=0.0, notes=None, entry_at=None,
               stop_loss=None, risk_pct=None, target_price=None, status="PENDING_FILL"):
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
                            entry_fees, stop_loss, risk_pct, target_price, notes, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (ticker, status, quantity, entry_price, entry_at or _now(), float(fees or 0),
          None if stop_loss is None else float(stop_loss),
          None if risk_pct is None else float(risk_pct),
          None if target_price is None else float(target_price), notes, _now()))
    trade_id = cursor.lastrowid
    conn.commit()
    conn.close()
    _audit_db_event("trades", "INSERT", trade_id, ticker, "open_trade")

    # Real-time push of the new lot (fire-and-forget; never raises).
    _safe_push("push_trades", _fetch_trade_rows([trade_id]))
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


def confirm_trade_fill(trade_id, broker_qty, broker_price, broker_fees, broker_ref):
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
            target_price=?, notes=?, updated_at=?
        WHERE id=? AND status='PENDING_FILL'
    """, (broker_qty, broker_price, broker_fees,
          None if target_price is None else float(target_price), notes, _now(), trade_id))
    if cursor.rowcount != 1:
        conn.rollback(); conn.close()
        raise RuntimeError(f"Failed to confirm trade id {trade_id}")
    debit = -(broker_qty * broker_price + broker_fees)
    _append_cash_ledger(cursor, debit, f"Broker fill {ticker} {broker_ref}: {broker_qty} sh @ {broker_price} plus fees {broker_fees}")
    conn.commit()
    conn.close()
    _audit_db_event("trades", "UPDATE", trade_id, ticker, "confirm_trade_fill")
    _safe_push("push_trades", _fetch_trade_rows([trade_id]))
    return _fetch_trade_rows([trade_id])[0]


def get_pending_fill_trades():
    """Return engine-approved trades awaiting manual broker confirmation."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, ticker, status, quantity, entry_price, entry_at,
               exit_price, exit_at, entry_fees, exit_fees,
               realized_pnl, realized_pnl_pct, parent_id,
               stop_loss, risk_pct, target_price, notes, updated_at
        FROM trades WHERE status = 'PENDING_FILL'
        ORDER BY entry_at ASC, id ASC
    ''')
    cols = [d[0] for d in cursor.description]
    rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
    conn.close()
    return rows


def close_trade(ticker, exit_price, quantity=None, fees=0.0, exit_at=None):
    """Close shares of `ticker` FIFO at `exit_price`.

    Partial sells SPLIT lots: if you sell fewer shares than the oldest open
    lot holds, that lot is split into a CLOSED portion (with realized P&L) and
    a remaining OPEN portion. `fees` (the sell-side commission) is distributed
    across the closed shares proportionally.

    If `quantity` is None, ALL open shares of the ticker are closed.
    Returns a list of the CLOSED trade ids created/affected.
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

    total_open = sum(int(r[1]) for r in open_lots)
    if total_open == 0:
        conn.close()
        raise ValueError(f"No open shares of {ticker} to close.")

    shares_to_close = int(quantity) if quantity not in (None, 0) else total_open
    if shares_to_close > total_open:
        # Don't oversell; clamp to what's open and note it.
        shares_to_close = total_open

    total_sell_fee = float(fees or 0)
    closed_ids = []
    remaining = shares_to_close

    for lot_id, lot_qty, entry_price, entry_at, entry_fee, stop_loss, risk_pct, target_price in open_lots:
        if remaining <= 0:
            break
        lot_qty = int(lot_qty)
        entry_price = float(entry_price)
        entry_fee = float(entry_fee or 0)

        take = min(remaining, lot_qty)
        # Proportional fees for the portion being closed.
        sell_fee_share = total_sell_fee * (take / shares_to_close) if shares_to_close else 0
        entry_fee_share = entry_fee * (take / lot_qty) if lot_qty else 0

        gross = (exit_price - entry_price) * take
        realized = gross - entry_fee_share - sell_fee_share
        cost_basis = entry_price * take
        realized_pct = (realized / cost_basis * 100) if cost_basis else None

        if take == lot_qty:
            # Close the whole lot in place.
            cursor.execute('''
                UPDATE trades
                SET status='CLOSED', exit_price=?, exit_at=?, exit_fees=?,
                    entry_fees=?, realized_pnl=?, realized_pnl_pct=?, updated_at=?
                WHERE id=?
            ''', (exit_price, exit_at, sell_fee_share, entry_fee_share,
                  realized, realized_pct, _now(), lot_id))
            closed_ids.append(lot_id)
        else:
            # SPLIT: shrink the open lot, create a new CLOSED child lot.
            new_open_qty = lot_qty - take
            new_entry_fee = entry_fee - entry_fee_share
            cursor.execute('''
                UPDATE trades SET quantity=?, entry_fees=?, updated_at=? WHERE id=?
            ''', (new_open_qty, new_entry_fee, _now(), lot_id))
            cursor.execute('''
                INSERT INTO trades (ticker, status, quantity, entry_price, entry_at,
                                    exit_price, exit_at, entry_fees, exit_fees,
                                    realized_pnl, realized_pnl_pct, parent_id,
                                    stop_loss, risk_pct, target_price, notes, updated_at)
                VALUES (?, 'CLOSED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (ticker, take, entry_price, entry_at, exit_price, exit_at,
                  entry_fee_share, sell_fee_share, realized, realized_pct, lot_id,
                  stop_loss, risk_pct, target_price,
                  f"Partial close split from lot #{lot_id}.", _now()))
            closed_ids.append(cursor.lastrowid)

        remaining -= take

    # Lots affected by this sell: the CLOSED lots we created/closed, plus any
    # parent lots whose quantity shrank from a partial split (their ids are the
    # open-lot ids we iterated). Push them all so the Vault mirrors the split.
    affected_ids = list(closed_ids) + [int(r[0]) for r in open_lots]

    conn.commit()
    conn.close()
    for _closed_id in closed_ids:
        _audit_db_event("trades", "UPDATE", _closed_id, ticker, "close_trade")
    for _affected_id in set(affected_ids) - set(closed_ids):
        _audit_db_event("trades", "UPDATE", _affected_id, ticker, "close_trade")

    # Real-time push of every affected lot (fire-and-forget; never raises).
    _safe_push("push_trades", _fetch_trade_rows(sorted(set(affected_ids))))
    return closed_ids


def get_trades(status=None, limit=500):
    """Return trade lots, newest activity first. Optional status filter."""
    conn = get_connection()
    cursor = conn.cursor()
    if status:
        cursor.execute('''
            SELECT id, ticker, status, quantity, entry_price, entry_at,
                   exit_price, exit_at, entry_fees, exit_fees,
                   realized_pnl, realized_pnl_pct, parent_id,
                   stop_loss, risk_pct, target_price, notes, updated_at
            FROM trades WHERE status = ?
            ORDER BY COALESCE(exit_at, entry_at) DESC, id DESC LIMIT ?
        ''', (status.upper(), limit))
    else:
        cursor.execute('''
            SELECT id, ticker, status, quantity, entry_price, entry_at,
                   exit_price, exit_at, entry_fees, exit_fees,
                   realized_pnl, realized_pnl_pct, parent_id,
                   stop_loss, risk_pct, target_price, notes, updated_at
            FROM trades
            ORDER BY COALESCE(exit_at, entry_at) DESC, id DESC LIMIT ?
        ''', (limit,))
    cols = [d[0] for d in cursor.description]
    rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
    conn.close()
    return rows


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
    _safe_push("push_trades", _fetch_trade_rows([int(trade_id)]))
    return changed


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
        SELECT ticker, quantity, entry_price, entry_at, stop_loss, risk_pct, target_price
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

    # Real-time push of the handoff snapshot (fire-and-forget; never raises).
    _safe_push("push_handoff", date_str, data_dict)


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
