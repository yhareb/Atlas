# P0K-1 READ-ONLY INTC Source-of-Truth Audit

**Scope:** read-only. No patches, no deploys, no DB/strategy/TFE/RAG/report/routing/scheduler/env/Telegram/stop/target/exit/risk changes.

**Problem:** Professor says INTC is still open at his broker, but the Atlas intraday report shows only 4 holdings (SYNA, RL, BAC, ABNB) with no INTC.

**P0K1_STATUS: AUDIT_COMPLETE**

## 1. Broker Source

**INTC_broker_status: UNAVAILABLE** — AtlasOps has no live broker API/session access in this environment. Atlas's broker "connection" is manual screenshot ingestion (`atlas_broker_ingest.py`), not a live polling API — there is no automated real-time broker read available to check current INTC status independently of what's already recorded in the DB. Cannot confirm or deny the broker's current live state from here; only DB-recorded evidence (§2) is available.

## 2. Canonical Atlas DB

**INTC_db_status: CLOSED**

`trades` table, single row for INTC (id 16):

| Field | Value |
|---|---|
| id | 16 |
| ticker | INTC |
| status | **CLOSED** |
| quantity | 7.70534157 |
| entry_price | 129.78 |
| entry_at | 2026-06-25 14:08:30 |
| exit_price | 112.97 |
| exit_at | **2026-07-07 13:40:20** |
| stop_loss | 113.02 |
| target_price | 162.25 |
| realized_pnl | -119.77 (-13.18%) |
| broker_ref | P780203310 |
| notes | "Broker fill confirmed ref P780203310" (entry only — no exit-side broker note recorded in `notes`, but `exit_at`/`exit_price` are populated) |

**latest_INTC_trade_row:** the row above — this is the only INTC row in `trades`, and its `status` is CLOSED.

**stop_hit_close_evidence:** `exit_price` 112.97 vs `stop_loss` 113.02 — price closed just below the recorded stop level, consistent with a stop-hit exit. `exit_at` timestamp `2026-07-07 13:40:20` matches a prior P0G-1/P0H-1 audit finding (documented earlier in this engagement) that INTC closed via stop hit at 17:40:20 local time (13:40:20 UTC) on 2026-07-07.

**cash_ledger_evidence:** No credit-side cash_ledger entry exists for the INTC close specifically with "INTC" in the `reason` text (only the original entry debit, id 6, `"Broker fill INTC P780203310..."`, ts 2026-06-25 14:26:24). Cash ledger entries around the INTC exit window (13:30–14:00 UTC on 2026-07-07) show only the IRDM stop-loss credit (id 21, ts 13:33:57, "Broker sell IRDM..."). **No matching INTC sell/credit ledger row was found** — this is a gap: the `trades` table shows INTC CLOSED with `exit_price`/`exit_at` populated, but there is no corresponding `cash_ledger` credit row for the INTC sale proceeds, unlike IRDM/MSM/ALGM which each have one. This is a DB-internal inconsistency worth flagging to Prof separately (not fixed here — read-only audit).

## 3. TFE/Report Path

**report_exclusion_reason:** INTC is excluded from the `HOLDING` section because the report's holdings source (`_holding_lines()` → `_open_trades()` → `atlas_db.get_open_positions()`) queries:
```sql
SELECT ... FROM trades WHERE status = 'OPEN'
```
Since INTC's only `trades` row has `status = 'CLOSED'`, it is correctly excluded by this DB-level filter — the report code performs no independent INTC-specific logic; it inherits whatever the DB says.

**Confirmed: exclusion is because DB says CLOSED.** There is no separate bug in the report-rendering path itself.

## 4. Vault/Source Sync

**Vault_status:** `com.atlas.vaultsync` launchd job is active (runs on a ~5-minute cadence per `vault_sync.log`). The sync log shows a `trades: 4` batch pushed around `2026-07-07T15:48:11Z` (shortly after the 13:40:20 UTC INTC close and 13:33:57 UTC IRDM close), consistent with the sync picking up recent trade-row updates from the canonical DB — the same `status='CLOSED'` value now on the INTC row. No evidence found of Vault holding a separately stale "INTC OPEN" record; Vault is a downstream mirror of the same `trades` table, synced incrementally by `updated_at`/cursor, not an independent source of truth. **No stale Vault-side INTC status detected in the sync log.**

## 5. RAG

**RAG_contains_stale_INTC_context: YES** — `/Users/yasser/atlas_inbox/latest_context.json` (generated `2026-07-07T14:00:59Z`, i.e. ~20 minutes after the INTC stop-hit close) lists `"ticker_notes": ["AAPL", "MU", "INTC", "BA", "CAT", "CRM"]` and `"suppressed_sectors": ["SEMI", "TECH"]`. This is **macro/sector risk commentary from the Perme brief pipeline** (INTC named as part of semiconductor-sector negative news flow — see `/Users/yasser/atlas_inbox/processed/perme_brief_20260707_1000.md`: "SMH -4.44% and XLK -2.79% ... MU and INTC are included in negative single-name news flow"). It is **not a portfolio/position record** — it does not claim INTC is an open Atlas holding; it is a market-commentary ticker mention. Calling this "stale portfolio context" would be a category error, but it does mean INTC appears in RAG-sourced text around the same time it was closing, which could visually coincide with a report and create confusion if skimmed alongside the HOLDING section.

**report_uses_RAG_for_holdings: NO** — confirmed via source: `_holding_lines()` / `_open_trades()` / `get_open_positions()` reads exclusively from the `trades` DB table (`WHERE status='OPEN'`). RAG flags (`_load_perme_flags_from_rag()`, `_perme_annotation_line()`) only produce sector/macro annotation lines elsewhere in the report (e.g. "⚠️ Perme: ..." notes attached to watch/holding tickers) — they do not determine which tickers appear in the HOLDING list itself. RAG is annotation-only, DB is authoritative for holdings membership.

## 6. Root Cause

**mismatch_found: YES** — between Professor's belief that INTC is still an open broker position and Atlas's DB, which shows INTC CLOSED as of 2026-07-07 13:40:20 UTC via a stop-hit exit at 112.97 (stop 113.02).

**root_cause:** Most likely **broker-DB timing/confirmation gap, not a report bug.** Atlas's DB correctly reflects a stop-hit close that was recorded on 2026-07-07 13:40:20 UTC. The report correctly omits INTC from HOLDING because the DB says CLOSED, and this is not sourced from stale RAG/Vault data — RAG's INTC mention is unrelated macro commentary, and Vault is a synced mirror of the same CLOSED status. Three candidate explanations for the mismatch, in order of likelihood given available evidence:

1. **Most likely:** The broker did in fact close the INTC position via stop-loss around 13:40 UTC on 2026-07-07, and Professor has not yet refreshed his broker app/statement to see the fill — his belief that INTC is "still open" reflects a broker-side view he checked *before* the stop hit, or he hasn't re-checked since.
2. **Possible:** The broker's stop-loss order did not actually execute (e.g. a broker-side glitch, a stop that was cancelled/modified outside Atlas's knowledge, or a partial fill), and Atlas's `trades` row was closed based on an assumption/notification that didn't fully match the broker's live state. The **missing cash_ledger credit row for the INTC sale** (§2) is a real anomaly that weakens confidence in this close being fully reconciled — every other recent stop-hit close (IRDM, MSM, ALGM) has a matching cash_ledger credit; INTC does not. This is the strongest piece of evidence suggesting the INTC close in the DB might not be fully broker-confirmed the way the others were.
3. **Less likely:** Vault/RAG staleness — ruled out per §4/§5.

Given finding #2, **AtlasOps cannot fully rule out a genuine broker/DB mismatch** — the missing INTC cash_ledger credit is the one piece of hard evidence that doesn't fit a routine, fully-confirmed stop-hit close. Recommend Prof independently verify INTC's actual current status directly in the broker app/statement to resolve this with certainty; if the broker shows INTC still open, the INTC `trades` row (id 16) and its CLOSED status/exit values would need Prof-authorized correction (a DB write, requiring explicit approval — not performed here).

## Summary

| Field | Value |
|---|---|
| P0K1_STATUS | AUDIT_COMPLETE |
| INTC_broker_status | UNAVAILABLE (no live broker API access) |
| INTC_db_status | CLOSED |
| latest_INTC_trade_row | id 16, status CLOSED, exit_price 112.97, exit_at 2026-07-07 13:40:20, stop_loss 113.02 |
| stop_hit_close_evidence | exit_price 112.97 vs stop_loss 113.02 — consistent with stop-hit |
| cash_ledger_evidence | **Missing** — no INTC sale credit row found (anomaly vs. IRDM/MSM/ALGM which each have one) |
| report_exclusion_reason | `get_open_positions()` / `_holding_lines()` filters `WHERE status='OPEN'`; INTC is CLOSED so correctly excluded |
| Vault_status | Synced mirror, no stale INTC OPEN record found; last relevant trades batch synced ~15:48 UTC 2026-07-07 |
| RAG_contains_stale_INTC_context | YES (as unrelated macro/sector commentary, not a portfolio record) |
| report_uses_RAG_for_holdings | NO — DB-only |
| mismatch_found | YES |
| root_cause | Most likely broker/Prof view timing gap; missing cash_ledger credit for INTC is a real anomaly that keeps a genuine broker/DB mismatch on the table — recommend Prof verify broker app directly |
| production changes | NONE |
