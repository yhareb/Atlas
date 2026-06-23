# TSM Sell Registration / LRCX Phantom Cleanup / Target Storage Fix — 2026-06-23

## Safety

- DB backup: `/Users/yasser/scripts/atlas_db_tsm_sell_targetfix_20260623_182617.db`
- Source backup: `/Users/yasser/scripts/atlas_db_tsm_sell_targetfix_20260623_182617.py`
- Edited source: `/Users/yasser/scripts/atlas_db.py`
- py_compile: OK
- Restore on failure: not needed
- No live flip: no live flags changed

## Before state

```json
{
  "cash_ledger": [
    {
      "amount": 37000.0,
      "balance_after": 37000.0,
      "id": 1,
      "reason": "Initial funding",
      "ts": "2026-06-21 22:32:04"
    },
    {
      "amount": -5005.2,
      "balance_after": 31994.8,
      "id": 2,
      "reason": "TSM broker fill P1104145955: 11.34288404 sh @ 440.81 plus $5.20 commission",
      "ts": "2026-06-23 13:51:59"
    }
  ],
  "counts": {
    "ema_retry_candidates": 1,
    "pending_pullbacks": 6,
    "trades": 4
  },
  "label": "before",
  "open_trades": [],
  "pending5": {
    "armed_at": "2026-06-22 15:51:54",
    "ema10": 366.81494032141825,
    "expired_at": null,
    "expires_at": "2026-06-25",
    "filled_at": null,
    "id": 5,
    "pct_over_ema": 7.8036787851387235,
    "reference_price": 395.44,
    "score": "3/4 Pillars",
    "signal": "\ud83d\udfe1 BUY (Small)",
    "signal_json": "{\"ticker\": \"LRCX\", \"signal\": \"\\ud83d\\udfe1 BUY (Small)\", \"entry_price\": 395.44, \"score\": \"3/4 Pillars\", \"rvol\": 0.33, \"pillars\": [\"\\u2705 Trend Stack: YES (Price > 50SMA > 150SMA > 200SMA)\", \"\\u2705 Relative Strength: YES (Within 3% of 52W High $402.08)\", \"\\u274c Volume: NO (RVOL: 0.33 < 2.0)\", \"\\u2705 Catalyst: YES \\u2014 Recent news\"], \"catalyst_reason\": \"LLM: Price target raises from analysts\", \"warnings\": [], \"regime\": {\"risk_on\": true, \"detail\": \"SPY 745.49 > 50SMA 730.97\"}, \"risk_card\": {\"daily_volatility_atr\": 26.1, \"stop_loss\": 356.29, \"max_loss_per_share\": 39.15, \"atr_stop_mult\": 1.5}}",
    "status": "WAITING",
    "ticker": "LRCX",
    "trigger_price": 368.65,
    "updated_at": "2026-06-23 14:20:30"
  },
  "trade5": {
    "entry_at": "2026-06-23 17:38:10",
    "entry_fees": 5.2,
    "entry_price": 440.81,
    "exit_at": "2026-06-23 14:10:11",
    "exit_fees": 0.0,
    "exit_price": 444.94,
    "id": 5,
    "notes": "Manual broker screenshot registration; reference P1104145955; Taiwan Semiconductor Manufacturing Co.; executed amount -5000.00 USD; commission incl VAT -5.20 USD; exact quantity 11.34288404; average price 440.81 USD; portfolio Main; market order.",
    "parent_id": null,
    "quantity": 11.34288404,
    "realized_pnl": 40.22999999999995,
    "realized_pnl_pct": 0.8296709982243421,
    "risk_pct": null,
    "status": "CLOSED",
    "stop_loss": 440.82,
    "target_price": null,
    "ticker": "TSM",
    "updated_at": "2026-06-23 14:10:11"
  },
  "trade6": {}
}
```

## After state

```json
{
  "cash_ledger": [
    {
      "amount": 37000.0,
      "balance_after": 37000.0,
      "id": 1,
      "reason": "Initial funding",
      "ts": "2026-06-21 22:32:04"
    },
    {
      "amount": -5005.2,
      "balance_after": 31994.8,
      "id": 2,
      "reason": "TSM broker fill P1104145955: 11.34288404 sh @ 440.81 plus $5.20 commission",
      "ts": "2026-06-23 13:51:59"
    },
    {
      "amount": 5062.16,
      "balance_after": 37056.96,
      "id": 3,
      "reason": "TSM sell P479872813: proceeds net of $5.20 commission",
      "ts": "2026-06-23 14:27:14"
    }
  ],
  "counts": {
    "ema_retry_candidates": 1,
    "pending_pullbacks": 6,
    "trades": 4
  },
  "label": "after",
  "open_trades": [],
  "pending5": {
    "armed_at": "2026-06-22 15:51:54",
    "ema10": 366.81494032141825,
    "expired_at": null,
    "expires_at": "2026-06-25",
    "filled_at": null,
    "id": 5,
    "pct_over_ema": 7.8036787851387235,
    "reference_price": 395.44,
    "score": "3/4 Pillars",
    "signal": "\ud83d\udfe1 BUY (Small)",
    "signal_json": "{\"ticker\": \"LRCX\", \"signal\": \"\\ud83d\\udfe1 BUY (Small)\", \"entry_price\": 395.44, \"score\": \"3/4 Pillars\", \"rvol\": 0.33, \"pillars\": [\"\\u2705 Trend Stack: YES (Price > 50SMA > 150SMA > 200SMA)\", \"\\u2705 Relative Strength: YES (Within 3% of 52W High $402.08)\", \"\\u274c Volume: NO (RVOL: 0.33 < 2.0)\", \"\\u2705 Catalyst: YES \\u2014 Recent news\"], \"catalyst_reason\": \"LLM: Price target raises from analysts\", \"warnings\": [], \"regime\": {\"risk_on\": true, \"detail\": \"SPY 745.49 > 50SMA 730.97\"}, \"risk_card\": {\"daily_volatility_atr\": 26.1, \"stop_loss\": 356.29, \"max_loss_per_share\": 39.15, \"atr_stop_mult\": 1.5}}",
    "status": "WAITING",
    "ticker": "LRCX",
    "trigger_price": 368.65,
    "updated_at": "2026-06-23 14:27:14"
  },
  "trade5": {
    "entry_at": "2026-06-23 17:38:10",
    "entry_fees": 5.2,
    "entry_price": 440.81,
    "exit_at": "2026-06-23 18:22:22",
    "exit_fees": 5.2,
    "exit_price": 446.74,
    "id": 5,
    "notes": "Manual broker screenshot registration; reference P1104145955; Taiwan Semiconductor Manufacturing Co.; executed amount -5000.00 USD; commission incl VAT -5.20 USD; exact quantity 11.34288404; average price 440.81 USD; portfolio Main; market order. | Sell ref P479872813 \u2014 engine fired early exit due to wrong target in DB ($440.83 instead of $501)",
    "parent_id": null,
    "quantity": 11.34288404,
    "realized_pnl": 56.96,
    "realized_pnl_pct": 1.14,
    "risk_pct": null,
    "status": "CLOSED",
    "stop_loss": 440.82,
    "target_price": 501.0,
    "ticker": "TSM",
    "updated_at": "2026-06-23 14:27:14"
  },
  "trade6": {}
}
```

## Count verification

Expected after counts:
```json
{
  "ema_retry_candidates": 1,
  "pending_pullbacks": 6,
  "trades": 4
}
```

Actual after counts:
```json
{
  "ema_retry_candidates": 1,
  "pending_pullbacks": 6,
  "trades": 4
}
```

## DB changes performed

1. TSM trade id 5 set/confirmed CLOSED:
   - exit_price: 446.74
   - exit_at: 2026-06-23 18:22:22
   - exit_fees: 5.20
   - realized_pnl: 56.96
   - realized_pnl_pct: 1.14
   - target_price: 501.00
   - notes appended with sell ref P479872813 and early-exit explanation
2. Cash ledger added +5062.16 net proceeds, unless already present.
3. LRCX phantom trade id 6: already absent at pre-state from prior cleanup; verified still absent.
4. LRCX pending_pullbacks id 5 restored/kept as active pre-fill state: `WAITING`, filled_at NULL.

Note: Atlas schema uses `WAITING` as the active pending state. Setting it to literal `OPEN` would make `get_pending_pullbacks(status="WAITING")` miss it, so the engine-watch state is `WAITING`.

## Target bug findings

Observed bug source: TSM id 5 had `target_price = NULL`. Exit logic fell back to computing target from the current persisted stop. Because a prior trailing-stop update had raised `stop_loss` to near breakeven, fallback target became about 440.83 instead of the intended 2R target.

Relevant existing exit path in `atlas_portfolio.py`:

```text
420:     hard_stop = float(persisted_stop) if persisted_stop is not None else fallback_stop
421:     risk = max(entry - hard_stop, 0.01)
422:     target = lot.get("target_price")
423:     target = float(target) if target is not None else entry + (2 * risk)
424: 
425:     high_water = max(max(highs) if highs else last, last)
426:     peak_R = (high_water - entry) / risk if risk > 0 else 0.0
427:     gain_R = (last - entry) / risk if risk > 0 else 0.0
428: 
429:     stop = hard_stop
430:     trail_note = "persisted decision stop"
431:     if peak_R >= 2.0:
432:         stop = max(stop, entry + risk)
433:         trail_note = "peak +2R reached -> stop locked at +1R"
434:     elif peak_R >= 1.0:
435:         stop = max(stop, entry)
436:         trail_note = "peak +1R reached -> stop at breakeven"
437: 
438:     regime_ok, regime_detail = regime if regime is not None else check_regime()
439:     earnings_ctx = check_earnings_context(ticker)
440:     fda_calendar = check_fda_calendar(ticker, holding=True)
441:     risk_off_tightened = False
442:     if not regime_ok and stop < entry:
443:         stop = entry
444:         risk_off_tightened = True
445:         trail_note = f"regime risk-OFF -> stop tightened to breakeven ({regime_detail})"
446: 
447:     if not dry_run and lot.get("id") and stop > hard_stop:
448:         atlas_db.update_trade_stop(lot.get("id"), round(stop, 2))

638:     risk_distance = fill - stop
639:     target = round(fill + (2 * risk_distance), 2)
640:     confluence_confirmed = bool(pillars == 3 and confluence.get("bullish"))
641:     momentum_weak = bool(pillars == 3 and confluence.get("weak"))
642:     confluence_note = confluence.get("note")
643:     if confluence_confirmed:
644:         trig_detail = f"{trig_detail}; RSI/MACD confluence confirmed"
645: 
646:     decision = {
647:         "ticker": ticker, "action": "BUY", "reason": trig_detail,
648:         "entry": fill, "stop": stop, "target": target, "shares": shares, "cost": cost,
649:         "risk_pct": (RISK_PCT_HALF if half else RISK_PCT_FULL) * 100,
650:         "cautious_mode": cautious,
651:         "score": score,
652:         "signal": signal_result.get("signal", ""),
653:         "rvol": signal_result.get("rvol"),
654:         "analyst_rating": signal_result.get("analyst_rating"),
655:         "analyst_insight": signal_result.get("analyst_insight"),
656:         "fundamentals": fundamentals,
657:         "fda_calendar": fda_calendar,
658:         "fda_note": fda_calendar.get("tag") if isinstance(fda_calendar, dict) else None,
659:         "indicator_info": indicator_info,
660:         "atr_info": signal_result.get("atr_info"),
661:         "sentiment_info": signal_result.get("sentiment_info"),
662:         "indicator_confluence": confluence,
663:         "confluence_confirmed": confluence_confirmed,
664:         "confluence_note": confluence_note,
665:         "momentum_weak": momentum_weak,
666:         "decision_quality": "CONFIRMED_ACT" if confluence_confirmed else ("MOMENTUM_WEAK_ALLOWED" if momentum_weak else "NORMAL"),
667:         "insider_activity": signal_result.get("insider_activity"),
668:         "macro_context": macro_ctx,
669:         "earnings_context": earnings_ctx,
670:         "earnings_note": (earnings_ctx.get("earnings_momentum") or {}).get("earnings_momentum_note")
671:                          or (earnings_ctx.get("earnings_miss") or {}).get("earnings_miss_note")
672:                          or (earnings_ctx.get("note") if earnings_ctx.get("unknown") else None),
673:         "equity": equity,
674:     }
675: 
676:     if not dry_run:
677:         try:
678:             atlas_db.open_trade(
679:                 ticker, fill, shares,
680:                 stop_loss=stop, risk_pct=decision["risk_pct"], target_price=target,
681:                 notes=f"Atlas v2 entry: {trig_detail}; stop {stop}; target {target}; "
```

Fix implemented in `atlas_db.py`: target is now persisted at write/update time when missing and a stop exists.

`open_trade()` target default:

```text
330:     """Open a new lot. Returns the new trade id."""
331:     ticker = (ticker or "").upper()
332:     quantity = int(quantity or 0)
333:     entry_price = float(entry_price)
334:     if target_price is None and stop_loss is not None:
335:         risk = entry_price - float(stop_loss)
336:         if risk > 0:
337:             target_price = round(entry_price + (2 * risk), 2)
338:     if not ticker or quantity <= 0 or entry_price <= 0:
339:         raise ValueError("open_trade requires ticker, positive quantity, positive entry_price")
340:     conn = get_connection()
341:     cursor = conn.cursor()
342:     cursor.execute('''
```

`update_trade_stop()` preserves/sets missing target before raising stop:

```text
487: def update_trade_stop(trade_id, stop_loss):
488:     """Raise/persist the structured stop on one trade lot. Never lowers it."""
489:     conn = get_connection()
490:     cursor = conn.cursor()
491:     cursor.execute("SELECT entry_price, stop_loss, target_price FROM trades WHERE id=? AND status='OPEN'", (int(trade_id),))
492:     row = cursor.fetchone()
493:     if not row:
494:         conn.close()
495:         return 0
496:     entry_price, current, target_price = row
497:     new_stop = float(stop_loss)
498:     if current is not None and float(current) >= new_stop:
499:         conn.close()
500:         return 0
501:     computed_target = None
502:     if target_price is None and current is not None:
503:         risk = float(entry_price) - float(current)
504:         if risk > 0:
505:             computed_target = round(float(entry_price) + (2 * risk), 2)
506:     if computed_target is None:
507:         cursor.execute("UPDATE trades SET stop_loss=?, updated_at=? WHERE id=? AND status='OPEN'", (new_stop, _now(), int(trade_id)))
508:     else:
509:         cursor.execute("UPDATE trades SET stop_loss=?, target_price=?, updated_at=? WHERE id=? AND status='OPEN'", (new_stop, computed_target, _now(), int(trade_id)))
```

## Verification result

- TSM id 5 matches requested sell fields.
- LRCX id 6 absent.
- LRCX pending id 5 active as WAITING with filled_at NULL.
- Counts match expected.
- py_compile OK.
- No restore needed.
