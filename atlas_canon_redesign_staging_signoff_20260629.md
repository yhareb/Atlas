# Atlas Canon Template Redesign — Staging Sign-off Packet — 2026-06-29

Status: **AWAITING PROF APPROVAL — DO NOT DEPLOY**

## Hard holds observed

- Production deploy: **not executed**
- Telegram config / `.env` / chat ID fields: **not touched**
- Production DB final state: unchanged at requested baseline

```text
FINAL_PROD_COUNTS
trades=10
signals=6906
pending_pullbacks=27
```

## Staging workspace

```text
/tmp/atlas_canon_redesign_staging_scripts
/tmp/atlas_staging.db
```

## Staged files changed only

```text
CHANGED_STAGED_FILES
atlas_intraday.py
pre_market_report.py
atlas_report_handoff.py
atlas_macro_premarket.py
atlas_macro_postmarket.py
atlas_premarket_gaps.py
post_market_report.py
atlas_audit_report.py
```

## Gate 1 — compile

Command:

```bash
cd /tmp/atlas_canon_redesign_staging_scripts
python3 -m py_compile atlas_intraday.py pre_market_report.py atlas_report_handoff.py atlas_macro_premarket.py atlas_macro_postmarket.py atlas_premarket_gaps.py post_market_report.py atlas_audit_report.py eod_writer.py
```

Output:

```text
(no output; py_compile exit 0)
```

## Gate 1 — requested behavior checks

```text
top picks: True
all signals: True
overflow in all signals: True
no stale label: True
dynamic footer: True
early movers filtered: True
macro pre gate: True
macro post gate: True
production DB unchanged: trades=10 signals=6906 pending_pullbacks=27
```

## Gate 1 — rendered Telegram output for all 7 reports

```text
===== 01_pre_market_brief.txt =====
🦅 ATLAS PRE-MARKET BRIEF — June 29, 2026 · SPY $655.00 (+0.4%) | QQQ $588.00 (+0.6%) | VIX $16.20 (-1.2%) · risk-on tone; macro events on deck

━━━ MACRO BRIEFING ━━━
Overnight Headlines
📰 Futures firm as yields ease
📰 Semiconductors lead pre-market risk appetite
Scheduled Events (4 AM–4 PM ET)
CPI at 8:30 ET

Fed speaker at 10:00 ET

Treasury auction at 13:00 ET


━━━ OPEN POSITIONS ━━━
🟢 MS (Morgan Stanley) ~$4,000  $124 → $129  +4% (+$160)

   🛑 $118  🎯 $161


━━━ 🔥 EARLY MOVERS (2) ━━━
Visibility only — on your radar, not a buy recommendation.
1. AAA (Alternative Access First Priority CLO Bond ETF) +18% · $12.00 · RVOL 3.2x · Catalyst: FDA clearance announced

2. CCC (CCC Intelligent Solutions Holdings) +11% · $31.00 · RVOL 1.9x · Catalyst: Raised FY guidance


━━━ PULLBACK CANDIDATES ━━━
🔸 MS (Morgan Stanley) Trigger $124 · Now $129 (+4%) · 4/4 · catalyst


━━━ SECTOR PULSE ━━━
XLK +1% — technology leading

XLF +0% — financials leading


━━━ SCOUTING ━━━
Earnings tonight: Company A after close | Company B before open

Analyst actions: Broker upgraded AAA | Broker cut ZZZ

Insider buys: Insider buy at CCC


===== 02_pre_market_gap_scan.txt =====
━━━ 🌅 PRE-MARKET GAPS — 8:30 AM ET ━━━
Visibility only — not a buy/sell signal.

🟢 GAP UPS

1. AAA +7.2% · pre-mkt $15.50 · prior close $14.46 · Catalyst: FDA clearance announced

🔴 GAP DOWNS

1. ZZZ -6.1% · pre-mkt $8.20 · prior close $8.73 · Catalyst: Guidance cut


===== 03_pre_market_macro_brief.txt =====
[macro_premarket] calendar gate closed; non-market ET day 2026-06-28; no report sent

🧭 ATLAS MACRO PRE-MARKET — Jun 29, 2026 · 08:45 AM ET

1. Futures Overview
S&P 500 futures are +0.4%, Nasdaq 100 is +0.6%, and Dow is +0.2%, leaving the tape risk-on before the open.

2. Bonds, FX, Commodities
The 10-year yield is near 4.30%, DXY is softer, and oil is steady.

3. Key Events Today
CPI is due at 08:30 ET.

Fed commentary follows at 10:00 ET.


===== 04_intraday_report.txt =====
🦅 ATLAS INTRADAY — 6:37 PM ET
📡 🔴 RISK-OFF · SPY N/A
💰 Equity $100,000 · Cash $80,000 · 0 positions

━━━ ACTIONS ━━━

🔥 TOP PICKS (5 of 6)

   • AAL (American Airlines Group) — $18 · stop $17 · target $22 · 4/4 Pillars · 1% risk

   • ELVN (Enliven Therapeutics) — $50 · stop $44 · target $62 · 4/4 Pillars · 1% risk

   • JNJ (Johnson & Johnson) — $255 · stop $246 · target $319 · 4/4 Pillars · 1% risk

   • MRK (Merck) — $129 · stop $124 · target $161 · 4/4 Pillars · 1% risk

   • RL (Ralph Lauren) — $411 · stop $391 · target $514 · 4/4 Pillars · 1% risk

📋 ALL SIGNALS (6)

   • AAL (American Airlines Group) — $18 · stop $17 · target $22 · 4/4 Pillars · 1% risk

   • ELVN (Enliven Therapeutics) — $50 · stop $44 · target $62 · 4/4 Pillars · 1% risk

   • JNJ (Johnson & Johnson) — $255 · stop $246 · target $319 · 4/4 Pillars · 1% risk

   • MRK (Merck) — $129 · stop $124 · target $161 · 4/4 Pillars · 1% risk

   • RL (Ralph Lauren) — $411 · stop $391 · target $514 · 4/4 Pillars · 1% risk

   • MS (Morgan Stanley) — $129 · stop $124 · target $161 · 3/4 Pillars · 0.5% risk

💰 SELL: none — holding all

━━━ ⏳ PENDING ENTRIES (0) ━━━
✅ none

━━━ 💼 HOLDING (0) ━━━
📭 none

━━━ 🚀 GAP-UP BREAKOUTS (0) ━━━

✅ none

━━━ 📈 INTRADAY BREAKOUTS (0) ━━━

✅ none

━━━ 🎣 WAITING FOR DIP (1) ━━━

🔸 MS (Morgan Stanley) buy $124.00 · now $129.00 (+4%)
   3/4


━━━ 🚦 TOO HOT (0) ━━━
none

━━━ 👀 WATCHING (0) ━━━
none


===== 05_post_market_report.txt =====
[macro_postmarket] calendar gate closed; non-market ET day 2026-06-28; no report sent

🧭 ATLAS MACRO POST-MARKET — Jun 29, 2026 · 04:15 PM ET

1. Opening Headline
US equities closed firmer as S&P 500 gained +0.5% and Nasdaq 100 gained +0.7%.

2. What Drove It
Rates eased and breadth improved into the close.

3. Into Tomorrow
The next session starts with macro data and Fed commentary on watch.


===== 06_eod_handoff.txt =====
─────────────────────────────────────────
🤖 ATLAS HANDOFF — JUNE 29 → 30, 2026
═══════════════════════════════

1️⃣ OPEN POSITIONS

   🟢 MS (Morgan Stanley) — entry $124 · close $129 · P/L +4%
      Stop: $118 · Target: $161
      ⚡ $20B buyback announced

─────────────────────────────────────────

2️⃣ WATCH TOMORROW

   🚀 Gap-up window 9:30–10:00 ET

   📈 Intraday breakout window 10:00–12:00 ET

   🎣 AAL — trigger $18 · at EMA · could fire on any dip
   🎣 INTC — trigger $150 · 5% above EMA · needs pullback

   ⚠️ MS — stop $118 · watch for drift

─────────────────────────────────────────

3️⃣ ENTRY TYPES

   🚀 Gap-Up Breakout    · 9:30–10:00 AM · RVOL >1.5x · Catalyst required · Risk 0.25%

   📈 Intraday Breakout  · 10:00–12:00 PM · RVOL >2.0x · Catalyst required · Risk 0.25%

   🎣 Pullback to EMA    · All day        · RVOL any   · Catalyst optional  · Risk 0.50%

─────────────────────────────────────────

4️⃣ IF SOMETHING BREAKS

   ❌ No intraday reports — restart com.atlas.intraday on M2

   ❌ Atlas silent on Telegram — run: hermes -p atlas gateway restart

   ⛔ AtlasOps must NOT touch Telegram .env — correct chat ID ends 9320

─────────────────────────────────────────
   ✅ All fixes verified · June 29, 2026
─────────────────────────────────────────


===== 07_audit_report.txt =====
🛡️ ATLAS OPS AUDIT — 12:00 PM ET
✅ All systems healthy
📡 API Health (last 30m)
- Massive: 1 calls · 0 errors

- EODHD: 1 calls · 0 errors

- Benzinga: 1 calls · 0 errors

🎯 Signals
- 2 tickers · 1 WAITING · 1 SKIP · 0 TOO HOT

💾 DB Events
- 2 writes (trades: 0 · pending_pullbacks: 1 · other: 1)

🛠️ Code Changes
- canon-template-redesign-staging · atlas_intraday.py

## Gate 2 — timing harness

Pass condition: under 480s and source production DB unchanged.

```json
{
  "candidate_count": 95,
  "elapsed_seconds": 276.888,
  "gate1_critical_tables": [
    "trades",
    "pending_pullbacks"
  ],
  "isolated_db": "/var/folders/nz/48nykj7s0tl__8dfhq6dd0vm0000gn/T/atlas_scan_timing_napriv40/atlas_timing.db",
  "max_seconds": 480.0,
  "result": "ACTION",
  "scanned_count": 76,
  "source_counts_after": {
    "pending_pullbacks": 27,
    "signals": 6906,
    "trades": 10
  },
  "source_counts_before": {
    "pending_pullbacks": 27,
    "signals": 6906,
    "trades": 10
  },
  "source_counts_unchanged": true,
  "source_critical_counts_unchanged": true,
  "temp_counts_after": {
    "pending_pullbacks": 27,
    "signals": 6906,
    "trades": 10
  },
  "temp_counts_before": {
    "pending_pullbacks": 27,
    "signals": 6906,
    "trades": 10
  },
  "under_limit": true
}
```

## Gate 3 — three staging cycles

Pass condition: 3 cycles, each under 480s, no errors. Staging DB is allowed to mutate; production DB must remain unchanged.

```json
[
  {
    "candidate_count": 95,
    "counts_after": {
      "pending_pullbacks": 28,
      "signals": 6992,
      "trades": 10
    },
    "counts_before": {
      "pending_pullbacks": 27,
      "signals": 6906,
      "trades": 10
    },
    "cycle": 1,
    "elapsed_seconds": 353.22,
    "result": "ACTION",
    "scanned_count": 76,
    "under_limit": true
  },
  {
    "candidate_count": 95,
    "counts_after": {
      "pending_pullbacks": 28,
      "signals": 7078,
      "trades": 10
    },
    "counts_before": {
      "pending_pullbacks": 28,
      "signals": 6992,
      "trades": 10
    },
    "cycle": 2,
    "elapsed_seconds": 156.799,
    "result": "ACTION",
    "scanned_count": 75,
    "under_limit": true
  },
  {
    "candidate_count": 95,
    "counts_after": {
      "pending_pullbacks": 28,
      "signals": 7164,
      "trades": 10
    },
    "counts_before": {
      "pending_pullbacks": 28,
      "signals": 7078,
      "trades": 10
    },
    "cycle": 3,
    "elapsed_seconds": 196.276,
    "result": "ACTION",
    "scanned_count": 75,
    "under_limit": true
  }
]
```

## Final production DB proof

```text
FINAL_PROD_COUNTS
trades=10
signals=6906
pending_pullbacks=27
```

## Deployment status

```text
HELD. Do not deploy until Prof explicitly says "Approved".
```
