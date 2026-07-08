# P0O-16: Fill-Time Revalidation Rule Design (Read-Only)

**Status:** READ-ONLY design document. No code/DB/production changes; no live strategy changes. `atlas_engine.py`/`atlas_portfolio.py` not edited — this design references only bounded function/path names already confirmed in P0O-15, never protected formulas/constants. Atlas remains orchestrator/renderer/messenger only; TFE remains the deterministic computation layer; Professor retains thesis approval and transaction authority — this document proposes a **rule design for Prof's review**, not an authorization to implement.

---

## 1. What Must Be Revalidated at Fill Time

Building directly on P0O-15's structural finding (current price/EMA and macro/regime ARE already re-checked live; score/signal/RVOL are NOT), the proposed rule adds exactly the fields P0O-15 identified as missing:

| Field | Current state (per P0O-15) | Proposed fill-time check |
|---|---|---|
| **Current signal label** | Stale (from arm-time `signal_result` snapshot) | Re-query the live `signals` table for the ticker's most recent row as of the fill-attempt timestamp; compare against the armed label |
| **Current pillar score** | Stale | Re-query the same live row's `score` field; compare against the armed score |
| **Current RVOL** | Stale | Re-query the same live row's `rvol` field; check against a minimum floor (not a new number invented here — this document proposes using the *same* threshold value already visible in the pillar gate's own volume sub-field logic, i.e. whatever RVOL floor already governs a live BUY-tier classification, not a new bespoke number) |
| **Current catalyst flag** | Partially re-fetched, but gated behind the stale pillar count | Make the catalyst re-fetch decision depend on the **freshly re-queried** pillar count instead of the stale one — a small but important sequencing fix within the same design |
| **Macro/regime state** | Already live (per P0O-15) | No change needed — already correct, continue passing fresh `regime` into the admission check unchanged |
| **Age since `armed_at`** | Governed only by a fixed calendar-day expiry + a price-distance expiry (both already existing, price/calendar-only) | Add an explicit, separate **signal-freshness age check**: if too much time has elapsed since `armed_at` relative to the ticker's own signal-refresh cadence, treat the armed snapshot as presumptively stale even before checking whether the current signal has literally changed label — this catches "the score number happens to still say 3/4 but is many hours old and last computed under very different conditions" cases that a label-only comparison could miss |

---

## 2. Proposed Outcomes

Four deterministic outcomes, matching the task's exact enum:

| Outcome | Meaning | Trigger condition (deterministic, non-formula) |
|---|---|---|
| **ALLOW_FILL** | Live signal state still supports the fill — proceed into the existing `consider_buy()` pipeline exactly as today | Current signal label is still BUY-tier (matching or exceeding the armed tier) AND current pillar score ≥ the minimum BUY-tier threshold AND current RVOL clears its floor AND age-since-armed is within the freshness window |
| **WAIT_STILL_ARMED** | Price hasn't reached the trigger yet — unchanged from today's existing WAIT path, no new logic needed here | Price has not yet touched the trigger (this path is untouched by this design — it's the existing behavior) |
| **EXPIRE_STALE_SIGNAL** | Price touched the trigger, but the signal is so stale/decayed that continuing to track it is pointless — remove the armed pullback entirely, similar to today's calendar/price expiry, but signal-driven | Current signal has fallen to AVOID (or below whatever floor Prof sets) AND/OR age-since-armed exceeds the freshness window, regardless of price | 
| **BLOCK_SIGNAL_DECAYED** | Price touched the trigger, and the signal has decayed but not all the way to full expiry-worthy AVOID — hold the armed row in place (don't delete it, don't fill it), report the block, let the next scan pass re-evaluate | Current signal has dropped from the armed tier (e.g. 4/4→2/4, or BUY→WATCH) but hasn't cleared the EXPIRE_STALE_SIGNAL threshold — a middle state distinct from both "still good" and "hopeless" |

**Design intent:** `EXPIRE_STALE_SIGNAL` is a terminal, DB-mutating outcome (row leaves the WAITING pool for good, mirroring the existing `expire_pending_pullback()` pattern). `BLOCK_SIGNAL_DECAYED` is non-terminal — the row stays WAITING, gets re-evaluated next pass, and simply doesn't fill *this* pass. This distinction matters so a temporarily-dipping signal (e.g., RVOL momentarily below floor on a single scan tick) isn't punished as harshly as a signal that has genuinely reversed to AVOID.

---

## 3. Conservative Default Behavior When Live Signal Data Is Missing

If the fresh `signals` table query returns no row (or a row too old to trust) for the ticker at fill-attempt time:

- **Default to `BLOCK_SIGNAL_DECAYED`, never `ALLOW_FILL`.** The absence of fresh data is not evidence the signal is still good — treat it the same as a decayed-but-not-yet-expired state. This is the conservative direction consistent with the existing codebase's general posture (e.g., P0O-9's exclusion-rule design, P0O-13's "never fabricate" principle) — when in doubt, don't act, don't lose the armed state either.
- **Do not auto-expire on missing data alone** — a missing signal row could simply mean the scan cadence hasn't run yet this cycle, not that the setup is actually dead. Auto-expiring on a transient data gap would be overly aggressive and could discard a genuinely-still-valid armed pullback due to a scan-timing artifact rather than real signal decay.
- **Log/flag distinctly** (see reason codes below) so this "missing data" case is visibly different from a "checked and confirmed decayed" case — important for future debugging and for any TFE recommendation model that might want to treat these differently.

---

## 4. Reason Codes

Deterministic, enumerated strings for every outcome (mirroring the existing codebase's reason-string convention already visible in `check_admission`'s `why` return and the various `SKIP`/`BLOCK` reasons in `consider_buy`/gap-breakout/sector-sweep paths):

| Reason code | Outcome | Meaning |
|---|---|---|
| `FILL_REVALIDATION_PASSED` | ALLOW_FILL | All 4 live checks (signal label, score, RVOL, age) passed |
| `FILL_STILL_WAITING_PRICE_NOT_TRIGGERED` | WAIT_STILL_ARMED | Unchanged — existing wait reasoning, no revalidation needed yet |
| `FILL_EXPIRED_SIGNAL_AVOID` | EXPIRE_STALE_SIGNAL | Live signal has fallen all the way to AVOID |
| `FILL_EXPIRED_SIGNAL_AGE_EXCEEDED` | EXPIRE_STALE_SIGNAL | Age since `armed_at` exceeded the freshness window, independent of current label |
| `FILL_BLOCKED_SIGNAL_DECAYED_SCORE` | BLOCK_SIGNAL_DECAYED | Current pillar score has dropped from the armed tier but hasn't hit AVOID |
| `FILL_BLOCKED_SIGNAL_DECAYED_RVOL` | BLOCK_SIGNAL_DECAYED | Current RVOL has fallen below the live-BUY floor |
| `FILL_BLOCKED_LIVE_DATA_MISSING` | BLOCK_SIGNAL_DECAYED | No fresh `signals` row found (or too old to trust) — conservative default per Section 3 |
| `FILL_BLOCKED_CATALYST_NO_LONGER_PRESENT` | BLOCK_SIGNAL_DECAYED | (Optional/secondary) live catalyst re-check, sequenced correctly per Section 1's fix, no longer qualifies |

Every outcome carries its reason code plus the actual current values (score, signal label, RVOL, age-in-hours) in the returned decision dict, matching the existing pattern of attaching diagnostic fields (`rvol`, `score`, `signal`) to decision dicts already visible in `evaluate_pending_pullback`'s return values (per P0O-15).

---

## 5. Avoiding Any Touch to Broker Flow or Existing Stop Logic

- **Scope confinement:** this rule only affects the **gate that decides whether an armed pullback's price-trigger touch is treated as fill-worthy** — it sits strictly between the existing price-vs-trigger check (`_pullback_state()`, unchanged) and the existing `consider_buy()` call (unchanged internally). It does not touch:
  - `evaluate_exit()`, `run_exits()`, or any mechanical stop-hit logic (completely separate code path, per P0O-1's original pipeline map)
  - `mark_pending_pullback_filled()` itself (unchanged — still only called after a BUY decision, exactly as today)
  - Any broker-reconciliation, cash-ledger, or bookkeeping table (zero relation to this gate)
  - Sizing/admission math inside `consider_buy()`/`check_admission()` (unchanged — this rule only decides whether to *call* `consider_buy()` at all, not how it computes size/admission once called)
- **New logic is purely additive and pre-emptive**: if the revalidation gate returns `ALLOW_FILL`, execution proceeds into today's exact unchanged pipeline. If it returns anything else, `consider_buy()` is simply never invoked this pass — a strict superset-safe insertion, not a modification of existing decision math.
- **No change to the mechanical stop path at all** — that remains entirely Prof's separately-approved, always-on safety net, untouched by this proposal.

---

## 6. Files/Functions Likely Affected Later (Not Implemented Here)

| File | Role | Protected? |
|---|---|---|
| `atlas_portfolio.py` | `evaluate_pending_pullback()` would need the new revalidation gate inserted between the price-trigger check and the `consider_buy()` call | **YES — protected, requires a direct Prof work order under the Standing Alpha-Work Override before any edit** |
| `atlas_db.py` | Likely needs one new read-only helper, e.g. `get_latest_signal(ticker, as_of=None)`, to fetch the freshest `signals` row for fill-time comparison — this is new, additive, unprotected | No |
| `atlas_manage.py` | Possibly needs to pass an explicit "as-of" timestamp or freshness-window config value into the pullback evaluation call, if that becomes a runtime parameter rather than a constant — TBD at implementation time | No |

No other files are expected to need changes for this specific rule — it is deliberately scoped to the single fill-time gate identified in P0O-15.

---

## Answers to Structured Fields

- **P0O16_STATUS:** RULE_DESIGN_COMPLETE — read-only design, zero implementation, zero protected-file edits
- **proposed_revalidation_rule:** At the moment an armed pullback's trigger price is touched, before calling `consider_buy()`, re-query the live `signals` table for the ticker's freshest row; require current signal label ≥ armed tier, current pillar score ≥ BUY-tier minimum, current RVOL ≥ the same floor already used for live BUY classification, and age-since-`armed_at` within a freshness window — all 4 conditions must pass for `ALLOW_FILL`; otherwise route to `WAIT_STILL_ARMED` (price not yet touched — unchanged), `BLOCK_SIGNAL_DECAYED` (partial decay or missing data), or `EXPIRE_STALE_SIGNAL` (full decay to AVOID or age exceeded)
- **required_current_fields:** current signal label, current pillar score, current RVOL, current catalyst flag (secondary, sequencing-fixed), macro/regime state (already live, unchanged), age since `armed_at`
- **allowed_outcomes:** `ALLOW_FILL`, `WAIT_STILL_ARMED` (unchanged existing path), `EXPIRE_STALE_SIGNAL` (terminal, DB-mutating), `BLOCK_SIGNAL_DECAYED` (non-terminal, re-evaluated next pass)
- **missing_data_behavior:** Default to `BLOCK_SIGNAL_DECAYED` (reason `FILL_BLOCKED_LIVE_DATA_MISSING`) — never `ALLOW_FILL` on missing data; never auto-expire on missing data alone, since that could be a transient scan-timing gap rather than genuine decay
- **reason_codes:** `FILL_REVALIDATION_PASSED`, `FILL_STILL_WAITING_PRICE_NOT_TRIGGERED`, `FILL_EXPIRED_SIGNAL_AVOID`, `FILL_EXPIRED_SIGNAL_AGE_EXCEEDED`, `FILL_BLOCKED_SIGNAL_DECAYED_SCORE`, `FILL_BLOCKED_SIGNAL_DECAYED_RVOL`, `FILL_BLOCKED_LIVE_DATA_MISSING`, `FILL_BLOCKED_CATALYST_NO_LONGER_PRESENT`
- **likely_files_later:** `atlas_portfolio.py` (protected — houses `evaluate_pending_pullback()`, the actual insertion point), `atlas_db.py` (new unprotected read-only helper for fetching the freshest live signal row), `atlas_manage.py` (possible freshness-window parameter wiring)
- **protected_work_order_needed:** YES — any actual implementation touches `evaluate_pending_pullback()` inside `atlas_portfolio.py`, which requires an explicit Prof work order under the Standing Alpha-Work Override (with the standard staging-first, backup, compile-check, dry-run-verification protocol) before any edit proceeds
- **production changes:** NONE
