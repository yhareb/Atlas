#!/usr/bin/env python3
"""Atlas Docling RAG ingestion daemon.

Polls an inbox for PDF/DOCX/HTML/TXT files, converts with IBM Docling,
chunks with HybridChunker, embeds locally with all-MiniLM-L6-v2, and stores in
ChromaDB. Dry-run mode suppresses Telegram but still processes the configured
staging inbox/vector DB for gate verification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable

SCRIPTS_DIR = os.environ.get("ATLAS_SCRIPTS_DIR") or os.path.dirname(os.path.abspath(__file__))
for _path in (SCRIPTS_DIR, "/Users/yasser/scripts"):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from atlas_notify import send_telegram  # noqa: E402
from atlas_rag_flags import parse_flags  # noqa: E402

SUPPORTED_EXTS = {".pdf", ".docx", ".html", ".htm", ".txt", ".md", ".jpg", ".jpeg", ".png"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
BROKER_INGEST_EXTS = IMAGE_EXTS | {".pdf"}
DEFAULT_INBOX = Path(os.environ.get("ATLAS_INGEST_INBOX", "/Users/yasser/atlas_inbox"))
DEFAULT_VECTORDB = Path(os.environ.get("ATLAS_VECTORDB", "/Users/yasser/atlas_vectordb"))
COLLECTION_NAME = os.environ.get("ATLAS_VECTOR_COLLECTION", "atlas_knowledge")
POLL_SECONDS = int(os.environ.get("ATLAS_INGEST_POLL_SECONDS", "60"))
LOG_PATH = Path(os.environ.get("ATLAS_INGEST_LOG", "/Users/yasser/scripts/atlas_ingest.log"))
EMBED_MODEL = os.environ.get("ATLAS_INGEST_EMBED_MODEL", "all-MiniLM-L6-v2")


def _log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _ensure_dirs(inbox: Path) -> tuple[Path, Path]:
    processed = inbox / "processed"
    failed = inbox / "failed"
    inbox.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    failed.mkdir(parents=True, exist_ok=True)
    return processed, failed


def _fingerprint(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _iter_new_files(inbox: Path, processed: Path) -> Iterable[Path]:
    processed_names = {p.name for p in processed.iterdir() if p.is_file()} if processed.exists() else set()
    for path in sorted(inbox.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_EXTS:
            continue
        if path.name in processed_names:
            _log(f"skip already processed name={path.name}")
            continue
        yield path


def _chunk_text(text: str, size: int = 1200) -> list[str]:
    text = str(text or "").strip()
    return [text[i:i+size] for i in range(0, len(text), size) if text[i:i+size].strip()]


def _brief_timestamp_from_name(name: str) -> str:
    stem = Path(name).stem
    prefix = "perme_brief_"
    if not stem.startswith(prefix):
        return stem
    raw = stem[len(prefix):]
    try:
        dt = datetime.strptime(raw, "%Y%m%d_%H%M")
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return raw


def _markdown_section(text: str, heading: str) -> list[str]:
    lines = str(text or "").splitlines()
    target = heading.strip().lower()
    in_section = False
    found: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            if in_section:
                break
            in_section = stripped[3:].strip().lower() == target
            continue
        if in_section:
            found.append(line.rstrip())
    return found


def _clean_section_line(line: str) -> str:
    cleaned = line.strip()
    while cleaned.startswith(("-", "*", "•")):
        cleaned = cleaned[1:].strip()
    return cleaned


def _perme_brief_ingest_message(path: Path) -> str | None:
    name = path.name
    if not name.startswith("perme_brief_"):
        return None
    try:
        text = path.read_text(errors="replace")
    except Exception as exc:
        _log(f"perme brief summary warning for {name}: {type(exc).__name__}: {exc}")
        text = ""
    flags_text = "\n".join(_clean_section_line(line) for line in _markdown_section(text, "FLAGS"))
    flags = parse_flags(flags_text)
    flags_summary = ", ".join(flags) if flags else "None · Clean bill"
    regime_lines = [_clean_section_line(line) for line in _markdown_section(text, "REGIME")]
    regime = next((line for line in regime_lines if line), "Unknown")
    return f"📡 Perme brief ingested — {_brief_timestamp_from_name(name)}\nFlags: {flags_summary}\nRegime: {regime}"


def _ocr_image(path: Path) -> str:
    """Extract text from broker screenshots using Docling's native image OCR."""
    try:
        from docling.document_converter import DocumentConverter
        result = DocumentConverter().convert(str(path))
        text = result.document.export_to_markdown().strip()
        if not text:
            _log(f"docling image OCR warning for {path.name}: no text extracted")
        return text
    except Exception as exc:
        _log(f"docling image OCR warning for {path.name}: {type(exc).__name__}: {exc}")
        return ""


def _convert_and_chunk(path: Path) -> list[str]:
    if path.suffix.lower() in IMAGE_EXTS:
        return _chunk_text(_ocr_image(path))

    from docling.document_converter import DocumentConverter
    from docling.chunking import HybridChunker

    converter = DocumentConverter()
    result = converter.convert(str(path))
    doc = result.document
    chunker = HybridChunker()
    chunks = []
    try:
        for chunk in chunker.chunk(doc):
            text = getattr(chunk, "text", None)
            if not text:
                try:
                    text = chunker.contextualize(chunk)
                except Exception:
                    text = str(chunk)
            text = str(text or "").strip()
            if text:
                chunks.append(text)
    except Exception as exc:
        _log(f"hybrid chunker warning for {path.name}: {type(exc).__name__}: {exc}")
    if not chunks:
        try:
            text = doc.export_to_markdown().strip()
        except Exception:
            text = path.read_text(errors="replace").strip() if path.suffix.lower() == ".txt" else ""
        chunks = _chunk_text(text)
    return chunks


def _embed_texts(texts: list[str]) -> list[list[float]]:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(EMBED_MODEL)
    vectors = model.encode(texts, normalize_embeddings=True)
    return [list(map(float, row)) for row in vectors]


def _collection(vector_db: Path):
    import chromadb

    vector_db.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(vector_db))
    return client.get_or_create_collection(name=COLLECTION_NAME)


def _move_unique(src: Path, dest_dir: Path) -> Path:
    dest = dest_dir / src.name
    if dest.exists():
        stem, suffix = src.stem, src.suffix
        dest = dest_dir / f"{stem}_{int(time.time())}{suffix}"
    shutil.move(str(src), str(dest))
    return dest


def _post_ingest_trade_hook(chunks: list[str], source_filename: str, dry_run: bool = False) -> dict:
    suffix = Path(str(source_filename or "")).suffix.lower()
    if suffix not in BROKER_INGEST_EXTS:
        return {"event": "SKIPPED", "status": "ignored", "reason": "non_broker_file_type", "suffix": suffix}
    extracted_text = "\n\n".join(str(chunk or "") for chunk in chunks if str(chunk or "").strip())
    if not extracted_text.strip():
        return {"event": "UNKNOWN", "status": "ignored", "reason": "empty_text"}
    old_suppress = os.environ.get("ATLAS_BROKER_INGEST_SUPPRESS_TELEGRAM")
    if dry_run:
        os.environ["ATLAS_BROKER_INGEST_SUPPRESS_TELEGRAM"] = "1"
    try:
        import atlas_broker_ingest
        return atlas_broker_ingest.detect_and_register(extracted_text, source_filename)
    except Exception as exc:
        _log(f"broker post-ingest hook failed for {source_filename}: {type(exc).__name__}: {exc}")
        return {"event": "ERROR", "status": "error", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        if dry_run:
            if old_suppress is None:
                os.environ.pop("ATLAS_BROKER_INGEST_SUPPRESS_TELEGRAM", None)
            else:
                os.environ["ATLAS_BROKER_INGEST_SUPPRESS_TELEGRAM"] = old_suppress


def ingest_file(path: Path, inbox: Path, vector_db: Path, dry_run: bool = False) -> dict:
    processed, failed = _ensure_dirs(inbox)
    name = path.name
    try:
        digest = _fingerprint(path)
        chunks = _convert_and_chunk(path)
        if not chunks:
            raise RuntimeError("0 chunks produced")
        embeddings = _embed_texts(chunks)
        collection = _collection(vector_db)
        ids = [f"{digest}:{i}" for i in range(len(chunks))]
        metas = [{"source": name, "sha256": digest, "chunk": i, "ingested_at": datetime.now().isoformat()} for i in range(len(chunks))]
        collection.add(ids=ids, documents=chunks, embeddings=embeddings, metadatas=metas)
        broker_result = _post_ingest_trade_hook(chunks, name, dry_run=dry_run)
        perme_msg = _perme_brief_ingest_message(path)
        moved = _move_unique(path, processed)
        msg = perme_msg or f"📚 Ingested: {name} → {len(chunks)} chunks added to Atlas knowledge base"
        _log(msg)
        _log("broker_hook_result=" + json.dumps(broker_result, sort_keys=True, default=str))
        if dry_run:
            _log("dry-run: telegram suppressed")
        elif perme_msg is None:
            send_telegram(msg, label="atlas", parse_mode="", print_fallback=True)
        return {"file": name, "status": "processed", "chunks": len(chunks), "moved_to": str(moved), "broker_ingest": broker_result}
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        try:
            moved = _move_unique(path, failed)
        except Exception:
            moved = path
        msg = f"⚠️ Ingest failed: {name} — {err}"
        _log(msg)
        if dry_run:
            _log("dry-run: telegram suppressed")
        elif not name.startswith("perme_brief_"):
            send_telegram(msg, label="atlas", parse_mode="", print_fallback=True)
        return {"file": name, "status": "failed", "error": err, "moved_to": str(moved)}


def run_once(inbox: Path, vector_db: Path, dry_run: bool = False) -> list[dict]:
    processed, _failed = _ensure_dirs(inbox)
    results = []
    for path in list(_iter_new_files(inbox, processed)):
        results.append(ingest_file(path, inbox, vector_db, dry_run=dry_run))
    if not results:
        _log("no new files")
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Atlas Docling RAG ingestion daemon")
    parser.add_argument("--once", action="store_true", help="Process inbox once and exit")
    parser.add_argument("--dry-run", action="store_true", help="Suppress Telegram notifications")
    parser.add_argument("--inbox", default=str(DEFAULT_INBOX))
    parser.add_argument("--vectordb", default=str(DEFAULT_VECTORDB))
    args = parser.parse_args(argv)
    inbox = Path(args.inbox).expanduser()
    vector_db = Path(args.vectordb).expanduser()
    _ensure_dirs(inbox)
    if args.once:
        results = run_once(inbox, vector_db, dry_run=args.dry_run)
        print("INGEST_RESULT_JSON=" + json.dumps(results, sort_keys=True))
        return 0 if all(r.get("status") == "processed" for r in results) or not results else 1
    _log(f"daemon start inbox={inbox} vectordb={vector_db} poll={POLL_SECONDS}s")
    while True:
        run_once(inbox, vector_db, dry_run=args.dry_run)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
