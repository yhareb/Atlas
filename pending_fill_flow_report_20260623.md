# Pending Broker Confirmation Flow — Verification Report

## Files edited

- `/Users/yasser/scripts/atlas_db.py`
- `/Users/yasser/scripts/atlas_portfolio.py`
- `/Users/yasser/scripts/atlas_intraday.py`
- `/Users/yasser/scripts/atlas_manage.py`

## Backups

- `/Users/yasser/scripts/atlas_db_pendingflow_20260623_183251.py`
- `/Users/yasser/scripts/atlas_portfolio_pendingflow_20260623_183251.py`
- `/Users/yasser/scripts/atlas_intraday_pendingflow_20260623_183251.py`
- `/Users/yasser/scripts/atlas_manage_pendingflow_20260623_183251.py`
- `/Users/yasser/scripts/atlas_pendingflow_20260623_183251.db`

## Safety state

Before:
```json
{
  "cash_latest": 37056.96,
  "cash_ledger_count": 3,
  "counts": {
    "ema_retry_candidates": 1,
    "pending_pullbacks": 6,
    "trades": 4
  },
  "label": "before",
  "open_positions": [],
  "pending_fill": [],
  "trades": [
    {
      "entry_fees": 0.0,
      "entry_price": 299.81,
      "id": 1,
      "notes": "Atlas v2 entry: Pulled back to 10-EMA 298.44 (close 299.81); stop 292.31; 1% risk on equity $37,000",
      "quantity": 24,
      "status": "CLOSED",
      "stop_loss": null,
      "target_price": null,
      "ticker": "AAPL"
    },
    {
      "entry_fees": 0.0,
      "entry_price": 102.33,
      "id": 2,
      "notes": "Atlas v2 entry: Pulled back to armed 10-EMA limit 102.33 (last 100.40); stop 96.33; 1% risk on equity $37,000",
      "quantity": 61,
      "status": "CLOSED",
      "stop_loss": null,
      "target_price": null,
      "ticker": "PBXT"
    },
    {
      "entry_fees": 0.0,
      "entry_price": 101.0,
      "id": 3,
      "notes": "Atlas v2 entry: Pulled back to 10-EMA 100.18 (close 101.00); stop 95.0; 1% risk on equity $37,000",
      "quantity": 61,
      "status": "CLOSED",
      "stop_loss": null,
      "target_price": null,
      "ticker": "IBXT"
    },
    {
      "entry_fees": 5.2,
      "entry_price": 440.81,
      "id": 5,
      "notes": "Manual broker screenshot registration; reference P1104145955; Taiwan Semiconductor Manufacturing Co.; executed amount -5000.00 USD; commission incl VAT -5.20 USD; exact quantity 11.34288404; average price 440.81 USD; portfolio Main; market order. | Sell ref P479872813 \u2014 engine fired early exit due to wrong target in DB ($440.83 instead of $501)",
      "quantity": 11.34288404,
      "status": "CLOSED",
      "stop_loss": 440.82,
      "target_price": 501.0,
      "ticker": "TSM"
    }
  ]
}
```

After final cleanup:
```json
{
  "cash_latest": 37056.96,
  "cash_ledger_count": 3,
  "counts": {
    "ema_retry_candidates": 1,
    "pending_pullbacks": 6,
    "trades": 4
  },
  "label": "final",
  "open_positions": [],
  "pending_fill": [],
  "trades": [
    {
      "entry_fees": 0.0,
      "entry_price": 299.81,
      "id": 1,
      "notes": "Atlas v2 entry: Pulled back to 10-EMA 298.44 (close 299.81); stop 292.31; 1% risk on equity $37,000",
      "quantity": 24,
      "status": "CLOSED",
      "stop_loss": null,
      "target_price": null,
      "ticker": "AAPL"
    },
    {
      "entry_fees": 0.0,
      "entry_price": 102.33,
      "id": 2,
      "notes": "Atlas v2 entry: Pulled back to armed 10-EMA limit 102.33 (last 100.40); stop 96.33; 1% risk on equity $37,000",
      "quantity": 61,
      "status": "CLOSED",
      "stop_loss": null,
      "target_price": null,
      "ticker": "PBXT"
    },
    {
      "entry_fees": 0.0,
      "entry_price": 101.0,
      "id": 3,
      "notes": "Atlas v2 entry: Pulled back to 10-EMA 100.18 (close 101.00); stop 95.0; 1% risk on equity $37,000",
      "quantity": 61,
      "status": "CLOSED",
      "stop_loss": null,
      "target_price": null,
      "ticker": "IBXT"
    },
    {
      "entry_fees": 5.2,
      "entry_price": 440.81,
      "id": 5,
      "notes": "Manual broker screenshot registration; reference P1104145955; Taiwan Semiconductor Manufacturing Co.; executed amount -5000.00 USD; commission incl VAT -5.20 USD; exact quantity 11.34288404; average price 440.81 USD; portfolio Main; market order. | Sell ref P479872813 \u2014 engine fired early exit due to wrong target in DB ($440.83 instead of $501)",
      "quantity": 11.34288404,
      "status": "CLOSED",
      "stop_loss": 440.82,
      "target_price": 501.0,
      "ticker": "TSM"
    }
  ]
}
```

## Mandatory verification

1. Timestamped backups: complete, suffix `_pendingflow_20260623_183251`.
2. Before/after counts unchanged: `{'pending_pullbacks': 6, 'trades': 4, 'ema_retry_candidates': 1}` -> `{'pending_pullbacks': 6, 'trades': 4, 'ema_retry_candidates': 1}`.
3. Account state confirmed: cash latest `$37,056.96`, 0 OPEN rows, 0 PENDING_FILL rows before and after.
4. py_compile: OK for all edited files.
5. live=False dry-run: no PENDING_FILL rows written; counts unchanged.
6. synthetic live=True: PENDING_FILL row was written, not OPEN; captured below; then removed to restore counts.
7. Restore-on-failure: armed in verification script; not needed.
8. No live flip: no live flag was changed.

## Synthetic PENDING_FILL row captured

```json
{
  "entry_at": "2026-06-23 14:35:42",
  "entry_fees": 0.0,
  "entry_price": 100.0,
  "exit_at": null,
  "exit_fees": 0.0,
  "exit_price": null,
  "id": 7,
  "notes": "Atlas v2 entry: Synthetic pending-flow live verification; score 3/4 Pillars; signal \ud83d\udfe1 BUY (Small); stop 90.0; target 120.0; 0.5% risk on equity $37,057",
  "parent_id": null,
  "quantity": 18,
  "realized_pnl": null,
  "realized_pnl_pct": null,
  "risk_pct": 0.5,
  "status": "PENDING_FILL",
  "stop_loss": 90.0,
  "target_price": 120.0,
  "ticker": "ZZPF",
  "updated_at": "2026-06-23 14:35:42"
}
```

## Intraday AWAITING CONFIRMATION section captured

```text
⏳ AWAITING YOUR CONFIRMATION 🔔 (engine decided — confirm at broker then register)
1️⃣ ZZPF — 3/4 pillars · signal entry $100 · stop $90 · target $120 · 18 sh · 0.5% risk
   💡 Synthetic pending-flow live verification
   👉 register ZZPF buy qty=18 price=$100.00 fees=${commission} ref={broker_ref}
```

## Cash ledger proof

Before synthetic live: latest cash `37056.96`, cash ledger rows `3`.
After synthetic PENDING_FILL write: latest cash `37056.96`, cash ledger rows `3`.

Conclusion: cash ledger is NOT debited until `confirm_trade_fill()` is called.

## Key code snippets

### atlas_db.py:325-346
```text
325:     return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
326: 
327: 
328: def open_trade(ticker, entry_price, quantity, fees=0.0, notes=None, entry_at=None,
329:                stop_loss=None, risk_pct=None, target_price=None, status="PENDING_FILL"):
330:     """Open a new lot. Returns the new trade id."""
331:     ticker = (ticker or "").upper()
332:     quantity = int(quantity or 0)
333:     entry_price = float(entry_price)
334:     status = str(status or "PENDING_FILL").upper()
335:     if status not in ("PENDING_FILL", "OPEN"):
336:         raise ValueError("open_trade status must be PENDING_FILL or OPEN")
337:     if target_price is None and stop_loss is not None:
338:         risk = entry_price - float(stop_loss)
339:         if risk > 0:
340:             target_price = round(entry_price + (2 * risk), 2)
341:     if not ticker or quantity <= 0 or entry_price <= 0:
342:         raise ValueError("open_trade requires ticker, positive quantity, positive entry_price")
343:     conn = get_connection()
344:     cursor = conn.cursor()
345:     cursor.execute('''
346:         INSERT INTO trades (ticker, status, quantity, entry_price, entry_at,
```
### atlas_db.py:377-398
```text
377:     return balance_after
378: 
379: 
380: def confirm_trade_fill(trade_id, broker_qty, broker_price, broker_fees, broker_ref):
381:     """Flip a PENDING_FILL trade to OPEN using confirmed broker fill details."""
382:     trade_id = int(trade_id)
383:     broker_qty = float(broker_qty)
384:     broker_price = float(broker_price)
385:     broker_fees = float(broker_fees or 0.0)
386:     broker_ref = str(broker_ref or "").strip()
387:     if broker_qty <= 0 or broker_price <= 0:
388:         raise ValueError("confirm_trade_fill requires positive broker_qty and broker_price")
389:     conn = get_connection()
390:     cursor = conn.cursor()
391:     cursor.execute("""
392:         SELECT ticker, status, stop_loss, target_price, notes
393:         FROM trades WHERE id = ?
394:     """, (trade_id,))
395:     row = cursor.fetchone()
396:     if not row:
397:         conn.close()
398:         raise ValueError(f"Trade id {trade_id} not found")
```
### atlas_db.py:425-446
```text
425:     return _fetch_trade_rows([trade_id])[0]
426: 
427: 
428: def get_pending_fill_trades():
429:     """Return engine-approved trades awaiting manual broker confirmation."""
430:     conn = get_connection()
431:     cursor = conn.cursor()
432:     cursor.execute('''
433:         SELECT id, ticker, status, quantity, entry_price, entry_at,
434:                exit_price, exit_at, entry_fees, exit_fees,
435:                realized_pnl, realized_pnl_pct, parent_id,
436:                stop_loss, risk_pct, target_price, notes, updated_at
437:         FROM trades WHERE status = 'PENDING_FILL'
438:         ORDER BY entry_at ASC, id ASC
439:     ''')
440:     cols = [d[0] for d in cursor.description]
441:     rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
442:     conn.close()
443:     return rows
444: 
445: 
446: def close_trade(ticker, exit_price, quantity=None, fees=0.0, exit_at=None):
```
### atlas_db.py:326-347
```text
326: 
327: 
328: def open_trade(ticker, entry_price, quantity, fees=0.0, notes=None, entry_at=None,
329:                stop_loss=None, risk_pct=None, target_price=None, status="PENDING_FILL"):
330:     """Open a new lot. Returns the new trade id."""
331:     ticker = (ticker or "").upper()
332:     quantity = int(quantity or 0)
333:     entry_price = float(entry_price)
334:     status = str(status or "PENDING_FILL").upper()
335:     if status not in ("PENDING_FILL", "OPEN"):
336:         raise ValueError("open_trade status must be PENDING_FILL or OPEN")
337:     if target_price is None and stop_loss is not None:
338:         risk = entry_price - float(stop_loss)
339:         if risk > 0:
340:             target_price = round(entry_price + (2 * risk), 2)
341:     if not ticker or quantity <= 0 or entry_price <= 0:
342:         raise ValueError("open_trade requires ticker, positive quantity, positive entry_price")
343:     conn = get_connection()
344:     cursor = conn.cursor()
345:     cursor.execute('''
346:         INSERT INTO trades (ticker, status, quantity, entry_price, entry_at,
347:                             entry_fees, stop_loss, risk_pct, target_price, notes, updated_at)
```
### atlas_portfolio.py:678-699
```text
678:             atlas_db.open_trade(
679:                 ticker, fill, shares,
680:                 stop_loss=stop, risk_pct=decision["risk_pct"], target_price=target,
681:                 status="PENDING_FILL",
682:                 notes=f"Atlas v2 entry: {trig_detail}; score {score}; signal {signal_result.get('signal', '')}; stop {stop}; target {target}; "
683:                       f"{'0.5%' if half else '1%'} risk on equity ${equity:,.0f}"
684:                       f"{' (cautious weak-market/macro mode)' if cautious else ''}",
685:             )
686:         except Exception as e:
687:             decision["action"] = "ERROR"
688:             decision["reason"] = str(e)
689: 
690:     return decision
691: 
692: 
693: if __name__ == "__main__":
694:     acct.init_account()
695:     print(json.dumps({
696:         "account": acct.get_account_summary(price_lookup=_price_lookup),
697:         "open_positions": _open_positions(),
698:         "exits_dry_run": run_exits(dry_run=True),
699:     }, indent=2, default=str))
```
### atlas_intraday.py:342-363
```text
342:     return lines
343: 
344: 
345: def _pending_confirmation_lines():
346:     rows = atlas_db.get_pending_fill_trades()
347:     lines = ["", "⏳ AWAITING YOUR CONFIRMATION 🔔 (engine decided — confirm at broker then register)"]
348:     if not rows:
349:         lines.append("✅ No pending confirmations")
350:         return lines
351:     for i, row in enumerate(rows, 1):
352:         ticker = str(row.get("ticker") or "?").upper()
353:         entry = _num(row.get("entry_price"))
354:         stop = _num(row.get("stop_loss"))
355:         target = _num(row.get("target_price"))
356:         shares = row.get("quantity")
357:         risk_pct = row.get("risk_pct")
358:         notes = row.get("notes") or ""
359:         score_match = re.search(r"score\s+([^;]+)", notes)
360:         score = score_match.group(1).strip() if score_match else "?/4"
361:         reason = notes.split("; score", 1)[0].replace("Atlas v2 entry:", "").strip() or "Engine BUY decision awaiting broker confirmation"
362:         risk_txt = "n/a" if risk_pct in (None, "") else f"{_num(risk_pct):.1f}%"
363:         lines += [
```
### atlas_manage.py:427-448
```text
427:     return default
428: 
429: 
430: def handle_register(argv):
431:     """Register a user-confirmed broker fill.
432: 
433:     Usage: atlas_manage.py register TICKER buy qty=N price=P fees=F ref=REF
434:     If a PENDING_FILL row exists for the ticker, it is confirmed into OPEN.
435:     Otherwise a new OPEN trade is created for manual broker registrations.
436:     """
437:     if len(argv) < 4:
438:         raise SystemExit("Usage: atlas_manage.py register TICKER buy qty=N price=P fees=F ref=REF")
439:     ticker = argv[2].upper()
440:     side = argv[3].lower()
441:     if side != "buy":
442:         raise SystemExit("Only 'buy' register is supported here")
443:     qty_raw = _register_value(argv[4:], "qty")
444:     price_raw = _register_value(argv[4:], "price")
445:     if qty_raw is None or price_raw is None:
446:         raise SystemExit("register requires qty=N and price=P")
447:     qty = float(qty_raw)
448:     price = float(str(price_raw).replace("$", ""))
```
