#!/usr/bin/env python3
"""Production-safe single-ticker TFE runner contract for closure v1.

The runner owns the secure copied-atlas.db lifecycle. Ordinary production
construction does not accept a DB path from the router, LLM, profile, or user;
it creates a private SQLite-consistent snapshot internally for every fresh TFE
request, invokes TFE against that private copy, and cleans it in finally.
"""
from __future__ import annotations

import json, os, subprocess, sys, time
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Mapping

from atlas_conversation_schemas import Authority, RouterError, attach_digest, field
from atlas_conversation_db_snapshot import RuntimeDBSnapshotManager, SnapshotError, CANONICAL_SOURCE_DB, DEFAULT_RUNTIME_ROOT

SCHEMA_VERSION = "atlas_single_ticker_tfe_packet_v1"
PROD_SCRIPTS = Path("/Users/yasser/scripts")

class ProductionSafeTFERunner:
    def __init__(
        self,
        *,
        scripts_dir: str | Path = PROD_SCRIPTS,
        snapshot_manager: RuntimeDBSnapshotManager | None = None,
        source_db: str | Path = CANONICAL_SOURCE_DB,
        runtime_root: str | Path = DEFAULT_RUNTIME_ROOT,
        timeout_seconds: float = 45.0,
        total_timeout_seconds: float = 60.0,
        allow_test_override: bool = False,
    ):
        self.scripts_dir = Path(scripts_dir)
        self.timeout_seconds = float(timeout_seconds)
        self.total_timeout_seconds = float(total_timeout_seconds)
        self.snapshot_manager = snapshot_manager or RuntimeDBSnapshotManager(source_db=source_db, runtime_root=runtime_root, allow_test_override=allow_test_override)
        if not (self.scripts_dir / "atlas_engine.py").exists():
            raise RouterError("TFE_RUNNER_ENGINE_MISSING")

    def __call__(self, ticker: str) -> Mapping[str, Any]:
        return self.run(ticker=ticker)

    def run(self, *, ticker: str, request_id: str | None = None) -> Mapping[str, Any]:
        started_wall = time.time()
        runner_started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        ticker = str(ticker or "").strip().upper()
        if not ticker:
            raise RouterError("TFE_RUNNER_TICKER_MISSING")
        db_path = None
        manifest = None
        packet: dict[str, Any] | None = None
        cleanup_status = {"cleanup_status": "NOT_STARTED"}
        try:
            db_path, manifest = self.snapshot_manager.create_snapshot(request_id=request_id, acquisition_timeout=min(20.0, self.total_timeout_seconds))
            if time.time() - started_wall > self.total_timeout_seconds:
                raise RouterError("FRESH_TFE_RESULT_UNAVAILABLE:TOTAL_TIMEOUT_BEFORE_TFE")
            raw = self._invoke_tfe(ticker=ticker, db_path=db_path, remaining_timeout=max(0.001, min(self.timeout_seconds, self.total_timeout_seconds - (time.time() - started_wall))))
            packet = normalize_tfe_output(ticker, raw, source="production atlas_engine.py via secure runtime SQLite snapshot")
            runner_completed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            provenance = dict(packet.get("source_provenance") or {})
            provenance.update(manifest.public())
            provenance.update({
                "runner_started_at": runner_started_at,
                "runner_completed_at": runner_completed_at,
                "production_db_path_exposed_to_child": False,
                "telegram": "DISABLED",
                "broker": "NO_AUTHORITY",
            })
            packet["source_provenance"] = provenance
            packet["runtime_request_id"] = manifest.runtime_request_id
            packet["snapshot_table_count_digest"] = manifest.table_count_digest
            packet = attach_digest(packet)
            cleanup_status = self.snapshot_manager.cleanup_snapshot(db_path, success=True, manifest=manifest)
            packet["source_provenance"]["cleanup_status"] = cleanup_status.get("cleanup_status")
            packet["cleanup_status"] = cleanup_status.get("cleanup_status")
            packet = attach_digest(packet)
            return packet
        except Exception as exc:
            if db_path is not None:
                try:
                    cleanup_status = self.snapshot_manager.cleanup_snapshot(db_path, success=False, error=str(exc), manifest=manifest)
                except Exception as cleanup_exc:
                    raise RouterError("TFE_RUNNER_CLEANUP_FAILED:" + str(cleanup_exc)) from exc
            if isinstance(exc, RouterError):
                raise
            if isinstance(exc, SnapshotError):
                raise RouterError("FRESH_TFE_RESULT_UNAVAILABLE:SNAPSHOT:" + str(exc)) from exc
            raise RouterError("FRESH_TFE_RESULT_UNAVAILABLE:" + type(exc).__name__ + ":" + str(exc)) from exc

    def _invoke_tfe(self, *, ticker: str, db_path: Path, remaining_timeout: float) -> Mapping[str, Any]:
        if Path(db_path).resolve() == CANONICAL_SOURCE_DB.resolve():
            raise RouterError("TFE_RUNNER_REFUSES_PRODUCTION_DB_CHILD")
        env = dict(os.environ)
        env.update({
            "ATLAS_DB": str(db_path),
            "ATLAS_DISABLE_TELEGRAM": "1",
            "ATLAS_MOCK_TELEGRAM": "1",
            "ATLAS_CONVERSATION_RUNNER": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        # Ensure no inherited production DB path survives under common aliases.
        for key in ("ATLAS_PROD_DB", "ATLAS_DB_PATH_PROD"):
            env.pop(key, None)
        cmd = [sys.executable, str(self.scripts_dir / "atlas_engine.py"), ticker]
        try:
            proc = subprocess.run(cmd, cwd=str(self.scripts_dir), env=env, text=True, capture_output=True, timeout=remaining_timeout)
        except subprocess.TimeoutExpired as exc:
            raise RouterError("FRESH_TFE_RESULT_UNAVAILABLE:PROVIDER_TIMEOUT") from exc
        if proc.returncode != 0:
            raise RouterError("FRESH_TFE_RESULT_UNAVAILABLE:TFE_EXIT_" + str(proc.returncode))
        return self._parse_stdout(proc.stdout)

    @staticmethod
    def _parse_stdout(stdout: str) -> Mapping[str, Any]:
        text = (stdout or "").strip()
        if not text:
            raise RouterError("FRESH_TFE_RESULT_UNAVAILABLE:EMPTY_OUTPUT")
        candidates = []
        for start in [i for i, ch in enumerate(text) if ch in "[{"]:
            try:
                candidates.append(json.loads(text[start:]))
            except Exception:
                pass
        if not candidates:
            raise RouterError("FRESH_TFE_RESULT_UNAVAILABLE:JSON_PARSE")
        obj = candidates[-1]
        if isinstance(obj, list):
            if not obj:
                raise RouterError("FRESH_TFE_RESULT_UNAVAILABLE:EMPTY_JSON_LIST")
            obj = obj[0]
        if not isinstance(obj, Mapping):
            raise RouterError("FRESH_TFE_RESULT_UNAVAILABLE:NON_OBJECT")
        return obj


def _first(data: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data.get(key) is not None:
            return data.get(key)
    return None


def normalize_tfe_output(ticker: str, data: Mapping[str, Any], *, source: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    risk_card = data.get("risk_card") if isinstance(data.get("risk_card"), Mapping) else {}
    indicators = data.get("indicators") if isinstance(data.get("indicators"), Mapping) else {}
    moving = data.get("moving_averages") if isinstance(data.get("moving_averages"), Mapping) else {}
    pillars = data.get("pillars") if isinstance(data.get("pillars"), Mapping) else {
        "trend": data.get("trend_stack"),
        "relative_strength": data.get("relative_strength"),
        "volume": data.get("volume"),
        "catalyst": data.get("catalyst"),
    }
    pkt = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now,
        "ticker": ticker.upper(),
        "raw_tfe_classification": field(_first(data, "raw_tfe_classification", "signal", "classification", "action"), Authority.TFE_PACKET.value, source, now, "FRESH"),
        "score": field(_first(data, "score", "raw_tfe_score"), Authority.TFE_PACKET.value, source, now, "FRESH"),
        "pillars": field(pillars, Authority.TFE_PACKET.value, source, now, "FRESH"),
        "current_price": field(_first(data, "current_price", "price", "last_price", "entry_price"), Authority.APPROVED_PROVIDER_VIA_TFE.value, source, now, "FRESH"),
        "entry": field(_first(data, "entry", "entry_price", "trigger_price"), Authority.TFE_PACKET.value, source, now, "FRESH"),
        "stop": field(_first(data, "stop", "stop_loss", "stop_price", "risk_stop"), Authority.TFE_PACKET.value, source, now, "FRESH"),
        "target": field(_first(data, "target", "target_price", "analyst_target", "price_target") or risk_card.get("target_price"), Authority.TFE_PACKET.value, source, now, "FRESH"),
        "rsi": field(_first(data, "rsi") or indicators.get("rsi"), Authority.APPROVED_PROVIDER_VIA_TFE.value, source, now, "FRESH"),
        "macd": field(_first(data, "macd") or indicators.get("macd"), Authority.APPROVED_PROVIDER_VIA_TFE.value, source, now, "FRESH"),
        "rvol": field(_first(data, "rvol", "relative_volume") or indicators.get("rvol"), Authority.APPROVED_PROVIDER_VIA_TFE.value, source, now, "FRESH"),
        "atr": field(_first(data, "atr", "atr14") or indicators.get("atr14"), Authority.APPROVED_PROVIDER_VIA_TFE.value, source, now, "FRESH"),
        "ema10": field(_first(data, "ema10") or moving.get("ema10"), Authority.APPROVED_PROVIDER_VIA_TFE.value, source, now, "FRESH"),
        "ema21": field(_first(data, "ema21") or moving.get("ema21"), Authority.APPROVED_PROVIDER_VIA_TFE.value, source, now, "FRESH"),
        "ema50": field(_first(data, "ema50") or moving.get("ema50"), Authority.APPROVED_PROVIDER_VIA_TFE.value, source, now, "FRESH"),
        "sma50": field(_first(data, "sma50") or moving.get("sma50"), Authority.APPROVED_PROVIDER_VIA_TFE.value, source, now, "FRESH"),
        "sma200": field(_first(data, "sma200") or moving.get("sma200"), Authority.APPROVED_PROVIDER_VIA_TFE.value, source, now, "FRESH"),
        "catalyst_state": field(_first(data, "catalyst_state", "catalyst"), Authority.TFE_PACKET.value, source, now, "FRESH"),
        "fda_context": data.get("fda_context") or data.get("fda") or None,
        "source_provenance": {"runner": "ProductionSafeTFERunner", "source": source, "db_mode": "secure runtime SQLite snapshot", "telegram": "DISABLED", "broker": "NO_AUTHORITY"},
    }
    return attach_digest(pkt)

__all__ = ["ProductionSafeTFERunner", "normalize_tfe_output", "SCHEMA_VERSION"]
