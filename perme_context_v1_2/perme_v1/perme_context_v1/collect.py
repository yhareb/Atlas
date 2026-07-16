from __future__ import annotations
import importlib.util, sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
from .io import DB_PATH, open_trades_snapshot

PRODUCTION_COLLECTOR = "/Users/yasser/scripts/atlas_perme.py"
ET = ZoneInfo("America/New_York")

def _load_collector():
    scripts = str(Path(PRODUCTION_COLLECTOR).parent)
    if scripts not in sys.path: sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("atlas_perme_stage_readonly", PRODUCTION_COLLECTOR)
    if not spec or not spec.loader: raise RuntimeError("collector import unavailable")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

def collect(routine: str, mode: str) -> dict[str, Any]:
    module = _load_collector()
    # Provider env only. Do not load PERME_ENV or invoke any Telegram/report path.
    if mode == "live": module._load_env_file(module.ATLAS_ENV)
    provider = module.collect_context(routine, mock=(mode == "mock"))
    observed = datetime.fromisoformat(provider["generated_at_et"])
    if observed.tzinfo is None: observed = observed.replace(tzinfo=ET)
    trades = open_trades_snapshot()
    provider_rows=sum(len(provider.get(key) or []) for key in ("benzinga_news","benzinga_earnings","eodhd_economic_calendar","massive_sector_etfs"))
    return {
      "bundle_schema":"perme_raw_evidence_bundle_v1", "mode":mode,
      "observed_at":observed.astimezone(ET).isoformat(timespec="seconds"),
      "provider_status":{"status":"SUCCESS_NONEMPTY" if provider_rows else "SUCCESS_EMPTY","completeness":"COMPLETE_RETURN"},
      "provider_collector":{"path":PRODUCTION_COLLECTOR,"function":"collect_context","read_only":True},
      "portfolio_source":{"path":DB_PATH,"query":"SELECT id,ticker,status,entry_at,exit_at FROM trades WHERE status='OPEN' ORDER BY ticker,id","read_only":True},
      "provider_context":provider,"open_trades":trades
    }
