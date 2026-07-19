#!/usr/bin/env python3
"""Atlas RAG Phase 2 Perme brief Chroma indexer.

Standalone staging/prod-safe script:
- Indexes /Users/yasser/atlas_inbox/processed/*.md Perme briefs only.
- Persists Chroma collection "perme_briefs".
- Uses OpenAI text-embedding-3-small.
- Incremental by document ID == filename stem.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Iterable

DEFAULT_SOURCE_DIR = Path("/Users/yasser/atlas_inbox/processed")
DEFAULT_CHROMA_PATH = Path("/Users/yasser/atlas_rag/chroma_db")
COLLECTION_NAME = "perme_briefs"
EMBEDDING_MODEL = "text-embedding-3-small"

# Candidate Atlas profile env files. The loader below reads only OPENAI_API_KEY
# lines and never prints values. It intentionally ignores all other variables.
ENV_CANDIDATES = (
    Path("/Users/yasser/.hermes/profiles/atlas/.env"),
    Path("/Users/yasser/.hermes/profiles/atlasops/.env"),
    Path("/Users/yasser/.hermes/profiles/perme/.env"),
)


def _parse_env_assignment(line: str, key: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export "):].lstrip()
    prefix = key + "="
    if not stripped.startswith(prefix):
        return None
    value = stripped[len(prefix):].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return value or None


def load_openai_key() -> bool:
    """Ensure OPENAI_API_KEY is in os.environ without printing the value."""
    if os.environ.get("OPENAI_API_KEY"):
        return True
    for env_path in ENV_CANDIDATES:
        try:
            if not env_path.exists():
                continue
            with env_path.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    value = _parse_env_assignment(line, "OPENAI_API_KEY")
                    if value:
                        os.environ["OPENAI_API_KEY"] = value
                        return True
        except Exception:
            continue
    return False


def iter_brief_files(source_dir: Path = DEFAULT_SOURCE_DIR) -> list[Path]:
    return sorted(p for p in source_dir.glob("*.md") if p.is_file() and p.name.startswith("perme_brief_"))


def parse_generated_at(path: Path, text: str = "") -> str:
    match = re.search(r"perme_brief_(\d{8})_(\d{4})", path.stem)
    if match:
        date_raw, time_raw = match.groups()
        return f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]} {time_raw[:2]}:{time_raw[2:]} ET"
    heading = re.search(r"PERME BRIEFING\s*[—-]\s*(.+)", text, re.IGNORECASE)
    if heading:
        return heading.group(1).strip()
    return path.stem


def _section(text: str, name: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(name)}\s*$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return ""
    start = match.end()
    next_match = re.search(r"^##\s+", text[start:], re.MULTILINE)
    end = start + next_match.start() if next_match else len(text)
    return text[start:end].strip()


def parse_sentiment(text: str) -> str:
    regime = _section(text, "REGIME")
    flags = _section(text, "FLAGS")
    combined = f"{flags}\n{regime}".upper()
    if "RISK-OFF" in combined or "RISK_OFF" in combined:
        return "RISK_OFF"
    if "CAUTION" in combined or "FED_DAY" in combined or "FOMC_DAY" in combined or "CPI_DAY" in combined:
        return "CAUTION"
    if "NEUTRAL" in combined:
        return "NEUTRAL"
    return "UNKNOWN"


def get_openai_client():
    if not load_openai_key():
        raise RuntimeError("OPENAI_API_KEY not available from environment or Atlas profile env candidates")
    from openai import OpenAI
    return OpenAI()


def embed_texts(texts: list[str]) -> list[list[float]]:
    client = get_openai_client()
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]


def get_collection(db_path: Path = DEFAULT_CHROMA_PATH):
    import chromadb
    db_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(db_path))
    return client.get_or_create_collection(name=COLLECTION_NAME, metadata={"embedding_model": EMBEDDING_MODEL})


def existing_ids(collection) -> set[str]:
    try:
        data = collection.get(include=[])
        return set(data.get("ids") or [])
    except Exception:
        return set()


def index_perme_briefs(source_dir: Path = DEFAULT_SOURCE_DIR, db_path: Path = DEFAULT_CHROMA_PATH) -> dict:
    collection = get_collection(db_path)
    files = iter_brief_files(source_dir)
    indexed = existing_ids(collection)
    new_files = [p for p in files if p.stem not in indexed]
    if not new_files:
        return {"source_dir": str(source_dir), "db_path": str(db_path), "collection": COLLECTION_NAME, "available_briefs": len(files), "indexed_new": 0, "total_after": collection.count(), "new_ids": []}

    ids: list[str] = []
    docs: list[str] = []
    metadatas: list[dict] = []
    for path in new_files:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            continue
        ids.append(path.stem)
        docs.append(text)
        metadatas.append({
            "source": path.name,
            "generated_at": parse_generated_at(path, text),
            "sentiment": parse_sentiment(text),
        })

    if docs:
        embeddings = embed_texts(docs)
        collection.add(ids=ids, documents=docs, metadatas=metadatas, embeddings=embeddings)

    return {"source_dir": str(source_dir), "db_path": str(db_path), "collection": COLLECTION_NAME, "available_briefs": len(files), "indexed_new": len(ids), "total_after": collection.count(), "new_ids": ids}


def query_perme_context(query_text: str, n_results: int = 3, db_path: Path = DEFAULT_CHROMA_PATH) -> list[dict]:
    collection = get_collection(db_path)
    query_embedding = embed_texts([query_text])[0]
    result = collection.query(query_embeddings=[query_embedding], n_results=int(n_results), include=["documents", "metadatas", "distances"])
    docs = (result.get("documents") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]
    out: list[dict] = []
    for text, meta in zip(docs, metas):
        meta = meta or {}
        out.append({
            "text": text,
            "sentiment": meta.get("sentiment"),
            "generated_at": meta.get("generated_at"),
            "source": meta.get("source"),
        })
    return out


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Index Perme briefs into Chroma.")
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR))
    parser.add_argument("--db-path", default=str(DEFAULT_CHROMA_PATH))
    args = parser.parse_args(list(argv) if argv is not None else None)
    summary = index_perme_briefs(source_dir=Path(args.source_dir), db_path=Path(args.db_path))
    print(f"INDEXED_NEW={summary['indexed_new']}")
    print(f"TOTAL_AFTER={summary['total_after']}")
    print(f"COLLECTION={summary['collection']}")
    print(f"DB_PATH={summary['db_path']}")
    for doc_id in summary["new_ids"]:
        print(f"INDEXED_ID={doc_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
