#!/usr/bin/env python3
"""
atlas_manage.py  —  Atlas v2 daily portfolio runner
============================================================================

This is the ONE command you run each day. It executes the full v2 loop in the
correct order and prints a clean, human-readable summary:

  1. ACCOUNT      ensure the account table exists; print cash / equity.
  2. EXITS FIRST  evaluate every OPEN lot against the trailing-stop /
                  time-exit rules. We sell BEFORE buying so freed cash and
                  freed position slots are available to new entries today.
  3. REGIME       check the SPY > 50SMA gate once. If risk-OFF, no new buys.
  4. SCORE        run the v2 engine over the candidate list (CLI args, a
                  --file watchlist, or the default universe) -> BUY / BUY Small.
  5. CONSIDER     for each qualifying signal, run admission + sizing +
                  pullback-to-EMA10 trigger and (unless --dry-run) open lots.
  6. SUMMARY      print everything that happened.

SAFETY
------
  - Default mode is --dry-run = OFF only when you pass --live. Without --live,
    NOTHING is written: it just shows what it WOULD do.
  - All sells/buys go through the existing atlas_db FIFO ledger (open_trade /
    close_trade), which already pushes to The Vault. No data is ever deleted.

USAGE
-----
  python3 ~/scripts/atlas_manage.py                 # dry-run, default universe
  python3 ~/scripts/atlas_manage.py NVDA AMD PLTR   # dry-run, specific tickers
  python3 ~/scripts/atlas_manage.py --file wl.txt   # dry-run, watchlist file
  python3 ~/scripts/atlas_manage.py --live          # EXECUTE today's plan
  python3 ~/scripts/atlas_manage.py --exits-only --live   # only run exits
"""

import os
import sys
import json
import argparse
from datetime import datetime

sys.path.insert(0, "/Users/yasser/scripts")

import atlas_db
import atlas_account as acct
import atlas_portfolio as port
from atlas_engine import analyze_ticker, check_regime

# Default universe if the user passes no tickers. Kept small & liquid; the
# scout normally supplies the real candidates, but this gives a sane default.
DEFAULT_UNIVERSE = [
    "NVDA", "AMD", "AVGO", "SMCI", "MU",
    "AAPL", "MSFT", "GOOGL", "META", "AMZN",
    "TSLA", "NFLX", "PLTR", "SNOW", "CRWD",
    "LLY", "JPM", "COIN", "ORCL", "NOW",
]

LINE = "=" * 68
THIN = "-" * 68


def _hdr(title):
    print(f"\n{LINE}\n  {title}\n{LINE}")


def load_candidates(args):
    if args.tickers:
        return [t.upper() for t in args.tickers]
    if args.file and os.path.exists(args.file):
        with open(args.file) as f:
            toks = []
            for line in f:
                line = line.split("#", 1)[0].strip()
                if line:
                    toks += [p.strip().upper() for p in line.replace(",", " ").split()]
            return [t for t in toks if t]
    # Default: reuse the SAME news-driven discovery the scout uses, so the
    # daily manager scans exactly the universe market_scout.py would. Falls
    # back to the built-in liquid list if the scout isn't importable.
    try:
        from market_scout import discover_tickers
        found = discover_tickers()
        if found:
            return [t.upper() for t in found]
    except Exception:
        pass
    return list(DEFAULT_UNIVERSE)


def run(args):
    live = args.live
    mode = "LIVE — orders WILL be written" if live else "DRY-RUN — no writes"
    print(LINE)
    print(f"  ATLAS v2 DAILY MANAGER   {datetime.now():%Y-%m-%d %H:%M}")
    print(f"  Mode: {mode}")
    print(LINE)

    # 1. ACCOUNT ------------------------------------------------------------
    acct.init_account()  # idempotent; never resets
    summary = acct.get_account_summary(price_lookup=port._price_lookup)
    _hdr("ACCOUNT")
    print(f"  Cash available : ${summary['cash']:,.2f}")
    print(f"  Open invested  : ${summary['open_invested']:,.2f}")
    print(f"  Realized P&L   : ${summary['realized_pnl']:,.2f}")
    print(f"  Equity (MTM)   : ${summary['equity']:,.2f}")

    # 2. EXITS FIRST --------------------------------------------------------
    _hdr("EXITS  (evaluated before any new buys)")
    exit_results = port.run_exits(dry_run=not live)
    sells = [r for r in exit_results if r.get("action") == "SELL"]
    if not exit_results:
        print("  No open positions.")
    for r in exit_results:
        if r["action"] == "SELL":
            print(f"  SELL  {r['ticker']:<6} x{r.get('qty','?'):<5} @ {r.get('price')}  — {r['reason']}")
        elif r["action"] == "HOLD":
            print(f"  HOLD  {r['ticker']:<6} {r['reason']}")
        else:
            print(f"  {r['action']:<5} {r['ticker']:<6} {r['reason']}")

    if args.exits_only:
        _finish(live, sells, [])
        return

    # 3. REGIME -------------------------------------------------------------
    _hdr("REGIME GATE")
    regime = check_regime()
    regime_ok, regime_detail = regime
    print(f"  {'RISK-ON ' if regime_ok else 'RISK-OFF'} : {regime_detail}")
    if not regime_ok:
        print("  No new positions today (SPY below 50-day SMA).")
        _finish(live, sells, [])
        return

    # 4 + 5. SCORE & CONSIDER ----------------------------------------------
    candidates = load_candidates(args)
    _hdr(f"SCAN & ENTRIES  ({len(candidates)} candidates)")
    buys = []
    pending = []          # tickers approved this run (cap awareness)
    reserved_cash = 0.0   # cash earmarked by approved buys this run
    for tkr in candidates:
        try:
            res = analyze_ticker(tkr, regime=regime)
        except TypeError:
            res = analyze_ticker(tkr)  # back-compat if regime kwarg absent
        if "error" in res:
            print(f"  ----  {tkr:<6} {res['error']}")
            continue
        score = res.get("score", "0/4 Pillars")
        pillars = int(str(score).split("/")[0])
        if pillars < 3:
            print(f"  skip  {tkr:<6} {res.get('signal','')}  ({score})")
            continue

        decision = port.consider_buy(
            res, dry_run=not live, regime=regime,
            pending=pending, reserved_cash=reserved_cash,
        )
        act = decision["action"]
        if act == "BUY":
            buys.append(decision)
            pending.append(tkr.upper())
            reserved_cash += decision["cost"]
            print(f"  BUY   {tkr:<6} {decision['shares']} sh @ {decision['entry']} "
                  f"(stop {decision['stop']}, {decision['risk_pct']:.1f}% risk, "
                  f"${decision['cost']:,.0f}) — {decision['reason']}")
        elif act == "WAIT":
            print(f"  wait  {tkr:<6} ({score}) {decision['reason']}")
        elif act == "BLOCK":
            print(f"  block {tkr:<6} ({score}) {decision['reason']}")
        else:
            print(f"  {act.lower():<5} {tkr:<6} ({score}) {decision['reason']}")

    # --- PERSIST SCAN RESULT TO HANDOFF (so Vault + pre-market brief stay live) ---
    try:
        import datetime as _dt
        _today = _dt.date.today().strftime("%Y-%m-%d")
        _buy_syms = [b.get("ticker", b.get("symbol", "")) for b in buys]
        _buy_syms = [s.upper() for s in _buy_syms if s]
        _watch_syms = [t.upper() for t in pending]  # approved-but-not-bought + scanned
        _existing = atlas_db.get_handoff(_today) or {}
        _handoff = {
            "date": _today,
            "BUY": sorted(set(_buy_syms)),
            "WATCH": sorted(set((_existing.get("WATCH") or []) + _watch_syms)),
            "last_scan": _dt.datetime.now().isoformat(),
        }
        atlas_db.update_handoff(_today, _handoff)
        print(f"  [handoff] saved {len(_handoff['BUY'])} BUY / {len(_handoff['WATCH'])} WATCH for {_today}")
    except Exception as _e:
        print(f"  [handoff] persist skipped: {_e}")
    # ------------------------------------------------------------------------------

    _finish(live, sells, buys)


def _finish(live, sells, buys):
    _hdr("SUMMARY")
    print(f"  Sells executed : {len(sells)}" if live else f"  Sells planned  : {len(sells)}")
    print(f"  Buys executed  : {len(buys)}" if live else f"  Buys planned   : {len(buys)}")
    post = acct.get_account_summary(price_lookup=port._price_lookup)
    print(f"  Cash now       : ${post['cash']:,.2f}")
    print(f"  Equity now     : ${post['equity']:,.2f}")
    if not live:
        print(THIN)
        print("  This was a DRY-RUN. Re-run with --live to execute.")
    print(LINE + "\n")


def main():
    p = argparse.ArgumentParser(description="Atlas v2 daily portfolio manager")
    p.add_argument("tickers", nargs="*", help="Optional explicit tickers to scan")
    p.add_argument("--file", help="Path to a watchlist file (one/many tickers per line)")
    p.add_argument("--live", action="store_true", help="Execute orders (default is dry-run)")
    p.add_argument("--exits-only", action="store_true", help="Only run the exit engine")
    p.add_argument("--json", action="store_true", help="Also dump machine-readable JSON")
    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
