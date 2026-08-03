"""Custom multi-source retrieval over the PawPal knowledge base.

Loads every Markdown file in `knowledge_base/`, splits each file into
sections at `##` headings, and indexes the sections with TF-IDF vectors.
`retrieve()` returns the top-k sections by cosine similarity, each tagged
with a stable source ID like `pet_profiles.md#biscuit`.

The TF-IDF math is implemented directly (a few lines of pure Python) so the
project stays dependency-light and fully deterministic on Python 3.9 —
a hosted vector database would be overkill for four Markdown files.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Optional

from .schemas import RetrievedChunk

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list:
    """Lowercase a string and split it into simple word tokens."""
    return _WORD_RE.findall(text.lower())


def _slugify(heading: str) -> str:
    """Turn a section heading into a stable id fragment (e.g. 'Litter Box' -> 'litter-box')."""
    return re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")


class KnowledgeRetriever:
    """TF-IDF retriever over Markdown sections in a knowledge directory."""

    def __init__(self, knowledge_dir: Path, top_k: int = 4):
        """Create a retriever rooted at `knowledge_dir`, returning up to `top_k` chunks."""
        self.knowledge_dir = Path(knowledge_dir)
        self.top_k = top_k
        self.chunks: list = []  # list[RetrievedChunk] (scores filled at query time)
        self._doc_vectors: list = []  # one {token: tf-idf weight} dict per chunk
        self._idf: dict = {}
        self.build_index()

    # ------------------------------------------------------------- indexing

    def build_index(self) -> None:
        """Load and split every .md file, then compute TF-IDF vectors.

        A missing or empty knowledge directory produces an empty index;
        retrieve() then simply returns no chunks.
        """
        self.chunks = []
        if self.knowledge_dir.is_dir():
            for path in sorted(self.knowledge_dir.glob("*.md")):
                self.chunks.extend(self._split_file(path))

        token_lists = [_tokenize(f"{c.section} {c.text}") for c in self.chunks]
        total_docs = len(token_lists)
        doc_freq: dict = {}
        for tokens in token_lists:
            for token in set(tokens):
                doc_freq[token] = doc_freq.get(token, 0) + 1
        # Smoothed IDF: stays positive even for tokens present in every chunk.
        self._idf = {
            token: math.log((1 + total_docs) / (1 + freq)) + 1.0
            for token, freq in doc_freq.items()
        }
        self._doc_vectors = [self._vectorize(tokens) for tokens in token_lists]

    def _split_file(self, path: Path) -> list:
        """Split one Markdown file into RetrievedChunks at '##' headings."""
        chunks = []
        current_heading: Optional[str] = None
        current_lines: list = []

        def flush():
            if current_heading is None:
                return
            text = "\n".join(current_lines).strip()
            if text:
                chunks.append(
                    RetrievedChunk(
                        source_id=f"{path.name}#{_slugify(current_heading)}",
                        source_file=path.name,
                        section=current_heading,
                        text=text,
                        score=0.0,
                    )
                )

        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                flush()
                current_heading = line[3:].strip()
                current_lines = []
            elif current_heading is not None:
                current_lines.append(line)
        flush()
        return chunks

    def _vectorize(self, tokens: list) -> dict:
        """Build a normalized {token: tf-idf} vector from a token list."""
        if not tokens:
            return {}
        counts: dict = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
        vector = {
            token: (count / len(tokens)) * self._idf.get(token, 0.0)
            for token, count in counts.items()
        }
        norm = math.sqrt(sum(weight * weight for weight in vector.values()))
        if norm == 0:
            return {}
        return {token: weight / norm for token, weight in vector.items()}

    # ------------------------------------------------------------ retrieval

    def retrieve(self, query: str, source_files: Optional[list] = None) -> list:
        """Return the top-k most relevant chunks for `query`, scored 0..1.

        An empty/whitespace query or an empty index returns []. If
        `source_files` is given, only chunks from those files are considered.
        """
        if not query or not query.strip() or not self.chunks:
            return []
        query_vector = self._vectorize(_tokenize(query))
        if not query_vector:
            return []

        scored = []
        for chunk, doc_vector in zip(self.chunks, self._doc_vectors):
            if source_files is not None and chunk.source_file not in source_files:
                continue
            score = sum(
                weight * doc_vector.get(token, 0.0)
                for token, weight in query_vector.items()
            )
            if score > 0:
                scored.append((score, chunk))

        # Sort by score descending; break ties by source_id for determinism.
        scored.sort(key=lambda pair: (-pair[0], pair[1].source_id))
        return [
            RetrievedChunk(
                source_id=chunk.source_id,
                source_file=chunk.source_file,
                section=chunk.section,
                text=chunk.text,
                score=round(score, 4),
            )
            for score, chunk in scored[: self.top_k]
        ]

    def known_source_ids(self) -> set:
        """Return the set of every source ID in the index."""
        return {chunk.source_id for chunk in self.chunks}
