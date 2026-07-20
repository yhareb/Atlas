#!/usr/bin/env python3
from __future__ import annotations
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROD = Path("/Users/yasser/scripts")
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(PROD))

spec = importlib.util.spec_from_file_location("order52_atlas_perme", ROOT / "atlas_perme.py")
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)
from perme_context_v1_2.perme_v1.perme_context_v1.validation import ValidationError


def main() -> int:
    sends = []
    with tempfile.TemporaryDirectory(prefix="order52_graceful_") as td:
        root = Path(td)
        strict = root / "strict"
        os.environ["PERME_STRICT_OUTBOX"] = str(strict)
        os.environ["ATLAS_DB"] = "/Users/yasser/scripts/atlas.db"

        mod._non_trading_day_reason = lambda now: None
        mod._load_env_file = lambda path: None
        mod.collect_context = lambda routine, mock=False: {
            "routine": "intraday", "source_mode": "live",
            "benzinga_news": [], "benzinga_earnings": [],
            "eodhd_economic_calendar": [], "massive_sector_etfs": [],
        }
        mod.build_prompt = lambda context: "prompt"
        mod.run_perme = lambda prompt: "# PERME BRIEFING — TEST\n\n## FLAGS\nNone.\n"
        mod.write_latest_context = lambda *args, **kwargs: root / "latest_context.json"
        mod.write_engine_packet = lambda *args, **kwargs: root / "packet.jsonl"
        mod.format_telegram_brief = lambda *args, **kwargs: "HUMAN BRIEF"
        mod.deliver_telegram_brief = lambda message, dry_run=False: sends.append((message, dry_run))

        fake = types.ModuleType("atlas_perme_strict")
        def reject(*args, **kwargs):
            raise ValidationError("fixture rejection")
        fake.publish = reject
        sys.modules["atlas_perme_strict"] = fake

        out = io.StringIO(); err = io.StringIO()
        output_path = root / "brief.md"
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = mod.main(["--routine", "intraday", "--output", str(output_path)])
        text = out.getvalue(); errors = err.getvalue()
        assert rc == 0
        assert "PERME STRICT REJECTED — DATA INCOMPLETE: fixture rejection" in text
        result_line = next(x for x in text.splitlines() if x.startswith("PERME_RESULT_JSON="))
        result = json.loads(result_line.split("=", 1)[1])
        assert result["strict"] == "REJECTED"
        assert sends == [
            ("PERME STRICT REJECTED — DATA INCOMPLETE: fixture rejection", False),
            ("HUMAN BRIEF", False),
        ]
        assert "Traceback" not in text + errors
        assert not strict.exists()
        print("GRACEFUL_REJECT_LINE=PASS")
        print("DM_NOTICE_CAPTURED=PASS")
        print("HUMAN_BRIEF_CAPTURED=PASS")
        print("RESULT_STRICT_REJECTED=PASS")
        print("EXIT_ZERO=PASS")
        print("TRACEBACK_ZERO=PASS")
        print("STRICT_OUTBOX_UNPUBLISHED=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
