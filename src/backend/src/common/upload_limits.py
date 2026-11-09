"""Shared guards for multipart file uploads (DoS / abuse hardening).

Caps the number of files and the bytes read per-file and in total *before* any
content is decoded or parsed, so a huge payload — or a small alias-heavy YAML
file whose `safe_load` expansion balloons memory — cannot exhaust the process.

A breach is a request-level ``413`` (an abuse guard, deliberately distinct from
per-entity validation, which is reported as a failed item inside the batch
result and never aborts the batch).
"""
from typing import Callable, List, Optional, Tuple

from fastapi import HTTPException, UploadFile

# Conservative defaults; a single ODCS/ODPS document is a few KB, an array a few
# hundred KB. These leave generous headroom while bounding worst-case memory.
MAX_UPLOAD_FILES = 50
MAX_UPLOAD_FILE_BYTES = 5 * 1024 * 1024      # 5 MiB per file
MAX_UPLOAD_TOTAL_BYTES = 25 * 1024 * 1024    # 25 MiB per request


def _mib(n: int) -> int:
    return n // (1024 * 1024)


async def read_uploads_capped(
    files: List[UploadFile],
    sanitize: Callable[[Optional[str]], str],
) -> List[Tuple[str, bytes, Optional[str]]]:
    """Read uploaded files into memory under hard count/size caps.

    Args:
        files: The multipart files.
        sanitize: Maps a raw (possibly ``None``) client filename to a safe name;
            used both for the returned tuples and for 413 messages.

    Returns:
        ``(safe_filename, content_bytes, content_type)`` per file.

    Raises:
        HTTPException: ``413`` if the file count, any single file, or the running
            total exceeds its cap. We read one byte past the per-file cap so an
            oversize file is detected without loading it fully into memory.
    """
    if len(files) > MAX_UPLOAD_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"Too many files: {len(files)} (max {MAX_UPLOAD_FILES} per upload).",
        )

    out: List[Tuple[str, bytes, Optional[str]]] = []
    total = 0
    for f in files:
        name = sanitize(f.filename)
        chunk = await f.read(MAX_UPLOAD_FILE_BYTES + 1)
        if len(chunk) > MAX_UPLOAD_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File '{name}' exceeds the {_mib(MAX_UPLOAD_FILE_BYTES)} MiB per-file limit.",
            )
        total += len(chunk)
        if total > MAX_UPLOAD_TOTAL_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Upload exceeds the {_mib(MAX_UPLOAD_TOTAL_BYTES)} MiB total limit.",
            )
        out.append((name, chunk, f.content_type))
    return out
