"""Background embedding of search documents (#1060).

Off the request path: upserts only bump ``updated_at`` (and wake the worker);
the worker leases rows whose embedding is missing or older than their content,
calls the endpoint with no transaction open, re-embeds only rows whose text
hash changed (others are just marked current), and stores the vectors if the
row wasn't edited meanwhile. Backfill of an existing catalog is the same loop,
so it resumes naturally after a restart; replicas skip each other's leases.
Endpoint errors leave rows pending and back off; search keeps answering
lexically meanwhile. Text the endpoint rejects (4xx) is set aside per row, so
one bad document can't stall the rest.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional

from src.common.logging import get_logger
from src.common.search_embeddings import Embedder, embedding_text, is_input_rejection, text_hash

logger = get_logger(__name__)


class EmbeddingWorker:
    def __init__(
        self,
        session_factory: Callable,
        engine: Any,
        embedder: Embedder,
        *,
        batch_size: int = 32,
        poll_seconds: float = 60.0,
        debounce_seconds: float = 2.0,
        max_backoff_seconds: float = 300.0,
        lease_seconds: float = 300.0,
    ):
        self._session_factory = session_factory
        self._engine = engine
        self._embedder = embedder
        self._batch_size = max(1, int(batch_size))
        self._poll = poll_seconds
        self._debounce = debounce_seconds
        self._max_backoff = max_backoff_seconds
        self._lease = lease_seconds
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.embedded = 0
        self.unchanged = 0
        self.rejected = 0
        self.failed_batches = 0
        self.last_error: Optional[str] = None

    # --- lifecycle -------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="search-embeddings", daemon=True)
        self._thread.start()
        self._wake.set()  # backfill whatever is pending at startup
        logger.info("Search embedding worker started.")

    def stop(self, timeout: Optional[float] = None) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def notify(self) -> None:
        """Documents changed: embed them soon (debounced)."""
        self._wake.set()

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            out = {
                "embedded": self.embedded, "unchanged": self.unchanged, "rejected": self.rejected,
                "failed_batches": self.failed_batches, "last_error": self.last_error,
            }
        out["endpoint"] = self._embedder.stats.snapshot()
        return out

    # --- work ------------------------------------------------------------
    def run_batch(self) -> int:
        """Process one batch; returns the number of rows handled (0 = nothing pending)."""
        from src.repositories import search_repository as repo

        with self._session_factory() as db:  # committed: the lease, not a lock, holds the rows
            rows = repo.claim_pending_embeddings(db, self._batch_size, self._lease)
        if not rows:
            return 0
        try:
            model = getattr(self._embedder, "endpoint", "") or ""
            texts = {r["id"]: embedding_text(r["title"], r["description"], r["aux_text"]) for r in rows}
            hashes = {i: text_hash(t, model) for i, t in texts.items()}
            results, todo = [], []
            for r in rows:
                res = {"id": r["id"], "updated_at": r["updated_at"], "hash": hashes[r["id"]]}
                if r["has_embedding"] and r["embedding_hash"] == res["hash"]:
                    results.append(res)                    # unchanged: mark current
                elif not texts[r["id"]].strip():
                    results.append({**res, "rejected": True})  # nothing to embed
                else:
                    todo.append(res)
            for res, vec in zip(todo, self._embed([texts[res["id"]] for res in todo])):
                results.append({**res, "vector": vec} if vec is not None else {**res, "rejected": True})
            with self._session_factory() as db:
                repo.store_embeddings(db, results, self._engine)
        finally:
            with self._session_factory() as db:
                repo.release_embedding_claims(db, [r["id"] for r in rows])
        with self._lock:
            self.embedded += sum(1 for r in results if r.get("vector") is not None)
            self.rejected += sum(1 for r in results if r.get("rejected"))
            self.unchanged += sum(1 for r in results if r.get("vector") is None and not r.get("rejected"))
        return len(rows)

    def _embed(self, texts):
        """Vectors for ``texts``; ``None`` for a text the endpoint rejects. A
        rejected batch is retried one text at a time to find the bad ones;
        any other error (endpoint down, auth) propagates and the batch stays
        pending."""
        if not texts:
            return []
        try:
            return self._embedder.embed(texts)
        except Exception as e:
            if not is_input_rejection(e):
                raise
            if len(texts) == 1:
                logger.warning(f"Search embedding: endpoint rejected a document, skipping it: {e}")
                return [None]
        out = []
        for t in texts:
            out.extend(self._embed([t]))
        return out

    def run_until_idle(self, max_batches: Optional[int] = None) -> Dict[str, Any]:
        """Drain pending rows synchronously (tests, admin backfill). Raises on endpoint errors."""
        n = 0
        while max_batches is None or n < max_batches:
            if not self.run_batch():
                break
            n += 1
        return {**self.stats(), "batches": n}

    def _loop(self) -> None:
        backoff = 0.0
        while not self._stop.is_set():
            self._wake.wait(timeout=self._poll)
            self._wake.clear()
            if self._stop.is_set():
                break
            time.sleep(self._debounce)  # coalesce a burst of upserts into one pass
            try:
                handled = 0
                while not self._stop.is_set():
                    n = self.run_batch()
                    if not n:
                        break
                    handled += n
                if handled:
                    logger.info(f"Search embeddings: {handled} documents processed; {self.stats()}")
                backoff = 0.0
            except Exception as e:
                with self._lock:
                    self.failed_batches += 1
                    self.last_error = str(e)
                backoff = min(self._max_backoff, max(5.0, backoff * 2))
                logger.warning(f"Search embedding batch failed (retrying in {backoff:.0f}s): {e}")
                self._stop.wait(backoff)
                self._wake.set()
