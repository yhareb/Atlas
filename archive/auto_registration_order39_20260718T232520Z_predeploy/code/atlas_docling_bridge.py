#!/usr/bin/env python3
"""Atlas Docling-first ingress bridge (staging).

Single entry point for ALL Atlas-related screenshots/documents. Enforces:
  - No vision_analyze / ad-hoc OCR — Docling is the only image/document parser.
  - extract-only never writes DB.
  - broker-parse-dry-run never writes DB.
  - broker-register-approved requires an explicit --approved flag AND a confident parse.

Modes:
  --extract-only            Convert + export full artifact bundle. No DB write ever.
  --broker-parse-dry-run    Extract, then run broker parser in dry-run (no DB write).
  --broker-register-approved  Extract, dry-run parse, and (only if --approved and parse
                              is confident) call the real broker registration path.

Artifact bundle written to:
  /Users/yasser/atlas_inbox/docling_artifacts/<sha256>/
    original.<ext>
    document.md
    document.json
    tables/table_<n>.csv, table_<n>.html   (if any tables detected)
    figures/figure_<n>.png                 (if page/figure images available)
    metadata.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_DIR = os.environ.get("ATLAS_SCRIPTS_DIR") or os.path.dirname(os.path.abspath(__file__))
for _path in (SCRIPTS_DIR, "/Users/yasser/scripts"):
    if _path not in sys.path:
        sys.path.insert(0, _path)

DEFAULT_ARTIFACT_ROOT = Path(os.environ.get("ATLAS_DOCLING_ARTIFACTS", "/Users/yasser/atlas_inbox/docling_artifacts"))
DEFAULT_INCOMING_CHAT = Path(os.environ.get("ATLAS_INCOMING_CHAT", "/Users/yasser/atlas_inbox/incoming_chat"))
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tiff", ".bmp", ".webp"}
SUPPORTED_EXTS = IMAGE_EXTS | {".pdf", ".docx", ".html", ".htm", ".txt", ".md"}


def _log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] docling_bridge: {msg}"
    print(line, file=sys.stderr, flush=True)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save_chat_attachment(src_path: Path, filename: str | None = None) -> Path:
    """Copy a chat-originated attachment into the incoming_chat staging area.

    This is the ONLY sanctioned entry point for Telegram/chat screenshots destined for
    Atlas analysis. No OCR/vision happens here — it is a pure file copy.
    """
    DEFAULT_INCOMING_CHAT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = filename or src_path.name
    dest = DEFAULT_INCOMING_CHAT / f"{stamp}_{name}"
    if dest.exists():
        dest = DEFAULT_INCOMING_CHAT / f"{stamp}_{os.getpid()}_{name}"
    import shutil as _shutil
    _shutil.copy2(src_path, dest)
    _log(f"saved chat attachment -> {dest}")
    return dest


def _docling_version() -> str:
    try:
        import docling
        return getattr(docling, "__version__", "unknown")
    except Exception:
        return "unavailable"


def _convert(path: Path):
    from docling.document_converter import DocumentConverter
    converter = DocumentConverter()
    result = converter.convert(str(path))
    return result.document


def _export_tables(doc, out_dir: Path) -> list[dict]:
    tables_meta = []
    tables_dir = out_dir / "tables"
    try:
        tables = getattr(doc, "tables", None) or []
    except Exception:
        tables = []
    for idx, table in enumerate(tables):
        try:
            tables_dir.mkdir(parents=True, exist_ok=True)
            df = None
            if hasattr(table, "export_to_dataframe"):
                df = table.export_to_dataframe(doc=doc)
            if df is not None:
                csv_path = tables_dir / f"table_{idx}.csv"
                html_path = tables_dir / f"table_{idx}.html"
                df.to_csv(csv_path, index=False)
                html_path.write_text(df.to_html(index=False))
                tables_meta.append({"index": idx, "csv": str(csv_path), "html": str(html_path), "rows": len(df)})
        except Exception as exc:
            tables_meta.append({"index": idx, "error": f"{type(exc).__name__}: {exc}"})
    return tables_meta


def _export_figures(doc, out_dir: Path) -> list[dict]:
    figures_meta = []
    figures_dir = out_dir / "figures"
    try:
        pictures = getattr(doc, "pictures", None) or []
    except Exception:
        pictures = []
    for idx, pic in enumerate(pictures):
        try:
            img = None
            get_image = getattr(pic, "get_image", None)
            if callable(get_image):
                img = get_image(doc)
            if img is not None:
                figures_dir.mkdir(parents=True, exist_ok=True)
                fig_path = figures_dir / f"figure_{idx}.png"
                img.save(fig_path)
                figures_meta.append({"index": idx, "path": str(fig_path)})
        except Exception as exc:
            figures_meta.append({"index": idx, "error": f"{type(exc).__name__}: {exc}"})
    return figures_meta


def _export_markdown(doc) -> str:
    try:
        return doc.export_to_markdown()
    except Exception as exc:
        return f"<export_to_markdown failed: {type(exc).__name__}: {exc}>"


def _export_json(doc) -> dict:
    for method in ("export_to_dict", "model_dump"):
        fn = getattr(doc, method, None)
        if callable(fn):
            try:
                return fn()
            except Exception:
                continue
    try:
        return json.loads(doc.model_dump_json())
    except Exception:
        return {"error": "docling_document_json_export_unavailable"}


def extract_only(input_path: str, artifact_root: Path | None = None) -> dict:
    """Docling-only extraction. Never writes DB. Never calls broker registration."""
    path = Path(input_path).expanduser()
    if not path.exists():
        return {"status": "error", "reason": "file_not_found", "path": str(path)}
    if path.suffix.lower() not in SUPPORTED_EXTS:
        return {"status": "error", "reason": "unsupported_extension", "suffix": path.suffix.lower()}

    digest = sha256_of(path)
    root = artifact_root or DEFAULT_ARTIFACT_ROOT
    out_dir = root / digest
    out_dir.mkdir(parents=True, exist_ok=True)

    original_copy = out_dir / f"original{path.suffix.lower()}"
    if not original_copy.exists():
        import shutil as _shutil
        _shutil.copy2(path, original_copy)

    doc = _convert(path)
    markdown_text = _export_markdown(doc)
    (out_dir / "document.md").write_text(markdown_text)

    doc_json = _export_json(doc)
    (out_dir / "document.json").write_text(json.dumps(doc_json, indent=2, default=str))

    tables_meta = _export_tables(doc, out_dir)
    figures_meta = _export_figures(doc, out_dir)

    metadata = {
        "source_filename": path.name,
        "sha256": digest,
        "docling_version": _docling_version(),
        "parser_mode": "extract-only",
        "ocr_backend": "docling_default",
        "confidence": None,
        "broker_detection_result": None,
        "db_write_mode": "DRY_RUN",
        "tables": tables_meta,
        "figures": figures_meta,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "artifact_dir": str(out_dir),
    }
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, default=str))
    _log(f"extract-only complete sha={digest} artifacts={out_dir}")
    return {
        "status": "ok",
        "sha256": digest,
        "artifact_dir": str(out_dir),
        "markdown_path": str(out_dir / "document.md"),
        "json_path": str(out_dir / "document.json"),
        "metadata_path": str(out_dir / "metadata.json"),
        "markdown_len": len(markdown_text),
        "tables_count": len(tables_meta),
        "figures_count": len(figures_meta),
    }


def broker_parse_dry_run(input_path: str, artifact_root: Path | None = None) -> dict:
    """Extract via Docling, then classify with the broker parser. Never writes DB."""
    extraction = extract_only(input_path, artifact_root=artifact_root)
    if extraction.get("status") != "ok":
        return extraction
    markdown_text = Path(extraction["markdown_path"]).read_text(errors="replace")

    old_suppress = os.environ.get("ATLAS_BROKER_INGEST_SUPPRESS_TELEGRAM")
    os.environ["ATLAS_BROKER_INGEST_SUPPRESS_TELEGRAM"] = "1"
    try:
        import atlas_broker_ingest
        classification = atlas_broker_ingest._classify(atlas_broker_ingest._clean_text(markdown_text))
        parsed = None
        if classification == atlas_broker_ingest._EVENT_BUY:
            parsed = atlas_broker_ingest._parse_buy(markdown_text)
        elif classification == atlas_broker_ingest._EVENT_SELL:
            parsed = atlas_broker_ingest._parse_sell(markdown_text)
        result = {
            "status": "ok",
            "mode": "broker-parse-dry-run",
            "classification": classification,
            "parsed_fields": parsed,
            "db_write_mode": "DRY_RUN",
            "would_register": bool(parsed) and classification != "UNKNOWN",
        }
    finally:
        if old_suppress is None:
            os.environ.pop("ATLAS_BROKER_INGEST_SUPPRESS_TELEGRAM", None)
        else:
            os.environ["ATLAS_BROKER_INGEST_SUPPRESS_TELEGRAM"] = old_suppress

    meta_path = Path(extraction["metadata_path"])
    try:
        meta = json.loads(meta_path.read_text())
        meta["broker_detection_result"] = result
        meta_path.write_text(json.dumps(meta, indent=2, default=str))
    except Exception:
        pass

    extraction["broker_dry_run"] = result
    return extraction


def broker_register_approved(input_path: str, approved: bool, artifact_root: Path | None = None) -> dict:
    """Only path that may write DB. Requires explicit --approved AND a confident parse."""
    dry = broker_parse_dry_run(input_path, artifact_root=artifact_root)
    if dry.get("status") != "ok":
        return dry
    result = dry.get("broker_dry_run", {})
    if not approved:
        dry["db_write_mode"] = "BLOCKED_NOT_APPROVED"
        dry["registered"] = False
        _log("registration blocked: --approved flag not set")
        return dry
    if not result.get("would_register"):
        dry["db_write_mode"] = "BLOCKED_NOT_CONFIDENT"
        dry["registered"] = False
        _log("registration blocked: parse not confident (UNKNOWN or missing fields)")
        return dry

    markdown_text = Path(dry["markdown_path"]).read_text(errors="replace")
    import atlas_broker_ingest
    registration = atlas_broker_ingest.detect_and_register(markdown_text, Path(input_path).name)
    dry["db_write_mode"] = "APPROVED_WRITE"
    dry["registered"] = registration
    meta_path = Path(dry["metadata_path"])
    try:
        meta = json.loads(meta_path.read_text())
        meta["db_write_mode"] = "APPROVED_WRITE"
        meta["registration_result"] = registration
        meta_path.write_text(json.dumps(meta, indent=2, default=str))
    except Exception:
        pass
    _log(f"registration approved and executed: {registration}")
    return dry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Atlas Docling-first ingress bridge")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--extract-only", metavar="PATH")
    group.add_argument("--broker-parse-dry-run", metavar="PATH")
    group.add_argument("--broker-register-approved", metavar="PATH")
    parser.add_argument("--approved", action="store_true", help="Required to allow DB write in --broker-register-approved mode")
    parser.add_argument("--artifact-root", default=None)
    args = parser.parse_args(argv)
    root = Path(args.artifact_root).expanduser() if args.artifact_root else None

    if args.extract_only:
        out = extract_only(args.extract_only, artifact_root=root)
    elif args.broker_parse_dry_run:
        out = broker_parse_dry_run(args.broker_parse_dry_run, artifact_root=root)
    else:
        out = broker_register_approved(args.broker_register_approved, approved=args.approved, artifact_root=root)

    print("DOCLING_BRIDGE_RESULT_JSON=" + json.dumps(out, indent=2, default=str))
    return 0 if out.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
