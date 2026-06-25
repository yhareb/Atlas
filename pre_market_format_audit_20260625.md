# Atlas pre-market report format audit — 2026-06-25

Scope: read-only audit of `/Users/yasser/scripts/pre_market_report.py` against Prof.'s target format.

No code changes made. No DB writes made.

## Target format sections

Prof.'s reference format:

1. `ATLAS PRE-MARKET BRIEF — June 25, 2026`
2. `MARKET PULSE`
3. `OPEN POSITIONS`
4. `GAP-UP BREAKOUTS (ready at open)`
5. `PULLBACK CANDIDATES (waiting for dip)`
6. `CATALYST OVERRIDES (half-size, 5% stop)`
7. `TOO HOT — SKIP`

## Current active renderer

Active entrypoint:

- `generate_pre_market_report(send=True)` at lines 586-592
- It immediately returns `generate_wavef_pre_market_brief(send=send)`.
- The older report body after line 593 is unreachable dead code.

Active current sections from `generate_wavef_pre_market_brief`:

- `🌄 PRE-MARKET BRIEF — YYYY-MM-DD`
- `🧭 Market Sentiment Overview`
- `🚀 Pre-Market Movers / Gappers`
- `🧪 Screener Fresh Names`
- `📰 News + Sentiment Catalysts`
- `📊 Overnight Earnings`
- `🏦 Analyst Actions / PT Changes`
- `🏛 Insider Buys`
- `⚠️ Macro Events Today`
- `⚕️ FDA EVENTS`
- `🎯 Setups Armed For The Day`
- `_Scouting only — no pre-market trades._`

## Fit against target format

Verdict: PARTIAL / mostly not aligned.

### 1. Header

Target:
`ATLAS PRE-MARKET BRIEF — June 25, 2026`

Current:
`🌄 PRE-MARKET BRIEF — YYYY-MM-DD`

Status: PARTIAL

Missing:
- `ATLAS` prefix.
- Human-readable date format like `June 25, 2026`.
- Current title uses ISO date.

### 2. Market Pulse

Target:
`SPY $545.20 (+0.3%) | QQQ $480.15 (+0.5%) | VIX 12.40`
`Macro: Fed stress test results — watch semis/banks at open`

Current:
- `Market Sentiment Overview` uses ETF proxy lines from `get_futures()`.
- Macro is separate under `Macro Events Today`.

Status: PARTIAL

Missing:
- One-line compact SPY / QQQ / VIX pulse.
- Macro summary directly under the pulse.
- Current code does not combine macro into a single plain-English “Macro:” line.

### 3. Open Positions

Target:
`OPEN POSITIONS`
`LRCX | Entry $368.39 | Close $374.80 | Stop $329.50 | Target $446.95 | +$87`

Current:
- No dedicated open-positions section in pre-market report.
- No current holding P/L line.

Status: NO

### 4. Gap-Up Breakouts

Target:
`GAP-UP BREAKOUTS (ready at open)`
`Ticker | Gap | RVOL | Sentiment | Trigger`

Current:
- Generic `Pre-Market Movers / Gappers` exists.
- Generic `News + Sentiment Catalysts` exists.
- No dedicated Gap-Up Breakout section with all required fields.

Status: NO

Missing:
- Gap-up breakout classification.
- RVOL field.
- sentiment score field.
- trigger field.
- ready-at-open grouping.

### 5. Pullback Candidates

Target:
`PULLBACK CANDIDATES (waiting for dip)`
`Ticker | Pillars | Trigger | Now | % above trigger`

Current:
- `Setups Armed For The Day` merges BUY and WATCH names from handoff.
- `get_handoff_snapshot()` only renders ticker, current price, and day change.

Status: PARTIAL / NO as phrased

Missing:
- Dedicated pullback section.
- Pillar score.
- trigger price.
- now vs trigger percentage.

### 6. Catalyst Overrides

Target:
`CATALYST OVERRIDES (half-size, 5% stop)`
`Ticker | RVOL | Gap | Sentiment | Trigger`

Current:
- No separate Catalyst Override section.
- Current catalyst section is news/headline based, not override-entry structured.

Status: NO

Missing:
- Half-size/5% stop grouping.
- RVOL.
- gap.
- sentiment.
- trigger.

### 7. Too Hot — Skip

Target:
`TOO HOT — SKIP`
`PLSM +76% | ABSI +34%`

Current:
- No dedicated Too Hot skip section in pre-market report.

Status: NO

## Data-source gaps implied by target format

To fully implement the target format, pre-market report would need structured pulls from:

1. Open positions:
   - `atlas_db.get_open_positions()` plus live/last price lookup.

2. Pending pullbacks:
   - `atlas_db.get_pending_pullbacks(status="WAITING")` plus trigger/score/current price/pct over trigger.

3. Gap-up breakouts:
   - current discovery/engine metadata for gap, RVOL, sentiment, trigger.
   - Current report only shows generic movers/catalysts; it does not build a breakout-ready roster.

4. Catalyst overrides:
   - current engine/decision metadata for override-qualified names.
   - Needs explicit separation from generic news catalyst lines.

5. Too hot skips:
   - scan candidates where decision reason starts with `TOO EXTENDED` / too hot.
   - Current pre-market report does not surface this group.

## Safety / DB state

Read-only audit only.

DB counts checked before and after audit:

- trades: 7
- pending_pullbacks: 12
- ema_retry_candidates: 1
- signals: 3653
- handoff: 5
- cash_ledger: 4

Counts unchanged.

## Bottom line

Current pre-market report is a broad Wave-F scouting brief, not the concise execution-ready format Prof pasted.

It needs a presentation-layer redesign plus some structured data wiring to match the target sections. The most important missing pieces are:

1. Open positions with live P/L.
2. Dedicated Gap-Up Breakout section.
3. Dedicated Pullback Candidates section with trigger/now/%.
4. Dedicated Catalyst Override section.
5. Dedicated Too Hot skip section.
6. Compact Market Pulse line with SPY / QQQ / VIX and plain-English macro note.
