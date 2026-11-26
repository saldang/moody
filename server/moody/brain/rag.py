"""Local knowledge base (RAG) - open-source replacement for a managed knowledge index.

Deliberately simple: Markdown files -> chunks -> embeddings (local Ollama model)
-> SQLite. Brute-force cosine search is fast enough for a few thousand chunks
(a care home's activity calendar, house rules, FAQ). For larger corpora swap in
Qdrant or pgvector behind the same interface.

Only non-personal, curated content belongs in the knowledge base.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx
import numpy as np


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OllamaEmbedder:
    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(trust_env=False, timeout=120) as client:
            resp = await client.post(f"{self.base_url}/api/embed", json={"model": self.model, "input": texts})
            resp.raise_for_status()
            return resp.json()["embeddings"]


class OpenAICompatEmbedder:
    """Embeddings from any OpenAI-compatible server (e.g. vLLM serving bge-m3)."""

    def __init__(self, base_url: str, model: str, api_key: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(trust_env=False, timeout=120, headers=self.headers) as client:
            resp = await client.post(f"{self.base_url}/embeddings", json={"model": self.model, "input": texts})
            resp.raise_for_status()
            return [row["embedding"] for row in sorted(resp.json()["data"], key=lambda r: r["index"])]


@dataclass(frozen=True)
class Passage:
    source: str
    text: str
    score: float


def chunk_markdown(text: str, max_chars: int = 900) -> list[str]:
    """Split on headings/blank lines, then pack paragraphs up to ``max_chars``."""
    blocks = [b.strip() for b in re.split(r"\n(?=#)|\n\s*\n", text) if b.strip()]
    chunks: list[str] = []
    current = ""
    for block in blocks:
        if len(current) + len(block) + 1 > max_chars and current:
            chunks.append(current)
            current = ""
        current = f"{current}\n{block}".strip()
        while len(current) > max_chars:
            chunks.append(current[:max_chars])
            current = current[max_chars:]
    if current:
        chunks.append(current)
    return chunks


class KnowledgeBase:
    def __init__(self, db_path: Path | str, embedder: Embedder, min_score: float = 0.55) -> None:
        self.embedder = embedder
        self.min_score = min_score
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS chunk (id INTEGER PRIMARY KEY, source TEXT, digest TEXT, "
            "text TEXT, vec BLOB)"
        )
        self._matrix: np.ndarray | None = None
        self._rows: list[tuple[str, str]] = []

    async def index_dir(self, folder: Path) -> int:
        """(Re)index Markdown files whose content changed. Returns number of new chunks."""
        added = 0
        seen: set[str] = set()
        for path in sorted(folder.glob("**/*.md")):
            if path.name.lower() == "readme.md":
                continue  # documentation about the folder, not knowledge
            source = str(path.relative_to(folder))
            seen.add(source)
            content = path.read_text(encoding="utf-8")
            # The embedding model is part of the digest: switching model forces a full re-index
            # (vectors from different models live in incompatible spaces, even with equal dims).
            model_id = getattr(self.embedder, "model", type(self.embedder).__name__)
            digest = hashlib.sha256(f"{model_id}\0{content}".encode()).hexdigest()
            row = self._db.execute("SELECT digest FROM chunk WHERE source=? LIMIT 1", (source,)).fetchone()
            if row and row[0] == digest:
                continue
            self._db.execute("DELETE FROM chunk WHERE source=?", (source,))
            chunks = chunk_markdown(content)
            if not chunks:
                continue
            vectors = await self.embedder.embed(chunks)
            for text, vec in zip(chunks, vectors, strict=True):
                arr = np.asarray(vec, dtype=np.float32)
                arr /= np.linalg.norm(arr) or 1.0
                self._db.execute(
                    "INSERT INTO chunk(source, digest, text, vec) VALUES (?,?,?,?)",
                    (source, digest, text, arr.tobytes()),
                )
                added += 1
        for (source,) in self._db.execute("SELECT DISTINCT source FROM chunk").fetchall():
            if source not in seen:
                self._db.execute("DELETE FROM chunk WHERE source=?", (source,))
        self._db.commit()
        self._load()
        return added

    def _load(self) -> None:
        rows = self._db.execute("SELECT source, text, vec FROM chunk").fetchall()
        self._rows = [(s, t) for s, t, _ in rows]
        self._matrix = np.vstack([np.frombuffer(v, dtype=np.float32) for _, _, v in rows]) if rows else None

    async def search(self, query: str, k: int = 3, min_score: float | None = None,
                     margin: float = 0.05) -> list[Passage]:
        """Top-k passages above ``min_score`` and within ``margin`` of the best one.

        The relative margin drops weakly related chunks even with embedding models whose absolute
        scores are compressed (everything scores 0.8): only clearly relevant text reaches the LLM.
        """
        min_score = self.min_score if min_score is None else min_score
        if self._matrix is None:
            self._load()
        if self._matrix is None:
            return []
        q = np.asarray((await self.embedder.embed([query]))[0], dtype=np.float32)
        q /= np.linalg.norm(q) or 1.0
        scores = self._matrix @ q
        best = np.argsort(-scores)[:k]
        top = float(scores[best[0]])
        return [
            Passage(self._rows[i][0], self._rows[i][1], float(scores[i]))
            for i in best if scores[i] >= min_score and scores[i] >= top - margin
        ]


def format_passages(passages: list[Passage]) -> str:
    """Wrap retrieved text as clearly delimited, untrusted data."""
    if not passages:
        return ""
    body = json.dumps([{"fonte": p.source, "testo": p.text} for p in passages], ensure_ascii=False)
    return f"<documenti>\n{body}\n</documenti>"
