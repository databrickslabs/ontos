"""Unit tests for the shared upload caps (DoS / abuse hardening, #860).

Exercises ``read_uploads_capped`` directly (no HTTP layer): file-count, per-file
and total byte caps each raise a 413, and a within-limits batch returns the
``(name, bytes, content_type)`` tuples.
"""
import asyncio

import pytest
from fastapi import HTTPException

import src.common.upload_limits as ul
from src.common.upload_limits import read_uploads_capped


class _FakeUpload:
    """Minimal stand-in for starlette's UploadFile (only what the helper uses)."""

    def __init__(self, filename, data: bytes, content_type="application/json"):
        self.filename = filename
        self.content_type = content_type
        self._data = data

    async def read(self, n: int = -1) -> bytes:
        return self._data if n is None or n < 0 else self._data[:n]


def _run(coro):
    return asyncio.run(coro)


def _ident(n):
    return n or "upload.bin"


def test_within_limits_returns_tuples():
    files = [_FakeUpload("a.json", b"{}"), _FakeUpload("b.yaml", b"x: 1", "application/x-yaml")]
    out = _run(read_uploads_capped(files, sanitize=_ident))
    assert [(n, raw) for n, raw, _ in out] == [("a.json", b"{}"), ("b.yaml", b"x: 1")]
    assert out[1][2] == "application/x-yaml"


def test_too_many_files_413(monkeypatch):
    monkeypatch.setattr(ul, "MAX_UPLOAD_FILES", 3)
    files = [_FakeUpload(f"f{i}.json", b"{}") for i in range(4)]
    with pytest.raises(HTTPException) as ei:
        _run(read_uploads_capped(files, sanitize=_ident))
    assert ei.value.status_code == 413
    assert "Too many files" in ei.value.detail


def test_per_file_cap_413(monkeypatch):
    monkeypatch.setattr(ul, "MAX_UPLOAD_FILE_BYTES", 10)
    files = [_FakeUpload("big.json", b"x" * 11)]
    with pytest.raises(HTTPException) as ei:
        _run(read_uploads_capped(files, sanitize=_ident))
    assert ei.value.status_code == 413
    assert "per-file limit" in ei.value.detail


def test_total_cap_413(monkeypatch):
    monkeypatch.setattr(ul, "MAX_UPLOAD_FILE_BYTES", 10)
    monkeypatch.setattr(ul, "MAX_UPLOAD_TOTAL_BYTES", 15)
    # Each file is within the per-file cap, but together they exceed the total.
    files = [_FakeUpload("a.json", b"x" * 9), _FakeUpload("b.json", b"y" * 9)]
    with pytest.raises(HTTPException) as ei:
        _run(read_uploads_capped(files, sanitize=_ident))
    assert ei.value.status_code == 413
    assert "total limit" in ei.value.detail
