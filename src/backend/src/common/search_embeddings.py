"""Embeddings for DB-backed semantic search (#1060).

- ``embedding_text``: the one place that decides what a search document's
  embedding represents (reused by glossary synonyms #1054 and the term-mapping
  suggester #1055).
- ``Embedder`` / ``DatabricksEmbedder``: batch text -> vectors via a Databricks
  embedding serving endpoint (OpenAI-compatible API), with call/token counts.
- ``QueryEmbeddingCache``: short-lived cache so a query is embedded once per
  request burst, not once per page or ranked list.
"""
from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from src.common.logging import get_logger

logger = get_logger(__name__)

# databricks-gte-large-en accepts 8192 tokens; ~4 chars per token keeps well
# under it while covering title + description + tags/domains/owner/concepts.
MAX_EMBEDDING_CHARS = 8000


def embedding_text(title: str | None, description: str | None, aux_text: str | None) -> str:
    """Text embedded for a search document: title, description, then aux text
    (tags, domains, owner, linked concept labels), truncated to the model limit."""
    parts = [p.strip() for p in (title, description, aux_text) if p and p.strip()]
    return "\n".join(parts)[:MAX_EMBEDDING_CHARS]


def text_hash(text: str, model: str = "") -> str:
    """Hash stored next to the embedding, so unchanged text isn't re-embedded.
    Covers the model (endpoint) too: switching to another model of the same
    size re-embeds everything instead of mixing vectors from both."""
    return hashlib.sha256(f"{model}\n{text}".encode("utf-8")).hexdigest()


class EmbeddingInputRejected(Exception):
    """The endpoint rejected the input itself (4xx), as opposed to being down.
    Retrying the same text won't help."""


def is_input_rejection(error: BaseException) -> bool:
    if isinstance(error, EmbeddingInputRejected):
        return True
    status = getattr(error, "status_code", None)
    return isinstance(status, int) and 400 <= status < 500 and status not in (401, 403, 404, 408, 429)


@dataclass
class EmbeddingStats:
    calls: int = 0
    texts: int = 0
    tokens: int = 0
    errors: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def add(self, *, calls: int = 0, texts: int = 0, tokens: int = 0, errors: int = 0) -> None:
        with self.lock:
            self.calls += calls
            self.texts += texts
            self.tokens += tokens
            self.errors += errors

    def snapshot(self) -> dict[str, int]:
        with self.lock:
            return {"calls": self.calls, "texts": self.texts, "tokens": self.tokens, "errors": self.errors}


class Embedder(Protocol):
    dim: int
    stats: EmbeddingStats

    def embed(self, texts: Sequence[str]) -> list[list[float]]:  # pragma: no cover - protocol
        ...


class DatabricksEmbedder:
    """Embeddings from a Databricks serving endpoint through ``create_openai_client``.

    The client is reused for ``CLIENT_TTL_SECONDS`` and then rebuilt, so the
    OAuth token behind it is refreshed well before it expires (1 h) without
    resolving a token on every call. Calls have a timeout and few retries: a
    hanging endpoint must not stall a search request or the worker.
    """

    CLIENT_TTL_SECONDS = 600.0
    TIMEOUT_SECONDS = 30.0
    MAX_RETRIES = 1

    def __init__(self, settings: Any, endpoint: str, dim: int):
        self._settings = settings
        self.endpoint = endpoint
        self.dim = dim
        self.stats = EmbeddingStats()
        self._client: Any = None
        self._client_at = 0.0
        self._client_lock = threading.Lock()

    def _get_client(self) -> Any:
        from src.common.llm_client import create_openai_client

        with self._client_lock:
            now = time.monotonic()
            if self._client is None or now - self._client_at > self.CLIENT_TTL_SECONDS:
                self._client = create_openai_client(self._settings).with_options(
                    timeout=self.TIMEOUT_SECONDS, max_retries=self.MAX_RETRIES,
                )
                self._client_at = now
            return self._client

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        if any(not t.strip() for t in texts):
            self.stats.add(calls=1, errors=1)
            raise EmbeddingInputRejected("empty text")  # the endpoint rejects it anyway
        try:
            resp = self._get_client().embeddings.create(model=self.endpoint, input=list(texts))
        except Exception:
            self.stats.add(calls=1, errors=1)
            raise
        usage = getattr(resp, "usage", None)
        self.stats.add(calls=1, texts=len(texts), tokens=int(getattr(usage, "total_tokens", 0) or 0))
        vectors = [list(d.embedding) for d in sorted(resp.data, key=lambda d: d.index)]
        if vectors and len(vectors[0]) != self.dim:
            raise ValueError(
                f"{self.endpoint} returned {len(vectors[0])}-dim embeddings; "
                f"SEARCH_EMBEDDING_DIM is {self.dim}"
            )
        return vectors


def create_embedder(settings: Any) -> DatabricksEmbedder | None:
    """The configured embedder, or None (semantic search off) when no endpoint is set."""
    endpoint = getattr(settings, "SEARCH_EMBEDDING_ENDPOINT", None)
    if not endpoint:
        logger.info("SEARCH_EMBEDDING_ENDPOINT not set: semantic search is off (lexical only).")
        return None
    return DatabricksEmbedder(settings, endpoint, int(getattr(settings, "SEARCH_EMBEDDING_DIM", 1024)))


class QueryEmbeddingCache:
    """Tiny thread-safe TTL + LRU cache for query embeddings."""

    def __init__(self, embedder: Embedder, ttl_seconds: float = 300.0, max_entries: int = 256):
        self._embedder = embedder
        self._ttl = ttl_seconds
        self._max = max_entries
        self._data: OrderedDict[str, tuple[float, list[float]]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, query: str) -> list[float]:
        key = " ".join(query.lower().split())
        now = time.monotonic()
        with self._lock:
            hit = self._data.get(key)
            if hit and now - hit[0] < self._ttl:
                self._data.move_to_end(key)
                return hit[1]
        vec = self._embedder.embed([key])[0]
        with self._lock:
            self._data[key] = (now, vec)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)
        return vec
