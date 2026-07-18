#!/usr/bin/env python3
"""Atlas production conversation entrypoint.

This module is the concrete subprocess/Python entry used by Atlas profile
instructions. It constructs the lifecycle-owning ProductionSafeTFERunner, injects
it into ConversationRouter, and calls dispatch_atlas_trading_question().
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import argparse, json

from atlas_conversation_router import ConversationRouter, dispatch_atlas_trading_question, RouteResult
from atlas_single_ticker_tfe_runner import ProductionSafeTFERunner

REQUIRED_PROFILE_PHRASES = [
    "DETERMINISTIC CONVERSATION DISPATCHER — PRODUCTION",
    "dispatch_atlas_trading_question",
    "No legacy direct-engine prose path",
]
FORBIDDEN_PROFILE_PHRASES = [
    "staging-only",
    "not production",
    "Package B not production",
    "run `python3 /Users/yasser/scripts/atlas_engine.py TICKER` for EVERY ticker analysis",
]


def build_production_router(*, scripts_dir: str | Path = "/Users/yasser/scripts", source_db: str | Path = "/Users/yasser/scripts/atlas.db", runtime_root: str | Path = "/Users/yasser/Library/Application Support/Atlas/conversation_determinism/run", timeout_seconds: float = 45.0, total_timeout_seconds: float = 60.0, allow_test_override: bool = False) -> ConversationRouter:
    runner = ProductionSafeTFERunner(
        scripts_dir=scripts_dir,
        source_db=source_db,
        runtime_root=runtime_root,
        timeout_seconds=timeout_seconds,
        total_timeout_seconds=total_timeout_seconds,
        allow_test_override=allow_test_override,
    )
    return ConversationRouter(db_path=None, tfe_runner=runner, timeout_seconds=total_timeout_seconds)


class AtlasProfileConversationSimulator:
    def __init__(self, *, soul_path: str | Path, skill_path: str | Path, router: ConversationRouter):
        self.soul_path=Path(soul_path); self.skill_path=Path(skill_path); self.router=router
        self.soul_text=self.soul_path.read_text()
        self.skill_text=self.skill_path.read_text()

    def verify_profile_dispatch_contract(self) -> dict[str, Any]:
        combined=self.soul_text+"\n"+self.skill_text
        required={p: (p in combined) for p in REQUIRED_PROFILE_PHRASES}
        forbidden={p: (p in combined) for p in FORBIDDEN_PROFILE_PHRASES}
        return {
            "required_present": required,
            "forbidden_absent": {k: not v for k,v in forbidden.items()},
            "pass": all(required.values()) and not any(forbidden.values()),
        }

    def ask(self, question: str, ticker: str, **kwargs: Any) -> RouteResult:
        contract=self.verify_profile_dispatch_contract()
        if not contract["pass"]:
            raise RuntimeError("PROFILE_DISPATCH_CONTRACT_INVALID:" + str(contract))
        return dispatch_atlas_trading_question(question, ticker, router=self.router, **kwargs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Atlas deterministic conversation entrypoint")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--scripts-dir", default="/Users/yasser/scripts")
    parser.add_argument("--source-db", default="/Users/yasser/scripts/atlas.db")
    parser.add_argument("--runtime-root", default="/Users/yasser/Library/Application Support/Atlas/conversation_determinism/run")
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--total-timeout-seconds", type=float, default=60.0)
    parser.add_argument("--allow-test-override", action="store_true", help="test-only: allow non-canonical source DB")
    args = parser.parse_args(argv)
    router = build_production_router(
        scripts_dir=args.scripts_dir,
        source_db=args.source_db,
        runtime_root=args.runtime_root,
        timeout_seconds=args.timeout_seconds,
        total_timeout_seconds=args.total_timeout_seconds,
        allow_test_override=args.allow_test_override,
    )
    result = dispatch_atlas_trading_question(args.question, args.ticker, router=router)
    print(json.dumps({
        "route_selected": result.route,
        "authoritative_source": result.source,
        "packet_freshness": result.freshness,
        "fresh_run_occurred": result.fresh_run_occurred,
        "rendered_answer": result.rendered_answer,
        "packet": dict(result.packet),
        "structured": dict(result.structured),
    }, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
