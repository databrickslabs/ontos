"""Entry point: parse an erwin model export into the IR."""
from __future__ import annotations

from typing import IO

from src.model_import.erwin.builder import build_model
from src.model_import.erwin.ir import ErwinModel
from src.model_import.erwin.xml_reader import ErwinParseError, read_erwin_xml

# A native .erwin file is a proprietary binary (only readable through erwin's
# Windows COM API). Tell the user how to export instead of failing on "invalid XML".
_EXPORT_HINT = (
    "Export the model from erwin Data Modeler with File → Save As → XML "
    "(\"XML Standard\") and upload the .xml file."
)


def detect_format(head: bytes) -> str:
    """'xml' | 'json' | 'unknown' from the first bytes of a file."""
    text = head.lstrip(b"\xef\xbb\xbf").lstrip()
    if text.startswith(b"<"):
        return "xml"
    if text[:1] in (b"{", b"["):
        return "json"
    return "unknown"


def parse_erwin(stream: IO[bytes]) -> ErwinModel:
    """Parse an erwin export from a seekable binary stream.

    Raises ``ErwinParseError`` for anything that is not a readable export.
    """
    head = stream.read(512)
    stream.seek(0)
    fmt = detect_format(head)
    if fmt == "json":
        raise ErwinParseError(
            "erwin JSON exports are not supported yet. " + _EXPORT_HINT
        )
    if fmt != "xml":
        raise ErwinParseError("Not an erwin XML export. " + _EXPORT_HINT)
    raw = read_erwin_xml(stream)
    return build_model(raw, source_format="erwin_xml")
