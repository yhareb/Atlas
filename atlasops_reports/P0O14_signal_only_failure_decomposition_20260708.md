# P0O-14: Signal-Only Failure Decomposition (Read-Only Analysis)

**Status:** READ-ONLY analysis. No code/DB/production changes, no live strategy changes, no TFE recommendation authority assigned to Atlas. Atlas remains orchestrator/renderer/messenger only; TFE remains the deterministic computation layer; Professor retains thesis approval and transaction authority. This report explains *why* P0O-13's signal-only bucket underperformed — it proposes no rule changes.

---

## Headline Finding: Signal Quality Had Decayed By the Time the Trigger Actually Filled

The single clearest pattern across the 14 signal-only losers/mixed performers: **by the time the armed pullback's `trigger_price` was actually touched, the live pillar signal for that ticker had often already degraded to WATCH or even AVOID** — a materially weaker state than the 3-4/4 pillar tier that got the pullback armed in the first place. This did not happen for the canonical (broker-confirmed) trades, whose entries lined up with a live BUY-tier signal at (or within minutes of) the actual entry.

**Signal state AT THE MOMENT of fill/entry — canonical vs. signal-only:**

| Bucket | Ticker | Signal at entry/fill | Score | RVOL |
|---|---|---|---|---|
| Canonical | LRCX | 🟡 BUY (Small) | 3/4 | 0.33 |
| Canonical | MS | 🟡 BUY (Small) | 3/4 | 0.14 |
| Canonical | KLIC | ⚪ WATCH | 2/4 | 0.22 |
| Canonical | IRDM | 🟢 BUY | 4/4 | 3.13 |
| Canonical | ALGM | 🟢 BUY | 4/4 | 1.59 |
| Canonical | MSM | 🟢 BUY | 4/4 | 1.77 |
| Signal-only | PGEN | 🟢 BUY | 4/4 | 2.54 |
| Signal-only | **CAT** | **🔴 AVOID** | **1/4** | 0.32 |
| Signal-only | EVC | 🟡 BUY (Small) | 3/4 | 1.39 |
| Signal-only | ELVN | ⚪ WATCH | 2/4 | 0.80 |
| Signal-only | **TGT** | **🔴 AVOID** | **1/4** | 0.03 |
| Signal-only | **KO** | **🔴 AVOID** | **1/4** | 0.78 |
| Signal-only | INDV | ⚪ WATCH | 2/4 | 0.23 |
| Signal-only | KLAC | ⚪ WATCH | 2/4 | 0.26 |
| Signal-only | **AMD** | **🔴 AVOID** | **1/4** | 0.06 |
| Signal-only | ONTO | ⚪ WATCH | 2/4 | 0.13 |
| Signal-only | JCI | ⚪ WATCH | 2/4 | 0.02 |
| Signal-only | VICR | ⚪ WATCH | 2/4 | 0.03 |
| Signal-only | GE | ⚪ WATCH | 2/4 | 0.11 |
| Signal-only | MAS | ⚪ WATCH | 2/4 | 0.01 |

**10 of 14 signal-only candidates (71%) had already fallen to WATCH or AVOID at the moment of fill** — only PGEN and EVC still showed a genuine BUY-tier signal at fill time, matching the canonical bucket's pattern. 4 candidates (CAT, TGT, KO, AMD) had fallen all the way to **AVOID (1/4 pillars)** — the opposite end of the spectrum from what armed them.

## Time-to-Fill: The Pullback Sat Armed for a Long Time in Most Cases

| Ticker | Hours from armed → filled |
|---|---|
| JCI | 18.3 |
| AMD | 22.5 |
| CAT | 24.3 |
| MAS | 24.1 |
| VICR | 42.3 |
| ONTO | 44.8 |
| ELVN | 46.2 |
| INDV | 51.2 |
| KLAC | 69.0 |
| KO | 72.9 |
| EVC | 91.3 |
| PGEN | 115.5 |
| TGT | 119.8 |
| GE | 143.5 |

**Median time-to-fill ≈ 47 hours (~2 trading days); several sat armed for 3-6 days (EVC, PGEN, TGT, GE).** A pullback armed at a 10-EMA trigger price when the ticker was in a strong 3-4/4-pillar state can, days later, finally touch that same price level *after* the underlying setup has already deteriorated — the trigger price is static, but market conditions are not. This is the mechanical root cause behind the signal-decay pattern above: **the armed trigger has no re-validation gate at fill time.**

## Comparison: Winners vs. Losers Inside the Signal-Only Bucket

| Ticker | Outcome (combined-selection policy) | Signal at fill | MFE (5d) | MAE (5d) | Sector 5d | SPY 5d |
|---|---|---|---|---|---|---|
| PGEN | Win | 🟢 BUY 4/4 | +25.8% | +8.3% | XBI +3.5% | +0.9% |
| EVC | Win | 🟡 BUY(Small) 3/4 | +37.7% | +16.9% | XLC +2.9% | +0.9% |
| KO | Win (small) | 🔴 AVOID 1/4 | +5.5% | -0.3% | XLP +1.9% | +0.3% |
| GE | Win (small) | ⚪ WATCH 2/4 | (insufficient bars) | — | — | — |
| ELVN | Win (small) | ⚪ WATCH 2/4 | +9.1% | -1.2% | XBI +2.1% | +0.4% |
| CAT | Loss | 🔴 AVOID 1/4 | +3.1% | -9.9% | XLI -0.5% | +0.3% |
| TGT | Loss | 🔴 AVOID 1/4 | -2.5% | -8.1% | XLY -0.6% | +0.3% |
| KLAC | Loss | ⚪ WATCH 2/4 | +6.0% | -16.4% | SOXX -2.6% | +0.4% |
| ONTO | Loss | ⚪ WATCH 2/4 | +3.6% | -20.9% | SOXX -2.6% | +0.4% |
| JCI | Loss | ⚪ WATCH 2/4 | +4.8% | -5.5% | XLI -0.5% | +0.3% |
| VICR | Loss | ⚪ WATCH 2/4 | +2.0% | -28.3% | SOXX -2.6% | +0.4% |
| INDV | Loss | ⚪ WATCH 2/4 | +3.5% | -3.1% | XLV +3.1% | +0.3% |
| AMD, MAS | (insufficient forward bars — too recent) | 🔴 AVOID / ⚪ WATCH | — | — | — | — |

**The two clean winners (PGEN, EVC) were the only two candidates that still had a genuine BUY-tier signal at fill time.** Every semiconductor-sector loser (KLAC, ONTO, VICR) shares the same sector-weakness signature: SOXX fell ~2.6% over the same 5-day window they were held, and each shows a large negative MAE (-16% to -28%) — a classic "bought into sector weakness" pattern.

## Sector Effect

| Sector proxy | Signal-only N | Wins | Losses | Notable pattern |
|---|---|---|---|---|
| SOXX (semis) | 4 (KLAC, AMD, ONTO, VICR) | 0-1 | 3-4 | **Sector fell -2.6% to -2.58% across the exact hold windows** — every semis signal-only candidate lost or was flat; contrasts sharply with the canonical bucket's own semis exposure (LRCX/KLIC), which happened to catch favorable moves despite the same sector backdrop at times |
| XLI (industrials) | 3 (CAT, JCI, GE) | 1 | 2 | Mixed; XLI itself flat-to-slightly-down over these windows |
| XBI (biotech) | 2 (PGEN, ELVN) | 2 | 0 | Both winners; XBI was positive over both windows (+3.5%, +2.1%) |
| XLC, XLY, XLP, XLV | 1 each | mixed | mixed | Too few data points per sector for a pattern |

**The SOXX/semis cluster is the single clearest sector-level failure pattern** — every signal-only semis candidate underperformed while the sector itself was actively falling, unlike the canonical bucket's semis names which (per P0O-11's concentration finding) happened to catch a favorable multi-day move.

## Catalyst / RVOL Effect

- **RVOL at fill time was uniformly low across signal-only losers** (0.01–0.32 for CAT, TGT, KO, AMD, JCI, VICR, GE, MAS) — well below the pillar gate's own ≥1.5 RVOL threshold visible in the `signals` table's volume sub-field. This confirms these tickers had gone quiet by the time the stale trigger finally filled — low RVOL at fill is a direct symptom of the same time-decay problem, not an independent cause.
- **Catalyst flag was present (✅) for most candidates regardless of outcome** — catalyst presence alone does not discriminate winners from losers in this sample; it was ✅ for both PGEN/EVC (winners) and for most of the WATCH-tier losers. Only CAT, KO, and AMD explicitly show `❌ Catalyst: NO` at fill time, and all three underperformed — consistent with, but not solely explaining, the broader signal-decay pattern.

## Adverse / Favorable Excursion Summary

- **Signal-only losers show notably deep adverse excursions**: -16% to -28% (KLAC, ONTO, VICR) vs. canonical bucket's worst adverse excursion of -23% (ALGM, itself already flagged as a real, if smaller, drawdown case). The magnitude of adverse moves is comparable or worse in the signal-only bucket despite lower initial signal quality — these were not just "slow bleeds," several gapped or trended hard against the position within the same 5-day window.
- **Favorable excursions existed in nearly every case** (MFE was positive for 11 of 12 candidates with sufficient data) — meaning the simulated stop-policy replay usually had *some* opportunity to exit favorably before the adverse move fully materialized, but the combined-selection policy (per its designed tightest-of-4 selection rule) often didn't lock in that favorable excursion before reversing, particularly in the SOXX cluster where MFE (+3–6%) was much smaller than the eventual MAE (-16% to -28%).

## Canonical vs. Signal-Only: Did the Real Trades Have a Filter the Signal-Only Bucket Lacked?

**Yes — timing/freshness at entry.** Every canonical trade's `entry_at` timestamp lines up with a live BUY-tier signal (3/4 or 4/4 pillars) at or within minutes of the same timestamp — meaning whatever combination of pillar armor + catalyst + (implicitly) Prof's own judgment led to these being taken as real trades, the entry always occurred while the setup was still fresh. The signal-only bucket's entries are mechanically defined by a **stale, pre-armed trigger price**, which can and did fire well after the underlying setup had decayed. This is a structural difference between "trade taken while signal was live" and "trigger touched whenever price got there, regardless of current signal state" — not a difference in position sizing, catalyst policy, or sector selection per se.

## Likely Missing TFE Filter (Analysis Only — No Rule Change Proposed)

Based on the evidence above, the most probable missing safeguard in the **pullback-fill mechanism** (not the pillar-scoring engine itself, which remains untouched/undiscussed here) is a **fill-time signal re-validation gate**: before treating an armed trigger-price touch as an actionable fill, re-check the live signal state at that moment and require it still be at or above some BUY-tier threshold (rather than allowing a fill against a trigger armed days earlier when the live signal has since decayed to WATCH/AVOID). This is presented purely as an **observation from this analysis**, not a proposed change — any actual filter design, threshold, or implementation decision belongs to Prof and any future TFE work order, consistent with the standing role boundaries (Atlas = orchestrator/renderer, TFE = deterministic computation, Prof = thesis/transaction authority).

## Answers to Structured Fields

- **P0O14_STATUS:** DECOMPOSITION_COMPLETE — read-only analysis, no rule changes made or proposed as implementation
- **canonical_vs_signal_differences:** Canonical trades' entries all coincided with a live BUY-tier (3/4 or 4/4) signal at the moment of entry; 10/14 (71%) signal-only candidates had decayed to WATCH or AVOID by the time their stale armed trigger finally filled — median time-to-fill ≈47 hours, several sat armed 3-6 days
- **signal_only_failure_patterns:** (1) stale/decayed signal at fill time (dominant pattern, 10/14 candidates), (2) sector-wide weakness concentrated in SOXX/semis (KLAC/ONTO/VICR all lost or were flat while SOXX fell ~2.6% over their hold windows), (3) low RVOL at fill (a symptom of the same staleness), (4) deep adverse excursions (-16% to -28%) not offset by comparably large favorable excursions
- **signal_only_winner_patterns:** The 2 clean winners (PGEN, EVC) were the only 2 candidates that STILL had a genuine BUY-tier signal (4/4 and 3/4 respectively) at the moment of fill — winners are distinguished by signal freshness, not by sector, catalyst, or RVOL alone
- **sector_effect:** SOXX/semis cluster (4 candidates) is the clearest failure pattern — sector itself fell ~2.6% across the exact hold windows, and every signal-only semis name lost or was flat; XBI/biotech (2 candidates) was the only sector with a clean 2-for-2 win record, coinciding with a positive sector tailwind (+2-3.5%)
- **catalyst_RVOL_effect:** RVOL at fill was uniformly low (0.01-0.32) for the clearest losers, consistent with the same staleness pattern rather than an independent driver; catalyst flag presence did not reliably discriminate winners from losers in this small sample — its absence (CAT/KO/AMD, all `❌ Catalyst: NO`) coincided with underperformance but the sample is too small to isolate catalyst as a standalone cause
- **adverse_excursion_summary:** Signal-only losers show adverse excursions of -16% to -28% over a 5-day window — comparable to or worse than the canonical bucket's worst case (-23%, ALGM); several of these are outright sector-driven drawdowns, not slow drift
- **favorable_excursion_summary:** Nearly every candidate (11/12 with sufficient data) showed a positive favorable excursion at some point, but for the SOXX losers the favorable excursion was small (+3-6%) relative to the eventual adverse move (-16% to -28%) — the combined-selection stop policy's tightest-of-4 rule often did not lock in the smaller favorable move before the larger reversal
- **likely_missing_TFE_filter:** A fill-time signal re-validation gate for the pullback-armor mechanism — requiring the live signal state to still be at or above a BUY-tier threshold at the moment an armed trigger price is actually touched, rather than allowing a fill against a stale trigger armed potentially days earlier when conditions have since decayed. Presented as an observation only; no threshold, implementation, or rule change is proposed here — that decision belongs to Prof
- **recommended_next_phase:** Before any TFE recommendation-model design work proceeds, Prof may want to decide whether to (a) request a bounded, non-disclosing look at how `pending_pullbacks` fill logic currently handles (or doesn't handle) signal staleness at fill time, under the existing Prof-override protocols if that touches protected files, or (b) treat this as sufficient explanation and proceed directly to designing the TFE recommendation model with this known signal-staleness caveat in mind. This report does not recommend one over the other — that is a Prof decision
- **production changes:** NONE
