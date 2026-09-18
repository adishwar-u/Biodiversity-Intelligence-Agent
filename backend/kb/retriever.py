"""Store A: lightweight keyword/BM25 search over the literature corpus.

Deliberately dependency-light (rank_bm25 is pure Python, no torch/embedding
model download) so the project runs anywhere with no setup cost. Swapping in
a dense/hybrid retriever later only means replacing this module.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from rank_bm25 import BM25Okapi

CORPUS_DIR = Path(__file__).resolve().parent.parent / "data" / "corpus"

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@dataclass
class Document:
    id: str
    title: str
    org: str
    year: int
    topic: str
    body: str


def _parse_frontmatter(raw: str) -> tuple[dict, str]:
    if not raw.startswith("---"):
        return {}, raw
    _, fm_block, body = raw.split("---", 2)
    meta = {}
    for line in fm_block.strip().splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            meta[key.strip()] = val.strip().strip('"')
    return meta, body.strip()


class Retriever:
    def __init__(self, corpus_dir: Path = CORPUS_DIR):
        self.documents: list[Document] = []
        for path in sorted(corpus_dir.glob("*.md")):
            meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
            self.documents.append(
                Document(
                    id=path.stem,
                    title=meta.get("title", path.stem),
                    org=meta.get("org", "unknown"),
                    year=int(meta.get("year", 0) or 0),
                    topic=meta.get("topic", "general"),
                    body=body,
                )
            )
        corpus_tokens = [_tokenize(f"{d.title} {d.body}") for d in self.documents]
        self._bm25 = BM25Okapi(corpus_tokens) if corpus_tokens else None

    def search(self, query: str, top_k: int = 3) -> list[Document]:
        if not self._bm25 or not query.strip():
            return []
        scores = self._bm25.get_scores(_tokenize(query))
        ranked = sorted(zip(scores, self.documents), key=lambda x: x[0], reverse=True)
        return [doc for score, doc in ranked[:top_k] if score > 0]


_default_retriever: Retriever | None = None


def get_retriever() -> Retriever:
    global _default_retriever
    if _default_retriever is None:
        _default_retriever = Retriever()
    return _default_retriever


if __name__ == "__main__":
    r = get_retriever()
    print(f"Loaded {len(r.documents)} corpus documents.")
    for doc in r.search("legume cover crop soil organic carbon", top_k=3):
        print(f"- {doc.title} ({doc.org}, {doc.year})")
