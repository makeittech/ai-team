"""Embeddings used by the vector long-term memory.

The default :class:`HashingEmbedder` is a dependency-free, deterministic
bag-of-words hashing embedder. It gives stable, semantically-keyword-sensitive
vectors which is enough for fact recall in tests and offline deployments.

If ``sentence-transformers`` is installed you may swap in a real model by
implementing :class:`Embedder`; the rest of the system only depends on the
abstract interface.
"""

from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod

import numpy as np

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


class Embedder(ABC):
    """Abstract embedder interface."""

    dim: int

    @abstractmethod
    def embed(self, text: str) -> np.ndarray:  # pragma: no cover - interface
        ...

    def embed_many(self, texts: list[str]) -> np.ndarray:
        return np.vstack([self.embed(t) for t in texts]) if texts else np.zeros((0, self.dim))


class HashingEmbedder(Embedder):
    """Deterministic hashing bag-of-words embedder.

    Each token is hashed into ``dim`` buckets (with a sign hash to reduce
    collisions). The vector is L2-normalized so that cosine similarity equals a
    dot product. Identical/overlapping vocabularies produce high similarity,
    which is exactly what fact recall needs.
    """

    def __init__(self, dim: int = 256, ngram: int = 2) -> None:
        self.dim = dim
        self.ngram = ngram

    def _hash(self, token: str) -> int:
        # Stable across processes (Python's hash() is salted, so use a manual fnv-1a).
        h = 0x811C9DC5
        for ch in token.encode("utf-8"):
            h ^= ch
            h = (h * 0x01000193) & 0xFFFFFFFF
        return h

    def embed(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        tokens = _tokenize(text)
        grams = list(tokens)
        for n in range(2, self.ngram + 1):
            grams.extend("_".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1))
        for tok in grams:
            h = self._hash(tok)
            idx = h % self.dim
            sign = 1.0 if (h >> 31) & 1 else -1.0
            vec[idx] += sign
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
        return vec


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


_DEFAULT: Embedder | None = None


def get_default_embedder() -> Embedder:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = HashingEmbedder()
    return _DEFAULT
