# P0L-19 — Production valuation_marks Lot-ID Fix DEPLOYMENT PLAN (Evidence)

**Date:** 2026-07-07 23:00 +04
**Scope:** PLANNING ONLY. No execution. No production file edit. No
production DB write. No valuation_marks cleanup. This document is the plan
for Prof's review and explicit authorization before any execution step.

## 1. Production file SHA baseline (confirmed current)

| File | SHA256 |
|---|---|
| `atlas_db.py` | `93cdb28d98d6879d1fd6d13e043af8b4609c1427a4d586620981edc301345a85` |
| `atlas_intraday.py` | `49e30aff620140df218dc515cc77b0e4b97fa99a5c517dad7f27946b5fc768d8` |

Both match the P0L-16 deployed baseline exactly — no drift since that
deployment.

## 2. Staged P0L-18 file SHA (confirmed current, compile-verified fresh)

| File | SHA256 |
|---|---|
| `/tmp/p0l18/src/atlas_db.py` | `518278bf7c5309b34d14c24354f10828cbaa963ce21ea625d6d9988f33111830` |
| `/tmp/p0l18/src/atlas_intraday.py` | `f87071d3aa48741ec89618fc1c2fe19c684bb7906ac58861193be101eb966c29` |

Both: `python3 -m py_compile` → **PASS** (verified fresh, not relying on the
earlier P0L-18 result).

## 3. Production bad valuation_marks (confirmed current, NOT deleted)

| mark_id | lot_id | ticker | status |
|---|---|---|---|
| 1 | 53 | AAPL | CLOSED |
| 2 | 54 | PBXT | CLOSED |
| 3 | 55 | IBXT | CLOSED |
| 4 | 53 | AAPL | CLOSED |
| 5 | 54 | PBXT | CLOSED |
| 6 | 55 | IBXT | CLOSED |

**6 bad rows, 100% of the table** — unchanged from the P0L-18 audit.
Cleanup is explicitly out of scope for this deployment and has not been
touched.

## 4. Backup plan

1. `BACKUP_TAG=$(date -u +%Y%m%d_%H%M%S)_p0l19_predeploy`
2. `cp /Users/yasser/scripts/atlas_db.py /Users/yasser/scripts/archive/atlas_db.py_${BACKUP_TAG}.bak.py`
3. `cp /Users/yasser/scripts/atlas_intraday.py /Users/yasser/scripts/archive/atlas_intraday.py_${BACKUP_TAG}.bak.py`
4. `sha256sum` both backups — confirm each matches the §1 production baseline SHA exactly before touching either production file.
5. Archive directory writability already confirmed in P0L-15/P0L-16 (unchanged since).

## 5. Idle-window deployment plan (bounded poll)

**Current live state (checked at plan time): `atlas_intraday.py` IS
currently running** — PID `17986`, lock file `/tmp/atlas_intraday.lock`
present (created 23:00). Same live-blocker pattern as every prior P0L
code-deployment task (P0L-14, P0L-16).

**Planned execution sequence, mirroring the proven P0L-16 pattern exactly:**
1. Bounded idle poll: up to 12 minutes, 5-second interval.
2. Idle = no `atlas_intraday.py` process AND (`/tmp/atlas_intraday.lock`
   absent OR present-but-stale, age > ~500s, safely past the observed
   398–466s max runtime).
3. Do **not** take backups or copy files until idle is confirmed.
4. If no clean idle window appears within 12 minutes → **BLOCKED**, no
   files touched, report and stop (matching the first P0L-14 attempt's
   handling, not forcing through contention).
5. Once idle is confirmed, immediately re-verify (final gate, no delay)
   before backup, before copy, and immediately after copy — abort to
   rollback if a process appears at any of these checkpoints (matching the
   P0L-16 execution script's exact structure).

## 6. Deployment method (planned, not executed)

1. `cp /tmp/p0l18/src/atlas_db.py /Users/yasser/scripts/atlas_db.py`
2. `cp /tmp/p0l18/src/atlas_intraday.py /Users/yasser/scripts/atlas_intraday.py`
3. `sha256sum` both production files — confirm each now matches the §2 staged SHA exactly.

## 7. py_compile + pycache clear plan

1. `python3 -m py_compile /Users/yasser/scripts/atlas_db.py /Users/yasser/scripts/atlas_intraday.py` — expect clean PASS on the production copies (same content as staged, already compile-clean).
2. Clear stale bytecode caches for both module stems: standard `/Users/yasser/scripts/__pycache__/atlas_db*.pyc` / `atlas_intraday*.pyc`, plus any `~/Library/Caches/com.apple.python/**/atlas_db*.pyc` / `atlas_intraday*.pyc` matches (same sweep pattern used successfully in P0L-16, which found 60 total stale entries across historical staging paths).

## 8. Post-deploy smoke test plan (zero production DB writes)

All smoke tests are read-only imports, attribute checks, or static
source/AST scans of the deployed files — never DB writes, never forced
trades, never Telegram sends.

1. **Import check:** `python3 -c "import atlas_db"` from `/Users/yasser/scripts` — must succeed cleanly.
2. **Helper symbol checks:** confirm `hasattr(atlas_db, "_dualwrite_valuation_mark")`, `_bk_safe`, `_dualwrite_buy_fill`, `_dualwrite_sell_fill`, `record_manual_cash_correction` all still present post-deploy.
3. **Source check — no loop-index fallback:** scan the deployed `atlas_intraday.py`'s `_open_trades()` function body for `enumerate(rows` — must NOT be present (confirmed absent in staged file already; re-verify on the deployed copy). Additionally confirm `real_id_by_ticker` and the `resolved_trade_id = row.get("id") or row.get("trade_id") or real_id_by_ticker.get(t) or -1` line are present.
4. **Source check — valuation guard:** scan the deployed `atlas_db.py`'s `_dualwrite_valuation_mark()` function body for the literal guard clause `AND UPPER(ticker)=? AND status='OPEN'` — must be present (confirmed present in staged file; re-verify on deployed copy).
5. **Protected-file re-verification:** `grep -c "atlas_engine\|atlas_portfolio"` on deployed `atlas_db.py` (expect 0) and `atlas_intraday.py` (expect 3, byte-identical to backup via `diff`).
6. None of the above write to the real production `atlas.db`, call `confirm_trade_fill()`/`close_trade_broker_confirmed()`/`_cache_open_trade_prices()` against production, or trigger any Telegram send.

## 9. Rollback plan

1. `cp /Users/yasser/scripts/archive/atlas_db.py_${BACKUP_TAG}.bak.py /Users/yasser/scripts/atlas_db.py`
2. `cp /Users/yasser/scripts/archive/atlas_intraday.py_${BACKUP_TAG}.bak.py /Users/yasser/scripts/atlas_intraday.py`
3. `sha256sum` both restored files — confirm each matches the §1 baseline SHA exactly.
4. `python3 -m py_compile` both restored files — confirm clean pass.
5. Clear `__pycache__`/`com.apple.python` caches again (same paths as §7.2) so no stale post-rollback bytecode lingers.
6. No DB rollback needed — this deployment writes zero DB rows; the 6 bad `valuation_marks` rows remain untouched either way (cleanup is a separate future task).

## 10. Post-deploy expectation (for the next live cycle, observed read-only in a future task)

- The next scheduled `com.atlas.intraday` cycle should produce **up to 4**
  new `valuation_marks` rows — one each for SYNA (legacy id 18), RL (id 42),
  BAC (id 47), ABNB (id 48) — each correctly attached to its own `OPEN`
  `position_lots` row (63/64/65/66 respectively, per the P0L-18 test
  confirmation).
- **Zero** new marks should attach to the AAPL/PBXT/IBXT closed backfilled
  lots (53/54/55) — the exact defect this fix closes.
- If any resolvable ticker's lot lookup still fails for any reason, the
  defensive guard logs a `valuation_mark_lot_mismatch` WARN and skips rather
  than mismatching — so even an edge case is safe, just visible.
- No change to `trades`, `cash_ledger`, Telegram delivery, TFE, stops,
  targets, or exits is expected or introduced by this deployment.

## Cleanup deferred

**YES.** The 6 existing bad `valuation_marks` rows (and their 6 matching
stale `fallback_price_used` invariant rows) are explicitly **not** cleaned
up as part of this plan or deployment. The P0L-18 cleanup proposal remains
pending separate future authorization.

## Risks

| Risk | Assessment |
|---|---|
| Lock contention with a live `com.atlas.intraday` write cycle | **Confirmed currently present** — PID 17986 running at plan time. Mitigated by the same bounded-poll-then-abort pattern already proven twice (P0L-14 retry, P0L-16). |
| Stale bytecode cache masking the fix | LOW — mitigated by the explicit cache-clear step (§7.2), same pattern proven in P0L-16 (60 stale entries swept that time). |
| Fix introduces a new regression to legacy trade/cash logic | Very LOW — the P0L-18 diff only touches `_open_trades()`'s id-resolution logic and `_dualwrite_valuation_mark()`'s lot lookup; zero changes to any legacy `UPDATE`/`INSERT` statement, confirmed via the 14/14 regression pass plus the underlying diff being narrowly scoped. |
| Protected-file exposure | NIL — re-verified now at 0/0 for `atlas_engine`/`atlas_portfolio` in `atlas_db.py`, and the 3 pre-existing `atlas_portfolio` references in `atlas_intraday.py` confirmed byte-identical between production and staged via `diff`. |
| Stale marks remain visible/confusing until cleanup | Acceptable — explicitly deferred per this plan's scope; the marks are pure telemetry with no downstream consumer that trusts them blindly (confirmed in P0L-17: the report-snapshot manifest path already safely ignores them). |

## Conclusion

All preconditions for deployment are confirmed and ready: production file
SHAs match the untouched P0L-16 baseline, staged P0L-18 files are
fresh-compile-clean, both required source-level fixes (real trade-id
resolution, defensive ticker+status guard) are confirmed present in the
staged files via direct grep, and protected files remain untouched. The
only live blocker at plan time is a currently-running `atlas_intraday.py`
cycle (PID 17986) — execution must wait for a confirmed idle window per §5,
using the same bounded-poll pattern already proven twice.

**This plan requires Prof's explicit authorization before any execution
step is run.**
