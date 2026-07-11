# Position Ledger Reconciliation v1.1 — Staging Evidence

## Status

- **STATUS = PASS**
- **production touched = NO**
- New staging package: `/tmp/p0_position_ledger_reconciliation_v1_1/`
- `reconciliation_deployment_ready = YES`
- Production execution remains separately approval-gated.

## Exact posting-sign convention

Read-only audit found eight existing `BROKER_SELL_FILLED` events with complete posting sets; all eight balance to zero.

- Sell CASH leg: **positive** proceeds.
- Sell POSITION leg: **negative** historical cost basis.
- `REALIZED_PNL` is the balancing contra leg: **negative for an economic profit**, **positive for an economic loss**.
- Profitable examples: TSM `CASH +506216`, `POSITION -500520`, `REALIZED_PNL -5696`; LRCX `+587188`, `-500524`, `-86664`.
- Losing examples: MS `+94855`, `-100211`, `+5356`; IRDM `+145145`, `-150000`, `+4855`; INTC `+87167`, `-100210`, `+13043`.

Therefore corrected RL follows the existing convention:

- `CASH +287899`
- `POSITION:RL -300000`
- `REALIZED_PNL +12101`
- Event posting sum: `0`
- Economic lot result remains `position_lots.realized_pnl_cents = -12101`.

The failed package already contained numeric `12101`; v1.1 makes the intended positive contra sign explicit as `+12101`, documents the canonical convention, and—critically—adds a mandatory exact event-balance regression that the previous staging suite lacked. All reconciliation SQL logic, keys, guards, quantities, prices, and evidence links remain unchanged.

## Files and SHA256

- `/tmp/p0_position_ledger_reconciliation_v1_1/src/reconcile_position_lots.py` — `ff512d7fe852a3426b7af8b3853fef8d5b7edd77c0fcc43d8a17baac2a1795ae` (13518 bytes)
- `/tmp/p0_position_ledger_reconciliation_v1_1/tests/test_reconciliation_v1_1.py` — `6bf6eff222441bcdcd612a05da92d3800c7b6d0968c0fd2142d41a340154c594` (8100 bytes)
- `/tmp/p0_position_ledger_reconciliation_v1_1/repair.sql` — `4421a0c678824365175fa989c579d4a6a12690b0b4c2f1c1e4b21927184f14ae` (1665 bytes)
- `/tmp/p0_position_ledger_reconciliation_v1_1/output/first_run.json` — `cee4e7d0eb0c4fe8bee25e662afd5ffbf3024380c9ea640813d868640d3a6ecd` (34969 bytes)
- `/tmp/p0_position_ledger_reconciliation_v1_1/output/second_run.json` — `c56f734372fb6b83bb02adc64893e9a2aee1c27e1f2d87b4b3635ab40b014a03` (40946 bytes)
- `/tmp/p0_position_ledger_reconciliation_v1_1/output/final_evidence.json` — `3395ae384e678751d817bf5df962d247962c1ee9a7d4cdb9f6b9866764168401` (21630 bytes)
- `/tmp/p0_position_ledger_reconciliation_v1_1/output/test_results.txt` — `f7b031802959c2a3b346ca8027f58eb5786dee92e93b18bd1a0304ad7053b4fd` (443 bytes)

## Fresh copied-production-DB rehearsal

Before counts:

`{"broker_position_display_snapshots": 0, "broker_reconciliation": 0, "cash_ledger": 25, "invariant_checks": 89, "ledger_postings": 54, "portfolio_event_journal": 92, "position_lots": 68, "trades": 105, "valuation_marks": 74}`

After counts:

`{"broker_position_display_snapshots": 0, "broker_reconciliation": 0, "cash_ledger": 25, "invariant_checks": 89, "ledger_postings": 59, "portfolio_event_journal": 95, "position_lots": 69, "trades": 105, "valuation_marks": 74}`

Exact deltas:

- `position_lots +1`
- `portfolio_event_journal +3`
- `ledger_postings +5`
- `trades 0`
- `cash_ledger 0`
- broker reconciliation/display `0`
- valuation marks `0`
- invariant checks `0`

### Exact repaired rows

- RL trade 42 / lot 64: `CLOSED`, exit `388.99`, economic realized P&L `-12101` cents; reconstructed sell event linked to cash row 22.
- PENG trade 111 / new lot 69: `OPEN`, quantity `26.42008`, entry `75.7`, stop `75.71`, target `100.01`; reconstructed buy event linked to cash row 23; zero sell events and zero sell cash credits.
- LASR trade 114 / lot 68: shadow stop `59.82 → 66.94`; quantity `37.03214`, entry `75.61`, target `106.68` preserved; manual-correction evidence only, no posting.
- Canonical `trades` and relevant `cash_ledger` rows were byte-equivalent before/after.

## Event-level and global balance proof

- RL event 93: `287899 - 300000 + 12101 = 0`.
- PENG event 94: `-200000 + 200000 = 0`.
- LASR event 95: no postings; sum `0`.
- Global query `GROUP BY event_id HAVING SUM(amount_cents) != 0`: **no rows**.
- Existing balanced sell-event convention test: **PASS** across both profitable and losing exits.

## Integrity, FK, idempotency

- `PRAGMA integrity_check`: `ok`
- `PRAGMA foreign_key_check`: `0` rows
- First repaired-copy SHA: `b5d121ee428a87444f7e18921bfe8db708c31dc024d012e25e5b641e93b2573a`
- Second-run SHA: `b5d121ee428a87444f7e18921bfe8db708c31dc024d012e25e5b641e93b2573a`
- Second-run table deltas: all zero
- Duplicate repair events/lots/postings: zero
- Test suite: **4/4 PASS**
- `py_compile` staged runner and test: **PASS**

## Position Management reconciliation probe

The staged Position Management authority module was loaded against the repaired copied DB.

- PENG OPEN lot count: `1`; `MISSING_POSITION_LOTS` cleared.
- LASR stop-drift count: `0`.
- RL OPEN-orphan count: `0`.
- PENG sell-event count: `0`.
- PENG sell-cash-credit count: `0`.
- PENG, LASR, and RL produce no reconciliation conflict in the repaired copied-DB probe.

## Production invariants

- Production DB SHA before staging: `00eded2791541d71de2e1e1fed50e21e7fdf5b30fb5e778c239a650fece93c8d`.
- Production DB SHA after staging: `00eded2791541d71de2e1e1fed50e21e7fdf5b30fb5e778c239a650fece93c8d`.
- Byte-identical: **YES**.
- Failed v1 package runner SHA remains `f510e3075c8f180677231129bb9333bb7e579ba3ee63b7f361d0c09aad4aee6f`; it was not overwritten.
- Failed v1 package test SHA remains `1a23a676007fb5cbec4c12e85dedadc4251244aeac4648e05502480d71ff185f`; it was not overwritten.
- Production tracked target source status: clean; no production source changed.

## Rollback plan for a future separately authorized deployment

1. Require fresh process/launchd/lock/tick-window idle gate and exact preimages.
2. Capture immediate production SHA, integrity, FK, counts, and exact subject rows.
3. Create and SHA-verify a full timestamped DB backup under `/Users/yasser/scripts/archive/`.
4. Execute one guarded `BEGIN IMMEDIATE` transaction.
5. On any preimage, balance, integrity, FK, delta, or idempotency failure, wait for a verified idle window and restore the full DB backup.
6. Verify restored SHA equals backup, integrity `ok`, FK clean, counts restored, and repair keys absent.

## Deployment readiness

`reconciliation_deployment_ready = YES` for this exact v1.1 staged package and exact three-subject scope only. Do not execute the old package unchanged.
