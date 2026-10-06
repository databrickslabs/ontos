"""Classify an uploaded entity as an ODCS contract or an ODPS product.

The batch importers (`create_contracts_from_files` / `create_products_from_files`)
accept whatever YAML/JSON the user drops. Without a guard an ODPS *Data Product*
file is silently imported as a *Data Contract* (and vice versa), because the
contract builder tolerates missing fields and the product builder defaults `kind`.
This module provides the single discriminator both importers use to reject a
cross-type file and report it as a skipped item.

Primary signal is the standard top-level ``kind`` (ODCS → ``DataContract``,
ODPS → ``DataProduct``). When ``kind`` is absent we fall back to structural
markers that are exclusive to each standard, and only classify when exactly one
side matches — an ambiguous payload stays ``unknown`` so a legitimate but sparse
file is never wrongly rejected.
"""
from __future__ import annotations

from typing import Any, Literal

EntityKind = Literal["contract", "product", "unknown"]

# Structural markers exclusive to each standard, used only when `kind` is absent.
_PRODUCT_MARKERS = ("outputPorts", "inputPorts")
_CONTRACT_MARKERS = ("schema", "datasets")


def _normalize_kind(value: Any) -> str:
    """Collapse ``"Data Product"`` / ``"data-product"`` / ``"DataProduct"`` to ``dataproduct``."""
    if not isinstance(value, str):
        return ""
    return value.strip().lower().replace(" ", "").replace("-", "").replace("_", "")


def classify_import_entity(entity: Any) -> EntityKind:
    """Return ``"contract"``, ``"product"`` or ``"unknown"`` for a parsed entity dict."""
    if not isinstance(entity, dict):
        return "unknown"

    kind = _normalize_kind(entity.get("kind"))
    if kind == "datacontract":
        return "contract"
    if kind == "dataproduct":
        return "product"
    if kind:
        # A kind is declared but is neither standard — don't guess.
        return "unknown"

    # No kind: use mutually exclusive structural markers.
    has_product = any(m in entity for m in _PRODUCT_MARKERS)
    has_contract = any(m in entity for m in _CONTRACT_MARKERS)
    if has_product and not has_contract:
        return "product"
    if has_contract and not has_product:
        return "contract"
    return "unknown"


def describe_import_entity(entity: Any) -> str:
    """Human label for skip messages, e.g. ``"ODPS Data Product"``."""
    kind = classify_import_entity(entity)
    if kind == "product":
        return "ODPS Data Product"
    if kind == "contract":
        return "ODCS Data Contract"
    return "unrecognized entity"
