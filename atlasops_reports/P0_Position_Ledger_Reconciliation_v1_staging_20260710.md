# Atlas position-ledger reconciliation v1 — read-only audit and copied-DB staging

## Required return

**STATUS = PASS**  
**production touched = NO**  
**reconciliation_deployment_ready = YES**

Readiness applies only to the exact one-time, three-subject data reconciliation proven on the copied DB. Production execution still requires a separate Professor approval, a fresh full DB backup, a live idle gate, exact preimage verification, and post-transaction checks. No production repair was performed.

Staging workspace:

`/tmp/p0_position_ledger_reconciliation_v1/`

---

# Authority conclusion

`trades` remains the canonical OPEN/CLOSED-position authority.

`position_lots` is an additive bookkeeping/read-model that must mirror the canonical trade and confirmed cash/broker evidence. It must not override canonical trade status, quantity, stop, target, or broker reference when the stores conflict.

The proposed repair changes only the shadow bookkeeping/event layer on a copied DB:

- no `trades` mutation;
- no `cash_ledger` mutation;
- no broker action/event fabrication beyond reconstructing events already proven by canonical broker/cash evidence;
- no PENG sell event or cash credit;
- no stop/target decision change.

---

# Complete relationship audit

Production relationship inventory at the audit baseline:

| Classification | Count | Disposition |
|---|---:|---|
| Aligned CLOSED trade/lot | 11 | Untouched |
| Aligned OPEN trade/lot | 4 | Untouched except LASR shadow-stop correction |
| Aligned pending/provisional | 52 | Untouched |
| OPEN trade missing lot | 1 — PENG 111 | Create |
| Trade/lot status mismatch | 1 — RL 42/lot 64 | Close/correct lot |
| Material field mismatch | 1 — LASR 114/lot 68 | Correct lot stop |
| New PENDING_FILL trades without lots | 24 | Untouched; expected until fill confirmation |
| VOIDED trades without lots | 12 | Untouched |
| Lot without a trade | 0 | — |
| Duplicate lots per trade | 0 | — |
| NULL `legacy_trades_id` | 0 | — |
| Ticker mismatch | 0 | — |

Historical lots 53–55 use explicit `RECONCILIATION_EXCEPTION` events because no matching legacy cash confirmation was available. They remain quarantined/untouched; this work order does not manufacture missing evidence.

No orphan journal lot references, orphan posting event references, duplicate trade links, or unbalanced existing posting sets were found.

---

# Exact root causes and authoritative evidence

## RL — trade 42 / position lot 64

### Authoritative evidence

Canonical trade 42:

- ticker/status: `RL / CLOSED`
- quantity: `7.40119`
- entry: `405.34` at `2026-06-29 13:55:05`
- exit: `388.99` at `2026-07-08 13:57:00`
- realized P/L: `-121.01` / `-4.03%`
- stop/target preserved: `387.56 / 446.21`
- broker reference: `3500381742`

Existing lot 64 before repair:

- status: `OPEN` — wrong
- quantity/entry/stop/target all match canonical entry plan
- entry event 79 exists
- exit event/price/P&L are NULL

Confirmed evidence:

- buy cash row 9: `-2999.9983546`
- sell cash row 22: `+2878.99`, explicitly names broker sell, quantity `7.40119`, exit `388.99`, broker ref `3500381742`, P/L `-121.01`
- buy event 79 and balanced buy postings exist
- no shadow `BROKER_SELL_FILLED` event/postings existed
- dated pre-correction backup already showed the canonical trade CLOSED while lot 64 remained OPEN

### Root cause

Expected broker-close path:

- `atlas_db.close_trade_broker_confirmed()` lines 828–910
- legacy trade commit at lines 888–902
- nonfatal `_dualwrite_sell_fill()` call at lines 905–909
- `_dualwrite_sell_fill()` lines 217–251 closes linked lots at lines 240–245

The legacy trade/cash correction committed without completing the later shadow dual-write. `_bk_safe()` lines 156–174 intentionally swallows bookkeeping failures. Therefore legacy authority can succeed while the lot remains stale.

### Staged disposition

**CLOSE/CORRECT** lot 64:

- status `OPEN → CLOSED`
- exit `388.99`
- realized P/L `-12101` cents
- new idempotent `BROKER_SELL_FILLED` reconstruction linked to cash row 22
- balanced postings:
  - CASH `+287899`
  - POSITION:RL `-300000`
  - REALIZED_PNL `+12101`

No new cash row and no canonical trade change.

## PENG — trade 111

### Authoritative evidence

Canonical trade 111:

- status `OPEN`
- quantity `26.42008`
- entry `75.70`
- current official stop `75.71`
- official target `100.01`
- broker reference `3510574824`

Confirmed evidence:

- cash row 23: `-2000.000056`, explicitly identifies the PENG broker fill `26.42008 @ 75.70`
- trade notes preserve fill, broker ID, target governance, and both unauthorized-close reversals
- Professor-authorized REVERSAL events 91 and 92 explicitly say no broker sell fill and no cash adjustment
- dated backups show trade 111 becoming OPEN while no lot ever existed; later reversals did not remove a lot
- no PENG buy event, postings, lot, or valuation mark existed

### Root cause

Expected fill path:

- `atlas_db.confirm_trade_fill()` lines 644–699
- legacy trade/cash commit lines 689–691
- nonfatal `_dualwrite_buy_fill()` lines 693–697
- `_dualwrite_buy_fill()` lines 177–214 creates buy event, postings, and lot

The observed state is the exact non-atomic failure window after the canonical trade/cash commit and before/surrounding the nonfatal shadow dual-write, or a manual confirmation path that bypassed the helper. The immediate post-confirmation backup proves the omission originated at fill confirmation, not during later reversals.

### Staged disposition

**CREATE** the missing shadow buy chain:

- `BROKER_BUY_FILLED` reconstruction linked to cash row 23
- balanced postings:
  - CASH `-200000`
  - POSITION:PENG `+200000`
- one OPEN lot:
  - quantity text `26.42008`
  - scaled quantity `2642008000 / 100000000`
  - entry `75.7` / `75700000` micros
  - current official stop `75.71` / `75710000` micros
  - target `100.01` / `100010000` micros
  - cost basis `200000` cents
  - broker evidence text preserved

REVERSAL events 91/92 remain unchanged. **No PENG sell event or cash credit is created.**

## LASR — trade 114 / position lot 68

### Authoritative evidence

Canonical trade 114:

- status `OPEN`
- quantity `37.03214`
- entry `75.61`
- current stop `66.94`
- target `106.68`
- broker reference `3511939112`

Existing lot 68 before repair:

- quantity and entry match
- stop `59.82` — stale original planned stop
- target `106.68` matches
- buy event 87 and balanced postings 50/51 exist
- cost basis `280000` cents

Trade notes explicitly preserve both the initial plan stop `59.82` and the later broker/current official stop `66.94`.

### Root cause

- `_dualwrite_buy_fill()` lines 177–214 copies stop/target only when creating the lot.
- `atlas_db.update_trade_stop()` lines 1029–1057 updates only `trades` at lines 1049–1051.
- `approve_official_atlas_stop_update()` lines 1710–1715 also updates only `trades`.

Any post-fill canonical stop raise therefore leaves the lot’s stop frozen at its entry-time value.

### Staged disposition

**CORRECT** lot 68 only:

- stop `59.82 → 66.94`
- micros `59820000 → 66940000`
- append one idempotent `MANUAL_CORRECTION` evidence event
- preserve quantity `37.03214`, entry `75.61`, target `106.68`, cost basis, event 87, postings, cash row 24, and broker reference

---

# Staged repair artifacts

- `src/reconcile_position_lots.py`
  - guarded executable repair for copied DBs only
- `repair.sql`
  - non-executable human-readable repair plan
- `tests/test_reconciliation.py`
- `db/atlas_copy.db`
- `db/after_first.db`
- `output/first_run.json`
- `output/second_run.json`

The executable refuses paths outside `/tmp/p0_position_ledger_reconciliation_v1/` and explicitly rejects the production DB path.

## Transaction and idempotency design

- `PRAGMA foreign_keys=ON`
- `BEGIN IMMEDIATE`
- exact canonical trade/status/ticker preimage checks
- deterministic event keys:
  - `reconcile_v1_trade_42_missing_sell_lot_close`
  - `reconcile_v1_trade_111_missing_buy_lot`
  - `reconcile_v1_trade_114_lot_stop_sync`
- posting-level account/value drift checks
- existing repaired rows are verified rather than rewritten
- rollback on any exception
- `Decimal(str(value))` with fixed scales for quantity, price, and cents

---

# Copied-DB before/after proof

The copied DB initially matched production byte-for-byte:

`0132f3020b50f9752eca0d9d066e226358d2420549efb3accb708ec586588e3b`

## Counts

| Table | Before | After | Expected delta |
|---|---:|---:|---:|
| trades | 105 | 105 | 0 |
| cash_ledger | 25 | 25 | 0 |
| position_lots | 68 | 69 | +1 PENG lot |
| portfolio_event_journal | 92 | 95 | +3 evidence events |
| ledger_postings | 54 | 59 | +5 balanced postings |
| broker_reconciliation | 0 | 0 | 0 |
| broker_position_display_snapshots | 0 | 0 | 0 |
| valuation_marks | 74 | 74 | 0 |
| invariant_checks | 89 | 89 | 0 |

## Affected lots after repair

- RL lot 64: CLOSED, exit `388.99`, realized P/L `-12101` cents, exit event 93
- PENG lot 69: OPEN, quantity `26.42008`, entry `75.7`, stop `75.71`, target `100.01`, entry event 94
- LASR lot 68: OPEN, quantity `37.03214`, entry `75.61`, stop `66.94`, target `106.68`, correction event 95

## Event/posting proof

- event 93: reconstructed RL `BROKER_SELL_FILLED`, linked to trade 42/cash 22/lot 64; 3 postings sum to zero
- event 94: reconstructed PENG `BROKER_BUY_FILLED`, linked to trade 111/cash 23/lot 69; 2 postings sum to zero
- event 95: LASR `MANUAL_CORRECTION`, no cash posting required
- unbalanced event query: empty
- PENG `BROKER_SELL_FILLED` count: `0`

## Integrity

- `PRAGMA integrity_check = ok`
- `PRAGMA foreign_key_check = 0 rows`

---

# Idempotency proof

The repair was executed twice on the copied DB.

First-run post-repair SHA:

`44d6b8c7daf5168c96f4490052748dd3eb4384b6e77fafafe5a2a0f74e89dfac`

Second-run SHA:

`44d6b8c7daf5168c96f4490052748dd3eb4384b6e77fafafe5a2a0f74e89dfac`

Result: **byte-identical**.

Second-run before/after counts were identical; no event, posting, or lot duplicated.

Focused tests:

```text
Ran 3 tests in 0.048s
OK
```

Tests prove:

- expected-only count deltas;
- exact trade/cash preservation;
- exact quantity/entry/stop/target/broker evidence;
- PENG no-sell/no-credit invariant;
- integrity/FK/balance checks;
- byte-identical idempotency;
- production path rejection.

---

# Production invariants

Production operational source SHAs remained unchanged:

- `atlas_db.py` — `8ae022d2d0c0b8cbfe0320661cc48529b00aa33ab665a583f2d36bf5dbedf3f1`
- `atlas_intraday.py` — `bab765656b2362e33999966709003ecd3bb57943ba32635504af254dd74f88de`
- `atlas_manage.py` — `d7df29af75fa3ae073556cde2c531406e07910a61206f92b85c31d590d7f7ca7`

Production DB integrity remained `ok`, FK violations remained zero, and the relevant stable tables remained:

- trades `105`
- cash_ledger `25`
- position_lots `68`
- portfolio_event_journal `92`
- ledger_postings `54`
- valuation_marks `74`

The production DB SHA changed during the long read-only/staging window because normal scheduled Atlas cycles added `signals` and `report_snapshots`. This is attributed by their timestamps/count growth. The staging script cannot open the production path and contains no production write route.

---

# Rollback plan

For future separately authorized production execution:

1. wait for a verified idle window;
2. create a fresh timestamped full DB backup under `/Users/yasser/scripts/archive/`;
3. verify backup SHA equals pre-transaction production SHA and integrity is `ok`;
4. execute the guarded transaction against production only after updating the path guard in a separately reviewed deploy artifact;
5. verify exact expected deltas, balance, integrity, FK, and incident rows.

Primary rollback: restore the full pre-repair DB backup after a fresh idle gate and verify its SHA.

Logical rollback, if specifically approved instead of full restore:

- delete only postings belonging to the three deterministic reconciliation event keys;
- delete only those three events;
- delete the newly created PENG lot by its deterministic trade link;
- restore RL lot 64 to its exact preimage;
- restore LASR lot 68 stop to its exact preimage;
- leave `trades`, `cash_ledger`, reversal events 91/92, and all unrelated rows untouched.

Full-file restore is preferred because it is simpler and stronger.

---

# Recurrence risk

The one-time repair is production-ready as a data reconciliation, but two architecture gaps remain outside this work order:

1. shadow dual-writes run after the canonical commit and failures are swallowed, so missing lots/events can recur;
2. canonical stop updates do not synchronize the shadow lot stop, so future stop tightening can recreate LASR-type drift.

A separate staged code-hardening work order would be required to close those classes permanently. This does not block the exact one-time repair because the repair is preimage-guarded, idempotent, and fully proven.

---

## Final

**STATUS = PASS**  
**production touched = NO**  
**reconciliation_deployment_ready = YES**

The exact three-record reconciliation is staged and proven. Production remains unchanged, and no deployment, restart, Telegram test, canonical trade change, cash change, or broker action occurred.
