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
LAST_RUN_SUMMARY = {}


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




def _pillar_count(score):
    try:
        return int(str(score).split("/")[0])
    except Exception:
        return 0


def _catalyst_reason(res):
    reason = (res.get("catalyst_reason") or "").strip()
    if reason:
        return reason
    for pillar in res.get("pillars", []) or []:
        text = str(pillar)
        if "Catalyst:" in text and "YES" in text.upper():
            return "Recent news"
    return None

def run(args):
    global LAST_RUN_SUMMARY
    live = args.live
    mode = "LIVE — orders WILL be written" if live else "DRY-RUN — no writes"
    LAST_RUN_SUMMARY = {"live": live, "mode": mode, "started_at": datetime.now().isoformat()}
    print(LINE)
    print(f"  ATLAS v2 DAILY MANAGER   {datetime.now():%Y-%m-%d %H:%M}")
    print(f"  Mode: {mode}")
    print(LINE)

    # 1. ACCOUNT ------------------------------------------------------------
    atlas_db.init_db()    # idempotent; adds pending pullback table if missing
    acct.init_account()  # idempotent; never resets
    summary = acct.get_account_summary(price_lookup=port._price_lookup)
    try:
        open_positions_count = len(atlas_db.get_open_positions())
    except Exception:
        open_positions_count = 0
    LAST_RUN_SUMMARY.update({"account": summary, "open_positions_count": open_positions_count})
    _hdr("ACCOUNT")
    print(f"  Cash available : ${summary['cash']:,.2f}")
    print(f"  Open invested  : ${summary['open_invested']:,.2f}")
    print(f"  Realized P&L   : ${summary['realized_pnl']:,.2f}")
    print(f"  Equity (MTM)   : ${summary['equity']:,.2f}")

    # 2. EXITS FIRST --------------------------------------------------------
    _hdr("EXITS  (evaluated before any new buys)")
    exit_results = port.run_exits(dry_run=not live)
    sells = [r for r in exit_results if r.get("action") == "SELL"]
    LAST_RUN_SUMMARY.update({"exit_results": exit_results, "sells": sells})
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
        LAST_RUN_SUMMARY.update({"exits_only": True, "buys": [], "result": "ACTION" if sells else "DO NOTHING"})
        _finish(live, sells, [])
        return LAST_RUN_SUMMARY

    # 3. REGIME -------------------------------------------------------------
    _hdr("REGIME GATE")
    regime = check_regime()
    regime_ok, regime_detail = regime
    LAST_RUN_SUMMARY.update({"regime_ok": regime_ok, "regime_detail": regime_detail})
    print(f"  {'RISK-ON ' if regime_ok else 'RISK-OFF'} : {regime_detail}")
    if not regime_ok:
        print("  No new positions today (SPY below 50-day SMA).")
        LAST_RUN_SUMMARY.update({"candidates": [], "scanned_count": 0, "high_candidates": [], "watch_2": [], "catalysts": [], "buys": [], "result": "ACTION" if sells else "DO NOTHING"})
        _finish(live, sells, [])
        return LAST_RUN_SUMMARY

    # 4 + 5. SCORE & CONSIDER ----------------------------------------------
    candidates = load_candidates(args)
    pending_rows = atlas_db.get_pending_pullbacks(status="WAITING")
    pending_scan = [r.get("ticker", "").upper() for r in pending_rows if r.get("ticker")]
    candidates = list(dict.fromkeys(pending_scan + [t.upper() for t in candidates]))
    _hdr(f"SCAN & ENTRIES  ({len(candidates)} candidates)")
    buys = []
    watch = []
    expired_pullbacks = []
    pending = []          # tickers approved this run (cap awareness)
    reserved_cash = 0.0   # cash earmarked by approved buys this run
    scanned_count = 0
    high_candidates = []
    watch_2 = []
    catalysts = []
    scan_errors = []
    for tkr in candidates:
        pending_decision = port.evaluate_pending_pullback(
            tkr, dry_run=not live, regime=regime,
            pending=pending, reserved_cash=reserved_cash,
        )
        if pending_decision:
            pact = pending_decision.get("action")
            pscore = pending_decision.get("score") or "?"
            if pact == "BUY":
                buys.append(pending_decision)
                pending.append(tkr.upper())
                reserved_cash += pending_decision["cost"]
                high_candidates.append({
                    "ticker": tkr.upper(), "score": pscore, "pillars": _pillar_count(pscore),
                    "signal": pending_decision.get("signal", ""), "action": pact,
                    "reason": pending_decision.get("reason", ""),
                    "entry": pending_decision.get("entry"), "stop": pending_decision.get("stop"),
                    "cost": pending_decision.get("cost"), "shares": pending_decision.get("shares"),
                })
                print(f"  BUY   {tkr:<6} {pending_decision['shares']} sh @ {pending_decision['entry']} "
                      f"(stop {pending_decision['stop']}, {pending_decision['risk_pct']:.1f}% risk, "
                      f"${pending_decision['cost']:,.0f}) — {pending_decision['reason']}")
                continue
            if pact == "EXPIRE":
                expired_pullbacks.append(pending_decision)
                print(f"  ⌛ {pending_decision['reason']}")
                continue
            if pact == "WAIT":
                watch.append(tkr.upper())
                high_candidates.append({
                    "ticker": tkr.upper(), "score": pscore, "pillars": _pillar_count(pscore),
                    "signal": "PENDING PULLBACK", "action": pact,
                    "reason": pending_decision.get("reason", ""),
                    "entry": pending_decision.get("entry"),
                })
                print(f"  ⏳ {pending_decision['reason']}")
                continue
            if pact in ("BLOCK", "SKIP", "ERROR"):
                print(f"  {pact.lower():<5} {tkr:<6} ({pscore}) {pending_decision.get('reason','')}")
                continue

        try:
            res = analyze_ticker(tkr, regime=regime)
        except TypeError:
            res = analyze_ticker(tkr)  # back-compat if regime kwarg absent
        if "error" in res:
            scan_errors.append({"ticker": tkr.upper(), "error": res["error"]})
            print(f"  ----  {tkr:<6} {res['error']}")
            continue
        scanned_count += 1
        score = res.get("score", "0/4 Pillars")
        pillars = _pillar_count(score)
        catalyst = _catalyst_reason(res)
        if catalyst:
            catalysts.append({"ticker": tkr.upper(), "reason": catalyst})
        if pillars < 3:
            if "WATCH" in str(res.get("signal", "")).upper():
                watch.append(tkr.upper())
                if pillars == 2:
                    watch_2.append(tkr.upper())
            print(f"  skip  {tkr:<6} {res.get('signal','')}  ({score})")
            continue

        decision = port.consider_buy(
            res, dry_run=not live, regime=regime,
            pending=pending, reserved_cash=reserved_cash,
        )
        act = decision["action"]
        high_candidates.append({
            "ticker": tkr.upper(),
            "score": score,
            "pillars": pillars,
            "signal": res.get("signal", ""),
            "action": act,
            "reason": decision.get("reason", ""),
            "entry": decision.get("entry"),
            "stop": decision.get("stop"),
            "cost": decision.get("cost"),
            "shares": decision.get("shares"),
        })
        if act == "BUY":
            buys.append(decision)
            pending.append(tkr.upper())
            reserved_cash += decision["cost"]
            print(f"  BUY   {tkr:<6} {decision['shares']} sh @ {decision['entry']} "
                  f"(stop {decision['stop']}, {decision['risk_pct']:.1f}% risk, "
                  f"${decision['cost']:,.0f}) — {decision['reason']}")
        elif act == "WAIT":
            watch.append(tkr.upper())
            prefix = "⏳" if "WAITING FOR PULLBACK" in str(decision.get("reason", "")) else "wait"
            print(f"  {prefix} {decision['reason']}")
        elif act == "BLOCK":
            print(f"  block {tkr:<6} ({score}) {decision['reason']}")
        else:
            print(f"  {act.lower():<5} {tkr:<6} ({score}) {decision['reason']}")

    LAST_RUN_SUMMARY.update({
        "candidates": candidates,
        "scanned_count": scanned_count,
        "high_candidates": high_candidates,
        "watch_2": sorted(set(watch_2)),
        "catalysts": catalysts,
        "scan_errors": scan_errors,
        "expired_pullbacks": expired_pullbacks,
        "pending_pullbacks": atlas_db.get_pending_pullbacks(status="WAITING"),
        "buys": buys,
        "result": "ACTION" if (buys or sells) else "DO NOTHING",
    })

    # --- PERSIST SCAN RESULT TO HANDOFF (so Vault + pre-market brief stay live) ---
    try:
        import datetime as _dt
        _today = _dt.date.today().strftime("%Y-%m-%d")
        _buy_syms = [b.get("ticker", b.get("symbol", "")) for b in buys]
        _buy_syms = [s.upper() for s in _buy_syms if s]
        _watch_syms = [t.upper() for t in (pending + watch)]  # approved-but-not-bought + scanned
        _existing = atlas_db.get_handoff(_today) or {}
        _handoff = {
            "date": _today,
            "BUY": sorted(set(_buy_syms)),
            "WATCH": sorted(set((_existing.get("WATCH") or []) + _watch_syms)),
            "last_scan": _dt.datetime.now().isoformat(),
        }
        atlas_db.update_handoff(_today, _handoff)
        LAST_RUN_SUMMARY["handoff"] = _handoff
        print(f"  [handoff] saved {len(_handoff['BUY'])} BUY / {len(_handoff['WATCH'])} WATCH for {_today}")
    except Exception as _e:
        LAST_RUN_SUMMARY["handoff_error"] = str(_e)
        print(f"  [handoff] persist skipped: {_e}")
    # ------------------------------------------------------------------------------

    _finish(live, sells, buys)
    return LAST_RUN_SUMMARY


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
    summary = run(args)
    if args.json:
        print(json.dumps(summary, default=str))


if __name__ == "__main__":
    main()
