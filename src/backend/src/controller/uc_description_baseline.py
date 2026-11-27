"""The Unity Catalog comment Ontos last saw for an asset (the drift baseline).

Stored as the internal asset property ``uc_description_baseline`` (hidden from API clients, no
migration): ``{text, digest, at}``. It is set when the asset is imported from Unity Catalog,
when its description is reset to the comment, and when a write-back leaves Unity Catalog with
the Ontos description. Drift is read on demand: the comment read now differs from the baseline
means somebody changed it in Unity Catalog since.
"""
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from src.common.uc_comments import normalize_comment
from src.db_models.assets import AssetDb
from src.models.assets import DESCRIPTION_BASELINE_PROPERTY


def _digest(text: Optional[str]) -> str:
    return hashlib.sha256((normalize_comment(text) or '').encode('utf-8')).hexdigest()[:16]


def make_baseline(text: Optional[str]) -> Dict[str, Any]:
    """The stored baseline for a Unity Catalog comment (``text`` None: it had none)."""
    return {
        'text': text or None, 'digest': _digest(text),
        'at': datetime.now(timezone.utc).isoformat(),
    }


def baseline_of(properties: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The stored baseline of an asset's properties, or None when none was recorded."""
    stored = (properties or {}).get(DESCRIPTION_BASELINE_PROPERTY)
    if isinstance(stored, dict) and 'digest' in stored:
        return stored
    return None


def changed_since(baseline: Optional[Dict[str, Any]], uc_comment: Optional[str]) -> bool:
    """Whether the Unity Catalog comment differs from the baseline (False without a baseline)."""
    return baseline is not None and baseline.get('digest') != _digest(uc_comment)


def set_baseline(db: Session, asset: AssetDb, uc_comment: Optional[str]) -> None:
    """Record ``uc_comment`` as what Unity Catalog holds for ``asset`` (flushes, no commit)."""
    # A new dict, so the JSON column is seen as changed
    asset.properties = {
        **(asset.properties or {}), DESCRIPTION_BASELINE_PROPERTY: make_baseline(uc_comment)}
    db.flush()
