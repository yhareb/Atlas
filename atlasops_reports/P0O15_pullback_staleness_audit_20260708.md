# P0O-15: Pullback Fill Staleness-Path Audit (Read-Only)

**Status:** READ-ONLY structural audit. No code/DB/production changes; no strategy changes. `atlas_portfolio.py` is protected — only bounded function/path names and high-level control flow are reported below; zero scoring formulas, thresholds, or numeric constants from protected logic are disclosed. Atlas remains orchestrator/renderer only; this is an analysis artifact for Prof's review, not a TFE decision.

---

## 1. Files/Functions Involved

| Stage | File | Function (name/path only) | Protected? |
|---|---|---|---|
| **Arm** | `atlas_db.py` | `upsert_pending_pullback(...)` — inserts/updates a row with `status='WAITING'`, storing `score`, `signal`, `signal_result` (JSON), `armed_at`, `expires_at`, `ema10`, `trigger_price`, `reference_price`, `pct_over_ema` | No |
| **Read (active)** | `atlas_db.py` | `get_pending_pullback(ticker)` (single, WAITING-only by default), `get_pending_pullbacks(status="WAITING")` (bulk) | No |
| **Fill (status transition)** | `atlas_db.py` | `mark_pending_pullback_filled(ticker)` — `UPDATE ... SET status='FILLED', filled_at=... WHERE ticker=? AND status='WAITING'` | No |
| **Expire** | `atlas_db.py` | `expire_pending_pullback(ticker)` — `UPDATE ... SET status='EXPIRED' ...` | No |
| **Decision orchestration** | `atlas_manage.py` | Calls `_expire_stale_pending_pullbacks(pending_rows, live=..., threshold=0.07, ...)` (price-distance-based expiry, not signal-based) each scan pass; routes each WAITING row into `port.evaluate_pending_pullback(...)` | No |
| **Core fill-decision logic** | `atlas_portfolio.py` | `evaluate_pending_pullback(ticker, dry_run, regime, pending, reserved_cash)` — **the actual gate that decides WAIT vs. BUY vs. EXPIRE for an armed pullback** | **Yes (protected)** |
| **Price/trigger state check** | `atlas_portfolio.py` | `_pullback_state(ticker)` — bounded name only; computes current price relative to the stored EMA/trigger | **Yes (protected)** |
| **Buy execution path** | `atlas_portfolio.py` | `consider_buy(signal_result, dry_run, regime, pending, reserved_cash, pullback_override_entry, pullback_override_reason, manage_pending)` — the shared entry pipeline also used by non-pullback paths | **Yes (protected)** |
| **Admission gate** | `atlas_portfolio.py` | `check_admission(ticker, regime, pending)` — regime/cap/concentration-style admission check, called from inside `consider_buy` | **Yes (protected)** |

---

## 2. High-Level Control Flow (Bounded — No Formulas Disclosed)

1. `atlas_manage.py`'s scan loop calls `_expire_stale_pending_pullbacks()` first — this expires WAITING rows **purely on price distance** (if live price has moved too far above the armed trigger, expressed as a distance threshold), not on signal staleness.
2. For every remaining WAITING row, `atlas_manage.py` calls `atlas_portfolio.evaluate_pending_pullback(ticker, ...)`.
3. Inside `evaluate_pending_pullback` (bounded description of control flow only):
   - First checks calendar-day expiry (`expires_at` vs. today) → `EXPIRE` action if past.
   - Calls `_pullback_state(ticker)` to get the **current** price/EMA state (this part IS live/fresh — current price is re-fetched).
   - **Compares current price against the trigger price** (the same static number stored at arm time) — if price has pulled back to/through that trigger, proceeds toward a BUY attempt.
   - Builds a `sig` dict via `row.get("signal_result")` — **this is the JSON blob stored in the DB at arm time**, not a freshly recomputed signal.
   - Passes that `sig` dict into `consider_buy(sig, ...)`, which re-derives `pillars` from `sig`'s own `score` field (defaulting to `"3/4 Pillars"` if missing) and runs the shared admission/sizing pipeline.
   - If the resulting action is `BUY` and not a dry run, calls `atlas_db.mark_pending_pullback_filled(ticker)`.

**Key structural fact:** the price-vs-trigger check is live (current price is fetched fresh each pass), but **the score/signal/RVOL/catalyst values fed into the admission and sizing decision come from the stale arm-time snapshot stored in `signal_result`, not from a fresh signal recompute at fill time.**

---

## 3. Fields Re-Validated at Fill Time — Explicit Check

| Field | Re-validated fresh at fill? | Evidence |
|---|---|---|
| **Current price / EMA state** | **YES** | `_pullback_state(ticker)` fetches current price/EMA fresh each evaluation pass |
| **Pillar score** | **NO** | `sig.setdefault("score", row.get("score") or "3/4 Pillars")` — pulls from the stored arm-time value (or a hardcoded default), never re-queries the live `signals` table |
| **Signal label** (BUY/WATCH/AVOID) | **NO** | Same pattern — `sig.setdefault("signal", row.get("signal") or "")`, stale value only |
| **RVOL** | **NO** | `decision.setdefault("rvol", sig.get("rvol"))` — pulled from the same stale `signal_result` blob |
| **Catalyst status** | **PARTIALLY** | `fundamentals`/`fda_calendar`/`indicator_info` ARE conditionally re-fetched live (`check_fundamentals(ticker)`, `check_massive_indicators(ticker)`, `check_fda_calendar(...)`) if the stale row's pillar count was ≥3 — but this re-fetch is gated by the STALE pillar count, not by a fresh one, so a ticker whose live catalyst status has since expired can still pass if the old stored score was ≥3 |
| **Sector-relative state** | **NO explicit check found** in this function; sector-relative logic exists elsewhere in the codebase (per P0O-9/P0O-12) but is not visibly invoked inside `evaluate_pending_pullback` |
| **Macro/regime state** | **YES (partially)** | `check_macro_context()` IS called fresh and attached to the returned decision dict, and `regime` is passed into `consider_buy` → `check_admission`, which is regime-aware — this is the one dimension that IS re-validated live |

---

## 4. Can a Stale Armed Trigger Still Fill After Signal Decay to WATCH/AVOID?

**YES.** The price-vs-trigger check that decides *whether* to attempt a fill is entirely price-based and has no dependency on the current live signal state. The pillar-count/score gate that decides *whether the resulting attempt is admitted as a BUY* reads from the same stale `signal_result` snapshot — so if that snapshot said "3/4 Pillars" at arm time, the fill attempt still presents as pillar-qualified even if the ticker's live signal has since fallen to WATCH (2/4) or AVOID (1/4) in the `signals` table. This structurally confirms the exact mechanism suspected in P0O-14: **a stale armed trigger can and does fill against decayed conditions, because nothing in this path re-queries the live `signals` table for score/signal/RVOL before treating the trigger touch as actionable.**

---

## 5. Comparison Against P0O-14 Finding

P0O-14 found (empirically, from replay data) that 10 of 14 signal-only FILLED pullbacks had a live signal of WATCH or AVOID at the moment of fill, with a median time-to-fill of ~47 hours. This audit's structural review **fully explains that empirical finding**: there is no code path between arming and filling that re-checks the live signal table. The only fresh checks at fill time are (a) current price vs. the static trigger, (b) calendar-day expiry, (c) regime/macro context, and (d) a price-distance-based staleness expiry in `atlas_manage.py` (7% threshold, price-only). None of these substitute for re-validating the pillar score/signal/RVOL that originally justified arming the trigger.

---

## Answers to Structured Fields

- **P0O15_STATUS:** AUDIT_COMPLETE — structural root cause confirmed, matches P0O-14's empirical finding exactly
- **pullback_arm_path:** `atlas_db.py::upsert_pending_pullback()` — called from `atlas_manage.py`'s scan loop when a fresh signal qualifies; stores `score`/`signal`/`signal_result` snapshot + `trigger_price`/`ema10`/`armed_at`/`expires_at`, status set to `WAITING`
- **pullback_fill_path:** `atlas_manage.py` scan loop → `atlas_portfolio.py::evaluate_pending_pullback()` (protected) → `_pullback_state()` (protected, live price/EMA check) → `consider_buy()` (protected, uses stale `signal_result`) → on BUY+live, `atlas_db.py::mark_pending_pullback_filled()` flips status to `FILLED`
- **protected_files_involved:** YES — `atlas_portfolio.py` contains the actual fill-decision logic (`evaluate_pending_pullback`, `_pullback_state`, `consider_buy`, `check_admission`); only bounded function names and control flow reported, zero formulas/thresholds disclosed
- **fill_time_revalidation_exists:** YES, but PARTIAL — current price/EMA and macro/regime context ARE re-checked fresh at fill time; pillar score, signal label, and RVOL are NOT — they are read from the stale arm-time snapshot
- **fields_revalidated_at_fill:** Current price, current EMA state, macro/regime context (via `check_macro_context()` and `check_admission()`'s regime parameter); catalyst-related fields (`fundamentals`, `fda_calendar`, `indicator_info`) are conditionally re-fetched but gated behind the STALE pillar count, not a fresh one
- **stale_trigger_possible:** YES — confirmed structurally; a trigger armed while a ticker was 3/4 or 4/4 pillars can fill days later purely on price touching the static trigger level, carrying forward the same stale score/signal/RVOL values into the admission/sizing decision regardless of what the live `signals` table currently shows
- **TTL_or_max_age_exists:** YES, but PRICE-based and CALENDAR-based only, not SIGNAL-based — (a) `expires_at` gives a fixed calendar-day expiry (confirmed 3-day pattern from P0O-13/14 data), and (b) `atlas_manage.py::_expire_stale_pending_pullbacks()` expires a WAITING row if live price has moved more than a fixed distance threshold above the trigger — neither mechanism checks whether the underlying signal itself has decayed
- **likely_gap:** No fill-time re-query of the live `signals` table for current score/signal/RVOL before admitting a pullback fill as pillar-qualified — the exact mechanism identified in P0O-14, now structurally confirmed at the code-path level
- **files_likely_involved_later:** `atlas_portfolio.py` (protected — `evaluate_pending_pullback`, possibly `consider_buy`), `atlas_db.py` (possible new read helper for live signal lookup), `atlas_manage.py` (orchestration of any new re-validation step) — any actual change here requires a direct Prof work order per the Standing Alpha-Work Override, since it touches protected fill/admission logic
- **recommendation_for_next_phase:** This remains a Prof decision. Two non-exclusive options: (a) Prof issues a bounded, explicit work order to review/patch the fill-time revalidation gap in `atlas_portfolio.py` under the existing protected-file override protocols (backups, compile checks, dry-run verification per standing rules), or (b) Prof treats this as a known, documented characteristic of the current pullback mechanism and proceeds with TFE recommendation-model design carrying this caveat forward (e.g., the future TFE model could independently re-score any fill candidate before rendering a recommendation, without needing to touch the existing arm/fill mechanism at all). No fix is proposed or implied here.
- **production changes:** NONE
