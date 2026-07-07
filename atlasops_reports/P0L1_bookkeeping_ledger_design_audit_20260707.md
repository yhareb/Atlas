# P0L-1 READ-ONLY Bookkeeping/Ledger Design Audit

**Scope:** read-only design audit. No schema changes, no DB writes, no code changes, no strategy/TFE/report/routing/scheduler/env/Telegram/stop/target/exit/risk changes.

**P0L1_STATUS: AUDIT_COMPLETE — design proposal only, no implementation**

## 1. Current Schema Summary

**Canonical DB:** `/Users/yasser/scripts/atlas.db` (SQLite). Tables:

| Table | Purpose | Key columns |
|---|---|---|
| `signals` | Every scan result (buy/watch/avoid decisions) — append-only by convention, never updated | id, timestamp, ticker, signal, score, rvol, entry_price, stop_loss, ... |
| `trades` | One row per **lot** (a quantity bought together). Mutated in place: `status` flips OPEN→CLOSED, `exit_price`/`exit_at`/`realized_pnl` fields get written on close | id, ticker, status, quantity, entry_price, entry_at, exit_price, exit_at, realized_pnl, stop_loss, target_price, broker_ref, manual_stop_lock |
| `cash_ledger` | Append-only running cash balance — each row is a signed `amount` + `reason` free-text + computed `balance_after` | id, ts, amount, reason, balance_after |
| `account` | Single-row starting cash baseline | id, starting_cash, created_at, updated_at |
| `handoff` | Daily snapshot blob (BUY/WATCH/DECISIONS JSON) — one row per date, upserted | id, date (UNIQUE), data (JSON) |
| `pending_pullbacks` | Armed limit-order-style pullback state, one row per ticker (UNIQUE), mutated in place | id, ticker, status, armed_at, expires_at, trigger_price, filled_at, expired_at |
| `ema_retry_candidates` | Similar armed-state table for EMA retry logic | id, ticker, status, first_seen_at, last_seen_at |

**Separate audit trail (not in atlas.db):** `atlas_audit.py` writes to a **separate Postgres database** (`ops_db_events`, `ops_api_calls`, `ops_code_changes`, `ops_signals` tables) via `_audit_db_event()` calls sprinkled through `atlas_db.py`. This already captures `(table_name, operation, row_id, ticker, source_function, metadata, ts)` for most writes — i.e., **a partial append-only event log already exists**, but it: (a) lives in a different database engine/location than the transactional data, (b) is fire-and-forget / best-effort (wrapped in bare `except: pass`, so failures are silent), (c) has no defined event-type vocabulary (just raw table/operation names), and (d) is not consulted by any report, reconciliation, or invariant-check code today — it is write-only telemetry, not a queryable source of truth.

**Vault:** external mirror (`vault_sync.py`), synced incrementally from the same `trades`/`signals`/`cash_ledger`/`handoff` tables — a read replica, not an independent source of truth or an event log.

## 2. Gaps Found

1. **No linkage between decision and confirmation.** `trades.status` transitions directly from OPEN→CLOSED based on Atlas's own internal stop/target logic (`run_exits()`), with no separate record of "Atlas decided to sell" vs. "broker confirmed the sell." The INTC incident showed exactly this: the DB recorded CLOSED before any broker-side confirmation existed, and there was no way to query "is this CLOSED because Atlas decided, or because the broker confirmed, or both?"
2. **Cash postings are decoupled from position state changes with no enforced link.** `cash_ledger` rows are appended by separate code paths (`confirm_trade_fill`, manual broker-ingest scripts) with no foreign key or transactional guarantee tying a `trades` status change to a corresponding `cash_ledger` row. This is exactly how the INTC gap occurred: `trades.status='CLOSED'` with zero enforcement that a matching credit row must exist.
3. **No distinction between "internal decision" and "external event."** A `SELL` in `run_exits()` output is Atlas's own signal-engine conclusion; a broker fill notification/screenshot is an external fact. Today both collapse into the same `trades.status`/`exit_price` fields with no way to tell which stage produced the current value, or whether they agree.
4. **Mutation in place, not append-only.** `trades` rows are `UPDATE`d directly (status, exit_price, exit_at, realized_pnl all get overwritten). There is no historical record of what the row looked like *before* a correction — the P0K-2/P0K-3 backup-file approach was a manual, ad-hoc substitute for what should be a built-in append-only audit trail. Once a row is corrected, the fact that it was ever CLOSED-then-reopened-then-CLOSED-again is only recoverable by cross-referencing manually-created `.bak.db` files and Hermes session transcripts — not from the DB itself.
5. **No reconciliation table.** There is no structured comparison between broker state, Atlas DB state, and Vault state. Discrepancies (like the INTC mismatch) are currently discovered only by Prof manually noticing and asking AtlasOps to audit — there's no queryable "open reconciliation exceptions" view.
6. **Reports read live mutable state directly, not a stable point-in-time snapshot.** `_holding_lines()` queries `trades WHERE status='OPEN'` live at render time. This is why the INTC report displayed inconsistent numbers across adjacent cycles (once with a stale entry-fallback price, once correctly) — there is no `report_snapshot` capturing exactly what inputs produced a given report, making after-the-fact debugging of "why did the report say X" harder than necessary.
7. **The existing audit trail (`ops_db_events`) is disconnected from the domain model.** It logs raw table/operation pairs, not domain-meaningful events like `STOP_HIT_DETECTED` or `MANUAL_CORRECTION`. It also can't be joined against `cash_ledger`/`trades` easily since it lives in a separate DB engine, and its silent-failure design means it cannot be relied upon as a completeness guarantee.
8. **No explicit `evidence` linkage.** Broker screenshots and Prof's manual confirmations are currently pasted into `trades.notes` as free text (e.g., "Broker screenshot fill: ...") — functional but not structured, not queryable, and not attachable as a first-class evidence record tied to a specific event.

## 3. Proposed Minimum-Viable Ledger Schema (design only — not created)

### `portfolio_event_journal` (append-only, source of truth for "what happened, in order")
```
id              INTEGER PRIMARY KEY
event_type      TEXT NOT NULL   -- see §5 vocabulary
ticker          TEXT
lot_id          INTEGER         -- FK to trades.id / position_lots.id, nullable for account-level events
occurred_at     DATETIME NOT NULL   -- when the real-world event happened (may differ from recorded_at)
recorded_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP  -- when Atlas wrote this row
payload_json    TEXT NOT NULL   -- structured event-specific data (price, qty, broker_ref, reason, etc.)
source          TEXT NOT NULL   -- e.g. 'run_exits', 'broker_ingest', 'manual_correction', 'stop_monitor'
evidence_id     INTEGER         -- FK to evidence_attachments.id, nullable
prof_approved   INTEGER DEFAULT 0  -- 1 if this event required and received explicit Prof approval (e.g. MANUAL_CORRECTION)
supersedes_id   INTEGER         -- FK to a prior event this one corrects/reverses, nullable
```
**Never UPDATEd or DELETEd.** Corrections are new rows with `event_type='MANUAL_CORRECTION'` and `supersedes_id` pointing at what's being corrected.

### `ledger_postings` (double-entry cash/position postings)
```
id              INTEGER PRIMARY KEY
event_id        INTEGER NOT NULL   -- FK to portfolio_event_journal.id (every posting must trace to an event)
account         TEXT NOT NULL      -- 'CASH', 'POSITION:<TICKER>', 'REALIZED_PNL', 'FEES'
amount          REAL NOT NULL      -- signed; debits negative, credits positive by convention
balance_after   REAL               -- running balance for that account, computed at insert time
posted_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
reason          TEXT
```
**Invariant:** for any single `event_id`, the sum of all `ledger_postings.amount` across accounts touched by that event must be zero (true double-entry balance) — e.g. a BROKER_SELL_FILLED event posts a debit to `POSITION:INTC` and an equal-and-opposite credit split across `CASH` and `REALIZED_PNL`/`FEES`.

### `position_lots` (read model — current derived state, rebuildable from the journal)
```
id              INTEGER PRIMARY KEY   -- same identity as today's trades.id for continuity
ticker          TEXT NOT NULL
status          TEXT NOT NULL         -- OPEN | CLOSED | PENDING_BROKER_CONFIRMATION
quantity        REAL NOT NULL
entry_price     REAL NOT NULL
entry_event_id  INTEGER NOT NULL      -- FK to the BUY_DECISION or BROKER_BUY_FILLED event that opened it
exit_price      REAL
exit_event_id   INTEGER               -- FK to the SELL_DECISION/BROKER_SELL_FILLED event that closed it
stop_loss       REAL
target_price    REAL
last_rebuilt_at DATETIME              -- when this read-model row was last derived from the journal
```
This replaces today's mutable `trades` table conceptually — it's still queryable the same way for reports, but is explicitly a **projection** that can be rebuilt/verified from `portfolio_event_journal` at any time, rather than the sole record of truth.

### `broker_reconciliation`
```
id                  INTEGER PRIMARY KEY
lot_id              INTEGER NOT NULL       -- FK to position_lots.id
checked_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
atlas_status        TEXT NOT NULL          -- position_lots.status at check time
broker_status       TEXT                   -- 'OPEN' | 'CLOSED' | 'UNKNOWN' (from screenshot/manual input)
atlas_price         REAL
broker_price        REAL
match               INTEGER NOT NULL       -- 1 if statuses/prices reconcile within tolerance, 0 if exception
exception_note      TEXT
evidence_id         INTEGER                -- FK to evidence_attachments.id
```
Every audit like P0K-1 would populate a row here instead of being a one-off Markdown report — creating a queryable history of "when did we last confirm broker vs Atlas agreement for this lot."

### `report_snapshots`
```
id              INTEGER PRIMARY KEY
report_type     TEXT NOT NULL        -- 'intraday', 'pre_market', 'eod', etc.
generated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
inputs_hash     TEXT                 -- hash of the position_lots/journal state used to render
holdings_json   TEXT NOT NULL        -- frozen copy of exactly what HOLDING section showed
sell_now_json   TEXT
telegram_message_id  TEXT
```
Lets AtlasOps answer "what did the report actually say and why" without re-deriving from mutable live state — directly addresses the P0H-1 (IRDM stale-report) and P0K-4 (INTC $129.78 fallback) investigation pattern, where the biggest time cost was reconstructing what happened after the fact.

### `evidence_attachments`
```
id              INTEGER PRIMARY KEY
kind            TEXT NOT NULL        -- 'broker_screenshot', 'prof_message', 'system_log_excerpt'
description     TEXT
file_path       TEXT                 -- path to screenshot/log excerpt if stored, nullable
created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
```

## 4. Event Types (vocabulary for `portfolio_event_journal.event_type`)

| Event Type | Meaning | Typical source |
|---|---|---|
| `BUY_DECISION` | Atlas's internal signal engine decided to buy | `run_atlas_cycle`/scan |
| `BROKER_BUY_FILLED` | Broker confirmed the buy actually executed | `atlas_broker_ingest.py` / manual |
| `SELL_DECISION` | Atlas's `run_exits()` internally concluded a position should close (stop/target/manual) | `run_exits` |
| `BROKER_SELL_FILLED` | Broker confirmed the sell actually executed | `atlas_broker_ingest.py` / manual |
| `STOP_HIT_DETECTED` | A live price crossed the stop threshold (may precede `SELL_DECISION`, useful for early alerting even before an exit runs) | `run_exits` / price monitor |
| `CASH_DEBIT_POSTED` | A cash outflow was recorded (buy cost, fees) | `_append_cash_ledger` equivalent |
| `CASH_CREDIT_POSTED` | A cash inflow was recorded (sell proceeds) | `_append_cash_ledger` equivalent |
| `MANUAL_CORRECTION` | Prof-approved override of any prior event/state (e.g. P0K-3's INTC CLOSED→OPEN restoration) | AtlasOps, with `prof_approved=1` required |
| `RECONCILIATION_EXCEPTION` | An automated or manual check found Atlas/broker/Vault disagreement | `broker_reconciliation` check |

## 5. Required Invariants

1. **No `position_lots.status='CLOSED'` without a corresponding `SELL_DECISION` or `BROKER_SELL_FILLED` event** in `portfolio_event_journal` referencing that `lot_id` — directly closes the exact gap the INTC incident exposed (a trade was CLOSED with an implied sell that had no clearly linked decision/confirmation event trail).
2. **No `BROKER_BUY_FILLED` or `BROKER_SELL_FILLED` event without a corresponding `CASH_DEBIT_POSTED`/`CASH_CREDIT_POSTED` event and matching `ledger_postings` rows** — this is the exact rule that would have caught the missing INTC cash_ledger credit immediately (as a failed invariant) instead of Prof having to notice via a screenshot mismatch.
3. **Every event's `ledger_postings` must balance to zero** (double-entry) — enforced at write time, not just eyeballed.
4. **`report_snapshots.holdings_json` must be derived exclusively from `position_lots`/journal state, never recomputed ad hoc at render time from a separately-cached price field** — eliminates the P0K-4 failure mode where a stale/fallback `current_price` got silently cached and displayed as if live.
5. **Every `MANUAL_CORRECTION` event must reference an `evidence_id` and have `prof_approved=1`** — codifies the P0K-2/P0K-3 pattern (staging proof + explicit Prof approval before any production write) as a structural DB rule instead of a purely procedural one.
6. **`supersedes_id` chains must be traceable to a root event** — no correction can silently "lose" the event it's correcting; the full CLOSED→OPEN→CLOSED history for INTC would be fully reconstructable from the journal alone, without needing manual `.bak.db` files or session-transcript archaeology.
7. **`broker_reconciliation` rows are the only permitted source for flagging `atlas_status` vs `broker_status` mismatches** — gives future "is INTC really still open" questions a queryable table instead of an ad hoc audit each time.

## 6. Migration Risk

**migration_risk: MEDIUM-HIGH if attempted as a big-bang cutover; LOW-MEDIUM if done incrementally.**

Specific risks:
- `trades` is read by many production scripts (`atlas_intraday.py`, `atlas_portfolio.py` [protected], `atlas_eod_positions.py`, `vault_sync.py`, report renderers) via `atlas_db.get_open_positions()`/`get_trades()`. Replacing it outright would require touching every caller — high blast radius, directly conflicts with the standing rule to avoid unrelated changes to protected files.
- `run_exits()` decision logic lives in the protected `atlas_portfolio.py` — any design that requires `run_exits()` itself to emit journal events would need a Prof-authorized alpha-adjacent work order under the Standing Alpha-Work Override, not a routine ops change.
- Backfilling historical journal events for existing `trades`/`cash_ledger` rows (to avoid a "day one" gap) requires careful, one-time reconciliation of ~70 existing trade rows and ~21 cash_ledger rows — doable, but must be done read-only/staging-first with full before/after row counts, per standing protocol.
- Double-entry balance enforcement, if added as a hard `CHECK`/trigger constraint, risks breaking any existing write path that doesn't yet post both sides of a transaction — needs a transition period where invariants are checked/logged as warnings before being enforced as hard failures.

**Lowest-risk path:** introduce `portfolio_event_journal`, `ledger_postings`, `broker_reconciliation`, `report_snapshots`, and `evidence_attachments` as **new, additive tables** that get populated *alongside* the existing `trades`/`cash_ledger` tables (dual-write), without removing or restructuring anything existing initially. `position_lots` can start as a read-only view/mirror of `trades` rather than a replacement. This keeps `atlas_engine.py`/`atlas_portfolio.py` and all existing report code completely untouched in phase 1, while building the new audit trail in parallel and validating it against real events (starting with the next few buy/sell cycles) before ever considering deprecating the old tables.

## Staging Plan (proposed, not started)

1. **Phase 0 (this audit):** Design review with Prof — confirm table shapes, event vocabulary, and invariants above before any code is written. *(current step)*
2. **Phase 1 — additive schema, staging DB only:** Create the 5 new tables in a copied `/tmp` DB (same staging pattern used for P0J/P0K work). Write a read-only backfill script that reconstructs `portfolio_event_journal` rows from existing `trades`/`cash_ledger` history (best-effort, clearly flagging any row where the source event type is ambiguous — e.g. today's `trades` rows don't distinguish "Atlas decided" from "broker confirmed" retroactively).
3. **Phase 2 — dual-write shim, staging DB only:** Prototype a thin wrapper around `_append_cash_ledger`/`confirm_trade_fill`/`run_exits`-adjacent call sites (in `atlas_db.py`, non-protected) that additionally appends journal + posting rows, without changing any existing table's behavior. Validate against fixtures replaying the INTC incident's exact timeline (BUY_DECISION → BROKER_BUY_FILLED → SELL_DECISION → [gap] → MANUAL_CORRECTION → SELL_DECISION → BROKER_SELL_FILLED) and confirm all invariants in §5 hold or are correctly flagged as violated where they should be (e.g. the original ungapped INTC close should trip invariant #2).
4. **Phase 3 — reconciliation tooling:** Build a read-only script that populates `broker_reconciliation` from Prof-supplied screenshots/messages, on demand — replacing the ad hoc P0K-1-style Markdown audit with a queryable row.
5. **Phase 4 — report_snapshots adoption:** Have report renderers additionally persist a snapshot row (dual-write, no change to what's sent to Telegram) — enables future "why did the report say X" investigations without log archaeology.
6. **Phase 5 (future, requires separate approval):** Only after Phases 1–4 are proven stable across multiple real trading days, consider whether `position_lots` should become the primary read path for reports (replacing direct `trades` queries) — this step touches shared code paths and would need its own staging-first gate, dry-run proof, and Prof approval, following the same protocol as every other production change in this engagement.

**No implementation has occurred. This is a design document only.**

## Summary

| Field | Value |
|---|---|
| P0L1_STATUS | AUDIT_COMPLETE — design only |
| current_schema_summary | 7 SQLite tables (signals, trades, cash_ledger, account, handoff, pending_pullbacks, ema_retry_candidates) + separate Postgres `ops_db_events` telemetry (write-only, best-effort, not domain-modeled) |
| gaps_found | 8 — no decision/confirmation linkage, no enforced cash-posting link, no internal-vs-external distinction, mutation-in-place with no history, no reconciliation table, live-state-only reports, disconnected audit trail, unstructured evidence |
| proposed_tables | `portfolio_event_journal`, `ledger_postings`, `position_lots`, `broker_reconciliation`, `report_snapshots`, `evidence_attachments` |
| required_invariants | 7 (see §5) — directly close the INTC-incident gaps |
| migration_risk | MEDIUM-HIGH big-bang / LOW-MEDIUM incremental additive approach (recommended) |
| staging_plan | 5 phases, additive-first, staging-only until Prof approves each phase; Phase 5 (report read-path cutover) requires separate future approval |
| production changes | NONE |
