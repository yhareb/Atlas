#!/usr/bin/env python3
from __future__ import annotations
import copy
import datetime as dt
import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROD = Path("/Users/yasser/scripts")
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(PROD))

validation = importlib.import_module(
    "perme_context_v1_2.perme_v1.perme_context_v1.validation"
)
BASE = json.loads((ROOT / "tests/fixtures/order52/base_valid_canonical.json").read_text())


def validate(packet: dict) -> None:
    now = dt.datetime.fromisoformat(packet["generated_at"])
    validation.validate_context(packet, now=now)


def with_news_title(title: str) -> dict:
    packet = copy.deepcopy(BASE)
    for item in packet["evidence"]:
        if item["source_record_type"] == "BENZINGA_NEWS":
            item["raw_record"]["title"] = title
            for event in packet["events"]:
                if item["evidence_id"] in event["evidence_ids"]:
                    event["headline"] = title
            return packet
    raise AssertionError("fixture has no BENZINGA_NEWS evidence")


def expect_fail(packet: dict) -> None:
    try:
        validate(packet)
    except validation.ValidationError as exc:
        assert str(exc) == "trading instructions"
    else:
        raise AssertionError("expected ValidationError")


def main() -> int:
    validate(with_news_title("Stifel Maintains Buy on IBM"))
    print("FIXTURE_A_MAINTAINS_BUY=PASS")
    validate(with_news_title("‘Big Short’ Investor Discusses Banks"))
    print("FIXTURE_B_BIG_SHORT=PASS")
    validate(with_news_title("Semiconductor short-term volatility rises"))
    print("FIXTURE_C_SHORT_TERM=PASS")

    packet = copy.deepcopy(BASE)
    packet["trading_instructions"] = ["BUY NOW"]
    expect_fail(packet)
    print("FIXTURE_D_NONEMPTY_TRADING_INSTRUCTIONS_FAILS=PASS")

    packet = copy.deepcopy(BASE)
    packet["instruction_prose"] = "Buy NVDA now"
    old_top = validation.TOP
    old_fields = validation._INSTRUCTION_SCAN_FIELDS
    try:
        validation.TOP = set(old_top) | {"instruction_prose"}
        validation._INSTRUCTION_SCAN_FIELDS = ("instruction_prose",)
        expect_fail(packet)
    finally:
        validation.TOP = old_top
        validation._INSTRUCTION_SCAN_FIELDS = old_fields
    print("FIXTURE_E_ALLOWLISTED_IMPERATIVE_FAILS=PASS")
    print("FIXTURES=5/5 PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
