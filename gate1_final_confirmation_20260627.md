# Atlas Gate 1 Final Confirmation — 2026-06-27

Prof.

Gate 1 fixes applied to production.

## Backups

- `/Users/yasser/scripts/atlas_macro_premarket_backup_20260627_174033_gate1.py`
- `/Users/yasser/scripts/pre_market_report_backup_20260627_174033_gate1.py`
- `/Users/yasser/scripts/atlas_macro_postmarket_backup_20260627_174033_gate1.py`

## Compile Check

Command:

```bash
python3 -m py_compile /Users/yasser/scripts/atlas_macro_premarket.py /Users/yasser/scripts/pre_market_report.py /Users/yasser/scripts/atlas_macro_postmarket.py
```

Result: PASS

## Fix Confirmation

- Section 8 scrubber now strips any sentence containing `a major company`.
- Replacement fallback confirmed:

```text
The calendar is light — focus on any weekend developments and Monday's open.
```

- `pre_market_report.py` no longer imports/calls `build_atlas_handoff_report`.
- `atlas_macro_postmarket.py` now has a hard sanitizer to strip any accidental EOD handoff block.
- Re-run outputs contain no `ATLAS HANDOFF`, `WATCH TOMORROW`, `ENTRY TYPES`, or `IF SOMETHING BREAKS`.

Raw verification output directory:

```text
/Users/yasser/scripts/gate1_verify_20260627_174142/
```

---

## Force Dry-Run Output — atlas_macro_premarket.py

```text
=== atlas_macro_premarket.py --force --dry-run ===
[macro_premarket] collection_seconds=10.8 total_build_seconds=14.90
🧭 ATLAS MACRO PRE-MARKET — Jun 27, 2026 · 09:41 AM ET

1. Futures Overview
S&P 500 futures edged lower by 0.29% to 7,401.75, while Nasdaq 100 futures led the decline, dropping 1.20% to 29,368.25 amid tech sector pressures. Dow futures were more stable, slipping just 0.25% to 52,209, reflecting a cautious market tone.

2. NYSE/Nasdaq Breadth
NYSE and Nasdaq breadth was evenly split with 21 advancers and 21 decliners, indicating a narrow tape. Weakness in Nasdaq futures suggests concentrated pressure in a few large-cap names rather than broad-based selling.

3. Technology & Semiconductors
The SOX index tumbled 5.93%, with equipment makers under scrutiny following analyst concerns over capex timing. This decline underscores the sector's vulnerability as chip stocks have been pivotal in recent market rallies.

4. Artificial Intelligence
The AI sector was quiet overnight with no major deal announcements or model releases to shift sentiment. The group continues to trade on broader tech sector dynamics and regulatory developments.

5. Catalysts & Breaking News
Export-control discussions and pre-open earnings reports are in focus, providing insight into margin resilience. Options expiry could amplify index moves if futures weakness carries into the cash session.

6. Global Markets
Asian markets saw the Nikkei 225 fall 4.15% to 69,360.88, while European equities were softer with the Euro Stoxx 50 down 0.73% to 6,221.55. The Dollar Index was steady at 101.37, WTI crude oil slipped 3.74% to $69.23, and the US 10-year yield eased to 4.37%.

7. The Tone
The market tone is cautious as tech sector pressures weigh on sentiment.

8. Key Events Today
Today's calendar features European economic data at 13:45 ET and Chinese data at 01:30 ET. Fed speakers and pre-open earnings will be closely watched for guidance on economic and market conditions.
[macro_premarket] dry-run generated 1858 chars; Telegram not sent
```

---

## Force Dry-Run Output — pre_market_report.py

```text
=== pre_market_report.py --force --dry-run ===
[pre-market timing] overnight_headlines: 0.62s
[pre-market timing] spy_snapshot: 0.81s
[pre-market timing] fda: 0.01s
[pre-market timing] earnings: 0.87s
[pre-market timing] qqq_snapshot: 1.01s
[pre-market timing] analyst_actions: 1.09s
[pre-market timing] macro: 1.09s
[pre-market timing] vix_snapshot: 1.26s
[pre-market timing] insider_buys: 1.12s
[pre-market timing] sector_pulse: 1.14s
[pre-market timing] gapper_candidates: 3.37s
[pre-market timing] top_movers: 10.26s
[pre-market timing] pullbacks: 36.81s
[pre-market] Benzinga catalyst lookup failed for SDOT: Expecting value: line 1 column 1 (char 0)
[pre-market] Benzinga catalyst lookup failed for CNVS: Expecting value: line 1 column 1 (char 0)
[pre-market] Benzinga catalyst lookup failed for PCLA: Expecting value: line 1 column 1 (char 0)
[pre-market] Benzinga catalyst lookup failed for ZURA: Expecting value: line 1 column 1 (char 0)
[pre-market] Benzinga catalyst lookup failed for FCEL: Expecting value: line 1 column 1 (char 0)
[pre-market] Benzinga catalyst lookup failed for WSHP: Expecting value: line 1 column 1 (char 0)
[pre-market] Benzinga catalyst lookup failed for MRNA: Expecting value: line 1 column 1 (char 0)
[pre-market] Benzinga catalyst lookup failed for PRGS: Expecting value: line 1 column 1 (char 0)
[pre-market] Benzinga catalyst lookup failed for FDS: Expecting value: line 1 column 1 (char 0)
[pre-market] Benzinga catalyst lookup failed for APOG: Expecting value: line 1 column 1 (char 0)
[pre-market timing] early_movers: 160.96s
[pre-market timing] open_positions: 5.52s
[pre-market timing] gap_breakouts: 0.00s
[pre-market timing] catalyst_overrides: 0.00s
[pre-market timing] total: 173.75s
[pre-market] Benzinga catalyst lookup failed for PCLA: Expecting value: line 1 column 1 (char 0)
[pre-market] Benzinga catalyst lookup failed for ZURA: Expecting value: line 1 column 1 (char 0)
[pre-market] Benzinga catalyst lookup failed for CNVS: Expecting value: line 1 column 1 (char 0)
[pre-market] Benzinga catalyst lookup failed for SDOT: Expecting value: line 1 column 1 (char 0)
[pre-market] Benzinga catalyst lookup failed for WSHP: Expecting value: line 1 column 1 (char 0)
[pre-market] Benzinga catalyst lookup failed for MRNA: Expecting value: line 1 column 1 (char 0)
[pre-market] Benzinga catalyst lookup failed for PRGS: Expecting value: line 1 column 1 (char 0)
[pre-market] Benzinga catalyst lookup failed for APOG: Expecting value: line 1 column 1 (char 0)
[pre-market] Benzinga catalyst lookup failed for FCEL: Expecting value: line 1 column 1 (char 0)
[pre-market] Benzinga catalyst lookup failed for FDS: Expecting value: line 1 column 1 (char 0)
🦅 ATLAS PRE-MARKET BRIEF — June 26, 2026 · SPY $728.99 (-0.7%) | QQQ $706.52 (-1.4%) | VIX $18.41 (+6.5%) · risk-off tone; macro events on deck

━━━ MACRO BRIEFING ━━━
Overnight Headlines
📰 Benzinga Bulls And Bears: Micron, Take-Two, SpaceX — And Nasdaq Posts Sharpest Decline In Months
📰 Apple Vision Pro Hardware Chief Reportedly Jumps To OpenAI As Sam Altman's AI Device Ambitions Gather Momentum
Scheduled Events (4 AM–4 PM ET)
  • 08:30 ET — Goods Trade Balance Adv
  • 08:30 ET — Retail Inventories Ex Autos
  • 08:30 ET — Goods Trade Balance
  • 08:30 ET — Wholesale Inventories
  • 10:00 ET — Michigan Inflation Expectations
  • 10:00 ET — Michigan Consumer Sentiment
  • 10:00 ET — Michigan Consumer Expectations
  • 10:00 ET — Michigan Current Conditions

━━━ OPEN POSITIONS ━━━
🟢 LRCX (Lam Research) ~$4,928  $368.39 → $379.09  +2.9% (+$139)
   🛑 $368.40  🎯 $446.95
   ⚠️ Watch: watch macro event risk
🔴 INTC (Intel) ~$898  $129.78 → $128.32  -1.1% (−$10)
   🛑 $113.02  🎯 $162.25
   ⚠️ Watch: watch macro event risk
🔴 SYNA (Synaptics) ~$847  $126.44 → $121.00  -4.3% (−$38)
   🛑 $113.35  🎯 $156.61
   ⚠️ Watch: watch macro event risk

━━━ 🔥 EARLY MOVERS (10) ━━━
Visibility only — on your radar, not a buy recommendation.
1. SDOT (Sadot Group) +212% · $21.45 · RVOL 205.6x · No catalyst found
2. PCLA (PicoCELA Inc. American Depositary Shares) +130% · $6.97 · RVOL 85.6x · No catalyst found
3. WSHP (WeShop Holdings) +67% · $8.00 · RVOL 163.7x · No catalyst found
4. FCEL (FuelCell Energy Inc NEW) +22% · $24.00 · RVOL 2.4x · No catalyst found
5. CNVS (Cineverse) +19% · $3.15 · RVOL 40.4x · No catalyst found
6. ZURA (Zura Bio) +19% · $5.35 · RVOL 7.5x · No catalyst found
7. MRNA (Moderna) +12% · $67.27 · RVOL 2.1x · No catalyst found
8. APOG (Apogee Enterprises) +12% · $48.92 · RVOL 4.9x · No catalyst found
9. PRGS (Progress Software) +11% · $33.15 · RVOL 3.3x · No catalyst found
10. FDS (Factset Research Systems) +11% · $231.74 · RVOL 1.7x · No catalyst found

━━━ PULLBACK CANDIDATES ━━━
🔸 MU (Micron Technology) Trigger $105.80 · Now $113.23 (+7.0%) · 3/4 Pillars · catalyst · warnings
🔸 CAT (Caterpillar) Trigger $961.93 · Now $997.47 (+3.7%) · 3/4 Pillars · catalyst · warnings · ✅ solid fundamentals | fin margin 13%
🔸 JPM (JPMorgan Chase) Trigger $329.55 · Now $329.05 (-0.2%) · 3/4 Pillars · catalyst · warnings · ⚠️ weak fundamentals (high debt) | fin margin 32%
🔸 JNJ (Johnson & Johnson) Trigger $238.39 · Now $254.66 (+6.8%) · 3/4 Pillars · catalyst · warnings · ✅ solid fundamentals
🔸 AMAT (Applied Materials) Trigger $587.24 · Now $626.84 (+6.7%) · 3/4 Pillars · catalyst · warnings · ✅ solid fundamentals | fin margin 29%
🔸 BAC (Bank of America) Trigger $57.02 · Now $57.88 (+1.5%) · 3/4 Pillars · catalyst · warnings · ✅ solid fundamentals | fin margin 27%
🔸 RL (Ralph Lauren) Trigger $407.11 · Now $411.16 (+1.0%) · 3/4 Pillars · catalyst · warnings · ✅ solid fundamentals | fin margin 12%
🔸 CWAN (Clearwater Analytics) Trigger $24.54 · Now $24.55 (+0.0%) · 3/4 Pillars · warnings
🔸 MRK (Merck) Trigger $119.39 · Now $128.66 (+7.8%) · 3/4 Pillars · catalyst · warnings · ✅ solid fundamentals | fin margin 14%
🔸 MKSI (Mks) Trigger $381.34 · Now $388.61 (+1.9%) · 4/4 Pillars · catalyst · warnings · ✅ solid fundamentals
🔸 ALGM (Allegro MicroSystems) Trigger $55.54 · Now $57.89 (+4.2%) · 3/4 Pillars · catalyst · warnings · ⚠️ weak fundamentals (neg earnings) | fin margin -2%
🔸 KLIC (Kulicke & Soffa Industries) Trigger $120.68 · Now $125.22 (+3.8%) · 4/4 Pillars · catalyst · warnings · ✅ solid fundamentals
🔸 TGT (Target) Trigger $135.72 · Now $140.39 (+3.4%) · 3/4 Pillars · catalyst · warnings · ✅ solid fundamentals | fin margin 3%

━━━ TOO HOT SKIP ━━━
PGEN (Precigen) +22% | CGEM (Cullinan Therapeutics) +21% | EVC (Entravision Communication) +21% | ELVN (Enliven Therapeutics) +12% | EWTX (Edgewise Therapeutics) +13% | AAL (American Airlines Group) +13% | SLDB (Solid Biosciences) +16% | GLW (Corning) +11% | MRNA (Moderna) +13%

━━━ SECTOR PULSE ━━━
XLV +3.0% — healthcare leading
XLK -1.9% — technology under pressure
XLI -1.6% — industrials under pressure
XLE -0.5% — energy under pressure

━━━ SCOUTING ━━━
Earnings tonight: CNVS — EPS +600% / Rev +19% | XAIR — EPS -38% / Rev -17% | APOG — EPS +39% / Rev +3%
Analyst actions: WFRD - Citigroup buy PT $115 | SYNA - Wells Fargo overweight PT $160 | R - Barclays overweight PT $290
Insider buys: ABSI — 🏦 insider buying (1 buy, $200,748)
FDA calendar: ANIX 2026-06-26 Provided Update | CAPR 2026-06-26 Positive Data | AEMD 2026-06-26 Publication
[pre_market] dry-run generated 4541 chars; Telegram not sent
```

---

## Force Dry-Run Output — atlas_macro_postmarket.py

```text
=== atlas_macro_postmarket.py --force --dry-run ===
[macro_postmarket] collection_seconds=9.88 total_build_seconds=13.39
🧭 ATLAS MACRO POST-MARKET — Jun 27, 2026 · 09:45 AM ET

1. Opening Headline
US stocks ended mixed as the Dow Jones Industrial Average rose 0.6%, while the S&P 500 fell 2% and the Nasdaq 100 tumbled 4.2%. The divergence highlighted a rotation into defensive sectors amid a tech selloff.

2. What Drove It
The catalyst was a sharp decline in technology shares, exacerbated by concerns over rising hardware costs and regulatory scrutiny. This overshadowed gains in defensive sectors, as investors sought safety amid uncertainty.

3. Sector Breakdown
Technology and Communication Services led the declines, with Technology down 5.4% and Communication Services off 3%. Health Care surged 7.3%, leading gains alongside Utilities and Real Estate, as investors rotated into defensives.

4. Bonds, FX, Commodities
The 10-year yield edged down to 4.37%, while the Dollar Index firmed to 101.37. WTI crude plunged 7.5% to $69.23, pressured by easing supply concerns and demand uncertainties.

5. Sentiment
The VIX climbed to 18.4, reflecting heightened volatility as market breadth remained mixed. Credit proxies softened slightly, indicating a cautious risk environment without signs of stress.

6. Into Monday
Traders will focus on a busy economic calendar, including ISM Manufacturing PMI on Wednesday, ADP Employment Change on Thursday, and Nonfarm Payrolls on Friday. Jobless claims and the unemployment rate will also be closely watched for labor market insights.
[macro_postmarket] dry-run generated 1458 chars; Telegram not sent
```
