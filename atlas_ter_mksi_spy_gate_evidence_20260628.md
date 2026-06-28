# Atlas Evidence — TER/MKSI June 26 + SPY WEAK Gate

Generated for Prof. by AtlasOps on 2026-06-28.

## 1) June 26 — Did TER and MKSI appear as BUY signals in the 12:20–12:30 ET cycle?

### Bottom line

- Raw `signals` DB rows: **YES** — TER and MKSI were scored as `🟢 BUY` around `12:20–12:23`.
- Actual 12:20/12:30 ET full intraday Telegram report body: **not present in `atlas_intraday.log` for that cycle**. The log shows start/interim Telegram status messages only.
- Later full intraday Telegram report at `2:16 PM ET` showed:
  - TER under `CONFIRM AT BROKER`
  - MKSI under `WAITING FOR DIP`
  - `ACTIONS` still said `BUY: none this cycle`

### Evidence source paths checked

- `/Users/yasser/scripts/atlas_intraday.log`
- `/Users/yasser/scripts/atlas_intraday_status.log`
- `/Users/yasser/scripts/atlas_intraday.err.log`
- `/Users/yasser/scripts/atlas.db`, table `signals`

### 12:20/12:30 ET log output

```text
22852|[2026-06-26 20:20:01] Atlas intraday loop starting...
22853|[intraday] market-hours gate: market hours — Fri 2026-06-26 12:20 EDT
22854|[intraday] start status telegram subprocess queued
22855|[atlas_start_status] telegram chunk 1/1 sent on attempt 1: message_id=626
22856|[atlas_start_status] telegram report sent: chunks=1 message_ids=[626]
22857|[atlas_start_status] subprocess_send_ok=True
22858|[atlas_interim_status] telegram chunk 1/1 sent on attempt 1: message_id=627
22859|[atlas_interim_status] telegram report sent: chunks=1 message_ids=[627]
22860|[atlas_interim_status] subprocess_send_ok=True

22862|[2026-06-26 20:30:03] Atlas intraday loop starting...
22863|[intraday] market-hours gate: market hours — Fri 2026-06-26 12:30 EDT
22864|[intraday] start status telegram subprocess queued
22865|[atlas_start_status] telegram chunk 1/1 sent on attempt 1: message_id=628
22866|[atlas_start_status] telegram report sent: chunks=1 message_ids=[628]
22867|[atlas_start_status] subprocess_send_ok=True
22868|[atlas_interim_status] telegram chunk 1 attempt 1 failed: HTTPSConnectionPool(host='api.telegram.org', port=443): Read timed out. (read timeout=5); retrying in 2s
22869|[atlas_interim_status] telegram chunk 1 attempt 2 failed: HTTPSConnectionPool(host='api.telegram.org', port=443): Read timed out. (read timeout=5); retrying in 5s
22870|[atlas_interim_status] telegram chunk 1/1 sent on attempt 3: message_id=631
22871|[atlas_interim_status] telegram report sent: chunks=1 message_ids=[631]
```

### Raw DB rows for TER/MKSI, 12:20–12:30 ET

```text
TER|2026-06-26 12:20:05|4/4 Pillars|🟢 BUY|🟢 +1.0 news sentiment, ⚠️ Earnings in 21 trading days (2026-07-28) — elevated risk
MKSI|2026-06-26 12:20:49|4/4 Pillars|🟢 BUY|🟢 +1.0 news sentiment, ⚠️ Earnings in 27 trading days (2026-08-05) — elevated risk
TER|2026-06-26 12:23:21|4/4 Pillars|🟢 BUY|🟢 +1.0 news sentiment, ⚠️ Earnings in 21 trading days (2026-07-28) — elevated risk
MKSI|2026-06-26 12:23:32|4/4 Pillars|🟢 BUY|🟢 +1.0 news sentiment, ⚠️ Earnings in 27 trading days (2026-08-05) — elevated risk
```

### All BUY rows in that 12:20–12:30 ET window

```text
TER|2026-06-26 12:20:05|4/4 Pillars|🟢 BUY|🟢 +1.0 news sentiment, ⚠️ Earnings in 21 trading days (2026-07-28) — elevated risk
MKSI|2026-06-26 12:20:49|4/4 Pillars|🟢 BUY|🟢 +1.0 news sentiment, ⚠️ Earnings in 27 trading days (2026-08-05) — elevated risk
ALGM|2026-06-26 12:21:07|3/4 Pillars|🟡 BUY (Small)|🟢 +1.0 news sentiment, ⚠️ Earnings in 23 trading days (2026-07-30) — elevated risk
ONTO|2026-06-26 12:21:25|3/4 Pillars|🟡 BUY (Small)|🟢 +1.0 news sentiment, ⚠️ Earnings in 28 trading days (2026-08-06) — elevated risk
KLIC|2026-06-26 12:22:12|4/4 Pillars|🟢 BUY|🟢 +1.0 news sentiment, ⚠️ Earnings in 27 trading days (2026-08-05) — elevated risk
TER|2026-06-26 12:23:21|4/4 Pillars|🟢 BUY|🟢 +1.0 news sentiment, ⚠️ Earnings in 21 trading days (2026-07-28) — elevated risk
MKSI|2026-06-26 12:23:32|4/4 Pillars|🟢 BUY|🟢 +1.0 news sentiment, ⚠️ Earnings in 27 trading days (2026-08-05) — elevated risk
ALGM|2026-06-26 12:23:41|3/4 Pillars|🟡 BUY (Small)|🟢 +1.0 news sentiment, ⚠️ Earnings in 23 trading days (2026-07-30) — elevated risk
ONTO|2026-06-26 12:23:50|3/4 Pillars|🟡 BUY (Small)|🟢 +1.0 news sentiment, ⚠️ Earnings in 28 trading days (2026-08-06) — elevated risk
KLIC|2026-06-26 12:23:58|4/4 Pillars|🟢 BUY|🟢 +1.0 news sentiment, ⚠️ Earnings in 27 trading days (2026-08-05) — elevated risk
```

### Later full Telegram report body evidence, 2:16 PM ET

```text
🦅 ATLAS INTRADAY — 2:16 PM ET
📡 🟢 RISK-ON · SPY $734.25 · ⚠️ Fed/CPI day — cautious · 🧠 CAUTION: broad market/semis pressure
💰 Equity $29,202 · Cash $22,473 · 3 positions

━━━ ACTIONS ━━━
🛒 BUY: none this cycle
💰 SELL: none — holding all

━━━ 🔔 CONFIRM AT BROKER (2) ━━━

⏳ TER (Teradyne) buy $426.56 · stop $375.08 · target $529.52 · 0.5% risk
   👉 register TER buy qty=2 price=$426.56 ref=<your-broker-ref>
```

MKSI in same report:

```text
🔸 MKSI (Mks) buy $381.34 · now $387.00 (+1%)
   4/4 · ✅ fundamentals · 📉 RSI 67 · 📈 MACD+ · 🟢 +1.0
```

## 2) Is SPY WEAK currently suppressing or downgrading BUY signals during market hours?

### Bottom line

- SPY WEAK **does not block** BUY signals by itself.
- SPY WEAK **downgrades sizing/risk to half-size** via cautious mode.
- SPY WEAK also shows warning text in reports.
- Current live `check_regime()` returned `True`, even with SPY below 50SMA.

### Current live check result

Command run from `/Users/yasser/scripts`:

```bash
python3 - <<'PY'
from atlas_engine import check_regime
print(check_regime())
PY
```

Output:

```text
(True, '⚠️ WEAK — cautious (half size); SPY 728.99 < 50SMA 734.35')
```

### Code — `atlas_engine.py`, `check_regime()`

```python
def check_regime():
    """Informational SPY regime label. Never blocks buys by itself."""
    aggs = get_massive_aggs("SPY", days=120)
    if not aggs:
        return True, "⚠️ WEAK — cautious (half size); SPY data unavailable"
    closes = [d['c'] for d in aggs]
    sma50 = calculate_sma(closes, 50)
    if sma50 is None:
        return True, "⚠️ WEAK — cautious (half size); SPY history insufficient"
    ok = closes[-1] > sma50
    if ok:
        return True, f"🟢 RISK-ON ✅; SPY {closes[-1]:.2f} > 50SMA {sma50:.2f}"
    return True, f"⚠️ WEAK — cautious (half size); SPY {closes[-1]:.2f} < 50SMA {sma50:.2f}"
```

### Code — `atlas_portfolio.py`, admission does not block on weak SPY

```python
# Soft regime is informational for entries. Weak/missing SPY does not block buys;
# consider_buy() applies cautious half-size risk when the regime detail is WEAK.
if regime is None:
    regime = check_regime()
```

### Code — `atlas_portfolio.py`, sizing constants

```python
RISK_PCT_FULL = 0.01      # 1% equity risk for 4/4 BUY
RISK_PCT_HALF = 0.005     # 0.5% equity risk for 3/4 BUY (Small)
```

### Code — `atlas_portfolio.py`, sizing downgrade logic

```python
regime_detail = str((regime or (True, ""))[1])
cautious = ("WEAK" in regime_detail.upper() or "UNKNOWN" in regime_detail.upper()
            or "UNAVAILABLE" in regime_detail.upper() or bool((macro_ctx or {}).get("cautious")))
half = (pillars == 3) or cautious or catalyst_override_entry
shares = size_position(equity, fill, stop, half=half)
```

### Code — `atlas_portfolio.py`, decision records half/full risk

```python
"risk_pct": (RISK_PCT_HALF if half else RISK_PCT_FULL) * 100,
"cautious_mode": cautious,
```

### Code — `atlas_portfolio.py`, trade notes reflect cautious mode

```python
notes=f"Atlas v2 entry: {trig_detail}; score {score}; signal {signal_result.get('signal', '')}; stop {stop}; target {target}; "
      f"{'0.5%' if half else '1%'} risk on equity ${equity:,.0f}"
      f"{' (cautious weak-market/macro mode)' if cautious else ''}",
```

## Final determination

1. TER and MKSI were raw DB `🟢 BUY` signals during the 12:20–12:30 ET window, but the actual full Telegram report body for that exact cycle was not in the log; only status/interim sends are logged for 12:20 and 12:30.

2. SPY WEAK currently **downgrades position size to half risk** and adds caution wording. It does **not** hard-block the buy signal by itself because `check_regime()` returns `True` even when SPY is below 50SMA.
