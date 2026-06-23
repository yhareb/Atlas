# LRCX Phantom Trade Read-only Investigation — 2026-06-23

## Scope

Read-only investigation only. No DB changes. No source changes. No live flip.

## 1. Exact DB row for LRCX trade id 6

Current row from `trades`:

```json
{
  "entry_at": "2026-06-23 13:50:30",
  "entry_fees": 0.0,
  "entry_price": 368.65,
  "exit_at": null,
  "exit_fees": 0.0,
  "exit_price": null,
  "id": 6,
  "notes": "Atlas v2 entry: Pulled back to armed 10-EMA limit 368.65 (last 368.54); stop 329.5; target 446.95; 0.5% risk on equity $37,025 (cautious weak-market/macro mode)",
  "parent_id": null,
  "quantity": 4,
  "realized_pnl": null,
  "realized_pnl_pct": null,
  "risk_pct": 0.5,
  "status": "OPEN",
  "stop_loss": 368.66,
  "target_price": 446.95,
  "ticker": "LRCX",
  "updated_at": "2026-06-23 14:10:15"
}
```

Note:
- There is no `created_at` column in `trades`.
- Creation timestamp is `entry_at`.
- Current `stop_loss` is `368.66`, while original note says `stop 329.5`. That means a later stop-update path likely raised the DB stop after insertion.

## 2. Related pending pullback row

The LRCX pending pullback row shows it was marked filled at the same timestamp as the trade insert:

```json
{
  "id": 5,
  "ticker": "LRCX",
  "status": "FILLED",
  "score": "3/4 Pillars",
  "signal": "🟡 BUY (Small)",
  "armed_at": "2026-06-22 15:51:54",
  "expires_at": "2026-06-25",
  "ema10": 366.81494032141825,
  "trigger_price": 368.65,
  "reference_price": 395.44,
  "pct_over_ema": 7.8036787851387235,
  "filled_at": "2026-06-23 13:50:30",
  "updated_at": "2026-06-23 13:50:30"
}
```

## 3. Log evidence: inserted during live intraday cycle

Relevant `atlas_intraday.log` lines:

```text
4814: [2026-06-23 17:50:00] Atlas intraday loop starting...
4815: [intraday] market-hours gate: market hours — Tue 2026-06-23 09:50 EDT
4816: [atlas_stream] background stream started for CGEM,LRCX,MU,PGEN,PTGX,TSM
4819:   ATLAS v2 DAILY MANAGER   2026-06-23 17:50
4820:   Mode: LIVE — orders WILL be written
```

The buy line:

```text
4848:   BUY   LRCX   4 sh @ 368.65 (stop 329.5, 0.5% risk, $1,475) — Pulled back to armed 10-EMA limit 368.65 (last 368.54)
```

Summary:

```text
4880:   Sells executed : 0
4881:   Buys executed  : 1
4882:   Cash now       : $25,671.29
4883:   Equity now     : $32,055.74
```

Vault push evidence from the same cycle:

```text
4887: [2026-06-23T13:50:31+00:00] vault_client: pushed trades {'trades': 1}
```

Telegram report also announced it as an order placed:

```text
4920: 🟢 BUY NOW 🛒 (orders placed this cycle)
4921: 1️⃣ LRCX ⭐⭐⭐ 3/4 | 📊 RVOL 0.3🔥 | ✅ solid fundamentals | fin margin 31% | 📉 RSI 72 | 📈 MACD+ | ⚠️ momentum weak | ⚠️ Fed/CPI day — cautious
4922:    💵 Buy $369  🛑 Stop $330  🎯 Target $447
4924:    ⚖️ 4 sh (~$1,475)
4925:    💡 Pulled back to armed 10-EMA limit 368.65 (last 368.54)
```

Conclusion:
- LRCX id 6 was inserted automatically by the scheduled intraday live cycle.
- It was not inserted during dry-run.
- It was inserted because `atlas_intraday.py` runs `atlas_manage` with `live=True`.

## 4. Exact code path that made it happen

### A) `atlas_intraday.py` forces live mode

```text
520|    import atlas_manage
521|    args = SimpleNamespace(tickers=[], file=None, live=True, exits_only=False, json=False)
522|    stdout_buf = io.StringIO()
523|    stderr_buf = io.StringIO()
524|    with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
525|        summary = atlas_manage.run(args)
```

### B) `atlas_manage.py` converts `live=True` into `dry_run=False`

```text
111|def run(args):
112|    global LAST_RUN_SUMMARY
113|    live = args.live
114|    mode = "LIVE — orders WILL be written" if live else "DRY-RUN — no writes"
```

Pending pullback evaluation path:

```text
192|    for tkr in candidates:
193|        pending_decision = port.evaluate_pending_pullback(
194|            tkr, dry_run=not live, regime=regime,
195|            pending=pending, reserved_cash=reserved_cash,
196|        )
```

For normal scan decisions:

```text
302|        decision = port.consider_buy(
303|            res, dry_run=not live, regime=regime,
304|            pending=pending, reserved_cash=reserved_cash,
305|        )
```

Since `live=True`, both paths pass:

```text
dry_run=False
```

### C) `atlas_portfolio.py` pending pullback calls `consider_buy(...)`

```text
329|    if state["last_close"] <= trigger:
330|        sig = row.get("signal_result") or {}
331|        sig.setdefault("ticker", ticker)
332|        sig.setdefault("score", row.get("score") or "3/4 Pillars")
333|        decision = consider_buy(
334|            sig, dry_run=dry_run, regime=regime, pending=pending,
335|            reserved_cash=reserved_cash, pullback_override_entry=round(trigger, 2),
336|            pullback_override_reason=(f"Pulled back to armed 10-EMA limit {trigger:.2f} "
337|                                      f"(last {state['last_close']:.2f})"),
338|            manage_pending=False,
339|        )
340|        decision["pending_id"] = row.get("id")
341|        decision["from_pending_pullback"] = True
342|        decision.setdefault("score", sig.get("score") or row.get("score"))
343|        decision.setdefault("signal", sig.get("signal") or row.get("signal"))
344|        decision.setdefault("rvol", sig.get("rvol"))
345|        if decision.get("action") == "BUY" and not dry_run:
346|            atlas_db.mark_pending_pullback_filled(ticker)
```

### D) `atlas_portfolio.py` writes OPEN trade directly when not dry-run

```text
676|    if not dry_run:
677|        try:
678|            atlas_db.open_trade(
679|                ticker, fill, shares,
680|                stop_loss=stop, risk_pct=decision["risk_pct"], target_price=target,
681|                notes=f"Atlas v2 entry: {trig_detail}; stop {stop}; target {target}; "
682|                      f"{'0.5%' if half else '1%'} risk on equity ${equity:,.0f}"
683|                      f"{' (cautious weak-market/macro mode)' if cautious else ''}",
684|            )
```

### E) `atlas_db.py` inserts directly into `trades` as `OPEN`

```text
328|def open_trade(ticker, entry_price, quantity, fees=0.0, notes=None, entry_at=None,
329|               stop_loss=None, risk_pct=None, target_price=None):
330|    """Open a new lot. Returns the new trade id."""
331|    ticker = (ticker or "").upper()
332|    quantity = int(quantity or 0)
333|    entry_price = float(entry_price)
334|    if not ticker or quantity <= 0 or entry_price <= 0:
335|        raise ValueError("open_trade requires ticker, positive quantity, positive entry_price")
336|    conn = get_connection()
337|    cursor = conn.cursor()
338|    cursor.execute('''
339|        INSERT INTO trades (ticker, status, quantity, entry_price, entry_at,
340|                            entry_fees, stop_loss, risk_pct, target_price, notes, updated_at)
341|        VALUES (?, 'OPEN', ?, ?, ?, ?, ?, ?, ?, ?, ?)
342|    ''', (ticker, quantity, entry_price, entry_at or _now(), float(fees or 0),
343|          None if stop_loss is None else float(stop_loss),
344|          None if risk_pct is None else float(risk_pct),
345|          None if target_price is None else float(target_price), notes, _now()))
346|    trade_id = cursor.lastrowid
347|    conn.commit()
348|    conn.close()
349|
350|    # Real-time push of the new lot (fire-and-forget; never raises).
351|    _safe_push("push_trades", _fetch_trade_rows([trade_id]))
352|    return trade_id
```

## 5. Answer: where is the phantom path?

Confirmed path:

```text
atlas_intraday.py live=True
→ atlas_manage.run(args)
→ port.evaluate_pending_pullback(... dry_run=False ...)
→ consider_buy(... dry_run=False ...)
→ atlas_db.open_trade(...)
→ direct INSERT INTO trades ... VALUES (..., 'OPEN', ...)
```

There is no broker-confirmation step in this path. The code treats a BUY decision in live mode as enough to insert an OPEN trade row.

## 6. Direct answers

How did LRCX id 6 get inserted?
- It was inserted by the engine/portfolio path during a live scheduled intraday cycle at 09:50 ET / 17:50 local.
- It was triggered by a pending pullback fill:
  `Pulled back to armed 10-EMA limit 368.65 (last 368.54)`
- The insertion happened via `atlas_db.open_trade()` inside `atlas_portfolio.consider_buy()` because `dry_run=False`.

Was it inserted by dry-run?
- No.

Was it inserted by live cycle?
- Yes.

Was there confirmed broker fill evidence in this path?
- No. The inspected code writes the DB trade directly on BUY decision when live, before any broker-confirmation mechanism.
