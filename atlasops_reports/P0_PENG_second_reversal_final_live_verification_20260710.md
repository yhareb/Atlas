# P0 PENG Second Ledger Reversal and Final Live Verification

**STATUS = PASS**  
**production code touched = NO**  
**production_fix_complete = YES**

## Reconfirmation

- Trade 111 was CLOSED by the old-code 10:30 ET cycle: exit `$75.08`, `2026-07-10 14:30:13` DB time.
- No broker sell fill existed.
- `BROKER_SELL_FILLED` events: `0`.
- PENG cash credits: `0`.
- Cash remained `$25,374.95`.
- Professor explicitly confirmed PENG remains held and authorized this second reversal.

## Safety gate

The bounded worker waited for a normal idle window without killing, unloading, disabling, or rescheduling anything. Immediately before backup and again immediately before the transaction:

- `atlas_intraday.py`: absent
- `atlas_manage.py`: absent
- `market_scout.py`: absent
- `com.atlas.intraday` active work: false
- `/tmp/atlas_intraday.lock`: absent

## Backup

- Path: `/Users/yasser/scripts/archive/atlas.db_20260710T144623Z_p0_peng_second_reversal_predeploy.bak.db`
- SHA256: `cea55cc94aaf18732665374ef0bb8aaa31821f5b678b72b1a46b768cc2800aae`
- Equal to immediately-pre-correction production SHA: **YES**
- Integrity: `ok`

## DB immediately before correction

- SHA256: `cea55cc94aaf18732665374ef0bb8aaa31821f5b678b72b1a46b768cc2800aae`
- Integrity: `ok`
- Cash: `$25,374.95`
- Trade 111: `CLOSED`; quantity `26.42008`; entry `$75.70`; exit `$75.08`; exit time `2026-07-10 14:30:13`; realized P&L `-$16.12`; stop `$75.71`; target `$100.01`; risk `0.5`; broker reference and cached-price fields present.

Counts:

```text
account=1
broker_position_display_snapshots=0
broker_reconciliation=0
cash_ledger=25
ema_retry_candidates=0
evidence_attachments=1
handoff=16
invariant_checks=89
ledger_postings=54
manual_trade_overrides=1
pending_pullbacks=54
portfolio_event_journal=91
position_lots=68
report_snapshots=90
signals=33905
trades=99
valuation_marks=74
```

## Applied transaction

One `BEGIN IMMEDIATE` transaction revalidated the exact row preimage, then changed trade 111 only:

- `status='OPEN'`
- cleared `exit_price`, `exit_at`, `exit_fees`, `realized_pnl`, `realized_pnl_pct`
- preserved quantity `26.42008`, entry, broker reference, stop, target, risk, manual-stop, and cached-price fields
- changed no cash row
- preserved both unauthorized-close facts in notes and audit payload
- inserted one Professor-approved `REVERSAL` event

Second-reversal idempotency key: `prof_authorized_reversal_trade_111_old_code_reclose_20260710_1030ET`.

## Immediate post-correction verification

- SHA256: `6e5f58e417ccdccc54d7986a47f8464f6dec7a124ed6d54d641643e56080aeb4`
- Integrity: `ok`
- Exactly one trade 111: `OPEN`
- Exit/P&L fields: `NULL`
- Quantity: `26.42008`
- Cash: `$25,374.95` — unchanged
- `BROKER_SELL_FILLED`: absent
- Count delta only: `portfolio_event_journal 91 → 92`
- Every preservation check: **PASS**

## Reversal journal evidence

1. Event `91`, source `prof_authorized_p0_peng_repair`, Professor-approved: reversal of first unauthorized close at `13:40:12`, `$75.42`.
2. Event `92`, source `prof_authorized_p0_peng_second_repair`, Professor-approved: reversal of old-code re-close at `14:30:13`, `$75.08`; payload also references the first unauthorized close.

No sell-fill event or cash posting was fabricated.

## Final live verification

The existing scheduler remained enabled. Two subsequent normal production cycles ran the newly deployed code:

### Cycle 1

- Report snapshot `91`, generated `2026-07-10 14:56:15`
- PENG appeared under SELL NOW advisory: **YES**
- PENG remained in HOLDING: **YES**
- Trade 111 remained `OPEN`: **YES**
- Cash remained `$25,374.95`: **YES**
- Stop/target remained `$75.71` / `$100.01`: **YES**
- No sell fill/credit: **YES**

### Following cycle

- Report snapshot `92`, generated `2026-07-10 15:06:26`
- PENG again appeared under SELL NOW advisory: **YES**
- HOLDING still included PENG: **YES**
- Trade 111 remained `OPEN`: **YES**
- Cash remained `$25,374.95`: **YES**
- Stop/target remained unchanged: **YES**
- No broker-state mutation recorded: **YES**

Production code SHAs before and after verification were identical:

- `atlas_portfolio.py`: `8fed8d2985bb6ff4ac661dfa75f447f5d30b7325f335dede60232329a90b1444`
- `atlas_db.py`: `8ae022d2d0c0b8cbfe0320661cc48529b00aa33ab665a583f2d36bf5dbedf3f1`

## Final DB state

- SHA256: `9f3b021161d5018a456dce137bf3c159df94ff1f3ec0842549481f2ccbb5de72`
- Integrity: `ok`
- Cash: `$25,374.95`
- PENG: `OPEN`, quantity `26.42008`, exit/P&L fields `NULL`, stop `$75.71`, target `$100.01`
- Journal count: `92`; cash-ledger count: `25`

Final counts after two normal cycles:

```text
account=1
broker_position_display_snapshots=0
broker_reconciliation=0
cash_ledger=25
ema_retry_candidates=0
evidence_attachments=1
handoff=16
invariant_checks=89
ledger_postings=54
manual_trade_overrides=1
pending_pullbacks=54
portfolio_event_journal=92
position_lots=68
report_snapshots=92
signals=34047
trades=100
valuation_marks=74
```

The normal-cycle increases in `signals`, `report_snapshots`, and `trades` were scheduler activity; PENG's row, cash, stop, target, broker state, and reversal journal remained correct.

## Rollback

During a verified idle window:

```bash
cp /Users/yasser/scripts/archive/atlas.db_20260710T144623Z_p0_peng_second_reversal_predeploy.bak.db /Users/yasser/scripts/atlas.db
shasum -a 256 /Users/yasser/scripts/atlas.db
sqlite3 -readonly /Users/yasser/scripts/atlas.db 'PRAGMA integrity_check;'
```

Expected restored SHA: `cea55cc94aaf18732665374ef0bb8aaa31821f5b678b72b1a46b768cc2800aae`.

No code, strategy, scoring, stops, targets, Telegram routing, schedules, or unrelated records were modified.
