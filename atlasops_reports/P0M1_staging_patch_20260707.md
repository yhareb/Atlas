# P0M-1 — STAGING-ONLY Pending Broker-Confirmation Report Patch

**Date:** 2026-07-07/08
**Scope:** STAGING ONLY. No production patch/deploy/DB writes/strategy/TFE/routing/scheduler/env/Telegram/stops/targets/exits changes. `atlas_engine.py`/`atlas_portfolio.py` never touched.

## Staging Setup
- Copied production `atlas.db` → `/tmp/p0m1/atlas_copy_p0m1.db`
- Copied source files → `/tmp/p0m1/src/`: `atlas_db.py`, `atlas_intraday.py`, `atlas_eod_positions.py`, `atlas_macro_postmarket.py` — all confirmed byte-identical to production before any edit.
- Also copied (unmodified, import-resolution only, NOT part of this patch): `atlas_notify.py`, `atlas_symbol_meta.py`, `atlas_report_blocks.py`, `atlas_schemas.py` — all diff-confirmed byte-identical to production.
- `atlas_portfolio.py` and `atlas_engine.py` were **never copied into staging** — deliberately excluded; a live-render test correctly failed to import `atlas_portfolio` (expected, since it's out of scope and untouched).

## Patch Applied (staging only)

### `atlas_db.py`
Added one new read-only helper, `get_pending_broker_confirmation_trades(limit=500)`, inserted directly after `get_trades()`. Queries `trades` for `status='CLOSED' AND broker_ref IS NOT NULL AND broker_ref != '' AND entry_price != exit_price`, then excludes any trade with a `BROKER_SELL_FILLED` journal event or a matching `"Broker sell <TICKER>"` cash_ledger credit. Pure SELECT — no writes.

### `atlas_eod_positions.py`
Added `_pending_broker_confirmation_lines()` and inserted `lines.extend(_pending_broker_confirmation_lines())` into `build_report()` immediately after the existing `holding_block(...)` call — `HOLDING` logic itself untouched.

### `atlas_intraday.py`
Added `_pending_broker_confirmation_lines(summary=None)` and inserted `lines += _pending_broker_confirmation_lines(summary)` into `_build_report()` immediately after `_holding_lines(summary)` — `_holding_lines`/`_open_trades` untouched.

⚠️ **Self-caught error during patching (transparency note):** an initial `patch` call on `atlas_intraday.py` accidentally replaced (rather than added alongside) the `_buy_now_lines(...)` call in the report assembly. Caught immediately via post-patch `diff` against the production baseline, corrected in the same turn before any compile/test step, and the corrected diff was re-verified clean. No stale/broken state was ever tested or would have reached production.

## Diff Verification (staged vs. production baseline)
- `atlas_db.py`: clean additive diff, +48 lines, 0 removed/altered lines elsewhere.
- `atlas_eod_positions.py`: clean additive diff, +33 lines, 0 removed/altered lines elsewhere.
- `atlas_intraday.py`: clean additive diff, +34 lines total (33 new function + 1 call site), 0 removed/altered lines elsewhere (after the self-corrected fix above).
- `atlas_macro_postmarket.py`: **zero diff** — byte-identical, confirmed untouched.

## Compile
`python3 -m py_compile atlas_db.py atlas_intraday.py atlas_eod_positions.py atlas_macro_postmarket.py` → exit code 0, all 4 files compile clean.

## Live Render Tests (against staged DB copy, staged code — zero production DB/network writes)

### Direct helper test
```
pending count: 1
  id=16 ticker=INTC broker_ref=P780203310 entry=129.78 exit=112.12
```
Exactly INTC. Zero false positives (AAPL/PBXT/IBXT correctly excluded via the `broker_ref IS NOT NULL` filter — their `broker_ref` is NULL). Zero false negatives (all other CLOSED trades — TSM/LRCX/MS/KLIC/IRDM/ALGM/MSM — correctly excluded because each has a confirmed `BROKER_SELL_FILLED` event or matching cash_ledger credit).

### EOD Positions report (rendered via `build_report()` against staged DB)
```
━━━ 💼 HOLDING (4) ━━━
1. SYNA  2. RL  3. BAC  4. ABNB   (unchanged format/values)

━━━ ⏳ SELL TRIGGERED / BROKER CONFIRMATION PENDING (1) ━━━
⚠️ INTC
   🚦 Exit trigger: $112.12 (stop $113.02)
   🕐 Triggered: 2026-07-07 17:10:22
   📊 Est. P/L: −$136 (−13.6%)
   broker_confirmed: NO
   cash_credit: NO
```

### Intraday report (rendered via `_build_report(summary)` against staged DB, minimal synthetic summary to avoid live network calls)
Same result — `HOLDING (4)` section unchanged, new `⏳ SELL TRIGGERED / BROKER CONFIRMATION PENDING (1)` section shows exactly INTC with identical fields. Module-load asserted to originate from `/tmp/p0m1` (not production) before rendering, to guarantee the test exercised the staged code, not the live files.

## Non-Scope Confirmations
- **Existing HOLDING logic unchanged:** both `holding_block()` calls (EOD) and `_holding_lines()`/`_open_trades()` (intraday) are called exactly as before, with no signature or behavior change — confirmed via diff (zero lines altered in those functions) and via matching rendered output (SYNA/RL/BAC/ABNB values identical pre/post-patch).
- **Trade status lifecycle untouched:** the new helper is a pure SELECT; no `UPDATE`/`INSERT`/`DELETE` anywhere in the new code.
- **Macro postmarket untouched:** zero diff, confirmed via direct file comparison.
- **Protected files untouched:** `atlas_engine.py`/`atlas_portfolio.py` mtimes remain Jul 2 (pre-dating this task entirely); neither was ever copied into `/tmp/p0m1/src/`.
- **Production files/DB unchanged:** all 5 production file SHA256s re-verified identical to the pre-staging baseline captured at task start.
- **No Telegram sent during tests:** all renders called `build_report()` / `_build_report()` directly in-process; `send_telegram()` was never invoked.

---

## Return Fields

- **P0M1_STATUS:** PASS
- **staged_files:** `/tmp/p0m1/src/atlas_db.py`, `/tmp/p0m1/src/atlas_intraday.py`, `/tmp/p0m1/src/atlas_eod_positions.py` (patched); `/tmp/p0m1/src/atlas_macro_postmarket.py` (copied, confirmed unmodified)
- **compile_result:** PASS (all 4 files, exit code 0)
- **INTC_visible_in_intraday_pending_section:** YES
- **INTC_visible_in_EOD_pending_section:** YES
- **artifacts_excluded:** YES (AAPL/PBXT/IBXT absent from both rendered reports and from the direct helper query — confirmed via `broker_ref IS NOT NULL` filter correctly rejecting their NULL broker_ref)
- **existing_HOLDING_logic_unchanged:** YES
- **macro_postmarket_untouched:** YES (zero-diff, byte-identical)
- **protected_files_untouched:** YES (mtimes unchanged, never copied into staging)
- **production_files_unchanged:** YES (all SHA256s match pre-task baseline)
- **production_db_unchanged:** YES (SHA256 matches pre-task baseline)
- **ready_for_production_patch_review:** YES
- **production changes:** NONE
